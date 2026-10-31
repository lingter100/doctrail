"""Validate and reproduce the public OpenSearch development packet offline.

Python standard library only. No model, tokenizer, service, network, or local
experiment files are read. All paths in the packet are relative to its manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "data/meeting-qa-development/opensearch-v1"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def packet_path(bundle, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name
            and not PurePosixPath(name).is_absolute()
            and all(part not in ("", ".", "..") for part in name.split("/")), "relative_packet_path")
    root = bundle.resolve()
    target = root / name
    require(target.resolve().is_relative_to(root), "packet_path_escape")
    return target


def read_checked(bundle, row, digest="sha256"):
    path = packet_path(bundle, row["path"])
    require(path.stat().st_size <= 1024**2, "packet_file_limit")
    raw = path.read_bytes()
    require(len(raw) == row["size_bytes"] and sha(raw) == row[digest], "packet_file_changed")
    return raw


def meeting_units(source):
    """Portable copy of the current contract's span/lines/meeting_units rules.

    Source identity is recorded in manifest.json. Generated sidecar hashes check
    the result against the accepted packet, including all133 document-local units.
    """
    def span(start, end):
        return {"quote": source[start:end], "start_offset": start, "end_offset": end}

    units = []
    for match in re.finditer(r"[^\n]+", source):
        text = match.group()
        left = len(text) - len(text.lstrip())
        right = len(text.rstrip())
        if right > left:
            units.append(span(match.start() + left, match.start() + right))
    result, index = [], 0
    while index < len(units):
        current = units[index]
        if (re.fullmatch(r"#{1,6}\s+(?:Purpose|목적|회의\s*목적)\s*", current["quote"], re.IGNORECASE)
                and index + 1 < len(units) and not units[index + 1]["quote"].startswith("#")):
            result.append(span(current["start_offset"], units[index + 1]["end_offset"]))
            index += 2
        else:
            result.append(current)
            index += 1
    return result


def reproduce(bundle=DEFAULT_BUNDLE):
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    require(manifest["schema_version"] == 1 and manifest["kind"] == "open-development-qa-packet",
            "packet_schema")
    require(len(manifest["documents"]) == 3 and len(manifest["supporting_files"]) == 3,
            "source_file_count")
    sources = {}
    for row in [*manifest["documents"], *manifest["supporting_files"]]:
        raw = read_checked(bundle, row, "raw_sha256")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        require(blob == row["git_blob_sha1"], "git_blob_changed")
        text = raw.decode("utf-8", errors="strict")
        require(sha(text.encode("utf-8")) == row["processed_utf8_sha256"], "processed_source_changed")
        require(row["path"] not in sources, "duplicate_source_path")
        sources[row["path"]] = text
    cases = json.loads(read_checked(bundle, manifest["cases"]))["cases"]
    read_checked(bundle, manifest["review"])
    read_checked(bundle, manifest["review_metadata"])
    require(len(cases) == 2 and len({c["id"] for c in cases}) == 2, "case_count")
    content, documents, metadata, units = "", [], [], []
    for row in manifest["documents"]:
        title = row["title"]
        content += "\n\n# " + title + "\n\n"
        start = len(content)
        text = sources[row["path"]]
        content += text
        document = {"document_id": row["document_id"], "revision": 1, "title": title,
                    "content": text, "start_offset": start, "end_offset": len(content)}
        documents.append(document)
        metadata.append({k: document[k] for k in ("document_id", "revision", "title", "start_offset", "end_offset")}
                        | {"content_sha256": sha(text.encode("utf-8"))})
        for unit in meeting_units(text):
            units.append({"id": len(units), "document_id": row["document_id"], "revision": 1,
                          **unit, "bundle_start_offset": start + unit["start_offset"],
                          "bundle_end_offset": start + unit["end_offset"]})
    require(len(units) == manifest["unit_count"], "unit_count")
    outputs = {"SOURCE-SIDECAR.json": encoded({"bundle_sha256": sha(content.encode("utf-8")),
                                               "documents": metadata, "units": units})}
    for index, case in enumerate(cases, 1):
        reference = case["reference_answer"]
        require(reference["status"] in ("answered", "abstained")
                and bool(reference["claims"]) == (reference["status"] == "answered"), "reference_status")
        for claim in reference["claims"]:
            require(set(claim) == {"text", "evidence"} and isinstance(claim["text"], str)
                    and claim["text"] and claim["evidence"]
                    and all(type(i) is int and 0 <= i < len(units) for i in claim["evidence"]), "reference_evidence")
        outputs[f"case-{index:02d}.input.json"] = encoded({"id": case["id"], "title": manifest["input_title"],
            "question": case["question"], "bundle": content, "documents": documents})
    expected = {row["path"]: row for row in manifest["reproduced_files"]}
    require(set(outputs) == set(expected), "reproduced_file_set")
    for name, raw in outputs.items():
        require(len(raw) == expected[name]["size_bytes"] and sha(raw) == expected[name]["sha256"],
                "reproduced_bytes_changed")
    return outputs


def prepare(bundle, output):
    outputs = reproduce(bundle)  # Verify everything before creating any output.
    output = Path(output)
    require(not output.exists(), "new_output_required")
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in outputs.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "prepare"))
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if args.output is None:
            parser.error("prepare requires --output")
        outputs = prepare(args.bundle, args.output)
    else:
        if args.output is not None:
            parser.error("validate does not take --output")
        outputs = reproduce(args.bundle)
    print(json.dumps({"status": "PASS", "scope": "offline_byte_reproduction_not_model_quality",
                      "files": [{"path": name, "size_bytes": len(raw), "sha256": sha(raw)}
                                for name, raw in outputs.items()], "model_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
