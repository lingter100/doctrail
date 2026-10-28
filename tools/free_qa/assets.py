"""Pinned, opt-in asset preparation. Import never reads model assets or probes resources."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from tools.summary_grammar.runtime import BoundaryError, OwnedTree, parse_json, require, safe_path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "data/models/meetings-generation-qwen25-7b-q4km-v1.json"
PROFILE_SHA = "6cb34ab578e55c61e20b7c5d49fc7cbb9086fd06cd57359e6b2ccd1ff67f97c7"
TRANSFER = 5 * 1024**3
DISK = 6 * 1024**3
SECONDS = 1800
METADATA = 32 * 1024**2
CHUNK = 1024 * 1024
HOSTS = {"huggingface.co", "cas-bridge.xethub.hf.co", "cdn-lfs.huggingface.co",
         "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co", "cdn-lfs-eu-1.hf.co", "us.aws.cdn.hf.co"}
CONTROL = {"profile.json", "attempt.json", "supervisor.stdout", "supervisor.stderr", "supervisor.json",
           "acquisition.json", "failure.json", "download-1.json", "download-2.json", "shard-1.json", "shard-2.json",
           "verify/attempt.json", "verify/supervisor.stdout", "verify/supervisor.stderr",
           "verify/supervisor.json", "verify/metadata.json", "verify/failure.json",
           "verify/shard-1.json", "verify/shard-2.json",
           "supervisor-invalidation.json", "verify/supervisor-invalidation.json"}
DIRS = {"assets", "tmp", "verify", "verify/tmp"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def profile():
    data = small_bytes(PROFILE, 65536)
    require(sha(data) == PROFILE_SHA, "profile_bytes_changed")
    result = parse_json(data)
    require(result["gguf"]["total_size_bytes"] == 4683073632
            and len(result["gguf"]["shards"]) == 2, "profile_contract")
    return result


def regular(path, directory=False):
    info = Path(path).lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 1024,
            "linked_path")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "file_type")
    if not directory:
        require(info.st_nlink == 1, "hardlinked_file")
    return info


def checked_root(root):
    root = Path(root).absolute()
    # Inspect every existing ancestor before resolving; no junction/symlink shortcut.
    for path in reversed([root, *root.parents]):
        if path.exists() or path.is_symlink():
            regular(path, directory=True)
    safe_path(root.parent, root.name)
    return root


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def allowed_files(spec):
    return CONTROL | {"assets/" + s["filename"] + suffix for s in spec["gguf"]["shards"] for suffix in ("", ".part")}


def scan(root, spec):
    checked_root(root)
    files, total = {}, 0
    def walk(folder):
        nonlocal total
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                safe_path(root, name)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    regular(path, directory=True)
                    require(name in DIRS, "extra_directory")
                    walk(path)
                else:
                    info = regular(path)
                    require(name in allowed_files(spec), "extra_file")
                    total += info.st_size
                    require(total <= DISK, "disk_budget")
                    files[name] = info.st_size
    walk(root)
    return files, total


def small_bytes(path, limit):
    before = regular(path)
    require(before.st_size <= limit, "small_file_limit")
    with path.open("rb", buffering=0) as stream:
        require(identity(os.fstat(stream.fileno())) == identity(before), "small_file_identity")
        data = stream.read(limit + 1)
        require(len(data) <= limit and len(data) == before.st_size
                and identity(os.fstat(stream.fileno())) == identity(before) == identity(regular(path)), "small_file_changed")
    return data


def read_json(path):
    return parse_json(small_bytes(path, 1024**2))


def write_json(path, value):
    data = canonical(value) + b"\n"
    require(len(data) <= 1024**2, "receipt_size")
    safe_path(path.parent, path.name)
    with path.open("xb") as out:
        out.write(data)
    regular(path)


class Budget:
    def __init__(self, root, spec, deadline, clock=time.monotonic):
        self.root, self.spec, self.deadline, self.clock = root, spec, deadline, clock
        self.transferred = 0

    def time_check(self):
        require(self.clock() < self.deadline - 5, "shared_deadline")

    def check(self, incoming=0):
        require(type(incoming) is int and incoming >= 0, "byte_count")
        self.transferred += incoming
        require(self.transferred <= TRANSFER, "transfer_budget")
        self.time_check()
        files, total = scan(self.root, self.spec)
        require(total + incoming <= DISK, "disk_budget")
        return files, total


def checked_url(url):
    p = urlparse(url)
    require(p.scheme == "https" and p.hostname in HOSTS and p.port in (None, 443)
            and not p.username and not p.password and not p.fragment, "download_origin")
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    """Discard redirect bodies without a drain; all hops share the shard budget."""
    def __init__(self, budget):
        self.budget = budget
        self.visited = set()
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        require(req.get_method() == "GET" and req.data is None, "redirect_method")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_302(self, req, fp, code, msg, headers):
        # The stdlib implementation drains fp.read() without a size. Never call it.
        # Close even a rejected/malformed redirect; no discarded body is consumed.
        fp.close()
        self.budget.check()
        location = headers.get("location") or headers.get("uri")
        require(isinstance(location, str) and location
                and all(32 < ord(c) < 127 for c in location), "redirect_location")
        newurl = checked_url(urljoin(req.full_url, location))
        self.visited.add(req.full_url)
        require(newurl not in self.visited and self.hops < 10, "redirect_limit")
        self.hops += 1
        self.visited.add(newurl)
        redirected = self.redirect_request(req, fp, code, msg, headers, newurl)
        self.budget.check()
        timeout = min(req.timeout, 10, self.budget.deadline - self.budget.clock() - 5)
        require(timeout > 0, "shared_deadline")
        return self.parent.open(redirected, timeout=timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def atomic_publish(partial, target):
    # Windows rename fails if target exists; do not emulate with overwriting POSIX rename.
    require(os.name == "nt", "atomic_publish_requires_windows")
    regular(partial)
    require(partial.parent == target.parent and not target.exists() and not target.is_symlink(), "publish_target")
    os.rename(partial, target)
    regular(target)


def download_one(root, shard, budget, opener=None, publish=atomic_publish):
    require(shard in budget.spec["gguf"]["shards"], "unregistered_shard")
    checked_url(shard["url"])
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects(budget))
    partial = safe_path(root / "assets", shard["filename"] + ".part")
    target = safe_path(root / "assets", shard["filename"])
    require(not target.exists() and not partial.exists(), "no_retry_or_overwrite")
    budget.check()
    request = urllib.request.Request(shard["url"], headers={"User-Agent": "DocTrail-free-QA-assets/1", "Accept-Encoding": "identity"})
    count, h = 0, hashlib.sha256()
    with partial.open("xb") as output, opener.open(request, timeout=min(10, max(0.001, budget.deadline - budget.clock() - 5))) as response:
        checked_url(response.geturl())
        require(response.status == 200 and response.headers.get("Content-Encoding", "identity") == "identity", "http_response")
        length = response.headers.get("Content-Length")
        require(length is None or length == str(shard["size_bytes"]), "http_length")
        opened = os.fstat(output.fileno())
        while True:
            budget.check()
            chunk = response.read(min(CHUNK, shard["size_bytes"] - count + 1))
            if not chunk:
                break
            count += len(chunk)
            budget.check(len(chunk))
            require(count <= shard["size_bytes"], "shard_size")
            output.write(chunk)
            h.update(chunk)
        output.flush()
        os.fsync(output.fileno())
        finished = os.fstat(output.fileno())
        require(finished.st_nlink == 1 and (finished.st_dev, finished.st_ino) == (opened.st_dev, opened.st_ino)
                and finished.st_size == count and identity(regular(partial)) == identity(finished), "partial_identity")
    require(count == shard["size_bytes"] and h.hexdigest() == shard["sha256"], "shard_digest")
    budget.check()
    require(identity(regular(partial)) == identity(finished), "partial_changed")
    publish(partial, target)
    require(identity(regular(target)) == identity(finished), "published_identity")
    return {"filename": shard["filename"], "size_bytes": count, "sha256": h.hexdigest(), "url": shard["url"]}


# GGUF v3 little-endian metadata only. No tensor descriptor/payload parser.
FORMATS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "B", 10: "Q", 11: "q", 12: "d"}


class KVReader:
    def __init__(self, stream, check=lambda: None, max_bytes=METADATA):
        require(type(max_bytes) is int and 0 < max_bytes <= METADATA, "metadata_limit")
        self.maximum = max_bytes
        self.stream, self.check, self.used, self.values = stream, check, 0, 0
        self.whole = hashlib.sha256()
        self.value_hash = None

    def read(self, count):
        self.check()
        require(type(count) is int and 0 <= count <= self.maximum - self.used, "metadata_limit")
        data = self.stream.read(count)
        require(len(data) == count, "metadata_truncated")
        self.used += count
        self.whole.update(data)
        if self.value_hash is not None:
            self.value_hash.update(data)
        return data

    def number(self, fmt):
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))[0]

    def string(self, maximum=METADATA):
        length = self.number("Q")
        require(length <= maximum, "string_length")
        raw = self.read(length)
        raw.decode("utf-8", "strict")
        return raw

    def value(self, kind, retain=False):
        self.values += 1
        require(self.values <= 2_000_000, "metadata_value_count")
        if kind in FORMATS:
            value = self.number(FORMATS[kind])
            require(kind != 7 or value in (0, 1), "boolean_value")
            require(not isinstance(value, float) or math.isfinite(value), "nonfinite_value")
            return value if retain else None
        if kind == 8:
            value = self.string()
            return value if retain else None
        if kind == 9:
            element, count = self.number("I"), self.number("Q")
            require(element in {*FORMATS, 8} and count <= 2_000_000 - self.values, "array_type_or_count")
            minimum = 8 if element == 8 else struct.calcsize("<" + FORMATS[element])
            require(count * minimum <= self.maximum - self.used, "array_byte_limit")
            for _ in range(count):
                self.value(element)
            return {"element_type": element, "count": count}
        raise BoundaryError("metadata_type")

    def parse(self):
        require(self.read(4) == b"GGUF" and self.number("I") == 3, "gguf_magic_or_version")
        tensors, count = self.number("Q"), self.number("Q")
        require(0 < tensors <= 1_000_000 and 0 < count <= 65536, "gguf_counts")
        keys, tokenizer, scalars, template = set(), [], {}, None
        for _ in range(count):
            key = self.string(1024).decode("utf-8")
            require(re.fullmatch(r"[A-Za-z0-9_.-]+", key) and key not in keys, "metadata_key")
            keys.add(key)
            kind = self.number("I")
            self.value_hash = hashlib.sha256()
            value = self.value(kind, retain=key in {"general.architecture", "split.no", "split.count", "split.tensors.count", "tokenizer.chat_template"})
            value_sha = self.value_hash.hexdigest()
            self.value_hash = None
            if key.startswith("tokenizer."):
                item = {"key": key, "type": kind, "value_wire_sha256": value_sha}
                if kind == 9:
                    item.update(value)
                tokenizer.append(item)
            if key == "tokenizer.chat_template":
                require(kind == 8 and value and len(value) <= 256 * 1024, "template_type_or_size")
                template = {"raw_utf8_sha256": sha(value), "size_bytes": len(value)}
            elif key in {"general.architecture", "split.no", "split.count", "split.tensors.count"}:
                scalars[key] = {"type": kind, "value": value.decode() if isinstance(value, bytes) else value}
        return {"version": 3, "tensor_count_header": tensors, "metadata_bytes_read": self.used,
                "metadata_wire_sha256": self.whole.hexdigest(), "scalars": scalars,
                "template": template, "tokenizer": sorted(tokenizer, key=lambda x: x["key"]),
                "tensor_descriptors_or_payload_parsed": False}


def validate_metadata(rows):
    require(len(rows) == 2, "split_set")
    for i, row in enumerate(rows):
        scalars = row["scalars"]
        require(scalars.get("split.no") == {"type": 2, "value": i}
                and scalars.get("split.count") == {"type": 2, "value": 2}, "split_metadata")
        if i == 0 or "general.architecture" in scalars:
            require(scalars.get("general.architecture") == {"type": 8, "value": "qwen2"}, "architecture")
    first = rows[0]
    total = sum(r["tensor_count_header"] for r in rows)
    require(first["scalars"].get("split.tensors.count") == {"type": 5, "value": total}, "split_tensor_count")
    require(first["template"] is not None, "missing_embedded_template")
    tokens = {r["key"]: r for r in first["tokenizer"]}
    require(tokens.get("tokenizer.ggml.model", {}).get("type") == 8
            and tokens.get("tokenizer.ggml.tokens", {}).get("element_type") == 8
            and tokens["tokenizer.ggml.tokens"]["count"] > 0, "missing_tokenizer_metadata")
    if rows[1]["tokenizer"]:
        require(rows[1]["tokenizer"] == first["tokenizer"], "split_tokenizer_mismatch")
    if "split.tensors.count" in rows[1]["scalars"]:
        require(rows[1]["scalars"]["split.tensors.count"] == first["scalars"]["split.tensors.count"], "split_tensor_count")
    return {"shards": rows, "binding_sha256": sha(canonical(rows)), "execution_approved": False,
            "requires_separate_review": True, "runtime55_currently_verified": False,
            "template_or_tokenizer_overrides": False}


def verify_one(path, shard, budget, metadata_limit=METADATA):
    before = regular(path)
    require(before.st_size == shard["size_bytes"], "shard_size")
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as source:
        require(identity(os.fstat(source.fileno())) == identity(before), "asset_identity")
        while True:
            budget.check()
            block = source.read(CHUNK)
            if not block:
                break
            h.update(block)
        require(h.hexdigest() == shard["sha256"], "shard_digest")
        source.seek(0)
        metadata = KVReader(source, budget.time_check, metadata_limit).parse()
        require(identity(os.fstat(source.fileno())) == identity(before) == identity(regular(path)), "asset_changed")
    return metadata



def inspect_assets(root, spec, budget, folder):
    snapshots = [identity(regular(root / "assets" / s["filename"])) for s in spec["gguf"]["shards"]]
    rows, remaining = [], METADATA
    for i, shard in enumerate(spec["gguf"]["shards"], 1):
        row = verify_one(root / "assets" / shard["filename"], shard, budget, remaining)
        rows.append(row)
        write_json(folder / f"shard-{i}.json", {"filename": shard["filename"], "sha256": shard["sha256"], "metadata": row})
        remaining -= row["metadata_bytes_read"]
    require(snapshots == [identity(regular(root / "assets" / s["filename"])) for s in spec["gguf"]["shards"]], "late_asset_change")
    budget.check()
    return validate_metadata(rows)


def acquisition_complete(root, spec, verifying=False):
    files, _ = scan(root, spec)
    require(not {"supervisor-invalidation.json", "verify/supervisor-invalidation.json"} & files.keys(), "supervisor_invalidated")
    expected = {"assets/" + s["filename"] for s in spec["gguf"]["shards"]}
    require({p for p in files if p.startswith("assets/")} == expected, "asset_file_set")
    required = expected | {"profile.json", "attempt.json", "supervisor.stdout", "supervisor.stderr",
                           "supervisor.json", "acquisition.json", "download-1.json", "download-2.json", "shard-1.json", "shard-2.json"}
    permitted = required | ({"verify/attempt.json", "verify/supervisor.stdout", "verify/supervisor.stderr"} if verifying else set())
    require(required <= files.keys() and files.keys() <= permitted, "acquisition_file_set")
    require("failure.json" not in files and small_bytes(root / "profile.json", 65536) == small_bytes(PROFILE, 65536), "acquisition_failed_or_profile_changed")
    result = read_json(root / "acquisition.json")
    expected_assets = [{k: s[k] for k in ("filename", "size_bytes", "sha256", "url")} for s in spec["gguf"]["shards"]]
    require(result == {"status": "ACQUIRED_VERIFIED_METADATA_UNREVIEWED", "profile_sha256": PROFILE_SHA,
                       "assets": expected_assets, "transfer_bytes": sum(s["size_bytes"] for s in expected_assets),
                       "execution_approved": False, "metadata": result.get("metadata")}, "acquisition_receipt")
    require(result["metadata"] == validate_metadata(result["metadata"]["shards"]), "acquisition_metadata_binding")
    supervised = read_json(root / "supervisor.json")
    require(supervised["status"] == "TERMINAL_CLEAN" and supervised["cleanup"]["all_absent"]
            and not supervised["cleanup"]["errors"], "prior_cleanup")
    for i, shard in enumerate(spec["gguf"]["shards"], 1):
        stage = read_json(root / f"download-{i}.json")
        require(stage == {k: shard[k] for k in ("filename", "size_bytes", "sha256", "url")}, "download_receipt")
        metadata_stage = read_json(root / f"shard-{i}.json")
        require(metadata_stage == {"filename": shard["filename"], "sha256": shard["sha256"],
                "metadata": result["metadata"]["shards"][i - 1]}, "metadata_stage_binding")


def worker(root, operation, token, deadline, *, spec=None, opener=None, publish=atomic_publish, clock=time.monotonic):
    spec = profile() if spec is None else spec
    root = checked_root(root)
    folder = root if operation == "acquire" else root / "verify"
    attempt = read_json(folder / "attempt.json")
    require(operation in {"acquire", "verify-only"} and attempt["token"] == token
            and os.environ.get("DOCTRAIL_ASSET_WORKER") == token
            and attempt["operation"] == operation and attempt["deadline"] == deadline
            and attempt["root"] == str(root), "worker_binding")
    budget = Budget(root, spec, deadline, clock)
    try:
        if operation == "acquire":
            stages, snapshots = [], []
            for i, shard in enumerate(spec["gguf"]["shards"], 1):
                stage = download_one(root, shard, budget, opener, publish)
                write_json(root / f"download-{i}.json", stage)
                stages.append(stage)
                snapshots.append(identity(regular(root / "assets" / shard["filename"])))
            require(snapshots == [identity(regular(root / "assets" / s["filename"])) for s in spec["gguf"]["shards"]], "late_asset_change")
            budget.check()
            metadata = inspect_assets(root, spec, budget, root)
            result = {"status": "ACQUIRED_VERIFIED_METADATA_UNREVIEWED", "profile_sha256": PROFILE_SHA,
                      "assets": stages, "transfer_bytes": budget.transferred, "execution_approved": False, "metadata": metadata}
            write_json(root / "acquisition.json", result)
        else:
            acquisition_complete(root, spec, verifying=True)
            metadata = inspect_assets(root, spec, budget, folder)
            result = {"status": "VERIFIED_BYTES_METADATA_UNREVIEWED", "profile_sha256": PROFILE_SHA,
                      "assets": [{k: s[k] for k in ("filename", "size_bytes", "sha256")} for s in spec["gguf"]["shards"]],
                      "metadata": metadata, "network_calls": 0}
            budget.check()
            write_json(folder / "metadata.json", result)
        return result
    except Exception as error:
        write_json(folder / "failure.json", {"status": "FAILED_NO_RETRY", "error": type(error).__name__,
                   "reason": str(error), "partial_files_preserved": True, "transfer_bytes": budget.transferred})
        raise


def supervise(root, operation, *, allow_download=False, ps=None, popen=subprocess.Popen,
              clock=time.monotonic, sleeper=time.sleep):
    require(operation in {"acquire", "verify-only"}, "operation")
    require(operation != "acquire" or allow_download is True, "explicit_download_required")
    require(operation != "verify-only" or allow_download is False, "verify_never_downloads")
    spec = profile()
    root = checked_root(root)
    deadline = clock() + SECONDS
    if operation == "acquire":
        root.mkdir(exist_ok=False)
        (root / "assets").mkdir()
        (root / "profile.json").write_bytes(small_bytes(PROFILE, 65536))
        folder = root
    else:
        acquisition_complete(root, spec)
        folder = root / "verify"
        folder.mkdir(exist_ok=False)
    temporary = folder / "tmp"
    temporary.mkdir(exist_ok=False)
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ}
    token = secrets.token_hex(24)
    env.update(TEMP=str(temporary), TMP=str(temporary), PATH=str(Path(sys.executable).parent), DOCTRAIL_ASSET_WORKER=token)
    attempt = {"operation": operation, "token": token, "root": str(root), "deadline": deadline,
               "shared_seconds": SECONDS, "cleanup_reserved_seconds": 5, "profile_sha256": PROFILE_SHA,
               "transfer_limit": TRANSFER, "disk_limit": DISK, "retry": False}
    write_json(folder / "attempt.json", attempt)
    if ps is None:
        import psutil as ps
    command = [sys.executable, "-B", str(ROOT / "scripts/prepare_meeting_free_qa.py"), "_worker",
               "--root", str(root), "--operation", operation, "--token", token, "--deadline", str(deadline)]
    allowed = [Path(sys.executable), Path(getattr(sys, "_base_executable", sys.executable))]
    if "SystemRoot" in env:
        allowed.append(Path(env["SystemRoot"]) / "System32/conhost.exe")
    process = tree = None
    error = None
    record = {"status": "FAILED", "attempt": attempt, "cleanup": None, "argv": command}
    try:
        scan(root, spec)
        with (folder / "supervisor.stdout").open("xb") as stdout, (folder / "supervisor.stderr").open("xb") as stderr:
            process = popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            tree = OwnedTree(process, allowed, ps, clock, sleeper)
            tree.capture(ps.Process(process.pid))
            while True:
                tree.live()
                require(clock() < deadline - 5, "shared_deadline")
                scan(root, spec)
                require((folder / "supervisor.stdout").stat().st_size <= 1024**2
                        and (folder / "supervisor.stderr").stat().st_size <= 1024**2, "worker_log_limit")
                if process.poll() is not None:
                    break
                sleeper(0.1)
            require(process.wait(timeout=max(0.001, deadline - clock() - 5)) == 0, "worker_exit")
    except Exception as exc:  # noqa: BLE001 - preserve first failure through owned cleanup
        error = exc
        record["error"] = type(exc).__name__ + ":" + str(exc)
    finally:
        if tree is not None and tree.seen:
            record["cleanup"] = tree.cleanup(min(deadline, clock() + 5))
        elif process is not None:
            failures = ["identity_capture_failed"]
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=max(0.001, min(deadline, clock() + 5) - clock()))
                handle = getattr(process, "_handle", None)
                if handle is not None and process.returncode is not None:
                    handle.Close()
            except Exception as exc:  # noqa: BLE001 - never approve unobserved descendants
                failures.append(type(exc).__name__)
            record["cleanup"] = {"all_absent": False, "errors": failures, "original_handle_only": True,
                                 "descendant_absence_unverified": True}
        clean = record["cleanup"] is not None and record["cleanup"]["all_absent"] and not record["cleanup"]["errors"]
    # Final I/O is part of the same deadline, not work after a cached success.
    # A late/failed finalization never overwrites a preliminary success receipt.
    try:
        require(clean and clock() <= deadline, "cleanup_unverified_or_late")
        if error:
            raise error
        result = read_json(folder / ("acquisition.json" if operation == "acquire" else "metadata.json"))
        require(result["status"] == ("ACQUIRED_VERIFIED_METADATA_UNREVIEWED" if operation == "acquire" else "VERIFIED_BYTES_METADATA_UNREVIEWED"), "worker_result")
        scan(root, spec)
        require(clock() <= deadline, "finalization_deadline")
        record.update(status="TERMINAL_CLEAN", within_shared_deadline=True)
        write_json(folder / "supervisor.json", record)
        scan(root, spec)
        require(clock() <= deadline, "finalization_deadline")
        return result
    except BaseException as exc:  # preserve interruption/final I/O failure as invalidation too
        write_json(folder / "supervisor-invalidation.json", {
            "status": "INVALIDATED_NO_RETRY", "reason": type(exc).__name__ + ":" + str(exc),
            "observed_at": clock(), "deadline": deadline, "prior_records_preserved": True})
        if not (folder / "supervisor.json").exists():
            record.update(status="FAILED", within_shared_deadline=clock() <= deadline)
            record.setdefault("error", type(exc).__name__ + ":" + str(exc))
            write_json(folder / "supervisor.json", record)
        raise
