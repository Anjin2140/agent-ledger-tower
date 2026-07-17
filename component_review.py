#!/usr/bin/env python3
"""Fail closed when a release file has not received a concrete review.

The registry is intentionally small and deterministic. It does not judge whether
code is good; it makes the review contract explicit and refuses to call a package
complete when a source file has no stated purpose, test path, or boundary.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "agent-ledger-tower-component-review-v1"
ALLOWLIST_SCHEMA = "agent-ledger-tower-release-files-v1"
VALID_STATUSES = {"workable", "refine", "prototype", "rework", "discard"}
REQUIRED_TEXT_FIELDS = (
    "id",
    "status",
    "problem",
    "inputs",
    "outputs",
    "failure_modes",
    "reuses",
    "not_claimed",
)


@dataclass(frozen=True)
class ReviewResult:
    ok: bool
    reviewed_files: int
    discovered_files: int
    component_count: int
    status_counts: dict[str, int]
    errors: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ok": self.ok,
            "reviewed_files": self.reviewed_files,
            "discovered_files": self.discovered_files,
            "component_count": self.component_count,
            "status_counts": self.status_counts,
            "errors": list(self.errors),
        }


def load_registry(path: Path) -> dict[str, Any]:
    """Load the human-authored review registry without executing any project code."""
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("component review registry must be a JSON object")
    return value


def normalize_relative_path(value: object) -> str | None:
    """Accept portable relative paths only."""
    if not isinstance(value, str) or not value.strip():
        return None
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or str(pure) in {"", "."}:
        return None
    return pure.as_posix()


def load_release_files(path: Path, root: Path) -> set[str]:
    """Load the clean-export allowlist and reject paths outside the package."""
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema") != ALLOWLIST_SCHEMA:
        raise ValueError(f"release allowlist must use schema {ALLOWLIST_SCHEMA!r}")
    raw_files = value.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("release allowlist files must be a non-empty list")

    result: set[str] = set()
    for raw_path in raw_files:
        relative = normalize_relative_path(raw_path)
        if relative is None:
            raise ValueError(f"release allowlist has invalid relative path: {raw_path!r}")
        if relative in result:
            raise ValueError(f"release allowlist has duplicate path: {relative}")
        if not (root / relative).is_file():
            raise ValueError(f"release allowlist file is missing: {relative}")
        result.add(relative)
    return result


def validate_registry(registry: dict[str, Any], expected: set[str]) -> ReviewResult:
    """Check that every reviewable package file is covered exactly once."""
    errors: list[str] = []
    if registry.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")

    components = registry.get("components")
    if not isinstance(components, list) or not components:
        errors.append("components must be a non-empty list")
        components = []

    covered: dict[str, str] = {}
    status_counts: Counter[str] = Counter()

    for number, component in enumerate(components, start=1):
        label = f"component {number}"
        if not isinstance(component, dict):
            errors.append(f"{label} must be an object")
            continue

        component_id = component.get("id")
        if not isinstance(component_id, str) or not component_id.strip():
            errors.append(f"{label} is missing a non-empty id")
            component_id = f"<unnamed-{number}>"

        for field in REQUIRED_TEXT_FIELDS:
            value = component.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{component_id}: {field} must be non-empty text")

        status = component.get("status")
        if isinstance(status, str):
            status_counts[status] += 1
            if status not in VALID_STATUSES:
                errors.append(f"{component_id}: unknown status {status!r}")

        tests = component.get("tests")
        if not isinstance(tests, list) or not tests or not all(isinstance(test, str) and test.strip() for test in tests):
            errors.append(f"{component_id}: tests must be a non-empty list of names")

        files = component.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{component_id}: files must be a non-empty list")
            continue

        for raw_path in files:
            path = normalize_relative_path(raw_path)
            if path is None:
                errors.append(f"{component_id}: invalid relative path {raw_path!r}")
                continue
            if path not in expected:
                errors.append(f"{component_id}: registry path is not in the release allowlist: {path}")
                continue
            previous = covered.get(path)
            if previous is not None:
                errors.append(f"{path}: covered by both {previous} and {component_id}")
                continue
            covered[path] = component_id

    missing = sorted(expected - set(covered))
    for path in missing:
        errors.append(f"{path}: missing component review")

    return ReviewResult(
        ok=not errors,
        reviewed_files=len(covered),
        discovered_files=len(expected),
        component_count=len(components),
        status_counts=dict(sorted(status_counts.items())),
        errors=tuple(errors),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Agent Ledger Tower new-file review registry")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="package root to inspect")
    parser.add_argument("--registry", type=Path, help="registry JSON; defaults to component_review_registry.json in root")
    parser.add_argument("--allowlist", type=Path, help="release allowlist; defaults to release_files.json in root")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    registry_path = (args.registry or root / "component_review_registry.json").resolve()
    allowlist_path = (args.allowlist or root / "release_files.json").resolve()
    try:
        result = validate_registry(load_registry(registry_path), load_release_files(allowlist_path, root))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = ReviewResult(
            ok=False,
            reviewed_files=0,
            discovered_files=0,
            component_count=0,
            status_counts={},
            errors=(f"unable to validate registry: {type(exc).__name__}: {exc}",),
        )

    if args.json:
        print(json.dumps(result.as_json(), indent=2, sort_keys=True))
    elif result.ok:
        statuses = ", ".join(f"{status}={count}" for status, count in result.status_counts.items())
        print(
            "FILE REVIEW: PASS — "
            f"{result.reviewed_files}/{result.discovered_files} files covered by "
            f"{result.component_count} reviewed components ({statuses})"
        )
    else:
        print("FILE REVIEW: FAIL")
        for error in result.errors:
            print("  - " + error)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
