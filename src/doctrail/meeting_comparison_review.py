"""C2 review contracts and arithmetic, not an automated semantic judge.

All examples in tests are synthetic. The reviewer supplies factual judgments;
this module checks their coverage, source coordinates and internal consistency.
It never infers semantic truth from an exact quote or a successful parser.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from doctrail.inference import StrictModel, VersionedRequest
from doctrail.meeting_answer_v2 import response_language
from doctrail.meeting_contract import AnswerRequest

Text = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")]
Index = Annotated[int, Field(ge=0, strict=True)]
Flag = Annotated[bool, Field(strict=True)]


class Evidence(StrictModel):
    chunk_id: Id
    start_offset: Index
    end_offset: Annotated[int, Field(ge=1, strict=True)]
    quote: Text


class RequiredFact(StrictModel):
    id: Id
    text: Text
    # Each alternative is a sufficient set of exact spans, not an OR of fragments.
    evidence_alternatives: Annotated[list[Annotated[list[Evidence], Field(min_length=1)]],
                                     Field(max_length=10)]


class Oracle(StrictModel):
    id: Id
    family_id: Literal["C2-F01", "C2-F02", "C2-F03", "C2-F04"]
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
    human_review_count: Annotated[int, Field(ge=0, strict=True)]

    @model_validator(mode="after")
    def consistent(self):
        if (len({f.id for f in self.required_facts}) != len(self.required_facts)
                or self.independent_prereviewer in {self.question_author, self.oracle_author}
                or self.provenance != ("public" if self.family_id in {"C2-F01", "C2-F03"}
                                       else "synthetic")):
            raise ValueError("review_oracle_identity")
        missing = any(not f.evidence_alternatives for f in self.required_facts)
        if (missing != (self.expected_status == "abstained")
                or (self.unanswerable_reason is not None) != missing):
            raise ValueError("review_oracle_answerability")
        return self


class OracleFile(VersionedRequest):
    phase: Literal["calibration", "validation"]
    cases: list[Oracle]


class Quality(StrictModel):
    citation_exact: Flag
    claim_support: Flag
    completeness: Flag
    language: Flag
    temporal: Flag
    subject: Flag
    conditions: Flag
    correct_abstention_or_answer: Flag


class Support(StrictModel):
    citation_index: Index
    start_offset: Index
    end_offset: Annotated[int, Field(ge=1, strict=True)]


class AtomicFact(StrictModel):
    text: Text
    supported: Flag
    support: list[Support]

    @model_validator(mode="after")
    def complete_support(self):
        if self.supported != bool(self.support):
            raise ValueError("review_support_presence")
        return self


class CitationJudgment(StrictModel):
    citation_index: Index
    relevant: Flag
    reason: Text


class ClaimJudgment(StrictModel):
    claim_index: Index
    # Include optional examples, explanations and comparisons in this decomposition.
    facts: Annotated[list[AtomicFact], Field(min_length=1, max_length=30)]
    citations: Annotated[list[CitationJudgment], Field(min_length=1, max_length=4)]


class FactCoverage(StrictModel):
    fact_id: Id
    present: Flag
    reason: Text


class MaskingGuess(StrictModel):
    unit_style: Literal["unknown", "short_units", "broad_units"]
    confidence: Literal["none", "low", "medium", "high"]
    reason: Text

    @model_validator(mode="after")
    def consistent(self):
        if (self.unit_style == "unknown") != (self.confidence == "none"):
            raise ValueError("review_guess_confidence")
        return self


class Judgment(StrictModel):
    sample_id: Id
    quality: Quality
    claims: list[ClaimJudgment]
    required_facts: list[FactCoverage]
    full_correct: Flag
    reason: Text
    masking_guess: MaskingGuess


class JudgmentFile(VersionedRequest):
    reviewer_id: Id
    # Declared role separation is provenance, not cryptographic proof of blindness.
    mapping_not_seen: Literal[True]
    independent_of_authors_and_designers: Literal[True]
    human_review_count: Literal[0]
    judgments: list[Judgment]

    @model_validator(mode="before")
    @classmethod
    def literal_types(cls, value):
        # Pydantic Literal equality alone accepts 1 == True and False == 0.
        if isinstance(value, dict) and (
                type(value.get("mapping_not_seen")) is not bool
                or type(value.get("independent_of_authors_and_designers")) is not bool
                or type(value.get("human_review_count")) is not int):
            raise ValueError("review_literal_types")
        return value


def exact(citation, contexts):
    """Never search a different position to repair an incorrect citation."""
    context = next((c for c in contexts if c["chunk_id"] == citation.get("chunk_id")), None)
    start, end = citation.get("start_offset"), citation.get("end_offset")
    return (context is not None and type(start) is int and type(end) is int
            and context["start_offset"] <= start < end <= context["end_offset"]
            and citation.get("quote") == context["text"][start - context["start_offset"]:
                                                        end - context["start_offset"]])


def requires_multiple_sources(oracle, contexts):
    """Every sufficient evidence choice needs >=2 document/revision identities.

    A one-source combination exists iff one source appears as a sufficient
    singleton alternative for every required fact. Intersecting these sets
    avoids enumerating up to ten alternatives for each of twenty facts.
    """
    if oracle.expected_status != "answered":
        return False
    by_chunk = {c["chunk_id"]: (c["document_id"], c["revision"]) for c in contexts}
    common = None
    for fact in oracle.required_facts:
        singletons = set()
        for alternative in fact.evidence_alternatives:
            sources = {by_chunk[e.chunk_id] for e in alternative}
            if len(sources) == 1:
                singletons.update(sources)
        common = singletons if common is None else common & singletons
    return common == set()


def validate_oracles(inputs, data, phase):
    oracles = OracleFile.model_validate(data)
    if (oracles.phase != phase or inputs.get("phase") != phase
            or [c.id for c in oracles.cases] != [c["id"] for c in inputs["cases"]]):
        raise ValueError("review_oracle_cases")
    count = 8 if phase == "calibration" else 12
    families = {"C2-F01", "C2-F02"} if phase == "calibration" else {"C2-F03", "C2-F04"}
    answerable_per_family = 3 if phase == "calibration" else 4
    if (len(oracles.cases) != count or len({o.id for o in oracles.cases}) != count
            or {o.family_id for o in oracles.cases} != families
            or any(sum(o.family_id == f for o in oracles.cases) != count // 2 for f in families)
            or any(sum(o.family_id == f and o.language == "ko" for o in oracles.cases)
                   != count // 4 for f in families)
            or any(sum(o.family_id == f and o.expected_status == "answered" for o in oracles.cases)
                   != answerable_per_family for f in families)):
        raise ValueError("review_oracle_composition")
    multifactual, multisource, partial = {}, {}, {}
    for case, oracle in zip(inputs["cases"], oracles.cases, strict=True):
        request = AnswerRequest.model_validate(case["payload"])
        if oracle.language != response_language(request.query):
            raise ValueError("review_oracle_language")
        contexts = [c.model_dump() for c in request.contexts]
        for fact in oracle.required_facts:
            for alternative in fact.evidence_alternatives:
                if not all(exact(e.model_dump(), contexts) for e in alternative):
                    raise ValueError("review_oracle_evidence")
        family = oracle.family_id
        multifactual[family] = multifactual.get(family, 0) + (
            oracle.expected_status == "answered" and len(oracle.required_facts) >= 2)
        multisource[family] = multisource.get(family, 0) + requires_multiple_sources(oracle, contexts)
        partial[family] = partial.get(family, 0) + (
            oracle.expected_status == "abstained"
            and any(f.evidence_alternatives for f in oracle.required_facts)
            and any(not f.evidence_alternatives for f in oracle.required_facts))
    if (any(not multifactual.get(f) or not multisource.get(f) or not partial.get(f)
            for f in families)
            or sum(multifactual.values()) < (4 if phase == "calibration" else 6)
            or sum(multisource.values()) < (2 if phase == "calibration" else 4)):
        raise ValueError("review_oracle_complexity")
    return oracles


def union_length(intervals):
    groups = {}
    for key, start, end in intervals:
        groups.setdefault(key, []).append((start, end))
    total = 0
    for ranges in groups.values():
        right = -1
        for start, end in sorted(ranges):
            total += max(0, end - max(start, right))
            right = max(right, end)
    return total


def score_sample(sample, raw_judgment):
    """Check an independent review, returning counts; never supply missing votes."""
    judgment = Judgment.model_validate(raw_judgment)
    oracle = Oracle.model_validate(sample["oracle"])
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


def summarize(pack, judgments, mapping, phase, reviewer_id, excluded):
    parsed = JudgmentFile.model_validate(judgments)
    if parsed.reviewer_id != reviewer_id or parsed.reviewer_id in excluded:
        raise ValueError("review_role_conflict")
    samples = pack["samples"]
    identities = [s["sample_id"] for s in samples]
    if (len(set(identities)) != len(identities)
            or [j.sample_id for j in parsed.judgments] != identities
            or [m["sample_id"] for m in mapping["mappings"]] != identities):
        raise ValueError("review_sample_set")
    rows, paired = [], {}
    for sample, judgment, link in zip(samples, parsed.judgments, mapping["mappings"], strict=True):
        oracle = sample["oracle"]
        if reviewer_id in {oracle["question_author"], oracle["oracle_author"],
                           oracle["independent_prereviewer"]}:
            raise ValueError("review_role_conflict")
        row = score_sample(sample, judgment.model_dump())
        pair = paired.setdefault(link["case_id"], {})
        if link["arm"] in pair:
            raise ValueError("review_duplicate_pair")
        pair[link["arm"]] = row["full_correct"]
        rows.append({**row, "case_id": link["case_id"], "arm": link["arm"]})
    arms = {"L0", "C2"} if phase == "calibration" else {"C2"}
    count = 8 if phase == "calibration" else 12
    if len(paired) != count or any(set(p) != arms for p in paired.values()):
        raise ValueError("review_incomplete_phase")
    correct = {a: sum(p[a] for p in paired.values()) for a in sorted(arms)}
    improvements = sum(not p["L0"] and p["C2"] for p in paired.values()) if "L0" in arms else None
    regressions = sum(p["L0"] and not p["C2"] for p in paired.values()) if "L0" in arms else None
    passed = correct["C2"] == count and (phase == "validation" or improvements >= 1 and regressions == 0)
    return {"phase": phase, "cases": count, "samples": len(rows), "correct": correct,
            "improvements": improvements, "regressions": regressions, "passed": passed,
            "human_review_count": 0, "reviewer_id": reviewer_id, "rows": rows}
