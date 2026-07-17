#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from component_review import SCHEMA, load_registry, load_release_files, validate_registry


def component(files: list[str]) -> dict:
    return {
        "id": "example",
        "status": "workable",
        "files": files,
        "problem": "Keep the fixture reviewed.",
        "inputs": "A fixture file.",
        "outputs": "A validation result.",
        "failure_modes": "An unregistered file fails validation.",
        "reuses": "The review validator.",
        "tests": ["test_component_review.py"],
        "not_claimed": "This fixture does not prove production quality.",
    }


class ComponentReviewTests(unittest.TestCase):
    def test_checked_in_registry_covers_the_package(self) -> None:
        root = Path(__file__).resolve().parent
        result = validate_registry(
            load_registry(root / "component_review_registry.json"),
            load_release_files(root / "release_files.json", root),
        )
        self.assertTrue(result.ok, "\n".join(result.errors))
        self.assertEqual(result.reviewed_files, result.discovered_files)

    def test_unreviewed_new_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approved.py").write_text("x = 1\n", encoding="utf-8")
            registry = {"schema": SCHEMA, "components": [component(["approved.py"])]}
            self.assertTrue(validate_registry(registry, {"approved.py"}).ok)
            (root / "unreviewed.py").write_text("x = 2\n", encoding="utf-8")
            result = validate_registry(registry, {"approved.py", "unreviewed.py"})
            self.assertFalse(result.ok)
            self.assertIn("unreviewed.py: missing component review", result.errors)

    def test_duplicate_file_coverage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approved.py").write_text("x = 1\n", encoding="utf-8")
            registry = {"schema": SCHEMA, "components": [component(["approved.py"]), component(["approved.py"])]}
            result = validate_registry(registry, {"approved.py"})
            self.assertFalse(result.ok)
            self.assertTrue(any("covered by both" in error for error in result.errors))

    def test_missing_review_question_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approved.py").write_text("x = 1\n", encoding="utf-8")
            entry = component(["approved.py"])
            del entry["not_claimed"]
            result = validate_registry({"schema": SCHEMA, "components": [entry]}, {"approved.py"})
            self.assertFalse(result.ok)
            self.assertTrue(any("not_claimed" in error for error in result.errors))

    def test_readme_has_a_nontechnical_first_use_path(self) -> None:
        root = Path(__file__).resolve().parent
        readme = (root / "README.md").read_text(encoding="utf-8")
        for required in (
            "## First five minutes — use the local tower",
            "start_tower.ps1",
            "/search exact rational",
            "/math 0.1 + 0.2 - 0.3",
            "View saved evidence",
        ):
            self.assertIn(required, readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
