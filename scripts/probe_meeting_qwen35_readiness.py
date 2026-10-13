"""Hash-bound two-call neutral readiness only; not answer-quality or Java evidence."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_contract import strict_json
from doctrail.meeting_gguf import GREEDY
from doctrail.meeting_qwen35 import PREAMBLE_SHA256, Qwen35Generator
from doctrail.meeting_runtime import DEADLINE_SECONDS
from scripts.probe_meeting_gguf import ROOT, sha, verify_plan, write
from scripts.serve_meeting_qwen35 import start_llama

SYSTEM = 'Return only {"status":"abstained","claims":[]} for this neutral readiness check.'
NEUTRAL_INPUTS = ("Hello.", "This is neutral readiness text without document facts.\n" * 300)
EXPECTED_JSON = {"status": "abstained", "claims": []}
SAMPLE_INTERVAL = 0.5


def safe_error(error):
    code = getattr(error, "code", "")
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,80}", code):
        return code
    if str(error) in {"candidate_source_binding_mismatch", "candidate_fixture_binding_mismatch",
                      "candidate_case_set_mismatch"}:
        return str(error)
    return type(error).__name__


def sample_resources(pid):
    """Post-load observations: native PID RSS and whole-device VRAM, not allocations."""
    import psutil
    sample = {"native_rss_mib": None, "device_memory_mib": {}, "errors": []}
    try:
        sample["native_rss_mib"] = psutil.Process(pid).memory_info().rss / (1024 * 1024)
    except (psutil.Error, OSError):
        sample["errors"].append("native_rss_unavailable")
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("gpu_sample_failed")
        for line in result.stdout.splitlines():
            match = re.fullmatch(r"\s*(\d+)\s*,\s*(\d+)\s*", line)
            if not match:
                raise ValueError("gpu_sample_failed")
            sample["device_memory_mib"][match[1]] = int(match[2])
        if not sample["device_memory_mib"]:
            raise ValueError("gpu_sample_failed")
    except (OSError, subprocess.SubprocessError, ValueError):
        sample["device_memory_mib"] = {}
        sample["errors"].append("device_memory_unavailable")
    return sample


class ResourceSampler:
    def __init__(self, pid, interval=SAMPLE_INTERVAL):
        self.pid, self.interval = pid, interval
        self.samples = []
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="qwen35-readiness-sampler", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            sampling_started = time.monotonic()
            try:
                sample = sample_resources(self.pid)
            except Exception:  # noqa: BLE001 - resource failures must not leak process information
                sample = {"native_rss_mib": None, "device_memory_mib": {},
                          "errors": ["resource_sample_failed"]}
            sample["elapsed_seconds"] = round(time.monotonic() - self._started, 3)
            self.samples.append(sample)
            if self._stop.wait(max(0, self.interval - (time.monotonic() - sampling_started))):
                break

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise GenerationError("readiness_sampler_cleanup_failed")

    def summary(self):
        rss = [sample["native_rss_mib"] for sample in self.samples
               if sample["native_rss_mib"] is not None]
        devices = {}
        for sample in self.samples:
            for device, value in sample["device_memory_mib"].items():
                devices[device] = max(devices.get(device, 0), value)
        return {"scope": "post_load_periodic_samples_during_neutral_calls",
            "interval_seconds": self.interval, "sample_count": len(self.samples),
            "native_rss_sample_count": len(rss), "native_rss_sampled_max_mib": max(rss) if rss else None,
            "whole_device_memory_sampled_max_mib": devices,
            "whole_device_memory_sample_count": sum(bool(s["device_memory_mib"]) for s in self.samples),
            "startup_measured": False, "exact_peak_measured": False,
            "device_memory_is_model_specific": False, "samples": self.samples}


def native_observation(response):
    """Preserve raw neutral output and bounded native facts, excluding paths/prompts."""
    keys = {"content", "model", "tokens", "stop", "stop_type", "stopping_word", "truncated",
            "tokens_predicted", "tokens_evaluated", "tokens_cached", "timings"}
    result = {key: value for key, value in response.items() if key in keys}
    settings = response.get("generation_settings", {})
    result["generation_settings"] = {key: settings[key] for key in
        (*GREEDY, "n_predict", "grammar") if key in settings}
    return result


def run(plan_path, output):
    output, plan_path = Path(output), Path(plan_path)
    if output.exists():
        raise ValueError("candidate_output_exists")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    plan_hash = hashlib.sha256(plan_bytes).hexdigest()
    verify_plan(plan)  # verifies shared fixture bindings; never query the returned cases
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "qwen35_neutral_native_readiness",
        "started_at": datetime.now(UTC).isoformat(), "plan_sha256": plan_hash,
        "bound_files": plan["bound_files"], "status": "running", "attempt_limit": 2,
        "attempts": [], "paid_service_calls": 0, "quality_cases_queried": 0,
        "analysis_calls": 0, "human_review_count": 0, "model_runtime": None,
        "measurement_scope": "Python adapter and native HTTP only",
        "worker_http_measured": False, "java_service_measured": False,
        "semantic_quality_verified": False, "resources": None}

    def save():
        write(output / "report.json", report)

    save()
    try:
        with start_llama(log_dir=output / "native") as service:
            generator = Qwen35Generator(service.url, service.token, service.manifest)
            sampler = None
            try:
                generator.load()
                report["model_runtime"] = generator.public_metadata()
                sampler = ResourceSampler(service.process.pid)
                sampler.start()  # deliberately excludes native model load and adapter identity hashing
                original_request = generator._request
                current = None

                def observed_request(method, path, payload=None, deadline=None):
                    response = original_request(method, path, payload, deadline)
                    if method == "POST" and path == "/completion" and current is not None:
                        current["native_response"] = native_observation(response)
                        save()
                    return response

                generator._request = observed_request
                try:
                    for index, user in enumerate(NEUTRAL_INPUTS):
                        if len(report["attempts"]) >= 2:
                            raise GenerationError("readiness_call_budget")
                        current = {"id": f"neutral_{index + 1}", "status": "running",
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": user}]}
                        report["attempts"].append(current)
                        save()
                        started = time.monotonic()
                        generator.begin_request(started + DEADLINE_SECONDS)
                        try:
                            result = generator.generate_bounded(current["messages"],
                                                                started + DEADLINE_SECONDS)
                            current["output"] = (dataclasses.asdict(result)
                                                 if dataclasses.is_dataclass(result) else vars(result))
                            current["effective_config"] = generator.last_effective_config
                            current["model_runtime_after_call"] = generator.public_metadata()
                            if time.monotonic() - started >= DEADLINE_SECONDS:
                                raise GenerationError("generation_deadline_exceeded")
                            if result.finish_reason != "eos":
                                raise GenerationError("readiness_output_truncated")
                            if strict_json(result.text) != EXPECTED_JSON:
                                raise GenerationError("readiness_unexpected_output")
                            if (not current["model_runtime_after_call"]["nonthinking"]["last_template_verified"]
                                    or generator.last_effective_config.get(
                                        "observed_nonthinking_preamble_sha256") != PREAMBLE_SHA256):
                                raise GenerationError("generation_nonthinking_template_mismatch")
                            current["status"] = "passed"
                        except Exception as error:
                            current["status"], current["error"] = "failed", safe_error(error)
                            raise
                        finally:
                            current["elapsed_python_seconds"] = round(time.monotonic() - started, 3)
                            current["effective_config"] = generator.last_effective_config
                            current["model_runtime_after_call"] = generator.public_metadata()
                            generator.end_request()
                            save()
                finally:
                    generator._request = original_request
                report["status"] = "passed_neutral_readiness_only"
            finally:
                try:
                    if sampler is not None:
                        sampler.stop()
                        report["resources"] = sampler.summary()
                finally:
                    generator.close()
    except Exception as error:  # noqa: BLE001 - no native exception text/paths/credentials in report
        report["status"], report["error"] = "failed", safe_error(error)
    except KeyboardInterrupt:
        report["status"], report["error"] = "interrupted", "KeyboardInterrupt"
    finally:
        try:
            report["plan_sha256_after"] = sha(plan_path)
            report["bound_files_after"] = {relative: sha(ROOT / relative)
                                           for relative in plan["bound_files"]}
            verify_plan(plan)
            if report["plan_sha256_after"] != plan_hash:
                raise GenerationError("readiness_plan_changed")
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - preserve safe post-run binding failure
            report["status"], report["source_check_error"] = "failed", safe_error(error)
            report["sources_unchanged"] = False
        report["completed_at"] = datetime.now(UTC).isoformat()
        report["attempt_count"] = len(report["attempts"])
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.plan, args.output)
        print(json.dumps({"status": report["status"], "attempt_count": report["attempt_count"]}), flush=True)
        if report["status"] != "passed_neutral_readiness_only":
            parser.exit(1, "qwen35_readiness_failed\n")
    except Exception:  # noqa: BLE001 - never echo local paths or credentials
        parser.exit(1, "qwen35_readiness_failed\n")


if __name__ == "__main__":
    main()
