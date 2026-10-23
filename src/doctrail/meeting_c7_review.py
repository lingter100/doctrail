"""C7 independent final-answer contracts; no semantic votes are synthesized."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from doctrail.inference import StrictModel, VersionedRequest
from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_comparison_review import (
    Flag,
    Id,
    Judgment,
    JudgmentFile,
    RequiredFact,
    Text,
    exact,
    union_length,
)
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_requirements_review import ExposureAttestation as BaseExposure
from doctrail.meeting_requirements_review import exposure_label

COUNTS = {"calibration": 6, "validation": 8}
FAMILIES = {"calibration": ("c7-f01", "c7-f02"), "validation": ("c7-f03", "c7-f04")}


class SourceDocument(StrictModel):
    document_id: Id
    revision: Annotated[int, Field(strict=True, ge=1)]
    kind: Literal["general", "meeting"]
    language: Literal["ko", "en"]
    meeting_date: str | None


class C7Oracle(StrictModel):
    public_families: ClassVar[set[str]] = {"c7-f01", "c7-f03"}
    id: Id
    family_id: Literal["c7-f01", "c7-f02", "c7-f03", "c7-f04"]
    provenance: Literal["public", "synthetic"]
    language: Literal["ko", "en"]
    expected_status: Literal["answered", "abstained"]
    required_facts: Annotated[list[RequiredFact], Field(min_length=3, max_length=6)]
    source_documents: Annotated[list[SourceDocument], Field(min_length=3, max_length=3)]
    unanswerable_reason: Text | None
    forbidden_inferences: list[Text]
    limitations: list[Text]
    question_author: Id
    oracle_author: Id
    independent_prereviewer: Id
    human_review_count: Annotated[int, Field(strict=True, ge=0, le=0)]

    @model_validator(mode="after")
    def consistent(self):
        missing = any(not f.evidence_alternatives for f in self.required_facts)
        if (len({f.id for f in self.required_facts}) != len(self.required_facts)
                or self.independent_prereviewer in {self.question_author, self.oracle_author}
                or self.provenance != ("public" if self.family_id in self.public_families else "synthetic")
                or missing != (self.expected_status == "abstained")
                or (self.unanswerable_reason is not None) != missing
                or missing and not any(f.evidence_alternatives for f in self.required_facts)):
            raise ValueError("c7_oracle_contract")
        documents = self.source_documents
        meetings = [d for d in documents if d.kind == "meeting"]
        if (len({(d.document_id, d.revision) for d in documents}) != 3 or len(meetings) != 2
                or any(d.meeting_date is not None for d in documents if d.kind == "general")
                or any(d.meeting_date is None for d in meetings)
                or len({d.meeting_date for d in meetings}) != 2):
            raise ValueError("c7_source_composition")
        for document in meetings:
            if datetime.strptime(document.meeting_date, "%Y-%m-%d").date().isoformat() != document.meeting_date:
                raise ValueError("c7_source_date")
        return self


class C7OracleFile(VersionedRequest):
    phase: Literal["calibration", "validation"]
    cases: list[C7Oracle]


class AnonymousOracle(C7Oracle):
    public_families: ClassVar[set[str]] = {"family-public"}
    family_id: Literal["family-public", "family-synthetic"]


def review_oracle(value):
    model = AnonymousOracle if value.get("family_id") in {"family-public", "family-synthetic"} else C7Oracle
    return model.model_validate(value)


IDENTIFIER_KEYS = {"id", "family_id", "document_id", "chunk_id", "question_author", "oracle_author", "independent_prereviewer"}


def pack_identifiers(case, oracle):
    identifiers = {"meeting-answer-single-thinking-c7-v1", "meeting-answer-single-thinking-c4-v1"}
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in IDENTIFIER_KEYS and isinstance(child, str):
                    identifiers.add(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(case)
    visit(oracle.model_dump())
    return identifiers


def validate_pack_eligibility(case, oracle):
    domains = [{case["id"], oracle.id}, {oracle.family_id},
               {oracle.question_author, oracle.oracle_author, oracle.independent_prereviewer},
               {f.id for f in oracle.required_facts}, {d.document_id for d in oracle.source_documents},
               {c["chunk_id"] for c in case["payload"]["contexts"]}]
    if any(current & prior for index, current in enumerate(domains) for prior in domains[:index]):
        raise ValueError("c7_identifier_domain_collision")
    identifiers = pack_identifiers(case, oracle)
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in IDENTIFIER_KEYS:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and any(identity in value for identity in identifiers):
            raise ValueError("c7_identifier_in_natural_language")
    visit(case)
    visit(oracle.model_dump())


def sufficient_documents(oracle, contexts):
    """Exact OR-of-AND sets; <=3 adopted documents keeps the state space <=8."""
    lookup = {c["chunk_id"]: (c["document_id"], c["revision"]) for c in contexts}
    possibilities = {frozenset()}
    for fact in oracle.required_facts:
        alternatives = {frozenset(lookup[e.chunk_id] for e in a) for a in fact.evidence_alternatives}
        possibilities = {a | b for a in possibilities for b in alternatives}
    return possibilities


def validate_oracles(inputs, data, phase):
    parsed = C7OracleFile.model_validate(data)
    if (phase not in COUNTS or parsed.phase != phase or inputs.get("phase") != phase
            or len(parsed.cases) != COUNTS[phase]
            or [o.id for o in parsed.cases] != [c["id"] for c in inputs["cases"]]
            or len({o.id for o in parsed.cases}) != COUNTS[phase]):
        raise ValueError("c7_oracle_cases")
    for family in FAMILIES[phase]:
        rows = [o for o in parsed.cases if o.family_id == family]
        expected = {(lang, "answered"): 1 for lang in ("ko", "en")}
        expected |= ({("ko", "abstained"): 1, ("en", "abstained"): 1} if phase == "validation"
                     else {("ko" if family == "c7-f01" else "en", "abstained"): 1})
        if len(rows) != sum(expected.values()) or any(sum((o.language, o.expected_status) == key for o in rows) != n
                                                     for key, n in expected.items()):
            raise ValueError("c7_family_quota")
    modes, cross, multi, family_docs = set(), set(), 0, {}
    for case, oracle in zip(inputs["cases"], parsed.cases, strict=True):
        if len(case["payload"]["query"].encode("utf-8")) > 512:
            raise ValueError("c7_question_bytes")
        validate_pack_eligibility(case, oracle)
        request = AnswerRequest.model_validate(case["payload"])
        if not request.contexts or case.get("response_language") != oracle.language:
            raise ValueError("c7_explicit_language")
        contexts = [c.model_dump() for c in request.contexts]
        documents = {(d.document_id, d.revision): d for d in oracle.source_documents}
        current = [d.model_dump() for d in oracle.source_documents]
        if oracle.family_id in family_docs and family_docs[oracle.family_id] != current:
            raise ValueError("c7_family_document_drift")
        family_docs[oracle.family_id] = current
        if any((c.document_id, c.revision) not in documents for c in request.contexts):
            raise ValueError("c7_unregistered_document")
        catalog = build_block_catalog(request.contexts)
        units = {(u.chunk_id, u.start_offset, u.end_offset, u.quote) for u in catalog.spans if u.quote.strip()}
        for fact in oracle.required_facts:
            for alternative in fact.evidence_alternatives:
                keys = [(e.chunk_id, e.start_offset, e.end_offset, e.quote) for e in alternative]
                if len(set(keys)) != len(keys) or any(k not in units for k in keys) or not all(exact(e.model_dump(), contexts) for e in alternative):
                    raise ValueError("c7_oracle_evidence")
        if oracle.expected_status != "answered":
            continue
        sufficient = sufficient_documents(oracle, contexts)
        multi += all(len(group) >= 2 for group in sufficient)
        if all(all(documents[d].kind == "general" for d in group) for group in sufficient):
            modes.add("general")
        if all(len(group) >= 2 and all(documents[d].kind == "meeting" for d in group) for group in sufficient):
            modes.add("meetings")
        if all({documents[d].kind for d in group} == {"general", "meeting"} for group in sufficient):
            modes.add("mixed")
        if all(any(documents[d].language != oracle.language for d in group) for group in sufficient):
            cross.add(oracle.language)
    identities = [{(d["document_id"], d["revision"]) for d in rows} for rows in family_docs.values()]
    if (len(family_docs) != 2 or identities[0] & identities[1] or multi < 2
            or modes != {"general", "meetings", "mixed"} or cross != {"ko", "en"}):
        raise ValueError("c7_split_complexity")
    return parsed


class ExposureAttestation(BaseExposure):
    reasoning_seen: Flag


def validate_attestation(data, reviewer_id, excluded_roles, *, pack_opened_at):
    value = ExposureAttestation.model_validate(data)
    registered, opened = datetime.fromisoformat(value.registered_at), datetime.fromisoformat(pack_opened_at)
    if (value.reviewer_id != reviewer_id or reviewer_id in excluded_roles or value.actual_model != "gpt-6-astra"
            or not value.role_nonparticipation or value.participating_roles or value.mapping_seen or value.plan_seen
            or value.raw_trace_seen or value.reasoning_seen or value.prior_judgments_seen
            or opened.tzinfo is None or registered > opened):
        raise ValueError("c7_reviewer_exposure_or_time")
    return value


def validate_judgments(pack, data, reviewer_id, excluded_roles, attestation, *, opened_at):
    exposure = validate_attestation(attestation, reviewer_id, excluded_roles, pack_opened_at=opened_at)
    parsed = JudgmentFile.model_validate(data)
    samples = pack["samples"]
    if (parsed.reviewer_id != reviewer_id or len({s["sample_id"] for s in samples}) != len(samples)
            or [j.sample_id for j in parsed.judgments] != [s["sample_id"] for s in samples]):
        raise ValueError("c7_judgment_coverage")
    rows = []
    for sample, judgment in zip(samples, parsed.judgments, strict=True):
        oracle = review_oracle(sample["oracle"])
        if reviewer_id in {oracle.question_author, oracle.oracle_author, oracle.independent_prereviewer}:
            raise ValueError("c7_reviewer_author_conflict")
        rows.append(score_sample(sample, judgment.model_dump()))
    return {"rows": rows, "reviewer_id": reviewer_id, "human_review_count": 0, "exposure": exposure_label(exposure)}


def score_sample(sample, raw_judgment):
    """Check an independent review, returning counts; never supply missing votes."""
    judgment = Judgment.model_validate(raw_judgment)
    oracle = review_oracle(sample["oracle"])
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
