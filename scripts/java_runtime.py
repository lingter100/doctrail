"""Resolve the real JVM with an ASCII protocol, requiring the project's JDK 21+."""
from __future__ import annotations

import base64
import binascii
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PREFIX = b"DOCTRAIL_JAVA_HOME_V1="
PROBE = """class DocTrailJavaHome {
    public static void main(String[] args) {
        byte[] home = System.getProperty("java.home").getBytes(java.nio.charset.StandardCharsets.UTF_8);
        System.out.println("DOCTRAIL_JAVA_HOME_V1=" + java.util.Base64.getEncoder().encodeToString(home));
    }
}
"""


class JavaRuntimeError(RuntimeError):
    """Fixed diagnostics only; localized JVM stderr and paths are never copied."""

    CODES = frozenset({"java_discovery_unavailable", "java_discovery_timeout",
                       "java_discovery_failed", "java_discovery_invalid_response",
                       "java_runtime_executable_missing"})

    def __init__(self, code):
        super().__init__(code if code in self.CODES else "java_discovery_failed")


def java_executable() -> Path:
    """No locale guessing or replacement decoding. Source mode compiles only this probe."""
    try:
        command = shutil.which("java")
        if command is None:
            raise JavaRuntimeError("java_discovery_unavailable")
        # Resolve PATH symlinks (including Windows javapath) before starting the probe.
        command = str(Path(command).resolve(strict=True))
        with tempfile.TemporaryDirectory(prefix="doctrail-java-home-") as directory:
            source = Path(directory) / "DocTrailJavaHome.java"
            source.write_text(PROBE, encoding="ascii", newline="\n")
            result = subprocess.run([command, "--source", "21", str(source)],
                stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise JavaRuntimeError("java_discovery_failed")
        line = result.stdout.removesuffix(b"\n").removesuffix(b"\r")
        if len(line) > 65536 or not line.startswith(PREFIX):
            raise JavaRuntimeError("java_discovery_invalid_response")
        try:
            home = base64.b64decode(line[len(PREFIX):], validate=True).decode("utf-8", "strict")
            if not home or "\x00" in home or not Path(home).is_absolute():
                raise ValueError
        except (ValueError, UnicodeError, binascii.Error):
            raise JavaRuntimeError("java_discovery_invalid_response") from None
        executable = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if not executable.is_file():
            raise JavaRuntimeError("java_runtime_executable_missing")
        return executable.resolve(strict=True)
    except subprocess.TimeoutExpired:
        raise JavaRuntimeError("java_discovery_timeout") from None
    except OSError:
        raise JavaRuntimeError("java_discovery_unavailable") from None
