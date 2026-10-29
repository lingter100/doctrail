"""Public synthetic contracts only. No native/model/tokenizer/network/RAM execution."""
from __future__ import annotations

import copy
import io
import json
import os
import struct
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from scripts import probe_meeting_local_candidate as legacy
from tools.free_qa import assets
from tools.free_qa import policy as p
from tools.free_qa import runner as r
from tools.free_qa.adapter import PairedQAAdapter, validate_props
from tools.summary_grammar.runtime import BoundaryError

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PROFILES = {key: (ROOT / value[0]).read_bytes() for key, value in p.PROFILE_PINS.items()}

# Public Qwen2.5-7B-Instruct GGUF template, Apache-2.0; raw metadata pin.
# Qwen/Qwen2.5-7B-Instruct-GGUF@bb5d59e06d9551d752d08b292a50eb208b07ab1f
# Kept inline so CI uses no local assets. Runtime expectation is source-derived.
QWEN_RAW_TEMPLATE = (
    "{%- if tools %}\n"
    "    {{- '<|im_start|>system\\n' }}\n"
    "    {%- if messages[0]['role'] == 'system' %}\n"
    "        {{- messages[0]['content'] }}\n"
    "    {%- else %}\n"
    "        {{- 'You are Qwen, created by Alibaba Cloud. You are a helpful assistant.' }}\n"
    "    {%- endif %}\n"
    "    {{- \"\\n\\n# Tools\\n\\nYou may call one or more functions to assist with the user query.\\n\\nYou are provided with function signatures within <tools></tools> XML tags:\\n<tools>\" }}\n"
    "    {%- for tool in tools %}\n"
    "        {{- \"\\n\" }}\n"
    "        {{- tool | tojson }}\n"
    "    {%- endfor %}\n"
    "    {{- \"\\n</tools>\\n\\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\\n<tool_call>\\n{{\\\"name\\\": <function-name>, \\\"arguments\\\": <args-json-object>}}\\n</tool_call><|im_end|>\\n\" }}\n"
    "{%- else %}\n"
    "    {%- if messages[0]['role'] == 'system' %}\n"
    "        {{- '<|im_start|>system\\n' + messages[0]['content'] + '<|im_end|>\\n' }}\n"
    "    {%- else %}\n"
    "        {{- '<|im_start|>system\\nYou are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>\\n' }}\n"
    "    {%- endif %}\n"
    "{%- endif %}\n"
    "{%- for message in messages %}\n"
    "    {%- if (message.role == \"user\") or (message.role == \"system\" and not loop.first) or (message.role == \"assistant\" and not message.tool_calls) %}\n"
    "        {{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>' + '\\n' }}\n"
    "    {%- elif message.role == \"assistant\" %}\n"
    "        {{- '<|im_start|>' + message.role }}\n"
    "        {%- if message.content %}\n"
    "            {{- '\\n' + message.content }}\n"
    "        {%- endif %}\n"
    "        {%- for tool_call in message.tool_calls %}\n"
    "            {%- if tool_call.function is defined %}\n"
    "                {%- set tool_call = tool_call.function %}\n"
    "            {%- endif %}\n"
    "            {{- '\\n<tool_call>\\n{\"name\": \"' }}\n"
    "            {{- tool_call.name }}\n"
    "            {{- '\", \"arguments\": ' }}\n"
    "            {{- tool_call.arguments | tojson }}\n"
    "            {{- '}\\n</tool_call>' }}\n"
    "        {%- endfor %}\n"
    "        {{- '<|im_end|>\\n' }}\n"
    "    {%- elif message.role == \"tool\" %}\n"
    "        {%- if (loop.index0 == 0) or (messages[loop.index0 - 1].role != \"tool\") %}\n"
    "            {{- '<|im_start|>user' }}\n"
    "        {%- endif %}\n"
    "        {{- '\\n<tool_response>\\n' }}\n"
    "        {{- message.content }}\n"
    "        {{- '\\n</tool_response>' }}\n"
    "        {%- if loop.last or (messages[loop.index0 + 1].role != \"tool\") %}\n"
    "            {{- '<|im_end|>\\n' }}\n"
    "        {%- endif %}\n"
    "    {%- endif %}\n"
    "{%- endfor %}\n"
    "{%- if add_generation_prompt %}\n"
    "    {{- '<|im_start|>assistant\\n' }}\n"
    "{%- endif %}\n"
)


def ref(name, data=b"synthetic"):
    return {"file": name, "size_bytes": len(data), "sha256": p.sha(data)}


def runtime():
    pinned = p.parse(PUBLIC_PROFILES[p.CANDIDATE])["runtime_reuse"]["runtime_files"]
    return {"root": "models/existing/runtime", "tag": "b11429", "commit": p.RUNTIME_COMMIT,
            "server": "llama-server.exe", "files": [{"file": name, **value} for name, value in pinned.items()]}


def metadata(model):
    rows = [{"version": 3, "tensor_count_header": 1, "metadata_bytes_read": 120,
        "metadata_wire_sha256": "a" * 64, "scalars": {"general.architecture": {"type": 8, "value": "synthetic-baseline"}},
        "template": {"raw_utf8_sha256": p.sha(b"SYNTHETIC TEMPLATE"), "size_bytes": 18},
        "tokenizer": [{"key": "tokenizer.ggml.model", "type": 8, "value_wire_sha256": "b" * 64},
            {"key": "tokenizer.ggml.tokens", "type": 9, "element_type": 8, "count": 2, "value_wire_sha256": "c" * 64}],
        "tensor_descriptors_or_payload_parsed": False}]
    if model == p.CANDIDATE:
        rows[0]["scalars"].update({"general.architecture": {"type": 8, "value": "qwen2"},
            "split.no": {"type": 2, "value": 0}, "split.count": {"type": 2, "value": 2},
            "split.tensors.count": {"type": 5, "value": 2}})
        second = copy.deepcopy(rows[0])
        second["scalars"]["split.no"]["value"] = 1
        second["tokenizer"] = []
        second["template"] = None
        rows.append(second)
    return rows


def binding(model):
    rows = metadata(model)
    return {"schema_version": 1, "model_id": model, "profile_sha256": p.PROFILE_PINS[model][1],
        "runtime_sha256": p.sha(p.canonical(runtime())), "metadata": rows,
        "template_sha256": rows[0]["template"]["raw_utf8_sha256"],
        "tokenizer_sha256": p.sha(p.canonical(rows[0]["tokenizer"])),
        "metadata_receipt": ref("synthetic/metadata.json"), "review_receipt": ref("synthetic/review.json"),
        "acquisition_gate": ref("synthetic/accepted-gate.json")}


def model_policy(model=p.BASE):
    return p.bind_policy(PUBLIC_PROFILES[model], binding(model), runtime())


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now


def case_fixture(identity="case-0", texts=None):
    texts = texts or ["목적: 공개 합성 검증😀\r\n\n결정: 변경을 승인했다.\n", "English 👩‍💻 evidence.\n"]
    bundle, documents, side_documents, side_units, shifted = "", [], [], [], []
    for index, text in enumerate(texts):
        title = f"Synthetic document {index}"
        bundle += f"\n# {title}\n\n"
        start = len(bundle)
        bundle += text
        end = len(bundle)
        document = {"document_id": f"doc-{index}", "revision": 1, "title": title, "content": text,
                    "start_offset": start, "end_offset": end}
        documents.append(document)
        side_documents.append({k: document[k] for k in ("document_id", "revision", "title", "start_offset", "end_offset")}
                              | {"content_sha256": p.sha(text.encode())})
        for unit in r.meeting_units(text):
            moved = {"quote": unit["quote"], "start_offset": start + unit["start_offset"], "end_offset": start + unit["end_offset"]}
            side_units.append({"id": len(shifted), "document_id": f"doc-{index}", "revision": 1, **unit,
                "bundle_start_offset": moved["start_offset"], "bundle_end_offset": moved["end_offset"]})
            shifted.append(moved)
    data = {"id": identity, "title": "공개 합성 bundle", "question": "승인한 결정은? " + identity,
            "bundle": bundle, "documents": documents}
    side = {"bundle_sha256": p.sha(bundle.encode()), "documents": side_documents, "units": side_units}
    source = r.source_payload(data["title"], bundle, shifted)
    messages = legacy.source_wire_messages(legacy.qa_request_messages(source, data["question"], legacy.QA_COVERAGE_CONTROL),
                                          source, bundle, shifted, legacy.COMPACT_WIRE)
    row = {"id": identity, "content_sha256": p.sha(bundle.encode()), "question_sha256": p.sha(data["question"].encode()),
           "messages_sha256": p.sha(p.canonical(messages)), "input": ref("inputs/" + identity + ".json", p.canonical(data)),
           "sidecar": ref("inputs/" + identity + "-sidecar.json", p.canonical(side))}
    return row, data, side, messages


def safe_preflight(contract):
    """Synthetic source-only reviewer output, containing no per-case verdicts."""
    return {"schema_version": 1, "role": "source-only-preflight-review", "comparison_id": contract["id"],
        "cases": p.review_case_bindings(contract), "criteria": copy.deepcopy(contract["criteria"]),
        "aggregate": {"answerable": 4, "abstained": 2,
            "abstention_types": {"insufficient": 1, "unresolved_conflict": 1},
            "source_kinds": {"single_document": 2, "multiple_meetings": 2, "mixed": 2},
            "languages": {"ko": 2, "en": 2, "mixed": 2}}}


def contract_fixture():
    models = [{"id": model, "profile": ref(p.PROFILE_PINS[model][0], PUBLIC_PROFILES[model]),
        "binding": ref(f"synthetic/{model}-binding.json", p.canonical(binding(model))), "runtime": runtime(),
        "model_root": f"models/{model}", "asset_files": [ref("synthetic.gguf")]} for model in (p.BASE, p.CANDIDATE)]
    cases = []
    for index in range(6):
        row, _, _, _ = case_fixture(f"case-{index}", [f"공개 합성 서로 다른 원문 {index}😀\n"])
        row.update(family=f"family-{index}", aliases=[], ancestors=[])
        cases.append(row)
    neutral, _, _, _ = case_fixture("public-neutral")
    contract = {"schema_version": 1, "id": "synthetic-contract", "models": models, "cases": cases, "neutral": neutral,
        "order": [x["id"] for x in cases], "epochs": ["neutral", "baseline", "candidate"], "limits": dict(p.LIMITS),
        "code": [], "prompt": r.prompt_binding(), "exclusion": ref("synthetic/exclusion.json"),
        "criteria": ref("synthetic/criteria.lock"), "packet": ref("synthetic/packet.lock")}
    contract["preflight_review"] = ref("synthetic/preflight-review.json", p.canonical(safe_preflight(contract)))
    locks = {"schema_version": 1, "contract_sha256": p.sha(p.canonical(contract)),
        "reviewed_bindings": {m["id"]: m["binding"]["sha256"] for m in models},
        "runtime_sha256": p.sha(p.canonical(runtime())), "allowed_cases": contract["order"],
        **{key: copy.deepcopy(contract[key]) for key in ("exclusion", "criteria", "packet", "code", "prompt", "preflight_review")},
        "predecessors": {"neutral": [], "baseline": [ref("synthetic/neutral-custody.json")],
                         "candidate": [ref("synthetic/neutral-custody.json"), ref("synthetic/baseline-custody.json")]}}
    return contract, locks


def test_policy_deep_freeze_does_not_alias_input():
    raw = binding(p.BASE)
    policy = p.bind_policy(PUBLIC_PROFILES[p.BASE], raw, runtime())
    raw["metadata"][0]["tokenizer"].clear()
    assert len(policy.reviewed["metadata"][0]["tokenizer"]) == 2
    with pytest.raises(TypeError):
        policy.reviewed["metadata"][0]["template"]["size_bytes"] = 0
    with pytest.raises(FrozenInstanceError):
        policy.alias = "wrong"
    assert model_policy(p.CANDIDATE).alias != policy.alias
    expected = p.sha(p.canonical({"profile_sha256": policy.profile_sha256, "shards": p.thaw(policy.shards)}))
    assert policy.alias == expected and policy.alias != policy.shards[0]["sha256"]


@pytest.mark.parametrize("change", ["profile", "model", "template", "tokens", "metadata_missing", "review_missing", "runtime_count", "runtime_hash", "runtime_version", "extra"])
def test_policy_rejects_unreviewed_or_cross_model(change):
    raw, rt, profile = binding(p.CANDIDATE), runtime(), PUBLIC_PROFILES[p.CANDIDATE]
    if change == "profile": profile += b" "
    if change == "model": raw["model_id"] = p.BASE
    if change == "template": raw["template_sha256"] = "0" * 64
    if change == "tokens": raw["tokenizer_sha256"] = "0" * 64
    if change == "metadata_missing": raw["metadata"] = []
    if change == "review_missing": del raw["review_receipt"]
    if change == "runtime_count": rt["files"].pop()
    if change == "runtime_hash": rt["files"][0]["sha256"] = "0" * 64
    if change == "runtime_version": rt["commit"] = "0" * 40
    if change == "extra": raw["approved"] = True
    with pytest.raises((ValueError, KeyError)):
        p.bind_policy(profile, raw, rt)


def test_contract_is_frozen_and_has_closed_six_case_budget():
    contract, locks = contract_fixture()
    bound = p.validate_contract(contract, locks)
    contract["cases"][0]["aliases"].append("changed")
    assert bound.data["cases"][0]["aliases"] == ()
    assert sum(x.calls for x in p.EPOCHS.values()) == 13
    assert sum(x.calls * 256 for x in p.EPOCHS.values()) == 3328


@pytest.mark.parametrize("change", ["extra", "boolean_version", "order", "limit", "fewer", "family", "ancestor", "content", "question", "allowed", "criteria", "exclusion", "model_binding", "runtime", "distribution", "language", "neutral"])
def test_contract_rejects_substitution_even_after_relocking_digest(change):
    contract, locks = contract_fixture()
    if change == "extra": contract["override"] = True
    if change == "boolean_version": contract["schema_version"] = True
    if change == "order": contract["order"].reverse()
    if change == "limit": contract["limits"]["qa_tokens"] = 257
    if change == "fewer": contract["cases"].pop()
    if change == "family": contract["cases"][1]["family"] = contract["cases"][0]["family"]
    if change == "ancestor": contract["cases"][1]["ancestors"] = [contract["cases"][0]["family"]]
    if change == "content": contract["cases"][1]["content_sha256"] = contract["cases"][0]["content_sha256"]
    if change == "question": contract["cases"][1]["question_sha256"] = contract["cases"][0]["question_sha256"]
    if change == "allowed": locks["allowed_cases"] = ["evil"] * 6
    if change == "criteria": contract["criteria"]["sha256"] = "f" * 64
    if change == "exclusion": contract["exclusion"]["sha256"] = "f" * 64
    if change == "model_binding": contract["models"][0]["binding"]["sha256"] = "f" * 64
    if change == "runtime": contract["models"][0]["runtime"]["files"].pop()
    if change == "distribution": contract["cases"][5]["answerability"] = "answerable"
    if change == "language": contract["cases"][2]["language"] = contract["cases"][5]["language"] = "ko"
    if change == "neutral": contract["neutral"]["prepared"] = True
    locks["contract_sha256"] = p.sha(p.canonical(contract))
    with pytest.raises((ValueError, KeyError)):
        p.validate_contract(contract, locks)


def test_duplicate_keys_and_nonfinite_are_rejected():
    for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
        with pytest.raises(ValueError): p.parse(data)


def test_bundle_preserves_unicode_crlf_gaps_document_coordinates_and_message_bytes():
    row, data, side, expected = case_fixture()
    messages, mapping = r.prepare_case(row, data, side)
    assert p.canonical(messages) == p.canonical(expected)
    payload = json.loads(messages[1]["content"])
    assert "".join(x if isinstance(x, str) else x[1] for x in payload["source_parts"]) == data["bundle"]
    for index, item in mapping.items():
        original = next(d for d in data["documents"] if d["document_id"] == item["document_id"])
        assert original["content"][item["start_offset"]:item["end_offset"]] == item["quote"]
        assert side["units"][index]["id"] == index
    assert "\r\n" in data["bundle"] and "👩‍💻" in data["bundle"]


@pytest.mark.parametrize("change", ["id", "offset", "cross_boundary", "quote", "order", "text", "question", "messages"])
def test_bundle_rejects_rewrite_or_remapping(change):
    row, data, side, _ = case_fixture()
    if change == "id": side["units"][0]["id"] = 159
    if change == "offset": side["units"][0]["bundle_start_offset"] += 1
    if change == "cross_boundary": data["documents"][0]["end_offset"] = data["documents"][1]["end_offset"]
    if change == "quote": side["units"][0]["quote"] = "forged"
    if change == "order": data["documents"].reverse()
    if change == "text": data["bundle"] = data["bundle"].replace("\r", "")
    if change == "question": data["question"] += " changed"
    if change == "messages": row["messages_sha256"] = "0" * 64
    with pytest.raises(ValueError): r.prepare_case(row, data, side)


def transport_adapter(*, epoch="baseline", alter=None, clock=None, resource=None, evidence=None):
    clock = clock or Clock()
    selected = p.EPOCHS[epoch]
    policy = model_policy(selected.model_id)
    bodies, adapter = [], None
    def handle(request):
        body = json.loads(request.content) if request.content else None
        bodies.append((request.url.path, request.content))
        if request.url.path == "/apply-template": response = {"prompt": "SYNTHETIC TEMPLATE " + json.dumps(body["messages"], ensure_ascii=False)}
        elif request.url.path == "/tokenize": response = {"tokens": [101, 102, 103]}
        else:
            response = {"model": adapter._alias, "generation_settings": copy.deepcopy(body), "truncated": False,
                "stop": True, "stop_type": "eos", "tokens_predicted": 2, "tokens": [201, 202], "tokens_evaluated": len(body["prompt"]),
                "timings": {"cache_n": 0, "prompt_n": len(body["prompt"]), "predicted_n": 2},
                "content": '{"status":"answered","claims":[{"text":"합성 결정","evidence":[0]}]}'}
        if alter:
            replacement = alter(request.url.path, body, response, clock)
            if replacement is not None: return replacement
        return httpx.Response(200, json=response)
    adapter = PairedQAAdapter("http://127.0.0.1:54321", "t" * 40, policy=policy, epoch=selected,
        case_ids=tuple(f"case-{i}" for i in range(selected.calls)), resource_check=resource or (lambda: None),
        clock=clock, evidence=evidence or (lambda *args: None), transport=httpx.MockTransport(handle))
    # Explicit unit-test transport setup. No serialized prepared object or asset approval.
    adapter._alias, adapter._metadata = policy.alias, {"synthetic_test_only": True}
    return adapter, bodies, clock


def test_baseline_requests_are_byte_equal_to_legacy_candidate():
    adapter, bodies, clock = transport_adapter()
    _, _, _, messages = case_fixture()
    adapter.complete_qa("case-0", messages, 60)
    original_bodies = []
    def handler(request):
        payload = json.loads(request.content)
        original_bodies.append((request.url.path, request.content))
        if request.url.path == "/apply-template": response = {"prompt": "SYNTHETIC TEMPLATE " + json.dumps(payload["messages"], ensure_ascii=False)}
        elif request.url.path == "/tokenize": response = {"tokens": [101, 102, 103]}
        else: response = {"model": legacy.MODEL_SHA, "generation_settings": payload, "truncated": False,
            "stop": True, "stop_type": "eos", "tokens_predicted": 2, "tokens": [201, 202], "tokens_evaluated": 3,
            "timings": {"cache_n": 0, "prompt_n": 3, "predicted_n": 2}, "content": '{"status":"abstained","claims":[]}'}
        return httpx.Response(200, json=response)
    old = legacy.CandidateAdapter("http://127.0.0.1:54321", "t" * 40, "unused-profile", clock=clock,
        transport=httpx.MockTransport(handler), response_format=legacy.CLAIMS_JSON_FORMAT,
        summary_control=legacy.SUMMARY_BUDGET_CONTROL, qa_control=legacy.QA_COVERAGE_CONTROL)
    old._alias = legacy.MODEL_SHA
    old.complete("case-0", "qa", messages, 60)
    assert bodies == original_bodies
    assert "chat_template_kwargs" not in json.loads(bodies[0][1])
    old.close()
    adapter.close()


@pytest.mark.parametrize("epoch,calls", [("neutral", 1), ("baseline", 6), ("candidate", 6)])
def test_epoch_caps_and_duplicate_case(epoch, calls):
    adapter, bodies, _ = transport_adapter(epoch=epoch)
    messages = case_fixture()[3]
    for i in range(calls): adapter.complete_qa(f"case-{i}", messages, 60)
    assert adapter.counts["completions"] == calls and adapter.counts["requested_tokens"] == calls * 256
    with pytest.raises(ValueError): adapter.complete_qa("case-0", messages, 60)
    assert sum(path == "/completion" for path, _ in bodies) == calls
    adapter.close()


@pytest.mark.parametrize("fault", ["redirect", "timeout", "echo", "cache", "count", "boolean_count", "tokens", "timings", "alias", "limit_body"])
def test_inherited_transport_fault_latches_and_prevents_next_dispatch(fault):
    def alter(path, body, response, clock):
        if path != "/completion": return None
        if fault == "redirect": return httpx.Response(302, headers={"location": "https://example.invalid"})
        if fault == "timeout": raise httpx.ReadTimeout("synthetic timeout")
        if fault == "echo": response["generation_settings"]["seed"] = 1
        if fault == "cache": response["timings"]["cache_n"] = 1
        if fault == "count": response["tokens_predicted"] = 3
        if fault == "boolean_count": response["tokens_predicted"] = True
        if fault == "tokens": response["tokens"] = [True, 1]
        if fault == "timings": response["timings"]["predicted_n"] = 9
        if fault == "alias": response["model"] = "other-shard"
        if fault == "limit_body": return httpx.Response(200, content=b"x" * (2 * 1024**2 + 1))
    adapter, bodies, _ = transport_adapter(alter=alter)
    with pytest.raises((ValueError, legacy.WorkerError, GenerationError)): adapter.complete_qa("case-0", case_fixture()[3], 60)
    assert adapter.halted and adapter.counts["completions"] == 1
    with pytest.raises(ValueError): adapter.complete_qa("case-1", case_fixture()[3], 60)
    assert sum(path == "/completion" for path, _ in bodies) == 1
    adapter.close()


def test_input_limit_preserves_source_and_spends_no_completion():
    def alter(path, body, response, clock):
        if path == "/tokenize": response["tokens"] = [1] * 4097
    adapter, bodies, _ = transport_adapter(alter=alter)
    messages = case_fixture()[3]
    original = copy.deepcopy(messages)
    with pytest.raises(Exception) as error: adapter.complete_qa("case-0", messages, 60)
    assert error.value.code == "generation_input_limit"
    assert messages == original and adapter.counts["completions"] == 0 and not adapter.halted
    assert all(path != "/completion" for path, _ in bodies)
    adapter.close()


def test_output_limit_is_content_rejection_and_case_never_retried():
    def alter(path, body, response, clock):
        if path == "/completion": response["stop_type"] = "limit"
    adapter, _, _ = transport_adapter(alter=alter)
    with pytest.raises(Exception) as error: adapter.complete_qa("case-0", case_fixture()[3], 60)
    assert error.value.code == "generation_output_limit" and not adapter.halted
    with pytest.raises(ValueError): adapter.complete_qa("case-0", case_fixture()[3], 60)
    assert adapter.counts["requested_tokens"] == 256
    adapter.close()


@pytest.mark.parametrize("at", ["/apply-template", "/tokenize", "/completion"])
def test_each_http_boundary_uses_same_deadline_and_latches(at):
    def alter(path, body, response, clock):
        if path == at: clock.now = 61
    adapter, bodies, _ = transport_adapter(alter=alter)
    with pytest.raises(ValueError): adapter.complete_qa("case-0", case_fixture()[3], 60)
    assert adapter.halted and adapter._deadline is None
    assert sum(path == "/completion" for path, _ in bodies) == (1 if at == "/completion" else 0)
    adapter.close()


def test_missing_callbacks_unbounded_or_wrong_system_are_rejected():
    with pytest.raises(ValueError):
        PairedQAAdapter("http://127.0.0.1:54321", "t" * 40, policy=model_policy(), epoch=p.EPOCHS["baseline"],
            case_ids=tuple(f"case-{i}" for i in range(6)), resource_check=None, clock=Clock(), evidence=lambda *args: None)
    adapter, bodies, _ = transport_adapter()
    with pytest.raises(ValueError): adapter.complete_qa("case-0", case_fixture()[3], None)
    messages = case_fixture()[3]
    messages[0]["content"] += " override"
    with pytest.raises(ValueError): adapter.complete_qa("case-0", messages, 60)
    assert adapter.halted and not bodies
    adapter.close()


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return ref(name, data)


def metadata_tree(tmp_path, monkeypatch):
    """Synthetic metadata documents only; model/runtime roots deliberately absent."""
    contract, locks = contract_fixture()
    for row in [*contract["cases"], contract["neutral"]]:
        texts = [f"공개 합성 서로 다른 원문 {row['id'].split('-')[-1]}😀\n"] if row["id"].startswith("case-") else None
        _, data, side, _ = case_fixture(row["id"], texts)
        put(tmp_path, row["input"]["file"], p.canonical(data))
        put(tmp_path, row["sidecar"]["file"], p.canonical(side))
    contract["code"] = [put(tmp_path, "synthetic/code.py", b"# synthetic code binding\n")]
    monkeypatch.setattr(r, "CODE_FILES", ("synthetic/code.py",))
    excluded = {"catalogs": {name: "f" * 64 for name in p.CATALOGS}, "families": [], "ids": [],
                "content_hashes": [], "question_hashes": []}
    contract["exclusion"] = put(tmp_path, "synthetic/exclusion.json", p.canonical(excluded))
    for key in ("criteria", "packet"):
        contract[key] = put(tmp_path, f"synthetic/{key}.lock", b"opaque synthetic hash only")
    for model in contract["models"]:
        model_id = model["id"]
        put(tmp_path, model["profile"]["file"], PUBLIC_PROFILES[model_id])
        raw = binding(model_id)
        for key in ("metadata_receipt", "review_receipt"):
            raw[key] = put(tmp_path, f"synthetic/{model_id}-{key}.json", b'{"synthetic":true}')
        gate = {"status": "accepted", "profile_sha256": p.PROFILE_PINS[model_id][1],
            "canonical_root": str(tmp_path / model["model_root"]), "source_commit": "a" * 40,
            "source": [contract["code"][0]], "custody": put(tmp_path, f"synthetic/{model_id}-custody.json", b"opaque synthetic custody")}
        if model_id == p.CANDIDATE:
            attempt = {"operation": "acquire", "token": "synthetic-only", "root": gate["canonical_root"],
                "profile_sha256": gate["profile_sha256"], "retry": False, "shared_seconds": 1800,
                "cleanup_reserved_seconds": 5, "transfer_limit": 5 * 1024**3, "disk_limit": 6 * 1024**3}
            gate.update(kind="external_acquire", actual_cli_exit=0, cleanup_verified=True, attempt_token="synthetic-only",
                final_stdout={"status": "ACQUIRED_VERIFIED_METADATA_UNREVIEWED", "execution_approved": False},
                attempt=put(tmp_path, model["model_root"] + "/attempt.json", p.canonical(attempt)))
        else:
            gate.update(kind="existing_baseline_assets", asset_receipt=put(tmp_path, "synthetic/baseline-assets.json", b"opaque baseline receipt"))
        raw["acquisition_gate"] = put(tmp_path, f"synthetic/{model_id}-gate.json", p.canonical(gate))
        model["binding"] = put(tmp_path, model["binding"]["file"], p.canonical(raw))
        locks["reviewed_bindings"][model_id] = model["binding"]["sha256"]
    contract["preflight_review"] = put(tmp_path, "synthetic/preflight-review.json", p.canonical(safe_preflight(contract)))
    for key in ("code", "exclusion", "criteria", "packet", "preflight_review"):
        locks[key] = copy.deepcopy(contract[key])
    locks["contract_sha256"] = p.sha(p.canonical(contract))
    return contract, locks


def relock(contract, locks):
    locks["contract_sha256"] = p.sha(p.canonical(contract))


def paired_v2_registration(tmp_path, monkeypatch):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    old_contract_sha = locks["contract_sha256"]
    contract["id"] = "meeting-free-qa-paired-v2"
    contract["preflight_review"] = put(tmp_path, "synthetic/preflight-v2.json", p.canonical(safe_preflight(contract)))
    locks["preflight_review"] = contract["preflight_review"]
    locks["predecessors"] = {name: [] for name in p.EPOCHS}
    relock(contract, locks)
    root = ".local/meeting-free-qa-paired-v2"
    contract_ref = put(tmp_path, root + "/contract.json", p.canonical(contract))
    spec = {"schema_version": 1, "contract": contract_ref, "epoch": "neutral", "output_dir": root + "/neutral",
            "predecessors": []}
    spec["once_sha256"] = p.sha(p.canonical({"contract_sha256": locks["contract_sha256"],
        "epoch": "neutral", "output_dir": spec["output_dir"]}))
    registration = put(tmp_path, root + "/registrations/neutral.json", p.canonical(spec))
    # Even valid v2 lock bytes in the old path must never supply v2 authority.
    old = [put(tmp_path, "data/meetings/free-qa-trusted-locks-v1.json", p.canonical(locks)),
           put(tmp_path, ".local/meeting-free-qa-paired-v1/terminal.json", b"opaque closed v1 failure"),
           put(tmp_path, ".local/meeting-free-qa-once/" + old_contract_sha + "-neutral.json", b"opaque consumed v1 epoch")]
    put(tmp_path, r.TRUSTED_LOCK_FILE, p.canonical(locks))
    return contract, locks, spec, registration, old


@pytest.mark.parametrize("fault", [None, "v1_only", "changed_source"])
def test_paired_v2_uses_fixed_trust_and_current_source_binding(tmp_path, monkeypatch, fault):
    assert r.TRUSTED_LOCK_FILE == "data/meetings/free-qa-trusted-locks-v2.json"
    contract, locks, spec, registration, old = paired_v2_registration(tmp_path, monkeypatch)
    if fault == "v1_only": (tmp_path / r.TRUSTED_LOCK_FILE).unlink()
    if fault == "changed_source": (tmp_path / contract["code"][0]["file"]).write_bytes(b"changed source")
    def forbidden(*a, **k): pytest.fail("admission rejection must precede lease/preparation/launch")
    monkeypatch.setattr(r, "worker_lease", forbidden)
    if fault:
        with pytest.raises((ValueError, OSError)):
            r.run_epoch(tmp_path / registration["file"], registration["sha256"], spec["once_sha256"],
                root=tmp_path, clock=Clock(), preparer=forbidden, launcher=forbidden)
    else:
        _, verified, epoch, _, prior = r.load_registration(tmp_path / registration["file"], registration["sha256"], root=tmp_path)
        assert verified.contract.sha256 == locks["contract_sha256"] and verified.contract.data["id"] == "meeting-free-qa-paired-v2"
        assert epoch is p.EPOCHS["neutral"] and prior == 0
        assert verified.lock_ref["file"] == r.TRUSTED_LOCK_FILE
    assert not (tmp_path / spec["output_dir"]).exists()
    assert not (tmp_path / ".local/meeting-free-qa-once" / (spec["once_sha256"] + ".json")).exists()
    for row in old: assert ref(row["file"], (tmp_path / row["file"]).read_bytes()) == row


def test_paired_v2_own_once_preserves_v1_and_blocks_repetition_other_output(tmp_path, monkeypatch):
    _, locks, spec, registration, old = paired_v2_registration(tmp_path, monkeypatch)
    calls, leases = [], []
    @contextmanager
    def lease(path):
        leases.append(path)
        assert path == tmp_path / ".local/meeting-free-qa-comparison.lock"
        yield
    monkeypatch.setattr(r, "worker_lease", lease)
    def preparer(*a, **k):
        calls.append("prepare")
        raise ValueError("synthetic preparation stop before any model")
    def forbidden(*a, **k): pytest.fail("no model may launch")
    def run(reg, value):
        return r.run_epoch(tmp_path / reg["file"], reg["sha256"], value["once_sha256"], root=tmp_path,
            clock=Clock(), preparer=preparer, launcher=forbidden)
    report = run(registration, spec)
    assert report["status"] == "stopped" and report["counts"]["completions"] == 0
    once_dir = tmp_path / ".local/meeting-free-qa-once"
    epoch_file = once_dir / (locks["contract_sha256"] + "-neutral.json")
    assert p.parse(epoch_file.read_bytes())["once_sha256"] == spec["once_sha256"]
    assert p.parse((once_dir / (spec["once_sha256"] + ".json")).read_bytes())["contract_sha256"] == locks["contract_sha256"]
    with pytest.raises(ValueError): run(registration, spec)
    alternate = copy.deepcopy(spec)
    alternate["output_dir"] += "-alternate"
    alternate["once_sha256"] = p.sha(p.canonical({"contract_sha256": locks["contract_sha256"],
        "epoch": "neutral", "output_dir": alternate["output_dir"]}))
    alternate_ref = put(tmp_path, ".local/meeting-free-qa-paired-v2/registrations/alternate.json", p.canonical(alternate))
    with pytest.raises(FileExistsError): run(alternate_ref, alternate)
    assert calls == ["prepare"] and len(leases) == 2
    assert not (once_dir / (alternate["once_sha256"] + ".json")).exists()
    for row in old: assert ref(row["file"], (tmp_path / row["file"]).read_bytes()) == row


def test_metadata_verification_reads_no_models_or_inputs_and_creates_nothing(tmp_path, monkeypatch):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    before = sorted(str(x) for x in tmp_path.rglob("*"))
    original = assets.small_bytes
    reads = []
    def observed(path, limit):
        reads.append(Path(path))
        assert not Path(path).is_relative_to(tmp_path / "inputs") and (not Path(path).is_relative_to(tmp_path / "models") or Path(path).name == "attempt.json")
        return original(path, limit)
    monkeypatch.setattr(assets, "small_bytes", observed)
    monkeypatch.setattr(r.subprocess, "Popen", lambda *a, **k: pytest.fail("native forbidden"))
    verified = r.verify_contract(contract, locks, root=tmp_path)
    assert len(verified.policies) == 2 and reads
    assert sorted(str(x) for x in tmp_path.rglob("*")) == before
    assert not list(tmp_path.rglob("*.gguf")) and not (tmp_path / ".local").exists()


@pytest.mark.parametrize("fault", ["catalog", "family", "ancestor", "id", "content", "question", "extra_input", "missing_input", "gate_exit", "gate_status", "gate_root", "gate_cleanup", "missing_review", "code", "fixed_lock_missing"])
def test_metadata_denials_are_fail_closed_without_native(tmp_path, monkeypatch, fault):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    if fault in {"catalog", "family", "ancestor", "id", "content", "question"}:
        path = contract["exclusion"]["file"]
        excluded = p.parse((tmp_path / path).read_bytes())
        if fault == "catalog": excluded["catalogs"].pop("finaltest")
        if fault in {"family", "ancestor"}:
            value = contract["cases"][0]["family"]
            if fault == "ancestor":
                value = "excluded-ancestor"
                contract["cases"][0]["ancestors"] = [value]
            excluded["families"] = [value]
        if fault == "id": excluded["ids"] = [contract["cases"][0]["id"]]
        if fault == "content": excluded["content_hashes"] = [contract["cases"][0]["content_sha256"]]
        if fault == "question": excluded["question_hashes"] = [contract["cases"][0]["question_sha256"]]
        contract["exclusion"] = put(tmp_path, path, p.canonical(excluded))
        locks["exclusion"] = contract["exclusion"]
    if fault == "extra_input": put(tmp_path, "inputs/unapproved.json", b"public synthetic")
    if fault == "missing_input": (tmp_path / contract["cases"][0]["input"]["file"]).unlink()
    if fault.startswith("gate_") or fault == "missing_review":
        model = contract["models"][1]
        raw = p.parse((tmp_path / model["binding"]["file"]).read_bytes())
        if fault == "missing_review": (tmp_path / raw["review_receipt"]["file"]).unlink()
        else:
            gate = p.parse((tmp_path / raw["acquisition_gate"]["file"]).read_bytes())
            if fault == "gate_exit": gate["actual_cli_exit"] = 1
            if fault == "gate_status": gate["final_stdout"]["status"] = "VERIFY_ONLY"
            if fault == "gate_root": gate["canonical_root"] = str(tmp_path / "unrelated")
            if fault == "gate_cleanup": gate["cleanup_verified"] = False
            raw["acquisition_gate"] = put(tmp_path, raw["acquisition_gate"]["file"], p.canonical(gate))
            model["binding"] = put(tmp_path, model["binding"]["file"], p.canonical(raw))
            locks["reviewed_bindings"][model["id"]] = model["binding"]["sha256"]
    if fault == "code": (tmp_path / contract["code"][0]["file"]).write_bytes(b"changed")
    relock(contract, locks)
    with pytest.raises((ValueError, OSError, BoundaryError)):
        r.verify_contract(contract, None if fault == "fixed_lock_missing" else locks, root=tmp_path)
    assert not (tmp_path / ".local").exists()


def tiny_gguf():
    def string(value):
        raw = value.encode()
        return struct.pack("<Q", len(raw)) + raw
    entries = [("general.architecture", 8, string("synthetic")),
        ("tokenizer.chat_template", 8, string("SYNTHETIC TEMPLATE")),
        ("tokenizer.ggml.model", 8, string("synthetic")),
        ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 2) + string("A") + string("😀"))]
    return b"GGUF" + struct.pack("<IQQ", 3, 1, len(entries)) + b"".join(string(key) + struct.pack("<I", kind) + data for key, kind, data in entries)


def tiny_preparation(tmp_path):
    """Only a few hundred synthetic bytes; never a real model or reviewed profile."""
    blob = tiny_gguf()
    metadata_rows = [assets.KVReader(io.BytesIO(blob)).parse()]
    model_root = tmp_path / "synthetic-assets"
    rt_root = tmp_path / "synthetic-runtime"
    model_root.mkdir(); rt_root.mkdir()
    model_ref = put(model_root, "tiny.gguf", blob)
    rt_refs = [put(rt_root, "llama-server.exe" if i == 0 else f"file-{i}.dll", f"synthetic-{i}".encode()) for i in range(55)]
    rt = {"root": "synthetic-runtime", "tag": "b11429", "commit": p.RUNTIME_COMMIT, "server": "llama-server.exe", "files": rt_refs}
    raw = binding(p.BASE)
    raw.update(metadata=metadata_rows, template_sha256=p.sha(b"SYNTHETIC TEMPLATE"), tokenizer_sha256=p.sha(p.canonical(metadata_rows[0]["tokenizer"])))
    pol = p.ModelPolicy(p.BASE, "synthetic-profile.json", "0" * 64,
        ({"filename": "tiny.gguf", "size_bytes": len(blob), "sha256": p.sha(blob)},), "tiny.gguf", "synthetic-alias", raw, rt)
    contract = p.ComparisonContract({"models": [{"id": p.BASE, "model_root": "synthetic-assets", "asset_files": [model_ref]}]}, "f" * 64)
    # Test-only seal over tiny synthetic assets; production admission is exercised separately.
    admitted = r.AdmittedModel(contract.data["models"][0], pol, tmp_path, (), r._ADMITTED)
    verified = r.VerifiedContract(contract, (pol,), p.freeze({}), tmp_path, admitted_models=(admitted,))
    return verified, model_root, rt_root


def test_full_preparation_hashes_all_synthetic_files_and_binds_actual_kv(tmp_path):
    verified, model_root, _ = tiny_preparation(tmp_path)
    prepared = r.prepare_model(verified, p.BASE, 120, clock=Clock())
    assert len(prepared.files) == 56 and prepared.entry == model_root / "tiny.gguf"
    assert prepared.policy.reviewed["metadata"][0]["tensor_descriptors_or_payload_parsed"] is False
    r.check_prepared(prepared, prepared.policy, Clock(), 120)
    with pytest.raises(ValueError): r.check_prepared({"verified": True}, prepared.policy, Clock(), 120)
    (model_root / "extra").write_bytes(b"unapproved")
    with pytest.raises(ValueError, match="inventory"): r.check_prepared(prepared, prepared.policy, Clock(), 120)


@pytest.mark.parametrize("fault", ["extra", "missing", "mixed", "runtime", "hardlink", "metadata", "during_hash", "deadline"])
def test_full_preparation_rejects_synthetic_filesystem_and_metadata_faults(tmp_path, monkeypatch, fault):
    verified, model_root, rt_root = tiny_preparation(tmp_path)
    clock = Clock()
    if fault == "extra": (model_root / "other.gguf").write_bytes(b"other")
    if fault == "missing": (model_root / "tiny.gguf").unlink()
    if fault == "mixed": (model_root / "tiny.gguf").write_bytes(b"different")
    if fault == "runtime": (rt_root / "extra.dll").write_bytes(b"extra")
    if fault == "hardlink": os.link(model_root / "tiny.gguf", tmp_path / "second-link")
    if fault == "metadata":
        pol = verified.policies[0]
        raw = p.thaw(pol.reviewed); raw["metadata"][0]["tokenizer"] = []
        from dataclasses import replace
        changed = replace(pol, reviewed=raw)
        verified = replace(verified, policies=(changed,),
                           admitted_models=(replace(verified.admitted_models[0], policy=changed),))
    original = r.check_ref
    def check(row, root):
        original(row, root)
        if fault == "during_hash" and row["file"] == "tiny.gguf":
            with (root / row["file"]).open("ab") as stream: stream.write(b"changed")
        if fault == "deadline": clock.now = 121
    monkeypatch.setattr(r, "check_ref", check)
    with pytest.raises((ValueError, OSError, BoundaryError)): r.prepare_model(verified, p.BASE, 120, clock=clock)


@pytest.mark.parametrize("fault", [None, "path", "alias", "build", "ctx", "slot", "sleep", "template", "changed_asset"])
def test_load_requires_prepared_identity_and_exact_props(tmp_path, fault):
    verified, model_root, _ = tiny_preparation(tmp_path)
    clock = Clock()
    prepared = r.prepare_model(verified, p.BASE, 120, clock=clock)
    props = {"model_alias": prepared.policy.alias, "build_info": "b11429-" + p.RUNTIME_COMMIT[:7],
        "model_path": str(prepared.entry), "default_generation_settings": {"n_ctx": 6144},
        "total_slots": 1, "is_sleeping": False, "chat_template": "SYNTHETIC TEMPLATE"}
    if fault == "path": props["model_path"] = str(tmp_path / "wrong.gguf")
    if fault == "alias": props["model_alias"] = "first-shard-only"
    if fault == "build": props["build_info"] = "b11429-1234567"
    if fault == "ctx": props["default_generation_settings"]["n_ctx"] = 4096
    if fault == "slot": props["total_slots"] = True
    if fault == "sleep": props["is_sleeping"] = True
    if fault == "template": props["chat_template"] += " changed"
    if fault == "changed_asset": (model_root / "tiny.gguf").write_bytes(b"changed")
    calls = []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=props)
    adapter = PairedQAAdapter("http://127.0.0.1:54321", "t" * 40, policy=prepared.policy, epoch=p.EPOCHS["baseline"],
        case_ids=tuple(f"case-{i}" for i in range(6)), resource_check=lambda: None, clock=clock,
        evidence=lambda *args: None, transport=httpx.MockTransport(handle))
    adapter.begin_request(120)
    if fault:
        with pytest.raises(ValueError): adapter.load(prepared)
        assert adapter.halted
    else:
        assert adapter.load(prepared) is adapter and adapter._metadata["alias"] == prepared.policy.alias
    assert calls == ([] if fault == "changed_asset" else ["/props"])
    adapter.close()


def qwen_template_props(tmp_path):
    reviewed = binding(p.CANDIDATE)
    reviewed["template_sha256"] = p.sha(QWEN_RAW_TEMPLATE.encode())
    reviewed["metadata"][0]["template"] = {
        "raw_utf8_sha256": reviewed["template_sha256"], "size_bytes": len(QWEN_RAW_TEMPLATE.encode())}
    policy = p.bind_policy(PUBLIC_PROFILES[p.CANDIDATE], reviewed, runtime())
    prepared = SimpleNamespace(policy=policy, entry=tmp_path / "public-template-only.gguf")
    props = {"model_alias": policy.alias, "build_info": "b11429-" + p.RUNTIME_COMMIT[:7],
        "model_path": str(prepared.entry), "default_generation_settings": {"n_ctx": 6144},
        "total_slots": 1, "is_sleeping": False, "chat_template": QWEN_RAW_TEMPLATE[:-1]}
    return prepared, props


def test_qwen_public_template_pins_and_source_derived_runtime_bytes(tmp_path):
    raw = QWEN_RAW_TEMPLATE.encode("utf-8")
    assert len(raw) == 2509 and p.sha(raw) == "d5495a1e5db0611132a97e46a65dbb64a642a499421228b9c8b93229097fa9a4"
    assert raw.endswith(b"\n") and b"\r" not in raw and b"\x00" not in raw
    assert len(raw[:-1]) == 2508 and p.sha(raw[:-1]) == "4e9918361c284a93880606d182d64da6a9fe97cdc1f5c5a78c1c8840444246fc"
    prepared, props = qwen_template_props(tmp_path)
    assert validate_props(props, prepared) == {"build": props["build_info"], "context_tokens": 6144, "slots": 1}
    assert prepared.policy.reviewed["template_sha256"] == p.sha(raw)


@pytest.mark.parametrize("change", ["raw", "extra_lf", "crlf", "content", "space", "trailing_space", "none", "bytes", "integer", "object"])
def test_qwen_runtime_template_rejects_every_unmapped_response(tmp_path, change):
    prepared, props = qwen_template_props(tmp_path)
    template = props["chat_template"]
    props["chat_template"] = {
        "raw": QWEN_RAW_TEMPLATE, "extra_lf": QWEN_RAW_TEMPLATE + "\n",
        "crlf": template.replace("\n", "\r\n"), "content": template.replace("Qwen", "Other"),
        "space": " " + template, "trailing_space": template + " ", "none": None,
        "bytes": template.encode(), "integer": 2508, "object": {"template": template}}[change]
    with pytest.raises(ValueError, match="free_qa_runtime_template"):
        validate_props(props, prepared)


@pytest.mark.parametrize("change", ["model", "tag", "commit", "raw_digest", "raw_size"])
def test_qwen_runtime_template_mapping_requires_exact_admitted_tuple(tmp_path, change):
    prepared, props = qwen_template_props(tmp_path)
    policy = prepared.policy
    if change == "model": policy = replace(policy, model_id=p.BASE)
    if change in {"tag", "commit"}:
        rt = p.thaw(policy.runtime)
        rt[change] = "b99999" if change == "tag" else p.RUNTIME_COMMIT[:7] + "0" * 33
        policy = replace(policy, runtime=rt)
        props["build_info"] = rt["tag"] + "-" + rt["commit"][:7]
    if change in {"raw_digest", "raw_size"}:
        reviewed = p.thaw(policy.reviewed)
        if change == "raw_digest":
            reviewed["template_sha256"] = "0" * 64
            reviewed["metadata"][0]["template"]["raw_utf8_sha256"] = "0" * 64
        else: reviewed["metadata"][0]["template"]["size_bytes"] = 2508
        policy = replace(policy, reviewed=reviewed)
    prepared.policy = policy
    with pytest.raises(ValueError, match="free_qa_runtime_template"):
        validate_props(props, prepared)


@pytest.mark.parametrize("fault", [None, "raw", "type"])
def test_startup_qwen_runtime_template_one_get_zero_generation(tmp_path, fault):
    from scripts import probe_meeting_free_qa_startup as startup

    prepared, props = qwen_template_props(tmp_path)
    if fault == "raw": props["chat_template"] = QWEN_RAW_TEMPLATE
    if fault == "type": props["chat_template"] = {"PRIVATE": "response must not be retained"}
    sent = []
    def handler(request):
        sent.append((request.method, request.url.path))
        assert sent == [("GET", "/props")]
        return httpx.Response(200, stream=httpx.ByteStream(p.canonical(props)))
    metrics = {"props_requests": 0, "props_valid": False, "counts": {"completions": 0, "requested_tokens": 0}}
    service = SimpleNamespace(url="http://127.0.0.1:54321", token="t" * 40)
    def fetch():
        return startup.fetch_props(service, prepared, 120, metrics, lambda: None,
            clock=Clock(), transport=httpx.MockTransport(handler))
    if fault:
        with pytest.raises(ValueError) as caught: fetch()
        assert r.safe_error(caught.value) == {"code": "free_qa_runtime_template", "type": "ContractError"}
        assert "PRIVATE" not in str(caught.value)
    else:
        assert fetch() is None
    assert metrics == {"props_requests": 1, "props_valid": fault is None,
        "counts": {"completions": 0, "requested_tokens": 0}}
    with pytest.raises(ValueError, match="startup_props_once"): fetch()
    assert sent == [("GET", "/props")]


class FakeProcess:
    pid = 424242
    def __init__(self):
        self.stdout = io.BytesIO()
        self.stderr = self.stdin = None
        self.returncode = None
        self.terminations = 0
    def poll(self): return self.returncode
    def terminate(self): self.terminations += 1; self.returncode = 0
    def kill(self): self.terminations += 1; self.returncode = -9
    def wait(self, timeout=None): return self.returncode


class FakeGuard:
    def check(self): return {"synthetic": True}
    @contextmanager
    def arm(self, deadline, metrics):
        metrics["synthetic"] = True
        yield


@pytest.mark.parametrize("fault", [None, "ram", "identity", "drain", "ready_timeout", "ready_exit",
    "guard_deadline", "guard_resources", "guard_ownership", "guard_sampler_join", "dual", "guard_secret", "poll_unavailable"])
def test_launcher_reuses_leases_guard_and_owned_cleanup_without_live_process(tmp_path, monkeypatch, fault):
    import psutil
    verified, _, _ = tiny_preparation(tmp_path)
    clock = Clock()
    prepared = r.prepare_model(verified, p.BASE, 120, clock=clock)
    calls, leases, policies, process = [], [], [], FakeProcess()
    if fault == "poll_unavailable":
        poll = process.poll
        attempts = []
        def transient_poll():
            attempts.append(1)
            if len(attempts) == 1: raise OSError("PRIVATE poll detail")
            return poll()
        process.poll = transient_poll
    @contextmanager
    def lease(path):
        leases.append(path.name)
        yield
    monkeypatch.setattr(r, "worker_lease", lease)
    monkeypatch.setattr(r, "unused_port", lambda: 54321)
    monkeypatch.setenv("LLAMA_ARG_MODEL", "unapproved")
    ram = []
    def memory():
        ram.append(1)
        return SimpleNamespace(available=(7 if fault == "ram" else 8) * 1024**3)
    monkeypatch.setattr(psutil, "virtual_memory", memory)
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return process
    monkeypatch.setattr(r.subprocess, "Popen", popen)
    def identity(proc):
        assert proc is process
        if fault == "identity": raise ValueError("synthetic identity failure")
        return 123.0
    monkeypatch.setattr(r, "owned_create_time", identity)
    class Drain:
        started = False
        thread = SimpleNamespace(is_alive=lambda: False, ident=None)
        def __init__(self, stream):
            assert stream is process.stdout
            if fault == "drain": raise OSError("synthetic drain construction")
        def start(self): pass  # Existing cleanup_owner uses its exact handle-only unstarted branch.
    monkeypatch.setattr(r, "DiscardDrain", Drain)
    class Guard(FakeGuard):
        failure = None
        @contextmanager
        def arm(self, deadline, target):
            try:
                yield
            finally:
                if fault == "dual" or (fault or "").startswith("guard_"):
                    self.failure = "deadline" if fault == "dual" else fault.removeprefix("guard_")
                    if fault == "guard_secret": self.failure = "PRIVATE bearer synthetic-token"
                    raise ValueError("summary_mode_" + self.failure)
    monkeypatch.setattr(r, "make_resource_guard", lambda proc, policy, **kw: policies.append(policy) or Guard())
    def ready(*args, **kwargs):
        clock.now += 4
        if fault in {"ready_timeout", "dual"}: raise TimeoutError("service_startup_timeout")
        if fault == "ready_exit":
            process.returncode = 17
            raise RuntimeError("service_startup_exited")
    monkeypatch.setattr(r, "wait_ready", ready)
    metrics = {}
    if fault and fault != "poll_unavailable":
        with pytest.raises((ValueError, OSError, RuntimeError, BoundaryError)), r.launch_model(prepared, 120, metrics, clock=clock):
            pytest.fail("must not yield")
    else:
        with r.launch_model(prepared, 120, metrics, clock=clock) as service:
            assert service.process is process
    assert leases == ["meeting-generation.gpu.lock", "meeting-generation.worker.lock", "meeting-llama.lease"]
    assert ram == [1]
    assert len(calls) == (0 if fault == "ram" else 1)
    if fault != "ram":
        assert metrics["process_absence_confirmed"] is True and metrics["within_budget"] is True
        assert metrics["cleanup_deadline"] - metrics["cleanup_started_at"] == 5
        assert process.terminations == (0 if fault == "ready_exit" else 1) and process.stdout.closed
        if fault == "poll_unavailable":
            assert metrics["native_poll_observed"] is False
            assert metrics["native_poll_error"] == {"type": "OSError", "code": "free_qa_boundary"}
        else:
            assert metrics["native_poll_observed"] is True
            assert metrics["native_returncode_before_cleanup"] == (17 if fault == "ready_exit" else None)
        argv, kwargs = calls[0]
        assert argv == r.command(prepared, 54321)
        assert "LLAMA_ARG_MODEL" not in kwargs["env"] and kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert "--no-context-shift" in argv and argv[argv.index("--model") + 1] == str(prepared.entry)
    reached_readiness = fault not in {"ram", "identity", "drain"}
    assert policies == ([legacy.RSS6_RESOURCES] if reached_readiness else [])
    if reached_readiness:
        phase = metrics["phases"][0]
        assert phase["phase"] == "native_readiness" and phase["entered_at"] == 0 and phase["elapsed_seconds"] == 4
        assert phase["outcome"] == ("completed" if fault in {None, "poll_unavailable"} else "failed")
        if fault in {"ready_timeout", "dual", "ready_exit"}:
            assert metrics["readiness_error"]["code"] == ("service_startup_exited" if fault == "ready_exit" else "service_startup_timeout")
        else:
            assert "readiness_error" not in metrics
        if fault == "dual" or (fault or "").startswith("guard_"):
            expected = "summary_mode_deadline" if fault == "dual" else "summary_mode_" + fault.removeprefix("guard_")
            if fault == "guard_secret": expected = "free_qa_boundary"
            assert metrics["readiness_guard_failure"] == phase["error"]["code"] == expected
        else:
            assert metrics["readiness_guard_failure"] is None
        assert "PRIVATE" not in p.canonical(metrics).decode() and "synthetic-token" not in p.canonical(metrics).decode()


@pytest.mark.parametrize("error,code", [
    (ValueError("summary_mode_deadline"), "summary_mode_deadline"),
    (ValueError("summary_mode_resources"), "summary_mode_resources"),
    (ValueError("summary_mode_ownership"), "summary_mode_ownership"),
    (ValueError("summary_mode_sampler_join"), "summary_mode_sampler_join"),
    (TimeoutError("service_startup_timeout"), "service_startup_timeout"),
    (RuntimeError("service_startup_exited"), "service_startup_exited"),
    (ValueError("summary_mode_resources PRIVATE bearer synthetic-token"), "free_qa_boundary"),
    (ValueError({"PRIVATE": "synthetic-token"}), "free_qa_boundary"),
    (RuntimeError("PRIVATE prompt synthetic-token"), "free_qa_boundary"),
    (TimeoutError("service_startup_timeout PRIVATE"), "free_qa_boundary"),
    (GenerationError("generation_backend_unavailable"), "generation_backend_unavailable"),
])
def test_diagnostics_safe_errors_are_exact_allowlisted_or_typed(error, code):
    assert r.safe_error(error) == {"type": type(error).__name__, "code": code}


@pytest.mark.parametrize("fault", ["rss", "host", "identity"])
def test_existing_rss6_guard_latches_and_never_kills_reused_pid(fault):
    process, clock = FakeProcess(), Clock()
    state = {"created": 123, "rss": 6 * 1024**3, "available": 2 * 1024**3}
    native = SimpleNamespace(create_time=lambda: state["created"], memory_info=lambda: SimpleNamespace(rss=state["rss"]))
    ps = SimpleNamespace(Process=lambda pid: native, virtual_memory=lambda: SimpleNamespace(available=state["available"]))
    guard = legacy.make_resource_guard(process, legacy.RSS6_RESOURCES, clock=clock, ps=ps, expected_created=123)
    assert guard.check()["rss"] == 6 * 1024**3
    if fault == "rss": state["rss"] += 1
    if fault == "host": state["available"] -= 1
    if fault == "identity": state["created"] = 124
    with pytest.raises(ValueError): guard.check()
    state.update(rss=1, available=8 * 1024**3)
    with pytest.raises(ValueError): guard.check()
    if fault == "identity":
        guard.stop_owned()
        assert process.terminations == 0


def synthetic_execution(tmp_path, monkeypatch, *, epoch_name="baseline", fault=None):
    """Runner integration with explicit in-memory engine/resource doubles only."""
    from dataclasses import replace
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    verified = r.verify_contract(contract, locks, root=tmp_path)
    epoch, clock = p.EPOCHS[epoch_name], Clock()
    output = tmp_path / ".local" / "synthetic-output"
    registration = tmp_path / "synthetic-registration.json"
    registration.write_bytes(b"synthetic registration bytes")
    once = p.sha(b"synthetic-once")
    contract_ref = put(tmp_path, "synthetic/contract.json", p.canonical(contract))
    spec = {"once_sha256": once, "contract": contract_ref, "predecessors": []}
    selected = next(policy for policy in verified.policies if policy.model_id == epoch.model_id)
    fake_policy = replace(selected, runtime={**p.thaw(selected.runtime), "files": []})
    fake_prepared = SimpleNamespace(policy=fake_policy, model_root=tmp_path / "fake-assets", runtime_root=tmp_path / "fake-runtime")
    contract["models"][0 if epoch.model_id == p.BASE else 1]["asset_files"] = []
    verified = replace(verified, contract=p.ComparisonContract(contract, verified.contract.sha256))
    monkeypatch.setattr(r, "load_registration", lambda *a, **kw: (spec, verified, epoch, output, 1 if epoch_name == "baseline" else 0))
    calls, policies, cleanup = [], [], []
    @contextmanager
    def launcher(prepared, deadline, metrics, **kwargs):
        assert prepared is fake_prepared and deadline == 120
        metrics.update(owned_create_time=123, process_creation_attempted=True)
        try:
            yield SimpleNamespace(process=FakeProcess(), url="http://127.0.0.1:54321", token="synthetic-token")
        finally:
            cleanup.append(1)
            metrics.update(within_budget=fault != "cleanup", process_absence_confirmed=fault != "cleanup")
    def guard(process, policy, **kwargs):
        policies.append(policy)
        if fault == "guard_construction":
            clock.now += 2
            raise ValueError("summary_mode_ownership")
        return FakeGuard()
    monkeypatch.setattr(r, "make_resource_guard", guard)
    monkeypatch.setattr(r, "check_prepared", lambda *args: None)
    original_parser = r.grounded_answer_refs
    def parser(text, mapping):
        value = original_parser(text, mapping)
        if fault == "parser_late": clock.now += 61
        return value
    monkeypatch.setattr(r, "grounded_answer_refs", parser)
    original_evidence = r.Evidence
    class Evidence(original_evidence):
        def __call__(self, kind, value):
            if fault == "evidence_write" and kind == "qa": raise OSError("PRIVATE synthetic source must not leak")
            super().__call__(kind, value)
            if fault == "evidence_late" and kind == "qa": clock.now += 61
        def seal(self, report):
            super().seal(report)
            if fault == "seal_late": clock.now = 1026
    monkeypatch.setattr(r, "Evidence", Evidence)
    if fault in {"terminal_write", "terminal_late"}:
        original_open = Path.open
        def opened(path, mode="r", *args, **kwargs):
            if path.name == "terminal.json" and mode == "xb":
                if fault == "terminal_write": raise OSError("synthetic disk failure")
                clock.now = 1026
            return original_open(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, "open", opened)
    class Adapter:
        def __init__(self, *args, **kwargs):
            assert kwargs["epoch"] is epoch and callable(kwargs["resource_check"])
            if fault == "adapter_construction":
                clock.now += 2
                raise ValueError("PRIVATE synthetic token and prompt")
            self.counts = {"completions": 0, "requested_tokens": 0, "http": 0}
            self.halted = False
        def begin_request(self, deadline): assert deadline == 120
        def end_request(self): pass
        def load(self, prepared): assert prepared is fake_prepared
        def complete_qa(self, case_id, messages, deadline):
            calls.append(case_id)
            self.counts["completions"] += 1
            self.counts["requested_tokens"] += 256
            assert deadline - clock() <= 60 and messages[0]["content"] == legacy.QA_COVERAGE_CONTROL.system()
            if len(calls) == 1:
                if fault in {"lost_response", "close_secondary"}: raise GenerationError("generation_backend_unavailable")
                if fault == "content": raise legacy.WorkerError("generation_invalid_evidence", 502)
                if fault == "metadata_changed":
                    (tmp_path / selected.reviewed["review_receipt"]["file"]).write_bytes(b"changed")
                if fault == "preflight_changed":
                    (tmp_path / contract["preflight_review"]["file"]).write_bytes(b"changed")
            return SimpleNamespace(text='{"status":"answered","claims":[{"text":"synthetic","evidence":[0]}]}', input_tokens=9, output_tokens=2)
        def close(self):
            if fault == "close_secondary": raise OSError("synthetic close secondary")
    def run():
        return r.run_epoch(registration, p.sha(registration.read_bytes()), once, root=tmp_path, clock=clock,
            launcher=launcher, preparer=lambda *a, **kw: fake_prepared, adapter_factory=Adapter)
    return run, calls, policies, cleanup, output


@pytest.mark.parametrize("fault", ["adapter_construction", "guard_construction"])
def test_preload_construction_diagnostics_keep_once_cleanup_and_zero_calls(tmp_path, monkeypatch, fault):
    run, calls, _, cleanup, output = synthetic_execution(tmp_path, monkeypatch, epoch_name="neutral", fault=fault)
    report = run()
    assert report["status"] == "stopped" and report["counts"] == {"completions": 0, "requested_tokens": 0, "http": 0}
    assert report["valid_cases"] == 0 and report["AI_quality"] is False and calls == [] and cleanup == [1]
    assert [x["phase"] for x in report["phases"]] == ["asset_preparation", "adapter_construction", "final_custody"]
    assert [x["outcome"] for x in report["phases"]] == ["completed", "failed", "completed"]
    assert report["first_failure"]["code"] == ("summary_mode_ownership" if fault == "guard_construction" else "free_qa_boundary")
    assert all(x["elapsed_seconds"] >= 0 for x in report["phases"])
    assert report["phases"][1]["elapsed_seconds"] == 2 and report["phases"][-1]["entered_at"] == 2
    assert "PRIVATE" not in (output / "report.json").read_text()
    assert "load_resources" not in report["cleanup"]
    with pytest.raises(FileExistsError): run()
    assert calls == [] and cleanup == [1]


@pytest.mark.parametrize("fault", [None, "content", "lost_response", "close_secondary", "parser_late", "evidence_late", "evidence_write", "cleanup", "metadata_changed", "preflight_changed"])
def test_runner_denominator_stop_and_custody_without_engine(tmp_path, monkeypatch, fault):
    run, calls, policies, cleanup, output = synthetic_execution(tmp_path, monkeypatch, fault=fault)
    report = run()
    fatal = fault not in {None, "content"}
    assert report["status"] == ("stopped" if fatal else "completed")
    expected_calls = 6 if fault in {None, "content", "cleanup", "metadata_changed", "preflight_changed"} else 1
    assert calls == [f"case-{i}" for i in range(expected_calls)]
    assert report["denominator"] == 6 and len(report["cases"]) == 6
    assert report["counts"]["completions"] == expected_calls and report["counts"]["requested_tokens"] == expected_calls * 256
    assert sum(x["status"] == "unexecuted" for x in report["cases"]) == 6 - expected_calls
    if fault == "content": assert report["cases"][0]["status"] == "rejected" and report["valid_cases"] == 5
    if fault == "close_secondary":
        assert report["first_failure"]["code"] == "generation_backend_unavailable"
        assert report["secondary_failures"][0]["type"] == "OSError"
    assert report["AI_quality"] is False and report["retries"] == 0 and cleanup == [1]
    assert [x["phase"] for x in report["phases"][:3]] == ["asset_preparation", "adapter_construction", "adapter_load"]
    assert len([x for x in report["phases"] if x["phase"] == "completion"]) == expected_calls
    assert report["phases"][-1]["phase"] == "final_custody"
    assert report["phases"][-1]["outcome"] == ("failed" if fault in {"cleanup", "metadata_changed", "preflight_changed"} else "completed")
    assert policies == [legacy.RSS6_RESOURCES]
    assert "PRIVATE" not in p.canonical(report).decode() and "question" not in p.canonical(report).decode()
    terminal = p.parse((output / "terminal.json").read_bytes())
    assert terminal["status"] == report["status"] and terminal["cleanup_verified"] is (fault != "cleanup")
    assert terminal["report_sha256"] == p.sha((output / "report.json").read_bytes())
    before = list(calls)
    with pytest.raises(FileExistsError): run()
    assert calls == before and cleanup == [1]


@pytest.mark.parametrize("fault", ["content", "lost_response"])
def test_neutral_failure_never_continues_quality(tmp_path, monkeypatch, fault):
    run, calls, _, cleanup, _ = synthetic_execution(tmp_path, monkeypatch, epoch_name="neutral", fault=fault)
    report = run()
    assert report["status"] == "stopped" and report["denominator"] == 1 and calls == ["public-neutral"]
    assert report["valid_cases"] == 0 and report["counts"]["completions"] == 1 and cleanup == [1]


@pytest.mark.parametrize("fault", ["seal_late", "terminal_late", "terminal_write"])
def test_late_or_failed_final_storage_is_never_accepted(tmp_path, monkeypatch, fault):
    run, calls, _, cleanup, output = synthetic_execution(tmp_path, monkeypatch, fault=fault)
    with pytest.raises((ValueError, OSError)): run()
    assert calls == [f"case-{i}" for i in range(6)] and cleanup == [1]
    assert p.parse((output / "late-invalidation.json").read_bytes())["status"] == "INVALIDATED"


def predecessor_tree(tmp_path, monkeypatch, *, epoch_name="candidate", fault=None, comparison_id=None):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    if comparison_id is not None:
        contract["id"] = comparison_id
        contract["preflight_review"] = put(tmp_path, "synthetic/preflight-v2.json", p.canonical(safe_preflight(contract)))
        locks["preflight_review"] = contract["preflight_review"]
        relock(contract, locks)
    refs = []
    for name, count in [("neutral", 1), ("baseline", 6)]:
        terminal = {"status": "completed", "epoch": name, "AI_quality": False,
            "report_sha256": put(tmp_path, f"synthetic/{name}/report.json", b"opaque synthetic report")["sha256"],
            "contract_sha256": locks["contract_sha256"], "registration_sha256": "a" * 64,
            "once_sha256": "b" * 64, "cleanup_verified": True, "within_deadline": True,
            "counts": {"completions": count, "requested_tokens": count * 256, "http": 1 + count * 3}, "valid_cases": count}
        custody = {"epoch": name, "contract_sha256": locks["contract_sha256"], "registration_sha256": "a" * 64,
            "once_sha256": "b" * 64, "actual_cli_exit": 0, "custody_verified": True,
            "final_stdout": {"status": "completed", "epoch": name, "registration_sha256": "a" * 64,
                             "once_sha256": "b" * 64, "AI_quality": False}}
        if name == "neutral":
            if fault == "exit": custody["actual_cli_exit"] = 1
            if fault == "stdout": custody["final_stdout"]["status"] = "unknown"
            if fault == "custody": custody["custody_verified"] = False
            if fault == "source": custody["contract_sha256"] = "0" * 64
            if fault == "once": terminal["once_sha256"] = "0" * 64
            if fault == "neutral": terminal["valid_cases"] = 0
            if fault == "cleanup": terminal["cleanup_verified"] = False
            if fault == "deadline": terminal["within_deadline"] = False
            if fault == "caps": terminal["counts"] = {"completions": 2, "requested_tokens": 512, "http": 7}
            if fault == "epoch": terminal["epoch"] = "baseline"
            if fault == "report": terminal["report_sha256"] = "0" * 64
            if fault == "invalidated": put(tmp_path, f"synthetic/{name}/late-invalidation.json", b"invalidated")
            if fault == "zero_generation": terminal["counts"] = {"completions": 0, "requested_tokens": 0, "http": 1}
            if fault == "startup_terminal":
                terminal = {"diagnostic": "meeting-free-qa-startup-v2", "status": "startup_validated",
                    "registration_sha256": "a" * 64, "once_sha256": "b" * 64, "cleanup_verified": True,
                    "within_deadline": True, "props_requests": 1, "counts": {"completions": 0, "requested_tokens": 0}}
        custody["terminal"] = put(tmp_path, f"synthetic/{name}/terminal.json", p.canonical(terminal))
        refs.append(put(tmp_path, f"synthetic/{name}-custody.json", p.canonical(custody)))
    locks["predecessors"]["baseline"] = refs[:1]
    locks["predecessors"]["candidate"] = refs
    contract_ref = put(tmp_path, "synthetic/contract.json", p.canonical(contract))
    spec = {"schema_version": 1, "contract": contract_ref, "epoch": epoch_name,
            "output_dir": ".local/synthetic-output", "predecessors": locks["predecessors"][epoch_name]}
    spec["once_sha256"] = p.sha(p.canonical({"contract_sha256": locks["contract_sha256"], "epoch": epoch_name, "output_dir": spec["output_dir"]}))
    if fault == "order": spec["predecessors"] = list(reversed(refs))
    if fault == "registration_once": spec["once_sha256"] = "0" * 64
    registration = put(tmp_path, "synthetic/registration.json", p.canonical(spec))
    return registration, locks


@pytest.mark.parametrize("fault", [None, "exit", "stdout", "custody", "source", "once", "neutral", "cleanup", "deadline", "caps", "order", "registration_once", "epoch", "report", "invalidated", "zero_generation", "startup_terminal"])
def test_epoch_predecessors_require_actual_exit_stdout_custody_and_caps(tmp_path, monkeypatch, fault):
    registration, locks = predecessor_tree(tmp_path, monkeypatch, fault=fault)
    def check():
        return r.load_registration(tmp_path / registration["file"], registration["sha256"], trusted_locks=locks, root=tmp_path)
    if fault:
        with pytest.raises(ValueError): check()
    else:
        _, _, epoch, _, prior = check()
        assert epoch is p.EPOCHS["candidate"] and prior == 7 and prior + epoch.calls == 13
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("epoch_name,prior,total", [("neutral", 0, 1), ("baseline", 1, 7), ("candidate", 7, 13)])
def test_paired_v2_fixed_trust_keeps_neutral_quality_order_and_total_budget(tmp_path, monkeypatch, epoch_name, prior, total):
    registration, locks = predecessor_tree(tmp_path, monkeypatch, epoch_name=epoch_name,
        comparison_id="meeting-free-qa-paired-v2")
    put(tmp_path, r.TRUSTED_LOCK_FILE, p.canonical(locks))
    _, verified, epoch, _, actual_prior = r.load_registration(tmp_path / registration["file"], registration["sha256"], root=tmp_path)
    assert verified.contract.data["id"] == "meeting-free-qa-paired-v2"
    assert epoch is p.EPOCHS[epoch_name] and actual_prior == prior
    assert prior + epoch.calls == total and total * 256 <= 3328
    assert [p.parse((tmp_path / row["file"]).read_bytes())["epoch"] for row in locks["predecessors"][epoch_name]] == {
        "neutral": [], "baseline": ["neutral"], "candidate": ["neutral", "baseline"]}[epoch_name]
    if epoch_name == "candidate": assert total * 256 == 3328
    assert not (tmp_path / ".local").exists()


def test_cli_help_and_metadata_verify_have_no_native_network_ram_or_once(tmp_path, monkeypatch, capsys):
    import psutil

    from scripts import probe_meeting_free_qa as cli
    monkeypatch.setattr(psutil, "virtual_memory", lambda: pytest.fail("live RAM forbidden"))
    monkeypatch.setattr(r.subprocess, "Popen", lambda *a, **k: pytest.fail("native forbidden"))
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("network forbidden"))
    with pytest.raises(SystemExit) as result: cli.main(["--help"])
    assert result.value.code == 0
    capsys.readouterr()
    registration, locks = predecessor_tree(tmp_path, monkeypatch)
    original = r.load_registration
    monkeypatch.setattr(r, "load_registration", lambda path, digest: original(path, digest, trusted_locks=locks, root=tmp_path))
    assert cli.main(["verify", "--registration", str(tmp_path / registration["file"]), "--sha256", registration["sha256"]]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "METADATA_VERIFIED_NO_ASSETS_OR_EXECUTION" and out["execution_approved"] is False
    for override in ["--model", "--tokens", "--template", "--download", "--trusted-locks"]:
        with pytest.raises(SystemExit) as error:
            cli.main(["verify", "--registration", "not-read", "--sha256", "0" * 64, override, "override"])
        assert error.value.code == 2
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("fault", ["attempt_token", "verify_only", "source", "custody", "source_commit", "baseline_receipt"])
def test_acquisition_gate_binds_same_attempt_source_and_separate_baseline(tmp_path, monkeypatch, fault):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    model = contract["models"][0 if fault == "baseline_receipt" else 1]
    raw = p.parse((tmp_path / model["binding"]["file"]).read_bytes())
    gate = p.parse((tmp_path / raw["acquisition_gate"]["file"]).read_bytes())
    if fault == "attempt_token": gate["attempt_token"] = "different-attempt"
    if fault == "verify_only":
        attempt = p.parse((tmp_path / gate["attempt"]["file"]).read_bytes())
        attempt["operation"] = "verify-only"
        gate["attempt"] = put(tmp_path, gate["attempt"]["file"], p.canonical(attempt))
    if fault == "source": gate["source"] = []
    if fault == "custody": gate["custody"]["sha256"] = "0" * 64
    if fault == "source_commit": gate["source_commit"] = "unconfirmed"
    if fault == "baseline_receipt": (tmp_path / gate["asset_receipt"]["file"]).unlink()
    raw["acquisition_gate"] = put(tmp_path, raw["acquisition_gate"]["file"], p.canonical(gate))
    model["binding"] = put(tmp_path, model["binding"]["file"], p.canonical(raw))
    locks["reviewed_bindings"][model["id"]] = model["binding"]["sha256"]
    relock(contract, locks)
    with pytest.raises((ValueError, OSError)): r.verify_contract(contract, locks, root=tmp_path)
    assert not (tmp_path / ".local").exists()


def test_reparse_inventory_refuses_before_synthetic_hash(tmp_path, monkeypatch):
    verified, model_root, _ = tiny_preparation(tmp_path)
    original = legacy.linked
    monkeypatch.setattr(legacy, "linked", lambda path: path == model_root / "tiny.gguf" or original(path))
    monkeypatch.setattr(r, "check_ref", lambda *a: pytest.fail("must reject reparse before hash"))
    with pytest.raises(legacy.CandidateFailure, match="reparse"):
        r.prepare_model(verified, p.BASE, 120, clock=Clock())


def test_import_top_levels_have_no_runtime_side_effects(monkeypatch):
    import runpy

    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: pytest.fail("live RAM forbidden"))
    monkeypatch.setattr(r.subprocess, "Popen", lambda *a, **k: pytest.fail("native forbidden"))
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(r, "prepare_model", lambda *a, **k: pytest.fail("assets forbidden"))
    monkeypatch.setattr(r, "worker_lease", lambda *a, **k: pytest.fail("lease forbidden"))
    original_open = Path.open
    def read_only(path, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), "import must not write"
        assert path.suffix in {".py", ".pyc"}, "import must not read data/model assets"
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", read_only)
    for name in ["tools/free_qa/policy.py", "tools/free_qa/adapter.py", "tools/free_qa/runner.py", "scripts/probe_meeting_free_qa.py"]:
        runpy.run_path(str(ROOT / name), run_name="synthetic_import_only")


@pytest.mark.parametrize("field", ["answerability", "abstention_reason", "withholding_reason", "kind", "language"])
def test_executor_case_rejects_per_case_classification_even_if_relocked(field):
    contract, locks = contract_fixture()
    contract["cases"][0][field] = "private classification must not reach executor"
    relock(contract, locks)
    with pytest.raises(ValueError, match="free_qa_case"):
        p.validate_contract(contract, locks)


def test_safe_preflight_has_only_opaque_case_bindings_and_aggregate_counts():
    contract, locks = contract_fixture()
    review = safe_preflight(contract)
    p.validate_contract(contract, locks)
    p.validate_preflight_review(review, contract)
    opaque = {"id", "input", "sidecar", "content_sha256", "question_sha256", "messages_sha256"}
    assert all(set(case) == opaque for case in review["cases"])
    assert all(set(case) == opaque | {"family", "aliases", "ancestors"} for case in contract["cases"])
    assert [case["id"] for case in review["cases"]] == contract["order"] == locks["allowed_cases"]
    assert review["criteria"] == contract["criteria"] == locks["criteria"]
    assert review["aggregate"]["answerable"] == 4 and review["aggregate"]["abstained"] == 2
    assert review["aggregate"]["abstention_types"] == {"insufficient": 1, "unresolved_conflict": 1}
    assert "approved" not in review and "preflight_review" in locks


@pytest.mark.parametrize("fault", ["missing_ref", "missing_file", "swapped_ref", "changed_bytes", "other_cases", "order",
    "input", "sidecar", "content", "question", "messages", "criteria", "comparison", "role", "approved_flag",
    "mapping", "four_two", "boolean_count", "withholding_types", "coverage", "coverage_total"])
def test_preflight_receipt_rejects_missing_substitution_or_bad_aggregate(tmp_path, monkeypatch, fault):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    review = p.parse((tmp_path / contract["preflight_review"]["file"]).read_bytes())
    if fault == "missing_ref": del contract["preflight_review"]
    elif fault == "missing_file": (tmp_path / contract["preflight_review"]["file"]).unlink()
    elif fault == "swapped_ref":
        contract["preflight_review"] = put(tmp_path, "synthetic/registrant-self-review.json", p.canonical(review))
    elif fault == "changed_bytes": (tmp_path / contract["preflight_review"]["file"]).write_bytes(b'{"approved":true}')
    else:
        if fault == "other_cases": review["cases"][0]["id"] = "another-case"
        if fault == "order": review["cases"].reverse()
        if fault in {"input", "sidecar"}: review["cases"][0][fault]["sha256"] = "0" * 64
        if fault in {"content", "question", "messages"}: review["cases"][0][fault + "_sha256"] = "0" * 64
        if fault == "criteria": review["criteria"]["sha256"] = "0" * 64
        if fault == "comparison": review["comparison_id"] = "other-comparison"
        if fault == "role": review["role"] = "registrant-self-approval"
        if fault == "approved_flag": review["approved"] = True
        if fault == "mapping": review["cases"][0]["answerability"] = "answerable"
        if fault == "four_two": review["aggregate"].update(answerable=3, abstained=3)
        if fault == "boolean_count": review["aggregate"]["abstention_types"]["insufficient"] = True
        if fault == "withholding_types": review["aggregate"]["abstention_types"] = {"insufficient": 2, "unresolved_conflict": 0}
        if fault == "coverage": review["aggregate"]["source_kinds"] = {"single_document": 3, "multiple_meetings": 3, "mixed": 0}
        if fault == "coverage_total": review["aggregate"]["languages"] = {"ko": 3, "en": 3, "mixed": 3}
        contract["preflight_review"] = put(tmp_path, contract["preflight_review"]["file"], p.canonical(review))
        # A malformed reviewer receipt still fails even when its exact bytes are trusted.
        locks["preflight_review"] = copy.deepcopy(contract["preflight_review"])
    relock(contract, locks)
    with pytest.raises((ValueError, OSError)):
        r.verify_contract(contract, locks, root=tmp_path)
    assert not (tmp_path / ".local").exists()


def test_private_criteria_is_opaque_hash_only_not_parsed_or_classified(tmp_path, monkeypatch):
    contract, locks = metadata_tree(tmp_path, monkeypatch)
    opaque = b'\xff\xfePRIVATE-SYNTHETIC-UNPARSEABLE-CRITERIA\x00'
    contract["criteria"] = put(tmp_path, contract["criteria"]["file"], opaque)
    locks["criteria"] = copy.deepcopy(contract["criteria"])
    contract["preflight_review"] = put(tmp_path, contract["preflight_review"]["file"], p.canonical(safe_preflight(contract)))
    locks["preflight_review"] = copy.deepcopy(contract["preflight_review"])
    relock(contract, locks)
    parser = p.parse
    seen = []
    def parse_metadata(data):
        assert data != opaque, "private criteria must never reach a parser"
        seen.append(data)
        return parser(data)
    monkeypatch.setattr(p, "parse", parse_metadata)
    monkeypatch.setattr(r, "parse", parse_metadata)
    read_ref = r.read_ref
    criteria_reads = []
    def observe(row, root, *, metadata=True):
        if row["file"] == contract["criteria"]["file"]:
            criteria_reads.append(metadata)
            assert metadata is False
        return read_ref(row, root, metadata=metadata)
    monkeypatch.setattr(r, "read_ref", observe)
    verified = r.verify_contract(contract, locks, root=tmp_path)
    assert criteria_reads == [False] and seen and verified.contract.data["criteria"]["sha256"] == p.sha(opaque)
    assert opaque.decode("latin1") not in p.canonical(verified.contract.data).decode()
