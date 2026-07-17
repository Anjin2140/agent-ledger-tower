#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory_index import MemoryIndex, NO_MATCH_CONTEXT


class MemoryIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="memory-index-")
        self.root = Path(self.temp.name) / "sources"
        self.root.mkdir()
        (self.root / "ledger.md").write_text(
            "A policy gate denies unsafe action before execution.\n"
            "Every allowed action is recorded in a ledger.\n",
            encoding="utf-8",
        )
        (self.root / "math.py").write_text(
            "Exact rational arithmetic avoids rounding error in finite calculations.\n",
            encoding="utf-8",
        )
        (self.root / "api_key.txt").write_text("do-not-index", encoding="utf-8")
        self.index = MemoryIndex(Path(self.temp.name) / "memory.sqlite3")

    def tearDown(self):
        self.index.close()
        self.temp.cleanup()

    def test_index_search_and_citation(self):
        stats = self.index.index_root(self.root)
        self.assertEqual(stats.indexed, 2)
        self.assertEqual(stats.skipped_secret, 1)
        hits = self.index.search("unsafe action ledger")
        self.assertEqual(len(hits), 1)
        self.assertIn("policy gate", hits[0].text.lower())
        self.assertIn("ledger.md:1-2", hits[0].citation())

    def test_updates_and_removes_stale_sources(self):
        self.index.index_root(self.root)
        self.assertEqual(self.index.index_root(self.root).unchanged, 2)
        (self.root / "math.py").unlink()
        stats = self.index.index_root(self.root)
        self.assertEqual(stats.removed, 1)
        self.assertEqual(self.index.search("rational arithmetic"), [])

    def test_query_is_not_fts_syntax(self):
        self.index.index_root(self.root)
        self.assertEqual(self.index.search('" OR * ;'), [])

    def test_tied_hits_and_context_packet_are_deterministic(self):
        (self.root / "zulu.md").write_text("stable_context_token\n", encoding="utf-8")
        (self.root / "alpha.md").write_text("stable_context_token\n", encoding="utf-8")
        self.index.index_root(self.root)
        first = self.index.search("stable_context_token", limit=10)
        second = self.index.search("stable_context_token", limit=10)
        self.assertEqual([hit.citation() for hit in first], [hit.citation() for hit in second])
        self.assertEqual([Path(hit.path).name for hit in first], ["alpha.md", "zulu.md"])

        first_block = f"[{first[0].citation()}]\n{first[0].text}\n"
        packet = self.index.context_packet_for_hits(first, max_chars=len(first_block))
        self.assertEqual(packet.hits, (first[0],))
        self.assertIn(first[0].citation(), packet.text)
        self.assertEqual(len(packet.sha256), 64)

    def test_empty_packet_has_a_stable_no_match_context(self):
        packet = self.index.context_packet_for_hits([])
        self.assertEqual(packet.hits, ())
        self.assertEqual(packet.text, NO_MATCH_CONTEXT)
        self.assertEqual(len(packet.sha256), 64)

    def test_generated_directories_are_not_retrieved(self):
        generated = self.root / "generated"
        generated.mkdir()
        (generated / "stale.py").write_text(
            "generated_artifact_should_not_be_retrieved\n", encoding="utf-8"
        )
        stats = self.index.index_root(self.root)
        self.assertEqual(stats.indexed, 2)
        self.assertEqual(self.index.search("generated_artifact_should_not_be_retrieved"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
