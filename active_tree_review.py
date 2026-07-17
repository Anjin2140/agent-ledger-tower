#!/usr/bin/env python3
"""Fail closed when the active tower tree contains an unreviewed file.

The release registry answers: "was every published file reviewed?"
This check answers the earlier question in the workflow: "did a new file enter
the development tree without a review record?"

The reviewed release allowlist is the canonical source set. Runtime output and
explicitly documented administrative files are excluded by a separate config;
anything else is an admission failure, not an automatic archive decision.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "agent-ledger-tower-active-exclusions-v1"
ALLOWLIST_SCHEMA = "agent-ledger-tower-release-files-v1"


def normalize(value: object) -> str | None:
    """Return a safe portable relative path, or None for invalid input."""
    if not isinstance(value, str) or not value.strip():
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        return None
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def load_allowlist(path: Path) -> set[str]:
    value = load_json(path)
    if value.get("schema") != ALLOWLIST_SCHEMA:
        raise ValueError(f"allowlist must use schema {ALLOWLIST_SCHEMA!r}")
    raw_files = value.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("allowlist files must be a non-empty list")
    files: set[str] = set()
    for raw in raw_files:
        relative = normalize(raw)
        if relative is None:
            raise ValueError(f"invalid allowlist path: {raw!r}")
        if relative in files:
            raise ValueError(f"duplicate allowlist path: {relative}")
        files.add(relative)
    return files


def load_exclusions(path: Path) -> tuple[set[str], set[str], tuple[str, ...]]:
    value = load_json(path)
    if value.get("schema") != SCHEMA:
        raise ValueError(f"exclusions must use schema {SCHEMA!r}")
    entries = value.get("exclusions")
    if not isinstance(entries, list):
        raise ValueError("exclusions must be a list")

    files: set[str] = set()
    directories: set[str] = set()
    suffixes: list[str] = []
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"exclusion {number} must be an object")
        kind = entry.get("kind")
        relative = normalize(entry.get("path"))
        reason = entry.get("reason")
        if kind not in {"file", "directory", "suffix"}:
            raise ValueError(f"exclusion {number} has invalid kind")
        if not relative or not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"exclusion {number} needs a safe path and reason")
        if kind == "file":
            files.add(relative)
        elif kind == "directory":
            directories.add(relative.rstrip("/"))
        else:
            suffixes.append(relative)
    return files, directories, tuple(suffixes)


def is_excluded(
    relative: str,
    files: set[str],
    directories: set[str],
    suffixes: tuple[str, ...],
) -> bool:
    if relative in files:
        return True
    parts = relative.split("/")
    if any("/".join(parts[:index]) in directories for index in range(1, len(parts) + 1)):
        return True
    return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(parts[-1], pattern) for pattern in suffixes)


def inspect_tree(
    root: Path,
    allowlist_path: Path | None = None,
    exclusions_path: Path | None = None,
) -> tuple[list[str], int, int]:
    """Return (errors, canonical_count, excluded_count) for one tree."""
    root = root.resolve()
    allowlist = load_allowlist(allowlist_path or root / "release_files.json")
    excluded_files, excluded_dirs, excluded_suffixes = load_exclusions(
        exclusions_path or root / "active_tree_exclusions.json"
    )
    errors: list[str] = []
    for relative in sorted(allowlist):
        path = root / Path(relative)
        if not path.is_file():
            errors.append(f"canonical file is missing: {relative}")

    discovered = set()
    excluded_count = 0
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        current_relative = current_path.relative_to(root).as_posix() if current_path != root else ""
        kept_dirs: list[str] = []
        for directory in dirs:
            relative = "/".join(part for part in (current_relative, directory) if part)
            if relative == ".git" or relative.startswith(".git/"):
                excluded_count += 1
                continue
            if relative in excluded_dirs or any(relative.startswith(item + "/") for item in excluded_dirs):
                excluded_count += 1
                continue
            kept_dirs.append(directory)
        dirs[:] = kept_dirs

        for name in names:
            relative = "/".join(part for part in (current_relative, name) if part)
            full = current_path / name
            if full.is_symlink():
                errors.append(f"symlink is not admitted: {relative}")
                continue
            if relative in allowlist:
                discovered.add(relative)
            elif is_excluded(relative, excluded_files, excluded_dirs, excluded_suffixes):
                excluded_count += 1
            else:
                errors.append(f"unreviewed active file: {relative}")

    missing_from_walk = sorted(allowlist - discovered)
    for relative in missing_from_walk:
        if (root / Path(relative)).is_file():
            errors.append(f"canonical file was not discoverable: {relative}")
    return errors, len(discovered), excluded_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate active-tree admission coverage")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--exclusions", type=Path)
    args = parser.parse_args(argv)
    try:
        errors, canonical_count, excluded_count = inspect_tree(
            args.root,
            args.allowlist,
            args.exclusions,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [f"unable to inspect active tree: {type(exc).__name__}: {exc}"]
        canonical_count = excluded_count = 0

    if errors:
        print("ACTIVE TREE REVIEW: FAIL")
        for error in errors:
            print("  - " + error)
        return 1
    print(
        "ACTIVE TREE REVIEW: PASS — "
        f"{canonical_count} canonical files checked; {excluded_count} documented runtime/admin entries excluded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
