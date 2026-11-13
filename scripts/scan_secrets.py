#!/usr/bin/env python3
"""Fail the build if a credential-looking string is committed to the repository.

Only high-confidence patterns are checked, and placeholders used in
`.env.example`, tests and documentation are ignored.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PostgreSQL URI with embedded password", re.compile(r"postgres(?:ql)?://[^\s:/@]+:[^\s@]+@", re.I)),
    ("MongoDB URI with embedded password", re.compile(r"mongodb(?:\+srv)?://[^\s:/@]+:[^\s@]+@", re.I)),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]

IGNORED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".mp4", ".ico", ".woff", ".woff2"}
IGNORED_PATHS = {"frontend/vendor", "backend/tests", "docs", ".github"}
PLACEHOLDER = re.compile(
    r"(replace[-_ ]?me|change[-_ ]?me|your[-_ ]|example|placeholder|dummy|fake|demo|xxxx|<[^>]+>|\$\{|\bTODO\b)",
    re.I,
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if any(str(relative).startswith(prefix) for prefix in IGNORED_PATHS):
            continue
        if relative.name == ".env.example":
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in PATTERNS:
            for match in pattern.finditer(content):
                snippet = match.group(0)
                if PLACEHOLDER.search(snippet):
                    continue
                line = content[: match.start()].count("\n") + 1
                findings.append(f"{relative}:{line}: {name}")
    if findings:
        print("Secret scan failed — remove or rotate the following:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1
    print("Secret scan passed: no credential patterns found in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
