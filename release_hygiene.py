#!/usr/bin/env python3
"""Fail-closed hygiene checks for the standalone Agent Ledger Tower release.

This complements the component-review validator. It verifies that the checked-in
release manifest matches the allowlist, required runtime artifacts are ignored,
known mythic legacy terms do not return to the public package, and common live
credential formats are absent. It does not replace a professional secret scanner
or an independent security review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
MANIFEST_FORMAT = "agent-ledger-tower-release-v1"
ALLOWLIST_SCHEMA = "agent-ledger-tower-release-files-v1"

LEGACY_TERMS = {
    "legacy term 'sovereign'": re.compile(r"\bsovereign\b", re.IGNORECASE),
    "legacy term 'crystalline'": re.compile(r"\bcrystalline\b", re.IGNORECASE),
    "legacy term 'white hole'": re.compile(r"\bwhite[ -]?hole\b", re.IGNORECASE),
    "legacy term 'sokhotsky'": re.compile(r"\bsokhotsky\b", re.IGNORECASE),
    "legacy term 'shakespeare'": re.compile(r"\bshakespeare\b", re.IGNORECASE),
    "legacy term 'avon'": re.compile(r"\bavon\b", re.IGNORECASE),
    "legacy term 'muji'": re.compile(r"\bmuji\b", re.IGNORECASE),
    "legacy term 'armada'": re.compile(r"\barmada\b", re.IGNORECASE),
    "legacy term 'nemora'": re.compile(r"\bnemora\b", re.IGNORECASE),
    "legacy term 'transcendent'": re.compile(r"\btranscendent\b", re.IGNORECASE),
    "legacy term 'quintessential'": re.compile(r"\bquintessential\b", re.IGNORECASE),
    "legacy term 'bounded infinity'": re.compile(r"\bbounded infinity\b", re.IGNORECASE),
}

SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

# The policy demonstration intentionally tests private-key exfiltration using
# this inert marker. It is not a key and is kept as a narrowly scoped exception.
ALLOWED_FIXTURE_MATCHES = {("policy_gate_demo.py", "private key block", "-----BEGIN PRIVATE KEY-----")}
REQUIRED_GITIGNORE_ENTRIES = {".env", "*.pem", "*.key", "*.jsonl", "evidence_packets/"}
# These files intentionally contain forbidden example strings in order to test
# the checker itself. They are not public operator text or runtime behavior.
TEXT_SCAN_EXEMPTIONS = {"release_hygiene.py", "test_release_hygiene.py"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_allowlist(root: Path) -> list[str]:
    try:
        payload = json.loads((root / "release_files.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("release_files.json is unreadable") from exc
    if payload.get("schema") != ALLOWLIST_SCHEMA or not isinstance(payload.get("files"), list):
        raise ValueError("release_files.json has an unsupported schema")
    files = payload["files"]
    if not all(
        isinstance(item, str)
        and item
        and not Path(item).is_absolute()
        and not Path(item).drive
        and Path(item) != Path(".")
        and "." not in Path(item).parts
        and ".." not in Path(item).parts
        for item in files
    ):
        raise ValueError("release allowlist contains an invalid path")
    if len(files) != len(set(files)):
        raise ValueError("release allowlist contains duplicate paths")
    return files


def check_manifest(root: Path, files: Iterable[str]) -> list[str]:
    errors: list[str] = []
    try:
        # Windows PowerShell 5's `-Encoding utf8` emits a BOM. Accept that
        # harmless marker so the checker is portable across Windows and CI.
        manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest unreadable: {type(exc).__name__}"]
    if manifest.get("format") != MANIFEST_FORMAT:
        errors.append("manifest format is unsupported")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return errors + ["manifest files entry is missing"]
    expected = set(files)
    actual: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("manifest has an invalid file entry")
            continue
        path = entry["path"]
        if path in actual:
            errors.append(f"manifest duplicates {path}")
        actual[path] = entry
    for path in sorted(expected - set(actual)):
        errors.append(f"manifest missing {path}")
    for path in sorted(set(actual) - expected):
        errors.append(f"manifest includes unallowlisted {path}")
    for relative in sorted(expected & set(actual)):
        file_path = root / relative
        if not file_path.is_file():
            errors.append(f"allowlisted file missing: {relative}")
            continue
        entry = actual[relative]
        actual_hash = sha256_file(file_path)
        if entry.get("sha256") != actual_hash:
            errors.append(f"manifest hash mismatch: {relative}")
        if entry.get("bytes") != file_path.stat().st_size:
            errors.append(f"manifest byte count mismatch: {relative}")
    return errors


def check_gitignore(root: Path) -> list[str]:
    try:
        lines = {
            line.strip()
            for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except OSError as exc:
        return [f".gitignore unreadable: {type(exc).__name__}"]
    return [f".gitignore missing {entry}" for entry in sorted(REQUIRED_GITIGNORE_ENTRIES - lines)]


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check_public_text(root: Path, files: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if relative in TEXT_SCAN_EXEMPTIONS:
            continue
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            errors.append(f"cannot read {relative}: {type(exc).__name__}")
            continue
        for label, pattern in LEGACY_TERMS.items():
            for match in pattern.finditer(text):
                errors.append(f"{relative}:{_line_number(text, match.start())}: {label}")
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                fixture = (relative, label, match.group(0))
                if fixture in ALLOWED_FIXTURE_MATCHES:
                    continue
                errors.append(f"{relative}:{_line_number(text, match.start())}: possible {label}")
    return errors


def check_release(root: str | Path = HERE, *, require_manifest: bool = True) -> list[str]:
    root = Path(root).resolve()
    try:
        files = load_allowlist(root)
    except ValueError as exc:
        return [str(exc)]
    manifest_path = root / "RELEASE_MANIFEST.json"
    manifest_errors = check_manifest(root, files) if require_manifest or manifest_path.exists() else []
    return manifest_errors + check_gitignore(root) + check_public_text(root, files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify standalone release hygiene")
    parser.add_argument("--root", default=str(HERE), help="Release root to verify")
    parser.add_argument(
        "--allow-missing-manifest",
        action="store_true",
        help="For a development tree only: run all checks except a missing release manifest.",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors = check_release(root, require_manifest=not args.allow_missing_manifest)
    if errors:
        print("RELEASE HYGIENE: FAIL")
        for error in errors:
            print("  -", error)
        return 1
    checked = "runtime ignore, language, and credential checks"
    if (root / "RELEASE_MANIFEST.json").exists():
        checked = "manifest, " + checked
    print(f"RELEASE HYGIENE: PASS — {checked} passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
