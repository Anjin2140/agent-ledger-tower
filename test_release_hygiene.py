#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release_hygiene import check_manifest, check_public_text, check_release, load_allowlist


class ReleaseHygieneTests(unittest.TestCase):
    def test_checked_in_release_is_hygienic(self) -> None:
        root = Path(__file__).resolve().parent
        self.assertEqual(check_release(root, require_manifest=(root / "RELEASE_MANIFEST.json").exists()), [])

    def test_manifest_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.txt").write_text("safe text\n", encoding="utf-8")
            (root / "release_files.json").write_text(
                json.dumps({"schema": "agent-ledger-tower-release-files-v1", "files": ["sample.txt"]}),
                encoding="utf-8",
            )
            (root / "RELEASE_MANIFEST.json").write_text(
                json.dumps({"format": "agent-ledger-tower-release-v1", "files": [{"path": "sample.txt", "sha256": "0" * 64, "bytes": 10}]}),
                encoding="utf-8",
            )
            errors = check_manifest(root, ["sample.txt"])
            self.assertTrue(any("hash mismatch" in error for error in errors))

    def test_public_text_detects_legacy_and_live_key_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.md").write_text(
                "A sovereign title and AIza12345678901234567890 should not ship.\n",
                encoding="utf-8",
            )
            errors = check_public_text(root, ["sample.md"])
            self.assertTrue(any("legacy term 'sovereign'" in error for error in errors))
            self.assertTrue(any("Google API key" in error for error in errors))

    def test_explicit_private_key_fixture_is_allowed_only_in_the_demo_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "policy_gate_demo.py").write_text('blob = "-----BEGIN PRIVATE KEY-----"\n', encoding="utf-8")
            self.assertEqual(check_public_text(root, ["policy_gate_demo.py"]), [])
            (root / "other.py").write_text('blob = "-----BEGIN PRIVATE KEY-----"\n', encoding="utf-8")
            errors = check_public_text(root, ["other.py"])
            self.assertTrue(any("private key block" in error for error in errors))

    def test_allowlist_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release_files.json").write_text(
                json.dumps(
                    {
                        "schema": "agent-ledger-tower-release-files-v1",
                        "files": ["../outside.py"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid path"):
                load_allowlist(root)

    def test_allowlist_rejects_root_directory_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release_files.json").write_text(
                json.dumps(
                    {
                        "schema": "agent-ledger-tower-release-files-v1",
                        "files": ["."],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid path"):
                load_allowlist(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
