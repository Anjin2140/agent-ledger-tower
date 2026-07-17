#!/usr/bin/env python3
"""Shared, secret-safe Gemini configuration and model preflight.

This module deliberately uses only the Python standard library. It never logs
or returns an API key. The optional live preflight calls ``models.list`` only;
it does not submit a prompt or generate model output.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Mapping


DEFAULT_MODEL = "gemini-3.1-flash-lite"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
HERE = Path(__file__).resolve().parent
WINDOWS_NATIVE_TRANSPORT = HERE / "windows_native_http.ps1"


def _get_user_env(name: str) -> str:
    """Read a Windows user environment value without printing it."""
    try:
        import winreg  # Windows only
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value = winreg.QueryValueEx(key, name)[0]
            return value if isinstance(value, str) else ""
    except OSError:
        return ""


def get_api_key() -> str:
    """Return the process key, or the user's persisted key if available.

    ``setx`` affects newly opened terminals only. The registry fallback makes
    a local console usable immediately while keeping the secret out of files.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    key = _get_user_env("GEMINI_API_KEY")
    if key:
        os.environ["GEMINI_API_KEY"] = key
    return key


def configured_model(scope_variable: str, environ: Mapping[str, str] | None = None) -> str:
    """Resolve one stable model name with a shared override for both paths."""
    values = os.environ if environ is None else environ
    return values.get(scope_variable) or values.get("GEMINI_MODEL") or DEFAULT_MODEL


def normalized_model_name(value: str) -> str:
    """Normalize common provider/resource prefixes before comparing model IDs."""
    if "/" in value:
        value = value.split("/", 1)[1]
    return value.removeprefix("models/")


def safe_model_error(exc: BaseException) -> str:
    """Describe a failure without including credentials, prompts, or response text."""
    suffix = " No action was taken; local search and exact math remain available."
    if isinstance(exc, urllib.error.HTTPError):
        status = ""
        try:
            payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
            candidate = payload.get("error", {}).get("status", "")
            if isinstance(candidate, str) and re.fullmatch(r"[A-Z_]{1,64}", candidate):
                status = f" {candidate}"
        except (UnicodeDecodeError, ValueError, AttributeError, OSError):
            pass
        return f"Gemini request failed (HTTP {exc.code}{status})." + suffix
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            detail = str(reason).lower()
            if "basic constraints of ca cert not marked critical" in detail:
                return (
                    "Gemini request failed TLS validation because a local CA certificate is "
                    "incompatible with Python's verifier. Repair or update the local HTTPS "
                    "inspection certificate, or use a normal trusted network; TLS verification "
                    "stays enabled."
                    + suffix
                )
            if "unable to get local issuer certificate" in detail:
                return (
                    "Gemini request failed TLS validation because the local certificate chain "
                    "is not trusted by Python. Install the correct network root certificate or "
                    "use a normal trusted network; TLS verification stays enabled."
                    + suffix
                )
            return "Gemini request failed TLS certificate verification." + suffix
        if isinstance(reason, OSError) and getattr(reason, "winerror", None) == 10013:
            return "Gemini network access was denied by the local execution policy." + suffix
        if isinstance(reason, OSError) and getattr(reason, "winerror", None) in {11001, 11002}:
            return "Gemini request failed because the hostname could not be resolved." + suffix
        return "Gemini request failed before a response was received (network or TLS error)." + suffix
    if isinstance(exc, (TimeoutError, ssl.SSLError, OSError)):
        return "Gemini request timed out or encountered a local transport error." + suffix
    return "Gemini returned an invalid response." + suffix


def add_windows_root_certificates(context: ssl.SSLContext, enumerator: Callable[[str], Any] | None = None) -> int:
    """Add Windows' trusted-root certificates to an already secure context.

    CPython's OpenSSL context does not consistently consume the Windows root
    store. Importing that local trust store preserves certificate verification;
    it is intentionally not a verification bypass. On other systems this is a
    no-op and normal OpenSSL/Python trust paths remain in use.
    """
    if os.name != "nt":
        return 0
    enum = enumerator or getattr(ssl, "enum_certificates", None)
    if enum is None:
        return 0
    try:
        certificates = enum("ROOT")
    except OSError:
        return 0
    added = 0
    for certificate, encoding, _trust in certificates:
        if encoding != "x509_asn":
            continue
        try:
            context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
            added += 1
        except ssl.SSLError:
            continue
    return added


def secure_ssl_context() -> ssl.SSLContext:
    """Create a certificate-verifying context using normal and Windows roots."""
    context = ssl.create_default_context()
    add_windows_root_certificates(context)
    return context


def _local_ca_is_windows_compatible(exc: BaseException) -> bool:
    """Return true only for the strict-OpenSSL/local-Windows-CA mismatch."""
    return (
        os.name == "nt"
        and isinstance(exc, urllib.error.URLError)
        and isinstance(exc.reason, ssl.SSLError)
        and "basic constraints of ca cert not marked critical" in str(exc.reason).lower()
    )


def _windows_native_json_request(
    url: str,
    api_key: str,
    payload: Mapping[str, Any] | None,
    timeout: int,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Use Windows' native TLS verifier without putting credentials in argv.

    The reviewed PowerShell helper enforces an HTTPS Gemini-host/path allowlist,
    disables redirects, and reads the key only from its inherited environment.
    This is a compatibility path for a Windows-trusted local inspection CA; it
    does not disable certificate or hostname verification.
    """
    if os.name != "nt" or not WINDOWS_NATIVE_TRANSPORT.is_file():
        raise OSError("Windows native HTTPS transport is unavailable")
    environment = os.environ.copy()
    environment["GEMINI_API_KEY"] = api_key
    body = "" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    method = "GET" if payload is None else "POST"
    completed = runner(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_NATIVE_TRANSPORT),
            "-Method",
            method,
            "-Url",
            url,
            "-TimeoutSec",
            str(timeout),
        ],
        input=body,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=timeout + 10,
        env=environment,
        check=False,
    )
    try:
        envelope = json.loads(completed.stdout.strip())
    except (json.JSONDecodeError, AttributeError) as exc:
        raise OSError("Windows native HTTPS transport returned an invalid envelope") from exc
    if completed.returncode != 0 or not envelope.get("ok"):
        status = envelope.get("status")
        if isinstance(status, int) and status > 0:
            api_status = envelope.get("api_status", "")
            safe_body = b""
            if isinstance(api_status, str) and re.fullmatch(r"[A-Z_]{1,64}", api_status):
                safe_body = json.dumps({"error": {"status": api_status}}).encode("utf-8")
            raise urllib.error.HTTPError(url, status, "Gemini HTTP error", None, BytesIO(safe_body))
        raise OSError("Windows native HTTPS transport failed")
    try:
        return json.loads(envelope["body"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Gemini returned invalid JSON") from exc


def gemini_json_request(
    url: str,
    api_key: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: int = 30,
    opener: Callable[..., Any] = urllib.request.urlopen,
    native_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Send one verified Gemini request, using native Windows trust if needed."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    method = "GET" if payload is None else "POST"
    headers = {"x-goog-api-key": api_key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener(request, timeout=timeout, context=secure_ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        # Only the production opener may activate the OS-native compatibility
        # path. Injected test openers remain deterministic and fail directly.
        if opener is urllib.request.urlopen and _local_ca_is_windows_compatible(exc):
            return _windows_native_json_request(url, api_key, payload, timeout, runner=native_runner)
        raise


def list_models(api_key: str, opener: Callable[..., Any] = urllib.request.urlopen) -> list[dict[str, Any]]:
    """List models available to a key; this is a configuration request, not inference."""
    payload = gemini_json_request(MODELS_URL, api_key, timeout=20, opener=opener)
    models = payload.get("models")
    if not isinstance(models, list):
        raise ValueError("models.list response did not contain a model list")
    return [model for model in models if isinstance(model, dict)]


def preflight(
    *,
    live: bool,
    api_key: str | None = None,
    models: Mapping[str, str] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Return JSON-safe configuration evidence for chat and agent model paths."""
    key = get_api_key() if api_key is None else api_key
    selected = dict(models or {
        "chat": configured_model("CHAT_MODEL"),
        "agent": configured_model("AGENT_MODEL"),
    })
    result: dict[str, Any] = {
        "schema": "agent-ledger-tower-gemini-preflight-v1",
        "key_configured": bool(key),
        "network_checked": live,
        "models": [{"scope": scope, "configured": normalized_model_name(model)} for scope, model in selected.items()],
    }
    if not key:
        result.update({"status": "key_missing", "safe_error": "GEMINI_API_KEY is not configured."})
        return result
    if not live:
        result["status"] = "ready_for_network_check"
        return result

    try:
        available = {
            normalized_model_name(str(model.get("name", ""))): model
            for model in list_models(key, opener=opener)
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
        result.update({"status": "request_failed", "safe_error": safe_model_error(exc)})
        return result

    checks: list[dict[str, Any]] = []
    for scope, configured in selected.items():
        name = normalized_model_name(configured)
        model = available.get(name)
        methods = model.get("supportedGenerationMethods", []) if model else []
        supports = isinstance(methods, list) and "generateContent" in methods
        checks.append({"scope": scope, "configured": name, "available": model is not None, "supports_generate_content": supports})
    result["models"] = checks
    result["status"] = "ready" if all(check["supports_generate_content"] for check in checks) else "model_unavailable"
    return result
