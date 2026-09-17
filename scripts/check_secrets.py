#!/usr/bin/env python3
"""Pre-commit secret scanner for SNIST Helpdesk repository.

Scans changed or staged files to prevent committing hardcoded credentials,
API keys, tokens, or known compromised credentials.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Known compromised secrets that must NEVER be committed
KNOWN_LEAKED_STRINGS = [
    "c69fc621-e477-43c5-84ea-d9d94108d7cc",
    "sreenidhiclgbepfs44jy504",
    "wm84r8yhj9mzp9m1yrm78fqhpmzb8on0",
    "b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685",
]

# Patterns detecting generic secrets
SECRET_PATTERNS = [
    (re.compile(r"""(?:password|passwd|pwd|secret|api_key|token)\s*[:=]\s*['"][^'"]{8,}['"]""", re.IGNORECASE), "Generic credential assignment"),
    (re.compile(r"""-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"""), "Private Key PEM block"),
]

# File types and paths to ignore
IGNORED_PATHS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".venv",
    "scratch",
    "HWiNFOPortable",
    "docs/credential_rotation.md",  # Documentation of credentials to rotate
    "scripts/check_secrets.py",     # Scanner definition itself
    ".env",                         # Real local environment file (gitignored)
}

IGNORED_EXTENSIONS = {
    ".pyc",
    ".sql",  # Historical backups/dumps (already gitignored)
    ".pdf",
    ".png",
    ".jpeg",
    ".jpg",
    ".zip",
    ".gz",
    ".exe",
    ".paf.exe",
    ".json",
}


def scan_file(filepath: Path) -> list[str]:
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    # Check for known leaked strings
    for s in KNOWN_LEAKED_STRINGS:
        if s in content:
            findings.append(f"Matched known leaked credential: '{s[:12]}...'")

    # Check for regex secret patterns
    lines = content.splitlines()
    for line_idx, line in enumerate(lines, 1):
        if line.strip().startswith("#") or line.strip().startswith("//"):
            continue
        for pat, desc in SECRET_PATTERNS:
            if pat.search(line):
                # Ignore obvious dummy placeholders
                if any(dummy in line.lower() for dummy in ("example", "your_", "placeholder", "dummy", "test", "secretpassword")):
                    continue
                findings.append(f"Line {line_idx}: {desc}")

    return findings


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    violations = 0

    print("Running SNIST Helpdesk Secret Scanner...")
    for root, dirs, files in os.walk(repo_root):
        # Exclude ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_PATHS]

        for file in files:
            path = Path(root) / file
            rel_path = path.relative_to(repo_root).as_posix()

            if any(rel_path.startswith(p) for p in IGNORED_PATHS):
                continue
            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            findings = scan_file(path)
            if findings:
                print(f"\n[SECURITY VIOLATION] File: {rel_path}")
                for f in findings:
                    print(f"  - {f}")
                violations += len(findings)

    if violations > 0:
        print(f"\nScan FAILED: {violations} potential secret(s) found.")
        print("Please review and remove sensitive credentials before committing.")
        return 1

    print("Scan PASSED: Zero unredacted secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
