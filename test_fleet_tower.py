#!/usr/bin/env python3
"""Regression tests for local fleet-control input boundaries."""
from __future__ import annotations

import unittest

import fleet_tower
from operator_console import apply_fleet_action, html_page


class FleetControlTests(unittest.TestCase):
    def test_agent_ids_cannot_escape_the_fleet_directory(self) -> None:
        for value in ("", ".", "..", "../outside", "agent/other", "agent\\other", "agent id"):
            with self.assertRaises(ValueError, msg=value):
                fleet_tower.validate_agent_id(value)

    def test_valid_agent_id_produces_a_contained_kill_path(self) -> None:
        path = fleet_tower.kill_path("agent-01")
        self.assertTrue(path.endswith("fleet" + __import__("os").sep + "agent-01" + __import__("os").sep + "KILL"))

    def test_operator_html_embeds_a_per_process_post_token(self) -> None:
        page = html_page("test-token").decode("utf-8")
        self.assertIn("const token = \"test-token\"", page)
        self.assertIn("X-Tower-Token", page)

    def test_unknown_operator_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_fleet_action("erase_fleet")


if __name__ == "__main__":
    unittest.main(verbosity=2)
