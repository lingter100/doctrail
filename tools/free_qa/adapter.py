"""QA-only policy seam over the existing bounded GGUF HTTP transport."""
from __future__ import annotations

import re
from pathlib import Path

from doctrail.inference import WorkerError
from doctrail.meeting_gguf import GGUFGenerator, _integer
from scripts.probe_meeting_local_candidate import CONTENT_ERRORS, QA_COVERAGE_CONTROL, QA_GRAMMAR
from tools.free_qa.policy import EPOCHS, ModelPolicy, need, sha


def validate_props(props, prepared):
    """Pure runtime identity/settings validation; no transport or generation methods."""
    policy = prepared.policy
    build = re.fullmatch(r"b([0-9]+)-([a-f0-9]{7,40})", props.get("build_info", ""))
    need(props.get("model_alias") == policy.alias and build
         and "b" + build[1] == policy.runtime["tag"]
         and policy.runtime["commit"].startswith(build[2]), "runtime_identity")
    need(Path(props["model_path"]).resolve() == prepared.entry.resolve()
         and props["default_generation_settings"]["n_ctx"] == 6144
         and type(props["default_generation_settings"]["n_ctx"]) is int
         and type(props.get("total_slots")) is int and props["total_slots"] == 1
         and props.get("is_sleeping") is False, "runtime_settings")
    need(isinstance(props.get("chat_template"), str)
         and sha(props["chat_template"].encode()) == policy.reviewed["template_sha256"], "runtime_template")
    return {"build": props["build_info"], "context_tokens": 6144, "slots": 1}


class PairedQAAdapter(GGUFGenerator):
    def __init__(self, url, token, *, policy, epoch, case_ids, resource_check, clock, evidence, transport=None):
        need(isinstance(policy, ModelPolicy) and EPOCHS.get(epoch.name) is epoch
             and policy.model_id == epoch.model_id, "adapter_policy")
        need(callable(resource_check) and callable(clock) and callable(evidence), "required_callbacks")
        need(isinstance(case_ids, tuple) and len(case_ids) == epoch.calls and len(set(case_ids)) == len(case_ids), "adapter_cases")
        super().__init__(url, token, policy.profile_path, transport=transport)
        self.policy, self.epoch, self.case_ids = policy, epoch, case_ids
        self.resource_check, self.clock, self.evidence = resource_check, clock, evidence
        self.counts = {"completions": 0, "requested_tokens": 0, "http": 0}
        self.used, self.halted, self.stage = set(), False, None

    def _remaining(self, deadline=None):
        need(not self.halted, "halted")
        effective = self._deadline if deadline is None else deadline
        need(type(effective) in (int, float), "unbounded_request")
        self.resource_check()
        remaining = effective - self.clock()
        need(remaining > 0, "deadline")
        return remaining

    def _request(self, method, path, payload=None, deadline=None):
        try:
            self._remaining(deadline)
            need(path == "/props" or (self.stage == "qa" and path in ("/apply-template", "/tokenize", "/completion")), "qa_only_transport")
            if path == "/completion":
                need(self.counts["completions"] < self.epoch.calls and payload["n_predict"] == 256
                     and payload["grammar"] == QA_GRAMMAR and self.counts["requested_tokens"] + 256 <= self.epoch.calls * 256,
                     "completion_cap")
                self.counts["completions"] += 1
                self.counts["requested_tokens"] += 256  # Never refunded after lost response.
            self.counts["http"] += 1
            self.evidence("request", {"case_id": getattr(self, "case_id", None), "path": path, "body": payload})
            response = super()._request(method, path, payload, deadline)
            self.evidence("response", {"case_id": getattr(self, "case_id", None), "path": path, "body": response})
            if path == "/completion":
                tokens, count = response.get("tokens"), response.get("tokens_predicted")
                need(isinstance(tokens, list) and _integer(count, 1) and len(tokens) == count
                     and all(_integer(t) for t in tokens) and type(response.get("timings", {}).get("predicted_n")) is int
                     and response["timings"]["predicted_n"] == count, "response_token_integrity")
            self._remaining(deadline)
            return response
        except Exception as error:
            if getattr(error, "code", None) not in CONTENT_ERRORS:
                self.halted = True
            raise

    def _prepare(self, request_messages, deadline=None):
        prompt = self._request("POST", "/apply-template", {"messages": request_messages}, deadline).get("prompt")
        need(isinstance(prompt, str) and prompt, "template_protocol")
        tokens = self._request("POST", "/tokenize", {"content": prompt, "add_special": False,
            "parse_special": True, "with_pieces": False}, deadline).get("tokens")
        need(isinstance(tokens, list) and tokens and all(_integer(t) for t in tokens), "token_protocol")
        return tokens

    def load(self, prepared):
        from tools.free_qa.runner import check_prepared
        try:
            self._remaining()
            check_prepared(prepared, self.policy, self.clock, self._deadline)
            props = self._request("GET", "/props")
            validate_props(props, prepared)
            self._alias = self.policy.alias
            self._metadata = {"model_id": self.policy.model_id, "alias": self.policy.alias,
                "profile_sha256": self.policy.profile_sha256, "experimental": True,
                "runtime": {"build": props["build_info"], "context_tokens": 6144, "slots": 1},
                "metadata_review_sha256": self.policy.reviewed["review_receipt"]["sha256"]}
            self._remaining()
            return self
        except Exception:
            self.halted = True
            raise

    def complete_qa(self, case_id, messages, deadline):
        need(not self.halted and self._metadata is not None, "not_ready_or_halted")
        need(case_id in self.case_ids and case_id not in self.used and self.stage is None, "case_repeated_or_unknown")
        need(type(deadline) in (float, int) and 0 < deadline - self.clock() <= 60, "request_deadline")
        self.used.add(case_id)
        self.stage, self.case_id = "qa", case_id
        self.begin_request(deadline)
        try:
            need(isinstance(messages, list) and len(messages) == 2
                 and messages[0] == {"role": "system", "content": QA_COVERAGE_CONTROL.system()}
                 and isinstance(messages[1], dict) and set(messages[1]) == {"role", "content"}
                 and messages[1]["role"] == "user" and isinstance(messages[1]["content"], str), "qa_system")
            output = self._complete(messages, deadline, 256, QA_GRAMMAR)
            self._remaining(deadline)
            if output.finish_reason != "eos":
                raise WorkerError("generation_output_limit", 502)
            return output
        except Exception as error:
            if getattr(error, "code", None) not in CONTENT_ERRORS:
                self.halted = True
            raise
        finally:
            self.end_request()
            self.stage = None
