#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import ssl
import subprocess
import unittest
import urllib.error
from types import SimpleNamespace

from gemini_config import (
    DEFAULT_MODEL,
    WINDOWS_NATIVE_TRANSPORT,
    _local_ca_is_windows_compatible,
    _windows_native_json_request,
    add_windows_root_certificates,
    configured_model,
    normalized_model_name,
    preflight,
    safe_model_error,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeContext:
    def __init__(self):
        self.certificates = []

    def load_verify_locations(self, *, cadata):
        self.certificates.append(cadata)


class GeminiConfigTests(unittest.TestCase):
    def test_model_resolution_is_stable_and_overrideable(self) -> None:
        self.assertEqual(configured_model("CHAT_MODEL", {}), DEFAULT_MODEL)
        self.assertEqual(configured_model("CHAT_MODEL", {"GEMINI_MODEL": "gemini-custom"}), "gemini-custom")
        self.assertEqual(configured_model("CHAT_MODEL", {"GEMINI_MODEL": "shared", "CHAT_MODEL": "chat-only"}), "chat-only")
        self.assertEqual(normalized_model_name("models/gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(normalized_model_name("gemini/gemini-2.5-flash"), "gemini-2.5-flash")

    def test_dry_preflight_never_uses_network(self) -> None:
        def fail_opener(*_args, **_kwargs):
            raise AssertionError("network should not be called")
        result = preflight(live=False, api_key="test-key", models={"chat": "gemini-2.5-flash"}, opener=fail_opener)
        self.assertEqual(result["status"], "ready_for_network_check")
        self.assertFalse(result["network_checked"])

    def test_live_preflight_checks_exact_model_and_generate_content(self) -> None:
        def opener(*_args, **_kwargs):
            return FakeResponse({"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]})
        result = preflight(live=True, api_key="test-key", models={"chat": "gemini-2.5-flash"}, opener=opener)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["models"][0]["supports_generate_content"])

    def test_live_preflight_rejects_missing_or_unsupported_models(self) -> None:
        def opener(*_args, **_kwargs):
            return FakeResponse({"models": [{"name": "models/other", "supportedGenerationMethods": ["embedContent"]}]})
        result = preflight(live=True, api_key="test-key", models={"chat": "gemini-2.5-flash"}, opener=opener)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertFalse(result["models"][0]["available"])

    def test_network_denial_diagnostic_does_not_blame_key_or_model(self) -> None:
        denied = OSError(10013, "permission denied")
        denied.winerror = 10013
        self.assertIn("denied by the local execution policy", safe_model_error(urllib.error.URLError(denied)))

    def test_invalid_local_ca_diagnostic_does_not_offer_an_insecure_bypass(self) -> None:
        error = safe_model_error(urllib.error.URLError(
            ssl.SSLError("Basic Constraints of CA cert not marked critical")
        ))
        self.assertIn("local CA certificate", error)
        self.assertIn("TLS verification stays enabled", error)
        self.assertNotIn("AGENT_INSECURE_TLS", error)

    @unittest.skipUnless(os.name == "nt", "Windows native transport is Windows-only")
    def test_native_transport_keeps_key_out_of_arguments_and_payload_on_stdin(self) -> None:
        captured = {}

        def runner(argv, **kwargs):
            captured.update({"argv": argv, **kwargs})
            body = json.dumps({"models": []})
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"ok": True, "status": 200, "body": body}),
                stderr="",
            )

        payload = {"contents": [{"parts": [{"text": "harmless fixture"}]}]}
        result = _windows_native_json_request(
            "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent",
            "private-test-key",
            payload,
            10,
            runner=runner,
        )
        self.assertEqual(result, {"models": []})
        self.assertNotIn("private-test-key", " ".join(captured["argv"]))
        self.assertEqual(captured["env"]["GEMINI_API_KEY"], "private-test-key")
        self.assertEqual(json.loads(captured["input"]), payload)
        self.assertTrue(captured["capture_output"])
        self.assertFalse(captured["check"])

    @unittest.skipUnless(os.name == "nt", "Windows native transport is Windows-only")
    def test_native_script_rejects_non_gemini_destination_before_network(self) -> None:
        environment = os.environ.copy()
        environment["GEMINI_API_KEY"] = "private-test-key"
        completed = subprocess.run(
            [
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(WINDOWS_NATIVE_TRANSPORT),
                "-Method", "GET", "-Url", "https://example.com/v1beta/models",
            ],
            input="",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=False,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 64)
        self.assertEqual(json.loads(completed.stdout)["error"], "destination_not_allowed")
        self.assertNotIn("private-test-key", completed.stdout + completed.stderr)

    @unittest.skipUnless(os.name == "nt", "Windows native transport is Windows-only")
    def test_only_known_strict_ca_error_qualifies_for_native_fallback(self) -> None:
        compatible = urllib.error.URLError(ssl.SSLError("Basic Constraints of CA cert not marked critical"))
        unrelated = urllib.error.URLError(ssl.SSLError("hostname mismatch"))
        self.assertTrue(_local_ca_is_windows_compatible(compatible))
        self.assertFalse(_local_ca_is_windows_compatible(unrelated))

    @unittest.skipUnless(os.name == "nt", "Windows root store is Windows-only")
    def test_windows_roots_are_added_without_disabling_verification(self) -> None:
        context = FakeContext()
        added = add_windows_root_certificates(context, enumerator=lambda _store: [(b"0\x03\x02\x01\x01", "x509_asn", True), (b"ignored", "pkcs_7_asn", True)])
        self.assertEqual(added, 1)
        self.assertEqual(len(context.certificates), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
