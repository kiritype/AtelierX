"""Audit Git-visible files and filename history for obvious private artifacts.

This is a conservative release hygiene check, not a complete secret scanner.
It intentionally never prints file contents or credential matches.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_SCAN = 2 * 1024 * 1024
LARGE_FILE_BYTES = 100 * 1024 * 1024

PRIVATE_DIRS = {"config", "state", "data", "output", "vendor", "notes"}
PRIVATE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "credentials"}
MODEL_SUFFIXES = {".safetensors", ".ckpt", ".gguf", ".pt", ".pth", ".onnx", ".model"}
PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pem", ".p12", ".pfx", ".key"}

# Only unambiguous credential formats are detected; values are discarded immediately.
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
)


def git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
    )
    return result.stdout


def visible_paths() -> set[str]:
    raw = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return {entry.decode("utf-8", "surrogateescape").replace("\\", "/") for entry in raw.split(b"\0") if entry}


def historical_paths() -> set[str]:
    raw = git("log", "--all", "--format=", "--name-only", "-z")
    return {entry.decode("utf-8", "surrogateescape").replace("\\", "/") for entry in raw.split(b"\0") if entry}


def path_findings(path: str, *, historical: bool = False) -> list[dict[str, str]]:
    normalized = path.strip("/")
    parts = [part.lower() for part in normalized.split("/")]
    filename = parts[-1] if parts else ""
    # Sample work trees contain intentionally public fictional fixtures in this repository.
    # Keep this exception scoped to the samples subtree; never exempt generic data/config paths.
    sample_fixture = len(parts) > 1 and parts[0] == "samples" and filename.endswith((".md", ".json", ".jsx", ".csv"))
    findings: list[dict[str, str]] = []
    if not sample_fixture:
        if PRIVATE_DIRS.intersection(parts):
            findings.append({"path": path, "reason": "private-state directory name"})
        if filename in PRIVATE_NAMES or filename.startswith(".env."):
            findings.append({"path": path, "reason": "environment or credential filename"})
        if Path(filename).suffix.lower() in PRIVATE_SUFFIXES:
            findings.append({"path": path, "reason": "credential or local-database file type"})
        if Path(filename).suffix.lower() in MODEL_SUFFIXES:
            findings.append({"path": path, "reason": "model or checkpoint artifact"})
    if historical:
        for finding in findings:
            finding["reason"] = "historical filename: " + finding["reason"]
    return findings


def scan_secrets(paths: set[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in sorted(paths):
        path = ROOT / Path(relative)
        try:
            if not path.is_file() or path.stat().st_size > MAX_TEXT_SCAN:
                continue
            data = path.read_bytes()
        except (OSError, ValueError):
            continue
        if b"\0" in data:
            continue
        if contains_high_confidence_credential(data):
            findings.append({"path": relative, "reason": "high-confidence credential format"})
    return findings


def contains_high_confidence_credential(data: bytes) -> bool:
    return any(pattern.search(data) for pattern in SECRET_PATTERNS)


def run_audit() -> dict[str, object]:
    visible = visible_paths()
    history = historical_paths()
    path_findings_all = [finding for path in sorted(visible) for finding in path_findings(path)]
    path_findings_all.extend(
        finding for path in sorted(history - visible) for finding in path_findings(path, historical=True)
    )
    for relative in sorted(visible):
        path = ROOT / Path(relative)
        try:
            if path.is_file() and path.stat().st_size >= LARGE_FILE_BYTES:
                path_findings_all.append({"path": relative, "reason": "file is at least 100 MiB"})
        except OSError:
            continue
    credentials = scan_secrets(visible)
    findings = path_findings_all + credentials
    return {
        "schema_version": 1,
        "scope": "Git tracked + untracked non-ignored files; all reachable Git history filenames",
        "limits": [
            "Ignored files are excluded and their contents are never read.",
            "Credential scan recognizes only selected high-confidence formats in text-like files up to 2 MiB.",
            "This does not certify the absence of secrets or private material.",
            "The public samples subtree is treated as intentional fixture content for common text fixture extensions.",
        ],
        "counts": {
            "visible_paths": len(visible),
            "history_paths": len(history),
            "credential_paths": len(credentials),
            "path_findings": len(path_findings_all),
        },
        "findings": findings,
        "result": "fail" if findings else "pass_with_limits",
    }


def main() -> int:
    try:
        report = run_audit()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"public audit could not run ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
