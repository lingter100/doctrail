"""Custodian construction record for C1 calibration only; no model access.

Contains questions and semantic oracles. Do not rerun after item freeze.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
REGISTRY_PATH = REPO / "data/evaluation/meetings-c1-calibration-family-registry-v1.json"
FREEZE_PATH = REPO / "data/evaluation/meetings-c1-source-freeze-v1.json"
COMMIT = "82b0fff79761c0da86f4d8c5614aa20f9b12e7e5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(path, text):
    assert "\r" not in text
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def dump(path, value):
    put(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


registry = json.loads(REGISTRY_PATH.read_bytes())
freeze = json.loads(FREEZE_PATH.read_bytes())
integrity = json.loads((ROOT / "source-integrity.json").read_bytes())
assert len(freeze["bound_files"]) == 46
for file_name, expected in freeze["bound_files"].items():
    assert sha((REPO / file_name).read_bytes()) == expected
assert sha(REGISTRY_PATH.read_bytes()) == integrity["source_registry_sha256"]
assert sha(FREEZE_PATH.read_bytes()) == integrity["source_freeze_sha256"]
assert integrity["questions_authored_at_materialization"] == 0
source_records = []
raw_texts = {}
windows = {}
for src in registry["approved_public_sources"]:
    record = next(x for x in integrity["public_sources"] if x["source_id"] == src["source_id"])
    data = (ROOT / record["raw_path"]).read_bytes()
    assert sha(data) == src["raw_sha256"]
    raw_texts[src["source_id"]] = data.decode("utf-8")
    source_records.append({**src, **record, "origin": "public", "document_id": src["source_id"],
                           "document_revision": 1, "meeting_date": None,
                           "raw_codepoints": len(raw_texts[src["source_id"]]), "windows": []})


def window(source_id, suffix, start_marker, stop_marker, heading, selection):
    source = next(x for x in source_records if x["source_id"] == source_id)
    raw = raw_texts[source_id]
    start = 0 if start_marker is None else raw.index(start_marker)
    end = len(raw) if stop_marker is None else raw.index(stop_marker, start + 1)
    text = raw[start:end]
    assert text.strip() and text.endswith("\n")
    assert start == 0 or raw[start - 1] == "\n"
    chunk_id = f"{source_id}-{suffix}"
    path = f"sources/processed/{chunk_id}.txt"
    put(path, text)
    mapping = {"chunk_id": chunk_id, "processed_path": path,
               "processed_sha256": sha(text.encode()), "start_offset": start, "end_offset": end,
               "start_line": raw.count("\n", 0, start) + 1,
               "end_line_inclusive": raw.count("\n", 0, end - 1) + 1,
               "heading_context": heading, "selection_rule": selection,
               "complete_paragraphs": True, "rewritten_or_translated": False}
    source["windows"].append(mapping)
    windows[chunk_id] = {"document_id": source_id, "revision": 1, "chunk_id": chunk_id,
                         "title": f"{source['title']} — {heading}",
                         "meeting_date": source["meeting_date"], "page": None,
                         "start_offset": start, "end_offset": end, "text": text}
    return chunk_id


p1_review = window("C1-PY-PEP1", "review", "PEP Review & Resolution\n", "The final authority for PEP approval",
                   "PEP Review & Resolution", "Section heading and its first two complete paragraphs, covering author-initiated and council-initiated review; stop before the next delegation paragraph.")
p13_powers = window("C1-PY-PEP13", "powers", "Powers\n", "Electing the council\n", "Powers", "Complete heading-delimited subsection.")
p13_amendments = window("C1-PY-PEP13", "amendments", "History of amendments\n", "Acknowledgements\n", "History of amendments", "Complete heading-delimited subsection, including all recorded dates.")
p13_confidence = window("C1-PY-PEP13", "confidence", "Vote of no confidence\n", "The core team\n", "Vote of no confidence", "Complete heading-delimited subsection.")
np50_weak = window("C1-NP-NEP50", "weak", "Proposed weak promotion\n", "Related work\n", "Proposed weak promotion", "Complete heading-delimited subsection, including the future user-defined-DType note.")
np51_scope = window("C1-NP-NEP51", "scope", "Motivation and scope\n", "Usage and impact\n", "Motivation and scope", "Complete heading-delimited section with type lists and surrounding motivation paragraphs.")
np51_abstract = window("C1-NP-NEP51", "abstract", None, "Motivation and scope\n", "Header and Abstract", "Complete document metadata and abstract, including examples and relationship to NEP 50.")
np51_backward = window("C1-NP-NEP51", "backward", "Backward compatibility\n", "Changes to ``arr.tofile()``\n", "Backward compatibility", "Section heading and all complete paragraphs before the first nested subsection.")

synthetic = [
    ("C1-BIRD-MEETING", "C1-F03", "ko", "synthetic_meeting_record", "해솔만 물새 정점조사 운영회의", "2026-04-03", "1", "bird-meeting", """# 해솔만 물새 정점조사 운영회의
AI 작성 허구 자료. 기관·인물·관측값은 가상이며 실제 연구 기록이나 생태 조사 지침이 아니다.
회의일: 2026-04-03
참석: 라온, 보미, 건우

## C3 관측 기록 검토
4월 2일 C3 지점의 18마리는 두 관측자가 같은 9마리 무리를 각각 적은 뒤 합산한 중복으로 판정했다. 회의는 공식 정정값을 9마리로 정했다. 원래 값 18을 삭제하지 않고 정정 사유와 확인자를 연결한 정정 행을 추가하기로 했다. 수정된 기록표가 실제 반영됐는지는 이번 회의에서 확인하지 않았다.

## 조건부 인계
북측 정점의 담당자는 계속 라온이다. 4월 6일 현장 진입로 안전확인서가 접수된 경우에만 보미에게 담당을 인계한다. 일정표에 4월 6일이 적혀 있다는 사실만으로 인계가 성립하지 않는다. 건우는 확인서 접수 여부를 두 사람에게 알리는 연락 담당이다.

## 문서 개정
시야가 가려진 관측을 추정 수치로 합계에 넣는 문제를 줄이기 위해 관측 프로토콜 개정 2를 4월 4일부터 적용하기로 했다. 조사 위치 자체를 추가하거나 과거 기록을 일괄 삭제하는 결정은 하지 않았다.
"""),
    ("C1-BIRD-PROTOCOL-V1", "C1-F03", "ko", "synthetic_observation_protocol_revision", "해솔만 관측 프로토콜 — 개정 1 기록", None, "1", "bird-observation-protocol", """# 해솔만 관측 프로토콜 — 개정 1
AI 작성 허구 자료. 실제 연구 기록이나 생태 조사 지침이 아니다.
문서일: 2026-03-28. 과거 개정판 보존본.

## 가시성에 따른 기입
관측 무리 일부가 가려졌을 때에는 조사자가 전체 수를 추정하여 count 열에 숫자로 적는다. 이 추정 수치도 일일 합계에 포함한다. 시야가 모두 확보된 경우에는 직접 센 수치를 적는다.

## 기록 표식
각 행에는 지점 코드, 관측 시각과 관측자 이름을 함께 남긴다. 관측자의 자유 메모는 별도 칸에 기록한다. 이 보존본은 당시 규칙을 보여주며 이후 개정의 효력을 결정하지 않는다.
"""),
    ("C1-BIRD-PROTOCOL-V2", "C1-F03", "ko", "synthetic_observation_protocol_revision", "해솔만 관측 프로토콜 — 개정 2", None, "2", "bird-observation-protocol", """# 해솔만 관측 프로토콜 — 개정 2
AI 작성 허구 자료. 실제 연구 기록이나 생태 조사 지침이 아니다.
적용일: 2026-04-04. 개정 1의 가시성에 따른 기입 조항을 대체한다.

## 가시성에 따른 기입
관측 무리 일부가 가려졌을 때에는 전체 수를 추정하지 않고 count 열에 결측 표식 M을 적는다. 보이는 개체 수는 자유 메모에 남길 수 있지만 일일 합계에 넣지 않는다. 시야가 모두 확보된 경우에는 직접 센 수치를 적는다.

## 정정과 확인
이전 행을 지우지 않고 정정 행을 연결한다. 정정 행에는 이전 행 식별자, 변경 사유, 확인자를 기입한다. 문서가 개정됐다는 사실만으로 기존 현장 표의 정정이 완료됐다고 간주하지 않는다. 지점 코드와 관측 시각의 기록 방식은 개정 1과 같다.
"""),
    ("C1-CHESS-MEETING", "C1-F04", "en", "synthetic_meeting_record", "Harbor Lantern chess event committee minutes", "2026-05-12", "1", "chess-meeting", """# Harbor Lantern chess event committee minutes
AI-authored fiction. This event, people and rules are invented; these are not federation rules or a real event record.
Meeting date: 2026-05-12. Present: Jonah, Amina, Farah and Eli.

## Pairing administration
The committee approved correction-procedure revision 2 for round 2. Farah will maintain the written pairing-dispute register. Eli will post any authorized replacement pairing sheet; the posting assignment does not itself authorize a correction.

## Evidence available at the meeting
Round 2 has not yet begun. No completed correction approvals or round-2 dispute totals were presented at this meeting. The committee will review the event records afterward. The meeting did not change game-scoring or player eligibility rules.
"""),
    ("C1-CHESS-PROCEDURE-V1", "C1-F04", "en", "synthetic_adjudication_procedure_revision", "Harbor Lantern pairing correction procedure — revision 1 archive", None, "1", "chess-correction-procedure", """# Harbor Lantern pairing correction procedure — revision 1
AI-authored fiction, not federation rules. Historical procedure snapshot dated 2026-05-02.

## Authorization and posting
The head adjudicator alone may authorize a replacement pairing sheet. A desk volunteer may post it after that authorization. A player must describe the disputed pairing in writing so that the original and replacement can be connected in the register.

## Scope
This procedure concerns correcting a posted pairing. It does not decide game results, membership or entry eligibility. Keep the original sheet with the correction record.
"""),
    ("C1-CHESS-PROCEDURE-V2", "C1-F04", "en", "synthetic_adjudication_procedure_revision", "Harbor Lantern pairing correction procedure — revision 2", None, "2", "chess-correction-procedure", """# Harbor Lantern pairing correction procedure — revision 2
AI-authored fiction, not federation rules. Approved procedure dated 2026-05-12; replaces revision 1's authorization and posting section for round 2.

## Authorization and posting
A replacement pairing sheet requires written approval from both the head adjudicator and the deputy adjudicator before the first game clock of the round starts. It may be posted only once both approvals are recorded while that time condition still holds. If either approval is missing or the first clock has started, keep the current sheet and refer the dispute to the committee; there is no automatic replacement.

## Record linkage
Keep the original pairing sheet and link the written dispute and approvals to the replacement. This rule describes authorization conditions, not the number of corrections actually approved. Game-scoring and entry eligibility remain outside its scope.
"""),
]
for sid, family, language, kind, title, meeting_date, revision_label, group, raw in synthetic:
    path = f"sources/synthetic/{sid}.md"
    put(path, raw)
    raw_texts[sid] = raw
    source_records.append({"source_id": sid, "document_id": sid, "family_id": family,
                           "origin": "synthetic", "source_language": language, "source_kind": kind,
                           "title": title, "meeting_date": meeting_date, "document_revision": 1,
                           "source_revision_label": revision_label, "logical_document_group": group,
                           "revision_note": "Each preserved revision is a distinct evidence document, not simultaneous active search chunks of one mutable service document.",
                           "raw_path": path, "raw_sha256": sha(raw.encode()), "raw_bytes": len(raw.encode()),
                           "raw_codepoints": len(raw), "author_origin": "AI-authored fiction after source and family freeze",
                           "human_reviews": 0, "windows": []})
    window(sid, "whole", None, None, "Complete preserved source", "Whole bounded synthetic source, including provenance, headings and all paragraphs.")

cases = []
oracles = []
slots = {slot["item_id"]: (fam, slot) for fam in registry["families"] for slot in fam["slots"]}


def evidence(chunk_id, quote):
    ctx = windows[chunk_id]
    assert ctx["text"].count(quote) == 1, (chunk_id, quote)
    offset = ctx["start_offset"] + ctx["text"].index(quote)
    source = next(x for x in source_records if x["source_id"] == ctx["document_id"])
    return {"document_id": ctx["document_id"], "revision": ctx["revision"], "chunk_id": chunk_id,
            "source_raw_sha256": source["raw_sha256"], "processed_sha256": sha(ctx["text"].encode()),
            "quote": quote, "start_offset": offset, "end_offset": offset + len(quote)}


def fact(statement, support, alternatives=()):
    return {"statement": statement, "mandatory": True, "supporting_evidence": [evidence(*x) for x in support],
            "allowed_alternative_citations": [evidence(*x) for x in alternatives]}


def add(n, query, chunks, facts, forbidden, partial=(), missing=(), notes=None):
    case_id = f"C1CAL-{n:02d}"
    family, slot = slots[case_id]
    answerable = slot["intended_answerability"] == "answerable"
    assert answerable == bool(facts)
    for i, item in enumerate(facts, 1):
        item["fact_id"] = f"{case_id}-F{i}"
    for item in partial:
        item["mandatory"] = False
    cases.append({"id": case_id, "operation": "answer", "payload": {
        "schema_version": 1, "query": query, "contexts": [windows[x] for x in chunks]}})
    oracles.append({"id": case_id, "family_id": family["family_id"], "origin": family["origin"],
                    "question_language": slot["question_language"],
                    "source_languages": sorted({next(s["source_language"] for s in source_records if s["source_id"] == windows[c]["document_id"]) for c in chunks}),
                    "answerability": slot["intended_answerability"],
                    "expected_status": "answered" if answerable else "abstained",
                    "expected_reason": None if answerable else "insufficient_evidence",
                    "required_dimensions": slot["required_dimensions"], "required_facts": facts,
                    "answerable_parts_when_incomplete": list(partial), "missing_required_parts": list(missing),
                    "forbidden_inference": forbidden, "context_chunk_ids": chunks,
                    "source_binding": [{"chunk_id": c, "document_id": windows[c]["document_id"],
                                        "revision": windows[c]["revision"], "processed_sha256": sha(windows[c]["text"].encode())} for c in chunks],
                    "review_notes": notes, "ai_authored_question": True, "ai_author_self_review": True,
                    "independent_prereview_count": 0, "human_review_count": 0})


add(1, "PEP 작성자가 내용 검토와 최종 결정을 정식 요청하려면 언제 어디에서 시작해야 해? PEP 13에 따르면 Council의 권한 행사 투표에서 회원의 참여 의무, 이해상충 처리, 가결 기준은 각각 무엇이야?",
    [p1_review, p13_powers], [
        fact("When the authors and sponsor, if any, determine the PEP is ready for final review/resolution, they formally initiate it by opening a Steering Council issue.", [(p1_review, "However, content review and acceptance of the PEP is ultimately the\nresponsibility of the Steering Council, which is formally initiated by\nopening a `Steering Council issue`_ once the authors (and sponsor, if any)\ndetermine the PEP is ready for final review and resolution.")]),
        fact("Every council member must vote or explicitly abstain.", [(p13_powers, "Every council member must either\nvote or explicitly abstain.")]),
        fact("Members with conflicts of interest on the particular vote must abstain.", [(p13_powers, "Members with conflicts of interest on a\nparticular vote must abstain.")]),
        fact("Passing requires a strict majority of non-abstaining council members.", [(p13_powers, "Passing requires a strict majority of\nnon-abstaining council members.")]),
    ], ["PEP editor publication approval is substantive acceptance.", "Abstaining members are counted in the required majority denominator.", "The ordinary council vote always requires two thirds."],
    notes="Two documents are necessary: author-initiated formal request mechanics come from PEP 1, while voting participation/conflicts/threshold come from PEP 13. The separate council-initiated review paragraph does not negate the explicitly author-initiated question.")

add(2, "Which two amendments are recorded for 2024-12-10 in PEP 13? Under the supplied no-confidence procedure, how soon must a proposal be seconded, how long does voting last, and what support is required for it to succeed?",
    [p13_amendments, p13_confidence], [
        fact("The December 10, 2024 amendments adopted Multi-winner Bloc STAR council elections and added a one-week deadline for seconding a no-confidence vote.", [(p13_amendments, "* `2024-12-10 <https://discuss.python.org/t/64971>`__:\n  Adopted Multi-winner Bloc STAR voting for council elections.\n* `2024-12-10 <https://discuss.python.org/t/72293/4>`__:\n  Added a one-week deadline for seconding a vote of no confidence.")]),
        fact("The seconding deadline is one week.", [(p13_confidence, "A no-confidence vote is triggered when a core team member calls for\none publicly on an appropriate project communication channel, and\nanother core team member seconds the proposal within one week.")], [(p13_amendments, "Added a one-week deadline for seconding a vote of no confidence.")]),
        fact("The vote lasts two weeks.", [(p13_confidence, "The vote lasts for two weeks.")]),
        fact("The vote succeeds if at least two thirds of voters express a lack of confidence.", [(p13_confidence, "If at least two thirds of voters express a lack of confidence, then\nthe vote succeeds.")]),
    ], ["The one-week seconding deadline is the voting duration.", "These amendments prove that any particular no-confidence vote occurred or succeeded.", "A simple majority is enough for a successful no-confidence vote."])

add(3, "NEP 50에서 Python의 int·float·complex는 어떤 방식으로 타입을 취급하고, 값은 승격과 새 타입 변환에서 각각 어떻게 쓰여? NEP 51이 바꾸려는 스칼라 표현은 무엇이며 일반 print 출력과 배열 표현도 변경 범위에 들어가?",
    [np50_weak, np51_scope], [
        fact("Python int, float and complex use weak-scalar logic and special abstract DTypes such as Integral, Floating and ComplexFloating, rather than typical concrete dtypes such as int64 or float64.", [(np50_weak, "This proposal uses a \"weak scalar\" logic.  This means that Python ``int``, ``float``,\nand ``complex`` are not assigned one of the typical dtypes, such as float64 or int64.\nRather, they are assigned a special abstract DType, similar to the \"scalar\" hierarchy\nnames: Integral, Floating, ComplexFloating.")]),
        fact("The value never determines the promotion result; it is considered during conversion to the new dtype.", [(np50_weak, "At no time is the value used to decide the result of this promotion.  The value is only\nconsidered when it is converted to the new dtype; this may raise an error.")]),
        fact("NEP 51 changes scalar representation, __repr__, not how the scalars print; array representation is also unaffected.", [(np51_scope, "The NEP does not propose to change how these scalars print – only\ntheir representation (``__repr__``) will be changed.\nFurther, array representation will not be affected since it already\nincludes the ``dtype=`` when necessary.")]),
    ], ["Python scalar values select the promoted dtype under the proposed weak rules.", "NEP 51 changes all print output or array representation.", "Either document establishes a deployment date for a particular user's environment."],
    notes="Ask about the supplied design text, not installed NumPy behavior or the current release. Both sources are necessary. Exact abstract class-name examples are not independently required if the weak abstract-versus-concrete distinction is clear; mentioning possible conversion errors is optional supported detail.")

add(4, "What representation does NEP 51 propose for np.float32(3.0), and how many downstream packages had completed their doctest adaptations by the time the supplied document was written?",
    [np51_abstract, np51_backward, np50_weak], [],
    ["Any invented count, including zero, of downstream packages that completed adaptations.", "Expected future documentation fixups prove actual completed migrations.", "The proposal's Accepted status proves all downstream doctests were fixed."],
    partial=[fact("The proposed representation is np.float32(3.0).", [(np51_abstract, "In this NEP we propose to change the representation to include the\nNumPy scalar type information.  Changing the above example to::\n\n    >>> np.float32(3.0)\n    np.float32(3.0)")])],
    missing=["The number of downstream packages that had actually finished adapting doctests is not supplied."],
    notes="Useful representation and compatibility evidence is present, but the completion-count part is unanswerable. A partial representation answer is not a complete answer to the item; correct status is insufficient-evidence abstention.")

bird_meet, bird_v1, bird_v2 = "C1-BIRD-MEETING-whole", "C1-BIRD-PROTOCOL-V1-whole", "C1-BIRD-PROTOCOL-V2-whole"
add(5, "4월 3일 회의는 C3의 중복 기록을 몇 마리로 정정하기로 했고 원래 값 18은 어떻게 남기기로 했어? 개정 2에서는 무리 일부가 가려졌을 때 count 열과 일일 합계를 어떻게 처리해?",
    [bird_meet, bird_v2], [
        fact("The meeting decided on a corrected count of 9 birds for C3.", [(bird_meet, "회의는 공식 정정값을 9마리로 정했다.")]),
        fact("Keep the original 18 and add a linked correction row with the reason and verifier, rather than delete it.", [(bird_meet, "원래 값 18을 삭제하지 않고 정정 사유와 확인자를 연결한 정정 행을 추가하기로 했다.")]),
        fact("Revision 2 uses missing marker M in count without estimating the total; visible partial counts are excluded from the daily total.", [(bird_v2, "관측 무리 일부가 가려졌을 때에는 전체 수를 추정하지 않고 count 열에 결측 표식 M을 적는다. 보이는 개체 수는 자유 메모에 남길 수 있지만 일일 합계에 넣지 않는다.")]),
    ], ["The actual field table correction was confirmed complete at the meeting.", "Delete the original 18 without retaining a correction trail.", "Treat M as zero birds or add visible partial counts to the total."],
    notes="Meeting decision and revised observation protocol are independently necessary. Mentioning that visible partial counts may be recorded in a separate free-text note is optional supported detail; omitting that possibility does not make the answer incomplete. Fictional rules are not ecological advice.")

add(6, "What changed from revision 1 to revision 2 when a flock is partly obscured, including treatment in the daily total? Under what condition may Bomi take over the north-point assignment from Raon?",
    [bird_v1, bird_v2, bird_meet], [
        fact("Revision 1 required an estimated total in count and included that estimate in the daily total.", [(bird_v1, "관측 무리 일부가 가려졌을 때에는 조사자가 전체 수를 추정하여 count 열에 숫자로 적는다. 이 추정 수치도 일일 합계에 포함한다.")]),
        fact("Revision 2 replaces the estimate with M; visible partial counts may go in a note but not in the daily total.", [(bird_v2, "관측 무리 일부가 가려졌을 때에는 전체 수를 추정하지 않고 count 열에 결측 표식 M을 적는다. 보이는 개체 수는 자유 메모에 남길 수 있지만 일일 합계에 넣지 않는다.")]),
        fact("Transfer requires receipt of the site-access safety confirmation; the scheduled date alone does not effect a transfer.", [(bird_meet, "4월 6일 현장 진입로 안전확인서가 접수된 경우에만 보미에게 담당을 인계한다. 일정표에 4월 6일이 적혀 있다는 사실만으로 인계가 성립하지 않는다.")]),
    ], ["The handoff has already happened merely because April 6 is on the calendar.", "Geonwoo is the receiving observer because he sends the notification.", "Revision 1 and 2 have identical treatment of partial visibility."],
    notes="English answer required despite Korean evidence. This is three distinct preserved documents within one family, not three independent families.")

chess_meet, chess_v1, chess_v2 = "C1-CHESS-MEETING-whole", "C1-CHESS-PROCEDURE-V1-whole", "C1-CHESS-PROCEDURE-V2-whole"
add(7, "How did authorization to replace a pairing sheet change from revision 1 to revision 2? State the approval and timing conditions for posting under revision 2, and identify who the meeting assigned to post an authorized replacement.",
    [chess_v1, chess_meet, chess_v2], [
        fact("Revision 1 allowed the head adjudicator alone to authorize a replacement.", [(chess_v1, "The head adjudicator alone may authorize a replacement pairing sheet.")]),
        fact("Revision 2 requires written approval by both the head and deputy adjudicators.", [(chess_v2, "A replacement pairing sheet requires written approval from both the head adjudicator and the deputy adjudicator before the first game clock of the round starts.")]),
        fact("Both approvals must be recorded and posting must still occur before the round's first game clock starts; missing either condition prevents posting a replacement.", [(chess_v2, "A replacement pairing sheet requires written approval from both the head adjudicator and the deputy adjudicator before the first game clock of the round starts. It may be posted only once both approvals are recorded while that time condition still holds. If either approval is missing or the first clock has started, keep the current sheet and refer the dispute to the committee; there is no automatic replacement.")]),
        fact("The meeting assigned Eli to post an authorized replacement sheet.", [(chess_meet, "Eli will post any authorized replacement pairing sheet; the posting assignment does not itself authorize a correction.")]),
    ], ["Eli's posting assignment itself grants authority to approve the correction.", "The head alone remains sufficient under revision 2.", "A replacement may be automatically posted after play has begun."],
    notes="Historical rule, revised conditions and named task assignment come from three documents. These are invented event rules, not federation rules.")

add(8, "개정 2에서 교체 대진표를 게시할 수 있는 승인·시간 조건은 무엇이고, 실제 2라운드에서 그 조건에 따라 승인된 정정은 총 몇 건이야?",
    [chess_v2, chess_meet], [],
    ["Any actual round-2 approved-correction count, including zero.", "A meeting held before round 2 establishes the final event's correction total.", "Approval of procedure revision 2 is approval of a particular pairing correction."],
    partial=[fact("Posting needs recorded written approval from both adjudicators before the first game clock starts.", [(chess_v2, "A replacement pairing sheet requires written approval from both the head adjudicator and the deputy adjudicator before the first game clock of the round starts. It may be posted only once both approvals are recorded while that time condition still holds.")])],
    missing=["Actual approved corrections in round 2 have not been reported in the supplied evidence."],
    notes="The conditions are present, but the actual event count is absent. The pre-round meeting is not proof of a final count of zero; incomplete evidence requires abstention.")

assert len(cases) == 8
dump("cases.json", {"schema_version": 1, "cases": cases})
dump("oracles.json", {"schema_version": 1, "candidate_commit": COMMIT,
    "rubric": {
        "complete_answer": "All mandatory facts and requested facets must be correct, properly qualified, in the question language and supported by their selected citations. Faithful translation and paraphrase are allowed.",
        "citation_alternatives": "Exact oracle quotes identify support, not required citation lengths. A longer or overlapping preserved source span is acceptable if it supports the full claim. Explicit alternative citations may also support a fact; unsupported clauses cannot be rescued by a different uncited paragraph.",
        "insufficiency": "A useful partial fact is intentionally available in both insufficient-evidence items. The missing requested fact must not be guessed. Correct status is abstained with insufficient_evidence, not semantic_rejected or an incomplete answered result.",
        "evaluation": "Schema/quote exactness are separate from full semantic correctness. C1 verifier output is not an oracle. AI self-review is not independent review or human review.",
        "scope": "8 items from 4 families; within-family pairs are correlated. Synthetic statements are fiction, not real research records or official rules."},
    "cases": oracles})
dump("sources-manifest.json", {"schema_version": 1, "dataset_id": "meetings-c1-calibration-v1",
    "candidate_commit": COMMIT, "source_freeze_sha256": integrity["source_freeze_sha256"],
    "source_registry_sha256": integrity["source_registry_sha256"],
    "authored_at_utc": datetime.now(timezone.utc).isoformat(),
    "authored_after_source_and_family_freeze": True, "source_integrity_record": "source-integrity.json",
    "scope": "Fresh calibration only; no validation authoring. Prior prepared12/M5-B pools not opened or modified for this work.",
    "author_provenance": {"role": "/root/meetings_validation_custodian", "tool_accepted_model": "gpt-6-astra",
                          "tool_accepted_reasoning_effort": "xhigh", "settings_basis": "Previously accepted role reused by explicit parent instruction; no model change claimed.",
                          "ai_authored_questions": 8, "ai_authored_synthetic_documents": 6,
                          "independent_prereviews": 0, "human_reviews": 0, "model_calls": 0, "tokenizer_calls": 0},
    "raw_byte_policy": "Original pinned UTF-8 public bytes are preserved without normalization. All four originals were already LF. Synthetic and processed files use UTF-8 LF without BOM.",
    "coordinate_policy": "Unicode-codepoint offsets into the separately preserved raw document; line ranges are one-based and inclusive. Each processed context is one contiguous exact source range.",
    "sources": source_records})
print(json.dumps({"questions_authored": 8, "public_sources": 4, "synthetic_sources": 6, "model_calls": 0, "tokenizer_calls": 0}))
