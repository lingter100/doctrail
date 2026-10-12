"""CI downloads must stay limited to frozen tokenizer JSON, never model weights."""

import pytest

from scripts.replay_training_readiness import tokenizer_spec


def test_tokenizer_download_whitelists_four_files():
    names = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
    spec = {"repo_id": "synthetic", "revision": "fixed", "files":
            {name: {"sha256": name} for name in names + ["model.safetensors", "remote.py"]}}
    filtered = tokenizer_spec(spec)
    assert list(filtered["files"]) == names
    assert filtered["revision"] == "fixed"
    assert "model.safetensors" in spec["files"]


def test_tokenizer_download_refuses_incomplete_snapshot():
    with pytest.raises(ValueError, match="missing"):
        tokenizer_spec({"files": {"tokenizer.json": {}}})
