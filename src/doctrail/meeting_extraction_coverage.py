"""Opt-in deterministic assembly; classification and native policies are unchanged."""
from __future__ import annotations

import json
import re

from doctrail.inference import WorkerError
from doctrail.meeting_contract import extraction_analysis, metadata_values
from doctrail.meeting_worker import (
    LABELS,
    MeetingRuntime,
    classification_messages,
    merge_analyses,
    partitions,
    summary_boilerplate,
)

ASSEMBLY = "coverage-v1"
SUMMARY_ORDER = ("decision", "unresolved", "topic", "action", "proposal")
_SPAN_FIELDS = {"quote", "start_offset", "end_offset"}


def _validate(units, labels):
    # Live units and classifier rows carry no IDs. Their positions are the IDs;
    # the batch generator already validates wire IDs before returning these rows.
    if not isinstance(units, list) or not 1 <= len(units) <= 160:
        raise WorkerError("generation_partition_limit", 422)
    if not isinstance(labels, list) or len(labels) != len(units):
        raise WorkerError("generation_invalid_schema", 502)
    previous_end = 0
    for unit, row in zip(units, labels, strict=True):
        if (not isinstance(unit, dict) or set(unit) != _SPAN_FIELDS
                or not isinstance(unit["quote"], str) or not unit["quote"]
                or type(unit["start_offset"]) is not int or type(unit["end_offset"]) is not int
                or unit["start_offset"] < previous_end
                or unit["end_offset"] - unit["start_offset"] != len(unit["quote"])):
            raise WorkerError("generation_invalid_evidence", 502)
        previous_end = unit["end_offset"]
        if (not isinstance(row, dict) or set(row) != {"label"}
                or type(row["label"]) is not int or not 0 <= row["label"] <= 9):
            raise WorkerError("generation_invalid_schema", 502)


def _title(quote):
    # Evidence is never edited. Only the selected title's literal value is projected.
    if quote.splitlines() != [quote]:
        raise WorkerError("generation_unsupported_field", 502)
    values = metadata_values("meeting_title", quote)
    if values:
        value = values[0]
    else:
        empty_prefix = re.fullmatch(
            r"(?:\*\*)?(?:회의\s*제목|제목|title)(?:\*\*)?\s*[:：]\s*", quote, re.IGNORECASE)
        heading = re.fullmatch(r" {0,3}#{1,6}(?:[ \t]+(.*)|[ \t]*)", quote)
        if empty_prefix:
            raise WorkerError("generation_unsupported_field", 502)
        if heading:
            value = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", heading.group(1) or "").strip()
        else:
            value = quote
    if not value.strip() or len(value) > 200 or value not in quote:
        raise WorkerError("generation_unsupported_field", 502)
    return value


def assemble_coverage(units, labels):
    """Assemble actual span-only units and ordered label-only rows, without reclassification.

    Callers must bind these units to the original full source. This function can
    validate coordinate shape/order, but cannot authenticate a source it was not given.
    Offline custody must prove the original unit-ID-to-position mapping separately.
    """
    _validate(units, labels)
    metadata, items = [], []
    for index, row in enumerate(labels):
        field = LABELS[row["label"]]
        if field in {"meeting_title", "meeting_date", "participants", "purpose"}:
            metadata.append([index, field])
        elif field != "skip":
            items.append([index, field])
    if len(items) > 150:
        raise WorkerError("generation_item_limit", 422)
    if len(metadata) > 30:
        raise WorkerError("generation_metadata_limit", 422)

    pools = {kind: [index for index, field in items if field == kind
                   and (kind != "topic" or not summary_boilerplate(units[index]["quote"]))]
             for kind in SUMMARY_ORDER}
    selected = []
    while len(selected) < 4 and any(pools.values()):
        for kind in SUMMARY_ORDER:
            if pools[kind] and len(selected) < 4:
                selected.append(pools[kind].pop(0))
    analysis = extraction_analysis(json.dumps({
        "summary_lines": sorted(selected), "items": items,
        "metadata": [row for row in metadata if row[1] != "meeting_title"]}), units)
    for index, field in metadata:
        if field != "meeting_title":
            continue
        value = _title(units[index]["quote"])
        if analysis["meeting_title"] not in (None, value):
            raise WorkerError("generation_conflicting_metadata", 502)
        analysis["meeting_title"] = value
        analysis["metadata_evidence"].append({**units[index], "field": field})
    analysis["metadata_evidence"].sort(key=lambda row: row["start_offset"])
    return merge_analyses([analysis])


class CoverageMeetingRuntime(MeetingRuntime):
    """Replace only assembly inside the frozen admission/deadline lifecycle."""

    extraction_assembly = ASSEMBLY

    def analyze(self, request):
        def run(deadline, telemetry):
            self.last_assembly = {"assembly": ASSEMBLY, "failure": None}
            try:
                units = [unit for group in partitions(request.content, self.generator) for unit in group]
                if len(units) > 160:
                    raise WorkerError("generation_partition_limit", 422)
                prompts = [classification_messages(unit) for unit in units]
                labels, metrics = self.generator.classify_bounded(prompts, deadline)
                telemetry.append(metrics)
                analysis = assemble_coverage(units, labels)
                positions = {row["start_offset"]: index for index, row in enumerate(units)}
                selected = [positions[row["start_offset"]] for row in analysis["summary_evidence"]]
                self.last_assembly = {"assembly": ASSEMBLY, "failure": None,
                    "summary": [{"id": i, "type": LABELS[labels[i]["label"]]} for i in selected],
                    "title_candidate_ids": [i for i, row in enumerate(labels) if row["label"] == 1],
                    "title_projected": analysis["meeting_title"] is not None}
                return {"analysis": analysis}
            except WorkerError as error:
                self.last_assembly = {"assembly": ASSEMBLY, "failure": error.code}
                raise
        return self._run(run)
