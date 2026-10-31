"""Explicit one-call agenda analysis; QA and default analysis remain unchanged."""
from __future__ import annotations

import copy
import hashlib
import time

from doctrail import meeting_agenda_extraction as agenda
from doctrail.inference import WorkerError
from doctrail.meeting_structured import StructuredMeetingRuntime, literal_optional_analysis

LEGACY_ANALYSIS_CONTRACT = "legacy"
AGENDA_ANALYSIS_CONTRACT = agenda.MODE
ANALYSIS_CONTRACTS = (LEGACY_ANALYSIS_CONTRACT, AGENDA_ANALYSIS_CONTRACT)


def analysis_contract_metadata(contract):
    if contract not in ANALYSIS_CONTRACTS:
        raise ValueError("unknown_analysis_contract")
    if contract == LEGACY_ANALYSIS_CONTRACT:
        return {"name": contract, "flow": "classification_summary_review",
                "review": "same_model_not_independent", "semantic_quality_accepted": False}
    return {"name": contract, "prompt_sha256": hashlib.sha256(agenda.PROMPT.encode("utf-8")).hexdigest(),
            "prompt_hash_scope": "static_joint_extraction_prompt", "native_calls_per_analysis": 1,
            "input_tokens": agenda.INPUT_TOKENS, "context_tokens": agenda.CONTEXT_TOKENS,
            "output_tokens": agenda.OUTPUT_TOKENS, "shared_request_seconds": agenda.DEADLINE_SECONDS,
            "classification_calls": 0, "review_calls": 0, "review_performed": False,
            "semantic_quality_accepted": False}


class AgendaMeetingRuntime(StructuredMeetingRuntime):
    """Only analyze is replaced; inherited QA, lock and request cleanup stay intact."""

    def __init__(self, generator, **kwargs):
        super().__init__(generator, **kwargs)
        self.analysis_contract_info = analysis_contract_metadata(AGENDA_ANALYSIS_CONTRACT)

    def health(self):
        result = copy.deepcopy(super().health())
        result["analysis_contract"] = dict(self.analysis_contract_info)
        result["limits"].update(analysis_units=160, analysis_native_calls=1)
        structured = result["runtime"].get("structured_output")
        if isinstance(structured, dict):
            structured.update(analysis_contract=AGENDA_ANALYSIS_CONTRACT,
                              review="not_performed_for_agenda_extraction_v1")
        return result

    def analyze(self, request):
        def run(deadline, telemetry):
            def check_time():
                if time.monotonic() >= deadline:
                    raise WorkerError("generation_deadline_exceeded", 504)

            check_time()
            self.last_stage = "agenda_extraction"
            view = agenda.build_view(request.title, request.content)
            messages = agenda.extraction_messages(view)
            check_time()
            # StructuredGenerator records the exact prepared body/count and rejects
            # >6144 before completion dispatch; avoid an unobserved duplicate check.
            output = self.generator.structured(messages, deadline, "agenda_extraction",
                                               agenda.SCHEMA, agenda.OUTPUT_TOKENS)
            telemetry.append({"operation": "agenda_extraction", "completion_calls": 1,
                "input_tokens": output.input_tokens, "output_tokens": output.output_tokens,
                "output_cap": agenda.OUTPUT_TOKENS, "elapsed_seconds": output.elapsed_seconds,
                "finish_reason": output.finish_reason})
            check_time()
            if type(output.output_tokens) is not int or not 0 < output.output_tokens <= agenda.OUTPUT_TOKENS:
                raise WorkerError("generation_output_truncated", 502)
            self.last_stage = "agenda_assembly"
            analysis, diagnostics = agenda.compile_extraction(output.text, view,
                metadata_projector=literal_optional_analysis, finish_reason=output.finish_reason)
            telemetry.append(diagnostics)
            return {"analysis": analysis, "analysis_contract": dict(self.analysis_contract_info),
                    "summary_review": {"performed": False, "status": "not_performed",
                                       "semantic_quality_accepted": False}}
        return self._run(run)
