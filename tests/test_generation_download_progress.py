"""Small fake-network transfer checks; no downloads, Torch, or GPU execution."""

import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from doctrail import generation_runtime as runtime
from scripts import prepare_generation_model as prepare


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / "private-model-directory"
    root.mkdir()
    files = {}
    for name in sorted(runtime.ALLOWED_FILES):
        payload = name.encode()
        (root / name).write_bytes(payload)
        files[name] = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    manifest = {
        "schema_version": 1,
        "model": {"repo_id": runtime.MODEL_ID, "revision": runtime.MODEL_REVISION,
                  "license": "Apache-2.0", "files": files},
        "runtime": dict(runtime.RUNTIME),
    }
    path = tmp_path / "private-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, path


def fake_download(snapshot, monkeypatch, *, payload=None):
    root, _ = snapshot
    target = root / "config.json"
    original = target.read_bytes()
    target.unlink()
    state = SimpleNamespace(calls=0)

    class Response(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 2))

    def open_url(request, timeout):
        state.calls += 1
        response = Response(original if payload is None else payload)
        response.url = request.full_url
        return response

    monkeypatch.setattr(prepare.urllib.request, "urlopen", open_url)
    assert prepare.DOWNLOAD_PROGRESS_BYTES == 64 * 1024 * 1024
    monkeypatch.setattr(prepare, "DOWNLOAD_PROGRESS_BYTES", 4)
    return state


def test_optional_progress_reports_thresholds_and_final_size_with_only_safe_fields(
    snapshot, monkeypatch
):
    state = fake_download(snapshot, monkeypatch)
    events = []
    result = prepare.prepare_snapshot(*snapshot, download=True, progress=events.append)
    assert result["verified"] is True and state.calls == 1
    assert events == [
        {"filename": "config.json", "downloaded_bytes": count, "expected_bytes": 11}
        for count in [4, 8, 11]
    ]


def test_old_api_without_callback_still_works(snapshot, monkeypatch):
    state = fake_download(snapshot, monkeypatch)
    assert prepare.prepare_snapshot(*snapshot, download=True)["verified"] is True
    assert state.calls == 1


@pytest.mark.parametrize("download", [False, True])
def test_no_progress_for_existing_verified_files_or_offline_verification(
    snapshot, monkeypatch, download
):
    monkeypatch.setattr(prepare.urllib.request, "urlopen",
                        lambda *a, **kw: pytest.fail("unexpected download"))
    events = []
    assert prepare.prepare_snapshot(*snapshot, download=download, progress=events.append)["verified"]
    assert events == []


def test_transfer_progress_does_not_claim_hash_verification(snapshot, monkeypatch):
    fake_download(snapshot, monkeypatch, payload=b"X" * 11)
    events = []
    with pytest.raises(runtime.GenerationError, match="model_download_hash_mismatch"):
        prepare.prepare_snapshot(*snapshot, download=True, progress=events.append)
    assert events[-1] == {"filename": "config.json", "downloaded_bytes": 11, "expected_bytes": 11}
    assert not (snapshot[0] / "config.json").exists()


def test_exact_threshold_end_emits_once(snapshot, monkeypatch):
    fake_download(snapshot, monkeypatch)
    monkeypatch.setattr(prepare, "DOWNLOAD_PROGRESS_BYTES", 11)
    events = []
    prepare.prepare_snapshot(*snapshot, download=True, progress=events.append)
    assert events == [{"filename": "config.json", "downloaded_bytes": 11, "expected_bytes": 11}]


def test_cli_progress_is_flushed_stderr_json_and_receipt_remains_stdout(
    snapshot, monkeypatch, capsys
):
    fake_download(snapshot, monkeypatch)
    monkeypatch.setattr(prepare.sys, "argv", [
        "prepare_generation_model", "--snapshot", str(snapshot[0]),
        "--manifest", str(snapshot[1]), "--download",
    ])
    assert prepare.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["verified"] is True
    lines = [json.loads(line) for line in captured.err.splitlines()]
    assert [line["downloaded_bytes"] for line in lines] == [4, 8, 11]
    assert all(set(line) == {"filename", "downloaded_bytes", "expected_bytes"} for line in lines)
    assert "private-model-directory" not in captured.err
    assert "https://" not in captured.err


def test_progress_flushes_on_each_emit(monkeypatch):
    class Stream(io.StringIO):
        flushes = 0

        def flush(self):
            self.flushes += 1
            super().flush()

    stream = Stream()
    monkeypatch.setattr(prepare.sys, "stderr", stream)
    event = {"filename": "config.json", "downloaded_bytes": 4, "expected_bytes": 11}
    prepare._print_progress(event)
    assert stream.flushes == 1
    assert json.loads(stream.getvalue()) == event
