"""Rebuild local M4 packs and replay saved readiness evidence without model inference.

The optional download fetches four pinned tokenizer/config JSON files only. Saved
token evidence is structurally replayed; this does not rerun tokenization or review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import prepare_training as pilot
from scripts import prepare_training_ready as ready
from scripts.prepare_models import prepare_model

ROOT = pilot.ROOT
DRAFTS = [ROOT / f"data/training/generation/{name}.draft.jsonl" for name in
          ("m4-fit", "m4-calibration", "m4-calibration-supplement-v1")]
AUTHOR_PACKS = [ROOT / f".local/{name}.json" for name in
                ("m4-author-fit-v3", "m4-author-calibration-v3",
                 "m4-author-calibration-supplement-v1")]
POSITIVE_REVIEWS = [ROOT / f"data/training/reviews/{name}.jsonl" for name in
                    ("m4-fit-semantic-v1", "m4-calibration-semantic-v1",
                     "m4-calibration-supplement-semantic-v1")]
NEGATIVE_REVIEWS = [ROOT / f"data/training/reviews/m4-negative-{shard}-v1.jsonl"
                    for shard in ("a", "b")]


def tokenizer_spec(spec: dict) -> dict:
    names = {"config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"}
    if not names.issubset(spec["files"]):
        raise ValueError("Required pinned tokenizer files missing")
    return {**spec, "files": {name: value for name, value in spec["files"].items() if name in names}}


def readiness_args(snapshot: Path):
    return argparse.Namespace(
        command="replay", readiness_plan=ROOT / "data/training/m4-readiness-plan-v1.json",
        pilot_dir=ROOT / "data/training/m4-pilot-v2", drafts=DRAFTS, author_packs=AUTHOR_PACKS,
        positive_reviews=POSITIVE_REVIEWS, negative_reviews=NEGATIVE_REVIEWS,
        review_pack_dir=ROOT / ".local", e5_snapshot=snapshot,
        token_receipt=ROOT / "data/training/m4-tokenizer-receipt-v1.json",
        output=ROOT / "data/training/m4-training-manifest-v1.json", verify=True,
    )


def materialize_packs() -> None:
    for partition, path in zip(("fit", "calibration", "calibration"), AUTHOR_PACKS, strict=True):
        arguments = ["author-pack", "--inventory", str(ROOT / "data/training/m4-inventory-v3.json"),
                     "--partition", partition, "--output", str(path)]
        if path == AUTHOR_PACKS[-1]:
            arguments += ["--document-ids", "k8s-ko-05261080c1ab2828"]
        else:
            arguments += ["--selection", str(ROOT / "data/training/generation/selection-v1.json")]
        pilot.main(arguments + (["--verify"] if path.exists() else []))
    args = readiness_args(ROOT / "models/e5")
    args.command = "packs"
    context = ready.load_context(args)
    for shard, pack in context["review_packs"].items():
        path = ROOT / f".local/m4-negative-review-{shard.lower()}-v1.json"
        pilot.write_or_verify(path, pilot.json_bytes(pack), verify=path.exists())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-tokenizer-only", action="store_true")
    parser.add_argument("--e5-snapshot", type=Path, default=ROOT / "models/e5")
    parser.add_argument("--version", choices=("v1", "all"), default="v1")
    args = parser.parse_args()
    snapshot = args.e5_snapshot.resolve()
    if args.download_tokenizer_only:
        # Separate directory prevents a partial spec from accepting a weight snapshot.
        snapshot = ROOT / ".local/readiness-tokenizer/e5"
        spec = json.loads((ROOT / "data/models/m3-models.json").read_bytes())["models"]["e5"]
        prepare_model("e5", tokenizer_spec(spec), snapshot.parent)
    materialize_packs()
    options = readiness_args(snapshot)
    manifest, _ = ready.replay_manifest(options)
    pilot.write_or_verify(options.output, pilot.json_bytes(manifest), verify=True)
    print(json.dumps({"saved_v1_readiness_replayed": True, "data_ready": manifest["data_ready"],
                      "actual_tokenization_rerun": False, "model_weights_loaded": False,
                      "training_executed": False}))
    if args.version == "all":
        from scripts import prepare_training_ready_v2 as v2

        options.v1_manifest = options.output
        options.v1_token_receipt = options.token_receipt
        options.readiness_plan = ROOT / "data/training/m4-readiness-plan-v2.json"
        options.token_receipt = ROOT / "data/training/m4-tokenizer-receipt-v2.json"
        options.output = ROOT / "data/training/m4-training-manifest-v2.json"
        context = v2.load_context(options)
        path = ROOT / context["v2_plan"]["supplemental_negative_review"]["pack_path"]
        pilot.write_or_verify(path, pilot.json_bytes(context["supplement_pack"]), verify=path.exists())
        manifest, _ = v2.replay_manifest(options, context)
        pilot.write_or_verify(options.output, pilot.json_bytes(manifest), verify=True)
        print(json.dumps({"saved_v2_readiness_replayed": True, "data_ready": manifest["data_ready"],
                          "actual_tokenization_rerun": False, "model_weights_loaded": False,
                          "training_executed": False}))


if __name__ == "__main__":
    main()
