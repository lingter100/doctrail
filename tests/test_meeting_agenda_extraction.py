"""Generic source fixtures only; no model, native process or network."""
from __future__ import annotations

import copy
import json

import pytest

from doctrail import meeting_agenda_extraction as a
from doctrail.inference import WorkerError
from doctrail.meeting_structured import literal_optional_analysis

SOURCE = """# Library planning
Date: 2028-04-02
Participants: Ana, Bo

## Agenda
- Catalogue redesign
  - Proposal: consider a shared index.
  - Action Items (Ana & Bo)
    - Prepare a prototype by 2028-04-10; priority: high.
    - Can the old index be reused?
- Budget review
  - Funding remains unresolved.
  - Cara will send the estimate by 2028-04-12.
"""


def view(source=SOURCE):
    return a.build_view("Library planning", source)


def index(document, text):
    return next(unit["id"] for unit in document["units"] if text in unit["quote"])


def response(document):
    proposal = index(document, "Proposal:")
    parent = index(document, "Action Items")
    task = index(document, "Prepare a prototype")
    question = index(document, "Can the old")
    budget = index(document, "Funding remains")
    commitment = index(document, "Cara will")
    return {"status": "complete", "claims": [
        {"text": "공유 색인은 제안 상태이며 시제품 준비 작업과 재사용 관련 질문이 남았다.",
         "evidence": [[proposal, question]]},
        {"text": "예산은 미해결 상태이고 견적 전달 작업이 있다.", "evidence": [[budget, commitment]]}],
        "items": [[proposal, proposal, "proposal", None, None, None],
                  [parent, task, "action", "Ana & Bo", "2028-04-10", "high"],
                  [question, question, "unresolved", None, None, None],
                  [commitment, commitment, "action", "Cara", "2028-04-12", None]],
        "metadata": [[0, "meeting_title"], [1, "meeting_date"], [2, "participants"]]}


def compile_result(data, document, finish_reason="eos"):
    return a.compile_extraction(json.dumps(data, ensure_ascii=False), document,
                                metadata_projector=literal_optional_analysis, finish_reason=finish_reason)


def test_full_source_hierarchy_and_joint_projection():
    document = view()
    assert "".join(part["text"] for part in document["source_parts"]) == SOURCE
    analysis, diagnostic = compile_result(response(document), document)
    action = analysis["items"][1]
    assert action["assignee"] == "Ana & Bo" and action["due_date"] == "2028-04-10"
    assert action["priority"] == "high"
    assert action["quote"] == SOURCE[action["start_offset"]:action["end_offset"]] == action["text"]
    assert "Action Items (Ana & Bo)\n    - Prepare a prototype" in action["quote"]
    assert analysis["items"][0]["type"] == "proposal" and analysis["items"][2]["type"] == "unresolved"
    assert all(item["status"] == "needs_confirmation" and item["id"] == "" for item in analysis["items"])
    assert analysis["meeting_date"] == "2028-04-02" and analysis["participants"] == ["Ana", "Bo"]
    assert diagnostic["review_performed"] is False and diagnostic["semantic_quality_accepted"] is False
    assert diagnostic["metadata_policy"] == "literal_optional_v1"
    units = document["units"]
    parent, task = index(document, "Action Items"), index(document, "Prepare a prototype")
    assert units[task]["parent_id"] == parent and units[task]["action_block_id"] == parent
    assert units[index(document, "Budget review")]["action_block_id"] is None


def test_messages_preserve_unicode_crlf_gaps_and_never_duplicate_full_source():
    source = SOURCE.replace("Library planning", "도서관 😀 planning").replace("\n", "\r\n") + "\t \r\n"
    document = view(source)
    messages = a.extraction_messages(document)
    payload = json.loads(messages[1]["content"])
    assert set(payload) == {"policy", "untrusted_title", "source_parts"}
    assert "".join(part["text"] for part in payload["source_parts"]) == source
    for unit in document["units"]:
        assert source[unit["start_offset"]:unit["end_offset"]] == unit["quote"]
    assert len(messages) == 2 and "No self-review" in messages[0]["content"]


@pytest.mark.parametrize("where", ["claims", "items"])
def test_range_cannot_cross_next_agenda(where):
    document = view()
    data = response(document)
    first, last = index(document, "Action Items"), index(document, "Funding remains")
    if where == "claims":
        data["claims"][0]["evidence"] = [[first, last]]
    else:
        data["items"][1][:2] = [first, last]
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        compile_result(data, document)


@pytest.mark.parametrize("owner", ["Ana", "Ana and Bo", "Ana Example"])
def test_collective_owner_is_literal_and_not_expanded_or_split(owner):
    document = view()
    data = response(document)
    data["items"][1][3] = owner
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)


def test_presenter_and_attendance_do_not_imply_owner():
    source = "# Planning\nParticipants: Dee\n- Storage design (Dee)\n  - Prepare a draft.\n"
    document = view(source)
    data = {"status": "complete", "claims": [{"text": "설계 초안 준비가 논의됐다.", "evidence": [[2, 3]]}],
            "items": [[2, 3, "action", "Dee", None, None]], "metadata": []}
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)
    data["items"][0][3] = None
    assert compile_result(data, document)[0]["items"][0]["assignee"] is None


def test_parent_and_later_child_span_keeps_intervening_sibling_task():
    source = "# Planning\n## Action Items (Eli & Fay)\n- Prepare the map.\n- Review the schedule.\n"
    document = view(source)
    data = {"status": "complete", "claims": [{"text": "지도와 일정 검토 작업이 있다.", "evidence": [[1, 3]]}],
            "items": [[1, 3, "action", "Eli & Fay", None, None]], "metadata": []}
    analysis, diagnostics = compile_result(data, document)
    assert "Prepare the map.\n- Review" in analysis["items"][0]["text"]
    assert diagnostics["item_ranges_including_intervening_units"] == [{"item_index": 0, "first_unit": 1, "last_unit": 3}]


@pytest.mark.parametrize("field,value", [("due", "2028-04-02"), ("due", "tomorrow"), ("priority", "low")])
def test_deadline_and_priority_require_supported_literal_fields(field, value):
    document = view()
    data = response(document)
    data["items"][1][4 if field == "due" else 5] = value
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)


def test_ambiguous_owner_and_priority_must_remain_null():
    source = "# Planning\n## Action Items (Gus)\n- Hana will prepare the list; priority: high; priority: low.\n"
    document = view(source)
    data = {"status": "complete", "claims": [{"text": "목록 준비 작업이 있다.", "evidence": [[1, 2]]}],
            "items": [[1, 2, "action", "Gus", None, None]], "metadata": []}
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)
    data["items"][0][3] = None
    data["items"][0][5] = "high"
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)
    data["items"][0][5] = None
    assert compile_result(data, document)[0]["items"][0]["assignee"] is None


def test_literal_metadata_policy_omits_ambiguous_dates_with_warnings():
    document = view(SOURCE.replace("Participants: Ana, Bo", "Date: 2028-04-03"))
    data = response(document)
    data["metadata"] = [[1, "meeting_date"], [2, "meeting_date"]]
    analysis, diagnostics = compile_result(data, document)
    assert analysis["meeting_date"] is None
    assert [warning["reason"] for warning in diagnostics["metadata_warnings"]] == ["ambiguous_source_value"] * 2


def test_link_and_code_headings_are_not_current_header_or_action_parent():
    source = "# [Prior notes](previous.md)\n# Current session\n```md\n## Action Items (Invented)\n```\n- Draft topic\n"
    document = view(source)
    assert document["units"][0]["contains_link"] is True
    assert document["units"][0]["document_header_candidate"] is False
    assert document["units"][1]["document_header_candidate"] is True
    assert document["units"][3]["code_block"] is True
    assert document["units"][-1]["action_block_id"] is None
    assert "".join(part["text"] for part in document["source_parts"]) == source


def test_short_or_info_fence_does_not_promote_code_to_action_owner():
    source = "# Planning\n````md\n```\n#### Action Items (Invented)\n````still code\n- More example\n````\n- Real topic\n"
    document = view(source)
    assert all(unit["code_block"] for unit in document["units"][1:7])
    assert document["units"][-1]["code_block"] is False
    assert all(unit["action_block_id"] is None for unit in document["units"])


@pytest.mark.parametrize("reason", ["length", None])
def test_truncation_never_compiles_partial_result(reason):
    document = view()
    with pytest.raises(WorkerError, match="generation_output_truncated"):
        compile_result(response(document), document, reason)


def test_abstention_fails_analysis_without_empty_success_persistence():
    with pytest.raises(WorkerError, match="generation_summary_insufficient"):
        compile_result({"status": "abstained", "claims": [], "items": [], "metadata": []}, view())


@pytest.mark.parametrize("mutation", ["offset", "parent", "parts"])
def test_tampered_view_cannot_change_source_or_parent_binding(mutation):
    document = view()
    data = response(document)
    changed = copy.deepcopy(document)
    if mutation == "offset":
        changed["units"][1]["start_offset"] += 1
    elif mutation == "parent":
        changed["units"][1]["parent_id"] = 99
    else:
        changed["source_parts"][0]["text"] = "changed"
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        compile_result(data, changed)


@pytest.mark.parametrize("pair", [[True, 5], [-1, 5], [5, 4], [0, 999]])
def test_invalid_range_rejected(pair):
    document = view()
    data = response(document)
    data["claims"][0]["evidence"] = [pair]
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        compile_result(data, document)


def test_limits_reject_instead_of_dropping_items_or_source():
    document = view()
    data = response(document)
    data["items"] = data["items"] * 38
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        compile_result(data, document)
    with pytest.raises(WorkerError, match="generation_partition_limit"):
        view("\n".join(f"- Topic {index}" for index in range(161)))
    with pytest.raises(WorkerError, match="generation_input_limit"):
        view("x" * 24001)


@pytest.mark.parametrize("field", ["deadline", "priority", "expired_owner", "sibling_owner"])
def test_field_binding_rejects_intervening_sibling_or_expired_block(field):
    source = "# Planning\n- Workstream\n  - Action Items (Iris)\n    - Jules will draft A by 2028-04-10; priority: high.\n    - Draft B.\n  - Draft C.\n"
    if field == "expired_owner":
        source = source.replace("Jules will draft A", "Draft A")
    document = view(source)
    first, last = (2, 5) if field == "expired_owner" else (3, 4) if field == "sibling_owner" else (2, 4)
    owner = "Iris" if field == "expired_owner" else "Jules" if field == "sibling_owner" else None
    due = "2028-04-10" if field == "deadline" else None
    priority = "high" if field == "priority" else None
    data = {"status": "complete", "claims": [{"text": "초안 준비 작업이 있다.", "evidence": [[first, last]]}],
            "items": [[first, last, "action", owner, due, priority]], "metadata": []}
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)


def test_field_binding_keeps_legitimate_parent_owner_but_not_sibling_fields():
    source = "# Planning\n- Workstream\n  - Action Items (Iris)\n    - Jules will draft A by 2028-04-10; priority: high.\n    - Draft B.\n"
    document = view(source)
    data = {"status": "complete", "claims": [{"text": "초안 준비 작업이 있다.", "evidence": [[2, 4]]}],
            "items": [[2, 4, "action", "Iris", None, None]], "metadata": []}
    analysis, diagnostics = compile_result(data, document)
    item = analysis["items"][0]
    assert item["assignee"] == "Iris" and item["due_date"] is None and item["priority"] is None
    assert "Jules will draft A by 2028-04-10; priority: high." in item["quote"]
    assert item["quote"] == source[item["start_offset"]:item["end_offset"]] == item["text"]
    assert diagnostics["item_field_policy"] == "terminal_task_and_enclosing_action_owner_v1"
    assert diagnostics["item_ranges_including_intervening_units"] == [{"item_index": 0, "first_unit": 2, "last_unit": 4}]


def test_field_binding_does_not_inherit_other_task_ancestor_fields():
    source = "# Planning\n- Workstream\n  - Kira will prepare the package by 2028-04-10.\n    - Attach the inventory.\n"
    document = view(source)
    data = {"status": "complete", "claims": [{"text": "자료와 목록 준비 작업이 있다.", "evidence": [[2, 3]]}],
            "items": [[2, 3, "action", "Kira", "2028-04-10", None]], "metadata": []}
    with pytest.raises(WorkerError, match="generation_unsupported_field"):
        compile_result(data, document)
    data["items"][0][3:5] = [None, None]
    assert compile_result(data, document)[0]["items"][0]["assignee"] is None
