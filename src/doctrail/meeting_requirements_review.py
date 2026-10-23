"""C3 contracts check independently supplied judgments, never manufacture them.

Composition is specific to the registered six/eight fresh cases. Diagnostic plan
reviews cannot change the locked answer score or establish automatic root causes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from doctrail.inference import StrictModel, VersionedRequest
from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_answer_requirements import parse_requirement_plan
from doctrail.meeting_comparison_review import (
    Flag,
    Id,
    Index,
    Judgment,
    JudgmentFile,
    RequiredFact,
    Text,
    exact,
    requires_multiple_sources,
    union_length,
)
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_worker import safe_payload

COUNTS = {"calibration": 6, "validation": 8}
FAMILIES = {"calibration": ("C3-F01", "C3-F02"), "validation": ("C3-F03", "C3-F04")}
SOURCE_LANGUAGES = {"C3-F01": "en", "C3-F02": "ko", "C3-F03": "en", "C3-F04": "ko"}
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RequirementId = Annotated[int, Field(ge=1, le=6)]


class C3Oracle(StrictModel):
    id: Id
    family_id: Literal["C3-F01", "C3-F02", "C3-F03", "C3-F04"]
    provenance: Literal["public", "synthetic"]
    language: Literal["ko", "en"]
    expected_status: Literal["answered", "abstained"]
    required_facts: Annotated[list[RequiredFact], Field(min_length=1, max_length=20)]
    unanswerable_reason: Text | None
    forbidden_inferences: list[Text]
    limitations: list[Text]
    question_author: Id
    oracle_author: Id
    independent_prereviewer: Id
    human_review_count: Annotated[int, Field(ge=0, le=0)]

    @model_validator(mode="after")
    def consistent(self):
        if (len({f.id for f in self.required_facts}) != len(self.required_facts)
                or self.independent_prereviewer in {self.question_author, self.oracle_author}
                or self.provenance != ("public" if self.family_id in {"C3-F01", "C3-F03"}
                                       else "synthetic")):
            raise ValueError("review_oracle_identity")
        missing = any(not f.evidence_alternatives for f in self.required_facts)
        if (missing != (self.expected_status == "abstained")
                or (self.unanswerable_reason is not None) != missing
                or missing and not any(f.evidence_alternatives for f in self.required_facts)
                or not missing and not 3 <= len(self.required_facts) <= 6):
            raise ValueError("review_oracle_answerability")
        return self


class C3OracleFile(VersionedRequest):
    phase: Literal["calibration", "validation"]
    cases: list[C3Oracle]


def validate_oracles(inputs, data, phase):
    """Explicit requested language and OR-of-AND whole-block evidence; no script inference."""
    oracles = C3OracleFile.model_validate(data)
    if (phase not in COUNTS or oracles.phase != phase or inputs.get("phase") != phase
            or [o.id for o in oracles.cases] != [c["id"] for c in inputs["cases"]]
            or len(oracles.cases) != COUNTS[phase]
            or len({o.id for o in oracles.cases}) != COUNTS[phase]):
        raise ValueError("review_oracle_cases")
    families = FAMILIES[phase]
    if {o.family_id for o in oracles.cases} != set(families):
        raise ValueError("review_oracle_composition")
    for family in families:
        rows = [o for o in oracles.cases if o.family_id == family]
        ko = 2 if phase == "validation" or family == "C3-F01" else 1
        absent = [o.language for o in rows if o.expected_status == "abstained"]
        expected_absent = ["en", "ko"] if phase == "validation" else [
            "ko" if family == "C3-F01" else "en"]
        if (len(rows) != COUNTS[phase] // 2 or sum(o.language == "ko" for o in rows) != ko
                or sum(o.expected_status == "answered" for o in rows) != 2
                or sorted(absent) != expected_absent):
            raise ValueError("review_oracle_composition")
    multi = 0
    crossed = set()
    family_documents = {f: set() for f in families}
    for case, oracle in zip(inputs["cases"], oracles.cases, strict=True):
        request = AnswerRequest.model_validate(case["payload"])
        if case.get("response_language") != oracle.language:
            raise ValueError("review_oracle_language")
        contexts = [c.model_dump() for c in request.contexts]
        catalog = build_block_catalog(request.contexts)
        units = {(u.chunk_id, u.start_offset, u.end_offset, u.quote) for u in catalog.spans
                 if u.quote.strip()}
        for fact in oracle.required_facts:
            for alternative in fact.evidence_alternatives:
                keys = [(e.chunk_id, e.start_offset, e.end_offset, e.quote) for e in alternative]
                if (len(set(keys)) != len(keys) or any(k not in units for k in keys)
                        or not all(exact(e.model_dump(), contexts) for e in alternative)):
                    raise ValueError("review_oracle_evidence")
        documents = {(c.document_id, c.revision) for c in request.contexts}
        family_documents[oracle.family_id].update(documents)
        multi += requires_multiple_sources(oracle, contexts)
        if oracle.expected_status == "answered" and SOURCE_LANGUAGES[oracle.family_id] != oracle.language:
            crossed.add((SOURCE_LANGUAGES[oracle.family_id], oracle.language))
    if (multi < 2 or crossed != {("ko", "en"), ("en", "ko")}
            or any(not 1 <= len(d) <= 2 for d in family_documents.values())
            or family_documents[families[0]] & family_documents[families[1]]):
        raise ValueError("review_oracle_complexity")
    return oracles


class ExposureAttestation(VersionedRequest):
    reviewer_id: Id
    registered_at: Text
    actual_model: Id
    actual_effort: Literal["xhigh"]
    role_nonparticipation: Flag
    participating_roles: list[Id]
    mapping_seen: Flag
    plan_seen: Flag
    raw_trace_seen: Flag
    prior_judgments_seen: Flag
    model_metadata_seen: Flag
    hypothesis_metadata_seen: Flag
    prior_results_metadata_seen: Flag
    self_report_basis: Text
    human_review_count: Annotated[int, Field(ge=0, le=0)]

    @model_validator(mode="after")
    def timestamp(self):
        if datetime.fromisoformat(self.registered_at).tzinfo is None:
            raise ValueError("review_exposure_timestamp")
        return self


def validate_attestation(data, reviewer_id, excluded_roles, *, pack_opened_at=None):
    value = ExposureAttestation.model_validate(data)
    if (value.reviewer_id != reviewer_id or reviewer_id in excluded_roles
            or value.actual_model != "gpt-6-astra" or not value.role_nonparticipation
            or value.participating_roles or value.mapping_seen or value.plan_seen
            or value.raw_trace_seen or value.prior_judgments_seen):
        raise ValueError("review_role_or_exposure_conflict")
    if pack_opened_at is not None:
        opened = datetime.fromisoformat(pack_opened_at)
        if opened.tzinfo is None or datetime.fromisoformat(value.registered_at) > opened:
            raise ValueError("review_exposure_not_preregistered")
    return value


def exposure_label(attestation):
    return ("metadata-exposed, label-masked" if any((attestation.model_metadata_seen,
        attestation.hypothesis_metadata_seen, attestation.prior_results_metadata_seen))
        else "self-reported label-masked; metadata unexposed")


class PlanSupport(StrictModel):
    evidence_id: Index
    start_offset: Index
    end_offset: Annotated[int, Field(ge=1)]


class RequirementDiagnostic(StrictModel):
    requirement_id: RequirementId
    oracle_fact_ids: list[Id]
    need_relevant: Flag
    support_assessment: Literal["sufficient", "partial", "unsupported", "not_assessable"]
    status_justified: Flag
    reason: Text
    support_offsets: list[PlanSupport]


class OracleCoverage(StrictModel):
    fact_id: Id
    requirement_ids: list[RequirementId]
    need_covered: Flag
    reason: Text


class RealizationCheck(StrictModel):
    requirement_id: RequirementId
    fully_realized: Flag
    added_inference: Flag
    reason: Text


class FailureCategory(StrictModel):
    category: Literal["requirement_omission", "evidence_misclassification", "realization_omission",
                      "added_inference", "abstention_choice"]
    evidence: Text


class PlanDiagnostic(StrictModel):
    sample_id: Id
    plan_sha256: Digest
    requirements: Annotated[list[RequirementDiagnostic], Field(min_length=1, max_length=6)]
    oracle_coverage: list[OracleCoverage]
    realization_checks: Annotated[list[RealizationCheck], Field(max_length=6)]
    abstention_branch: Literal["stage1", "stage2"] | None
    abstention_appropriate: Flag | None
    abstention_reason: Text | None
    failure_categories: list[FailureCategory]


class PlanDiagnosticFile(VersionedRequest):
    purpose: Literal["post_lock_plan_diagnostic"]
    reviewer_id: Id
    answer_lock_sha256: Digest
    plan_pack_sha256: Digest
    human_review_count: Annotated[int, Field(ge=0, le=0)]
    items: list[PlanDiagnostic]


def validate_plan_diagnostics(data, samples, *, reviewer_id, answer_lock_sha256, plan_pack_sha256):
    """samples are replayed plan-pack rows, only available after the answer lock.

    Each row has sample_id/plan_sha256/plan/contexts/oracle/response_language/answer.
    Hash-to-bytes and lock ordering belong to the audit, not this shape validator.
    """
    parsed = PlanDiagnosticFile.model_validate(data)
    if (parsed.reviewer_id != reviewer_id or parsed.answer_lock_sha256 != answer_lock_sha256
            or parsed.plan_pack_sha256 != plan_pack_sha256
            or len({s["sample_id"] for s in samples}) != len(samples)
            or [r.sample_id for r in parsed.items] != [s["sample_id"] for s in samples]):
        raise ValueError("review_diagnostic_binding")
    for row, sample in zip(parsed.items, samples, strict=True):
        oracle = C3Oracle.model_validate(sample["oracle"])
        contexts = AnswerRequest.model_validate({"schema_version": 1, "query": "diagnostic",
                                                 "contexts": sample["contexts"]}).contexts
        catalog = build_block_catalog(contexts)
        plan = parse_requirement_plan(safe_payload(sample["plan"]), catalog, sample["response_language"])
        rids = [r.requirement_id for r in plan.requirements]
        fids = [f.id for f in oracle.required_facts]
        if (row.plan_sha256 != sample["plan_sha256"]
                or [r.requirement_id for r in row.requirements] != rids
                or [f.fact_id for f in row.oracle_coverage] != fids
                or len({f.category for f in row.failure_categories}) != len(row.failure_categories)):
            raise ValueError("review_diagnostic_coverage")
        for review, requirement in zip(row.requirements, plan.requirements, strict=True):
            if (len(set(review.oracle_fact_ids)) != len(review.oracle_fact_ids)
                    or not set(review.oracle_fact_ids) <= set(fids)):
                raise ValueError("review_diagnostic_fact_ids")
            if review.support_assessment in {"sufficient", "partial"} and not review.support_offsets:
                raise ValueError("review_diagnostic_support")
            for support in review.support_offsets:
                if support.evidence_id not in requirement.evidence_ids:
                    raise ValueError("review_diagnostic_support")
                unit = catalog.spans[support.evidence_id]
                if not unit.start_offset <= support.start_offset < support.end_offset <= unit.end_offset:
                    raise ValueError("review_diagnostic_support")
        for coverage in row.oracle_coverage:
            if (len(set(coverage.requirement_ids)) != len(coverage.requirement_ids)
                    or not set(coverage.requirement_ids) <= set(rids)
                    or coverage.need_covered and not coverage.requirement_ids
                    or set(coverage.requirement_ids) != {r.requirement_id for r in row.requirements
                                                        if coverage.fact_id in r.oracle_fact_ids}):
                raise ValueError("review_diagnostic_requirement_ids")
        answered = sample["answer"]["status"] == "answered"
        if answered:
            if (not plan.supported or len(sample["answer"]["claims"]) != len(rids)
                    or [c.requirement_id for c in row.realization_checks] != rids
                    or row.abstention_branch is not None or row.abstention_appropriate is not None
                    or row.abstention_reason is not None):
                raise ValueError("review_diagnostic_branch")
        elif (row.realization_checks or row.abstention_branch != ("stage2" if plan.supported else "stage1")
                or row.abstention_appropriate is None or row.abstention_reason is None):
            raise ValueError("review_diagnostic_branch")
    return parsed


def validate_judgments(pack, data, reviewer_id, excluded_roles, attestation):
    """Validate final answers only, without mapping or plans. No selection gate here."""
    exposure = validate_attestation(attestation, reviewer_id, excluded_roles)
    parsed = JudgmentFile.model_validate(data)
    samples = pack["samples"]
    if (parsed.reviewer_id != reviewer_id
            or len({s["sample_id"] for s in samples}) != len(samples)
            or [j.sample_id for j in parsed.judgments] != [s["sample_id"] for s in samples]):
        raise ValueError("review_sample_set")
    rows = []
    for sample, judgment in zip(samples, parsed.judgments, strict=True):
        oracle = C3Oracle.model_validate(sample["oracle"])
        if reviewer_id in {oracle.question_author, oracle.oracle_author, oracle.independent_prereviewer}:
            raise ValueError("review_role_conflict")
        rows.append(score_sample(sample, judgment.model_dump()))
    return {"rows": rows, "reviewer_id": reviewer_id, "human_review_count": 0,
            "exposure": exposure_label(exposure)}


def score_sample(sample, raw_judgment):
    """Check an independent review, returning counts; never supply missing votes."""
    judgment = Judgment.model_validate(raw_judgment)
    oracle = C3Oracle.model_validate(sample["oracle"])
    answer, contexts = sample["answer"], sample["contexts"]
    claims = answer["claims"]
    if (answer.get("status") not in {"answered", "abstained"}
            or not isinstance(claims, list)
            or answer["status"] == "answered" and (not claims or answer.get("reason") is not None)
            or answer["status"] == "abstained" and (
                claims or answer.get("reason") != "insufficient_evidence")):
        raise ValueError("review_answer_contract")
    if (judgment.sample_id != sample["sample_id"]
            or [c.claim_index for c in judgment.claims] != list(range(len(claims)))
            or [f.fact_id for f in judgment.required_facts] != [f.id for f in oracle.required_facts]):
        raise ValueError("review_coverage")
    total_citations = exact_citations = relevant = supported = facts = 0
    supports, quotes, per_claim = [], [], []
    for claim, review in zip(claims, judgment.claims, strict=True):
        citations = claim["citations"]
        if ([c.citation_index for c in review.citations] != list(range(len(citations)))
                or not citations):
            raise ValueError("review_citation_coverage")
        total_citations += len(citations)
        exact_citations += sum(exact(c, contexts) for c in citations)
        relevant += sum(c.relevant for c in review.citations)
        per_claim.append(sum(c["end_offset"] - c["start_offset"] for c in citations))
        for citation in citations:
            context = next(c for c in contexts if c["chunk_id"] == citation["chunk_id"])
            quotes.append(((context["document_id"], context["revision"]),
                           citation["start_offset"], citation["end_offset"]))
        for fact in review.facts:
            facts += 1
            supported += fact.supported
            for span in fact.support:
                if span.citation_index >= len(citations):
                    raise ValueError("review_support_index")
                citation = citations[span.citation_index]
                if (not exact(citation, contexts)
                        or not citation["start_offset"] <= span.start_offset < span.end_offset
                        <= citation["end_offset"]
                        or not review.citations[span.citation_index].relevant):
                    raise ValueError("review_support_range")
                context = next(c for c in contexts if c["chunk_id"] == citation["chunk_id"])
                supports.append(((context["document_id"], context["revision"]),
                                 span.start_offset, span.end_offset))
    abstained = answer["status"] == "abstained" and answer["reason"] == "insufficient_evidence"
    answered = answer["status"] == "answered" and bool(claims)
    correct_status = (answered if oracle.expected_status == "answered" else abstained)
    complete = all(f.present for f in judgment.required_facts) if answered else abstained and correct_status
    quality = judgment.quality.model_dump()
    derived = {"citation_exact": exact_citations == total_citations,
               "claim_support": supported == facts and (facts > 0 or abstained),
               "completeness": complete, "correct_abstention_or_answer": correct_status}
    if any(quality[k] != v for k, v in derived.items()):
        raise ValueError("review_quality_inconsistent")
    full = all(quality.values()) and relevant == total_citations and (answered or abstained)
    if judgment.full_correct != full:
        raise ValueError("review_full_inconsistent")
    source = [((c["document_id"], c["revision"]), c["start_offset"], c["end_offset"])
              for c in contexts]
    source_unique, quote_unique, support_unique = map(union_length, (source, quotes, supports))
    quote_total = sum(per_claim)
    return {"sample_id": judgment.sample_id, "full_correct": full, "quality": quality,
        "citations": total_citations, "exact_citations": exact_citations,
        "citation_exact_rate": exact_citations / total_citations if total_citations else None,
        "relevant_citation_links": relevant, "irrelevant_citation_links": total_citations - relevant,
        "citation_precision": relevant / total_citations if total_citations else None,
        "facts": facts, "supported_facts": supported,
        "fact_support_rate": supported / facts if facts else None,
        "source_codepoints": sum(len(c["text"]) for c in contexts),
        "source_unique_codepoints": source_unique, "claim_citation_codepoints": per_claim,
        "citation_codepoints": quote_total, "citation_unique_codepoints": quote_unique,
        "citation_duplicate_codepoints": quote_total - quote_unique,
        "support_unique_codepoints": support_unique,
        "source_quoted_fraction": quote_unique / source_unique if source_unique else None,
        "quote_to_support_width": quote_unique / support_unique if support_unique else None}
