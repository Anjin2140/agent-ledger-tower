from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import active_tree_review


class ActiveTreeReviewTests(unittest.TestCase):
    def _fixture(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "release_files.json").write_text(
            json.dumps(
                {
                    "schema": active_tree_review.ALLOWLIST_SCHEMA,
                    "files": ["reviewed.py", "release_files.json", "active_tree_exclusions.json"],
                }
            ),
            encoding="utf-8",
        )
        (root / "active_tree_exclusions.json").write_text(
            json.dumps(
                {
                    "schema": active_tree_review.SCHEMA,
                    "exclusions": [
                        {"kind": "directory", "path": "generated", "reason": "fixture output"},
                        {"kind": "suffix", "path": "*.jsonl", "reason": "fixture trace"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "reviewed.py").write_text("# reviewed\n", encoding="utf-8")
        (root / "release_files.json").write_text(
            json.dumps(
                {
                    "schema": active_tree_review.ALLOWLIST_SCHEMA,
                    "files": ["reviewed.py", "release_files.json", "active_tree_exclusions.json"],
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_current_tree_passes(self) -> None:
        errors, canonical, excluded = active_tree_review.inspect_tree(Path(__file__).parent)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(canonical, 1)
        self.assertGreaterEqual(excluded, 1)

    def test_unreviewed_file_fails_closed(self) -> None:
        root = self._fixture()
        (root / "new_feature.py").write_text("print('unreviewed')\n", encoding="utf-8")
        errors, _, _ = active_tree_review.inspect_tree(root)
        self.assertIn("unreviewed active file: new_feature.py", errors)

    def test_documented_runtime_output_is_excluded(self) -> None:
        root = self._fixture()
        (root / "trace.jsonl").write_text("{}\n", encoding="utf-8")
        (root / "generated").mkdir()
        (root / "generated" / "artifact.bin").write_bytes(b"generated")
        errors, _, _ = active_tree_review.inspect_tree(root)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
