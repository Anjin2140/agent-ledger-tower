#!/usr/bin/env python3
"""
sandbox_worker.py — STANDALONE confined worker: runs ONE tool, prints one JSON line.

This file must run ALONE (stdlib only, no local imports): Dockerfile.sandbox copies
just this module into the container and runs it as `python -I`. The same file is
used by the native tier (a subprocess with a scrubbed environment).

stdin job: {"tool","args","jail","grants","enable_probes"}
stdout   : {"status":"EXECUTED"|"BLOCKED","result":{...},"confinement":{...}}
If the OS kills it (a resource limit trips a signal) it prints nothing and exits
non-zero — the controller treats that as a fail-closed block.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys

try:
    import resource                      # POSIX only (present in the container)
except ImportError:                      # Windows native tier
    resource = None

SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL")


def safe_path(jail, name):
    jail = os.path.realpath(jail)
    full = os.path.realpath(os.path.join(jail, str(name)))
    if full != jail and not full.startswith(jail + os.sep):
        raise PermissionError("path escapes sandbox: %r" % name)
    return full


def _rlimit(attr, value):
    lim = getattr(resource, attr, None)
    if lim is None:
        return False
    try:
        resource.setrlimit(lim, (value, value))
        return True
    except (ValueError, OSError):
        return False


def _guard_network():
    def blocked(*a, **k):
        raise PermissionError("network denied by sandbox")
    socket.socket = blocked
    socket.create_connection = blocked


def _guard_spawn():
    def blocked(*a, **k):
        raise PermissionError("subprocess spawn denied by sandbox")
    subprocess.Popen = blocked
    os.system = blocked
    for fn in ("fork", "forkpty", "posix_spawn", "posix_spawnp", "execv", "execve"):
        if hasattr(os, fn):
            setattr(os, fn, blocked)


def confine(jail, grants):
    report = {"enforced": [], "unavailable": []}
    os.makedirs(jail, exist_ok=True)
    os.chdir(jail)
    report["enforced"].append("cwd-jail")
    if resource:
        if grants.get("fsize_mb") and _rlimit("RLIMIT_FSIZE", int(grants["fsize_mb"]) * 1024 * 1024):
            report["enforced"].append("RLIMIT_FSIZE")
        if grants.get("cpu_s") and _rlimit("RLIMIT_CPU", int(grants["cpu_s"])):
            report["enforced"].append("RLIMIT_CPU")
        if grants.get("nofile") and _rlimit("RLIMIT_NOFILE", int(grants["nofile"])):
            report["enforced"].append("RLIMIT_NOFILE")
    else:
        report["unavailable"].append("rlimits")
    if not grants.get("network"):
        _guard_network()
        report["enforced"].append("network-deny")
    _guard_spawn()
    report["enforced"].append("subprocess-deny")
    return report


def t_write_note(name, text="", size_kb=0):
    data = ("x" * (int(size_kb) * 1024)) if size_kb else str(text)
    with open(safe_path(os.getcwd(), name), "w", encoding="utf-8") as f:
        f.write(data)
    return {"bytes": len(data.encode("utf-8"))}


def t_sha256_note(name):
    with open(safe_path(os.getcwd(), name), "rb") as f:
        return {"sha256": hashlib.sha256(f.read()).hexdigest()}


def t_list_notes():
    return {"files": sorted(os.listdir(os.getcwd()))}


def t_probe_environment():
    present = sorted(k for k in os.environ if any(h in k.upper() for h in SECRET_HINTS))
    return {"secret_names_present": present}


BASE_TOOLS = {"write_note": t_write_note, "sha256_note": t_sha256_note, "list_notes": t_list_notes}


def main():
    job = json.loads(sys.stdin.read())
    report = confine(job["jail"], job.get("grants", {}) or {})
    tools = dict(BASE_TOOLS)
    if job.get("enable_probes"):
        tools["_probe_environment"] = t_probe_environment
    tool = job.get("tool")
    args = job.get("args", {}) or {}
    try:
        if tool not in tools:
            raise PermissionError("unknown tool: %r" % tool)
        result = tools[tool](**args)
        status = "EXECUTED"
    except Exception as e:
        result = {"error": "%s: %s" % (type(e).__name__, e)}
        status = "BLOCKED"
    sys.stdout.write(json.dumps({"status": status, "result": result, "confinement": report}) + "\n")


if __name__ == "__main__":
    main()
