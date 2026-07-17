#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_ledger import decode_record
from chat_console import ChatService, html_page


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chat-console-")
        self.root = Path(self.temp.name) / "sources"
        self.root.mkdir()
        (self.root / "facts.md").write_text(
            "The policy gate denies unsafe action before execution.\n"
            "The ledger records action metadata.\n",
            encoding="utf-8",
        )
        self.old_key = os.environ.pop("GEMINI_API_KEY", None)
        self.chat = ChatService(
            Path(self.temp.name) / "memory.sqlite3",
            Path(self.temp.name) / "chat.jsonl",
            [self.root],
        )
        self.chat.index_sources()

    def tearDown(self):
        self.chat.close()
        if self.old_key is not None:
            os.environ["GEMINI_API_KEY"] = self.old_key
        self.temp.cleanup()

    def test_math_is_exact_and_recorded(self):
        reply = self.chat.respond("/math 0.1 + 0.2 - 0.3")
        self.assertEqual(reply["mode"], "exact_math")
        self.assertIn("Fraction: 0", reply["text"])
        self.assertTrue(reply["ledger_block"])
        self.assertTrue(self.chat.ledger.verify()["ok"])

    def test_search_includes_provenance(self):
        reply = self.chat.respond("/search unsafe action")
        self.assertEqual(reply["mode"], "retrieval")
        self.assertIn("policy gate", reply["text"].lower())
        self.assertEqual(len(reply["citations"]), 1)

    def test_html_can_open_a_saved_evidence_packet(self):
        page = html_page("token-123").decode("utf-8")
        self.assertIn("Agent Ledger Tower — Local Evidence Chat", page)
        self.assertIn("Evidence packet:", page)
        self.assertIn("View saved evidence", page)
        self.assertIn("/evidence ", page)

    @patch("chat_console.get_api_key", return_value="")
    def test_no_model_means_no_fallback_execution(self, _mock_key):
        reply = self.chat.respond("Can you take an action for me?")
        self.assertEqual(reply["mode"], "offline")
        self.assertIn("No Gemini key", reply["text"])
        self.assertIn(reply["evidence"]["snapshot"], {"saved", "existing"})
        self.assertTrue((Path(self.temp.name) / "evidence_packets" / f"{reply['evidence']['sha256']}.json").is_file())
        self.assertTrue(self.chat.ledger.verify()["ok"])

    @patch("chat_console.gemini_answer")
    def test_model_action_claim_is_flagged_and_ledgered(self, mock_answer):
        mock_answer.return_value = (
            "Evidence: I wrote the requested file.\n"
            "Inference: It is complete.\n"
            "Unknown: none.",
            None,
        )
        with patch.object(self.chat.memory, "search", wraps=self.chat.memory.search) as search:
            reply = self.chat.respond("What does the policy say?")
        self.assertEqual(reply["mode"], "model_flagged")
        self.assertIn("action_claim_in_read_only_chat", reply["quality"]["flags"])
        self.assertTrue(reply["ledger_block"])
        self.assertTrue(self.chat.ledger.verify()["ok"])
        self.assertEqual(search.call_count, 1)
        self.assertEqual(len(reply["evidence"]["sha256"]), 64)
        self.assertIn(reply["evidence"]["snapshot"], {"saved", "existing"})

        snapshot_path = Path(self.temp.name) / "evidence_packets" / f"{reply['evidence']['sha256']}.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["sha256"], reply["evidence"]["sha256"])
        self.assertIn(reply["citations"][0], snapshot["packet"])
        self.assertNotIn("What does the policy say?", snapshot["packet"])
        self.assertNotIn("I wrote the requested file.", snapshot["packet"])

        block = json.loads(Path(self.chat.ledger.path).read_text(encoding="utf-8").splitlines()[-1])
        record = decode_record(bytes.fromhex(block["stateRcsHex"]))
        result = json.loads(record["result"])
        self.assertEqual(result["citations"], reply["citations"])
        self.assertEqual(result["evidence_packet"]["sha256"], reply["evidence"]["sha256"])
        self.assertEqual(result["evidence_packet"]["snapshot"], reply["evidence"]["snapshot"])

    @patch("chat_console.gemini_answer")
    def test_snapshot_failure_withholds_model_request(self, mock_answer):
        with patch.object(self.chat.evidence_packets, "save", side_effect=OSError("write denied")):
            reply = self.chat.respond("What does the policy say?")
        self.assertEqual(reply["mode"], "evidence_snapshot_error")
        self.assertEqual(reply["evidence"]["snapshot"], "unavailable")
        mock_answer.assert_not_called()
        self.assertTrue(self.chat.ledger.verify()["ok"])

    @patch("chat_console.gemini_answer", return_value=("Evidence: supplied.\nInference: none.\nUnknown: none.", None))
    def test_saved_packet_can_be_inspected_without_model_text(self, _mock_answer):
        first = self.chat.respond("What does the policy say?")
        packet_id = first["evidence"]["sha256"]
        reply = self.chat.respond(f"/evidence {packet_id}")
        self.assertEqual(reply["mode"], "evidence_snapshot")
        self.assertIn(packet_id, reply["text"])
        self.assertEqual(reply["citations"], first["citations"])
        self.assertNotIn("Evidence: supplied.", reply["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
