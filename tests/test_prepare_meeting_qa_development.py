"""Portable public packet checks; no local experiment/model/runtime dependencies."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import prepare_meeting_qa_development as packet


def copy_packet(tmp_path):
    return Path(shutil.copytree(packet.DEFAULT_BUNDLE, tmp_path / "packet"))


def test_fixed_public_packet_reproduces_exact_inputs_and133_units():
    outputs = packet.reproduce()
    assert packet.sha(outputs["case-01.input.json"]) == "dae9cce140f36e0b9e06c99cc2952d1957a7190133725a10ec4f1b3fae36865a"
    assert packet.sha(outputs["case-02.input.json"]) == "11b2139321cc7a781cda9178269e572b2fd072c87816a6353ed9159ce2b00858"
    assert packet.sha(outputs["SOURCE-SIDECAR.json"]) == "5c396824d33e675e84f47e353d004f1f9759aea8c363e64625944f00d3c61fd9"
    sidecar = json.loads(outputs["SOURCE-SIDECAR.json"])
    assert len(sidecar["units"]) == 133 and len(sidecar["documents"]) == 3


def test_prepare_refuses_overwrite(tmp_path):
    target = tmp_path / "generated"
    expected = packet.prepare(packet.DEFAULT_BUNDLE, target)
    with pytest.raises(ValueError, match="new_output_required"):
        packet.prepare(packet.DEFAULT_BUNDLE, target)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == expected


def test_tampered_notice_fails_before_creating_output(tmp_path):
    bundle = copy_packet(tmp_path)
    (bundle / "originals/NOTICE").write_bytes(b"changed attribution")
    target = tmp_path / "generated"
    with pytest.raises(ValueError, match="packet_file_changed"):
        packet.prepare(bundle, target)
    assert not target.exists()


def test_question_change_fails_even_if_cases_file_hash_is_updated(tmp_path):
    bundle = copy_packet(tmp_path)
    cases_path = bundle / "cases.json"
    cases = json.loads(cases_path.read_bytes())
    cases["cases"][0]["question"] += " changed"
    raw = packet.encoded(cases)
    cases_path.write_bytes(raw)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["cases"].update(size_bytes=len(raw), sha256=packet.sha(raw))
    manifest_path.write_bytes(packet.encoded(manifest))
    with pytest.raises(ValueError, match="reproduced_bytes_changed"):
        packet.reproduce(bundle)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/outside", "a\\b"])
def test_paths_are_portable_and_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError, match="relative_packet_path"):
        packet.packet_path(tmp_path, name)


def test_script_and_bundle_work_without_repository_imports(tmp_path):
    bundle = copy_packet(tmp_path)
    script = tmp_path / "prepare.py"
    shutil.copyfile(Path(packet.__file__), script)
    result = subprocess.run([sys.executable, "-I", "-B", str(script), "validate", "--bundle", str(bundle)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"
    assert json.loads(result.stdout)["model_calls"] == 0


def test_unicode_source_units_keep_exact_offsets():
    text = "\n## 회의 목적\n  범위를 정한다.\n\n# 다음\n 검토한다. \n"
    units = packet.meeting_units(text)
    assert units[0]["quote"] == "## 회의 목적\n  범위를 정한다."
    assert len(units) == 3
    assert all(text[u["start_offset"]:u["end_offset"]] == u["quote"] for u in units)
