"""Synthetic partial-report checks; no experiment data is opened."""
import json

import pytest

from scripts import prepare_meeting_partial_audit as partial
from tests import test_meeting_review_audit as synthetic

source = synthetic.source


@pytest.fixture
def failed(source, monkeypatch):
    files, seed, output, report = source
    spec = report["phase_inputs"]["calibration"]
    spec["input_file"] = str(files["cases"])
    report["results"] = report["results"][:4]
    report["results"][-1] = {"id": "synthetic-3", "structural_status": "failed",
                              "error": "generation_invalid_review"}
    report["stages"] = report["stages"][:4]
    report.update(phase="calibration", status="failed", sources_unchanged=False)
    bound = files["cases"].parent / "code.txt"
    bound.write_bytes(b"synthetic code")
    report["bound_files"] = {str(bound): partial.sha(bound)}
    plan = {"phases": report["phase_inputs"], "bound_files": report["bound_files"],
            "audit": {"seed_sha256": partial.sha(seed)}}
    plan_path = files["report"].parent / "plan.json"
    partial.write_json(plan_path, plan)
    report["plan_sha256"] = partial.sha(plan_path)
    partial.write_json(files["report"], report)
    monkeypatch.setattr(partial, "local_path", lambda value: type(plan_path)(value))
    return files, seed, output, report, plan_path, bound


def run(failed):
    files, seed, output, _, plan, _ = failed
    return partial.prepare(plan, files["report"], files["oracle"], seed, output)


def test_partial_prefix_is_preserved_as_failure_not_full_gate(failed):
    receipt = run(failed)
    _, _, output, _, _, _ = failed
    pack = json.loads((output / "review-input.json").read_text())
    assert receipt["samples"] == 8 and receipt["selection_gate_passed"] is False
    assert pack["planned_cases"] == 8 and pack["unexecuted_cases"] == 4
    assert sum(s["answer"]["status"] == "error" for s in pack["samples"]) == 1
    assert all(s["oracle"]["id"] in {f"synthetic-{n}" for n in range(4)} for s in pack["samples"])
    with pytest.raises(FileExistsError):
        run(failed)


@pytest.mark.parametrize("change", ["prefix", "source", "oracle", "plan"])
def test_unbound_or_nonprefix_failure_is_rejected(failed, change):
    files, _, output, report, plan, bound = failed
    if change == "prefix":
        report["results"].reverse()
        partial.write_json(files["report"], report)
    elif change == "source":
        bound.write_bytes(b"modified")
    elif change == "oracle":
        partial.write_json(files["oracle"], {"cases": []})
    else:
        plan.write_bytes(plan.read_bytes() + b" ")
    with pytest.raises(ValueError):
        run(failed)
    assert not output.exists()
