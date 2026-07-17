#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from tower_console import TowerHandler, TowerService, html_page


class TowerConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="tower-console-")
        self.root = Path(self.temp.name) / "sources"
        self.root.mkdir()
        (self.root / "evidence.md").write_text("A policy gate checks actions before execution.\n", encoding="utf-8")
        self.actions: list[tuple[str, str]] = []
        self.preflight_calls: list[bool] = []
        self.review_calls: list[str] = []
        self.service = TowerService(
            Path(self.temp.name) / "memory.sqlite3",
            Path(self.temp.name) / "ledger.jsonl",
            [self.root],
            report_fn=lambda: {"agents": [], "clear": 0, "flagged": 0, "killed": 0},
            action_fn=lambda action, agent: self.actions.append((action, agent)),
            preflight_fn=lambda *, live: self.preflight_calls.append(live) or {"status": "ready" if live else "ready_for_network_check", "key_configured": True},
            review_fn=lambda: self.review_calls.append("called") or {"ok": True, "reviewed_files": 61},
        )
        self.service.index_sources()

    def tearDown(self) -> None:
        self.service.close()
        self.temp.cleanup()

    def test_chat_and_fleet_share_one_service_without_tool_execution(self) -> None:
        reply = self.service.respond("/math 0.1 + 0.2 - 0.3")
        self.assertEqual(reply["mode"], "exact_math")
        report = self.service.fleet_action("launch")
        self.assertEqual(self.actions, [("launch", "")])
        self.assertEqual(report["clear"], 0)

    def test_model_preflight_is_explicit(self) -> None:
        status = self.service.status()
        self.assertEqual(status["model"]["status"], "ready_for_network_check")
        self.assertEqual(self.preflight_calls, [False])
        self.assertEqual(self.service.model_preflight()["status"], "ready")
        self.assertEqual(self.preflight_calls, [False, True])

    def test_release_review_is_explicit_and_local(self) -> None:
        self.assertEqual(self.review_calls, [])
        result = self.service.review_release()
        self.assertTrue(result["ok"])
        self.assertEqual(self.review_calls, ["called"])

    def test_html_uses_the_local_post_token_and_safe_dom_rendering(self) -> None:
        page = html_page("token-123").decode("utf-8")
        self.assertIn("const token=\"token-123\"", page)
        self.assertIn("X-Tower-Token", page)
        self.assertIn("textContent", page)
        self.assertIn("Evidence packet:", page)
        self.assertIn("View saved evidence", page)
        self.assertIn('id="reviewCheck"', page)

    def test_local_http_routes_enforce_token_and_join_chat_with_fleet(self) -> None:
        TowerHandler.service = self.service
        TowerHandler.token = "tower-test-token"
        server = ThreadingHTTPServer(("127.0.0.1", 0), TowerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/api/status")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("fleet", json.loads(response.read()))

            conn.request("POST", "/api/fleet/launch", headers={"X-Tower-Token": "wrong"})
            self.assertEqual(conn.getresponse().status, 403)

            payload = json.dumps({"message": "/math 1/3 + 1/3 + 1/3"})
            conn.request("POST", "/api/message", body=payload, headers={"Content-Type": "application/json", "X-Tower-Token": "tower-test-token"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["mode"], "exact_math")

            conn.request("POST", "/api/fleet/launch", headers={"X-Tower-Token": "tower-test-token"})
            self.assertEqual(conn.getresponse().status, 200)
            self.assertEqual(self.actions, [("launch", "")])

            conn.request("POST", "/api/model/preflight", headers={"X-Tower-Token": "tower-test-token"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["status"], "ready")

            conn.request("POST", "/api/review", headers={"X-Tower-Token": "tower-test-token"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])
            self.assertEqual(self.review_calls, ["called"])
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
