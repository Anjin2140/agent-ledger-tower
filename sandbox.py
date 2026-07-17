#!/usr/bin/env python3
"""
sandbox.py — SandboxExecutor: run one approved action in a confined worker process.

Two tiers, selected by `mode`:
  * "hard"   — a Docker container (Dockerfile.sandbox): network=none, read-only root,
               non-root user, pid/memory caps. describe()["hard_boundary"] is True.
               If Docker is unavailable the executor FAILS CLOSED (it does not
               silently fall back to a soft boundary).
  * "native" — a subprocess with a scrubbed environment, kernel rlimits, a realpath
               jail, and network/spawn guards. Honest soft boundary:
               describe()["hard_boundary"] is False.

Secrets never cross the boundary: the child environment is stripped of any
secret-looking variable name before the worker starts.

The worker (sandbox_worker.py) is standalone stdlib so the same file runs inside
the container and in the native subprocess. Controller stays stdlib-only too.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "sandbox_worker.py")
SANDBOX_IMAGE = os.environ.get("AGENT_SANDBOX_IMAGE", "agent-ledger-tower-sandbox:latest")
SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL")


def _is_secret_name(name):
    up = name.upper()
    return any(h in up for h in SECRET_HINTS)


def scrubbed_env():
    return {k: v for k, v in os.environ.items() if not _is_secret_name(k)}


def docker_available():
    return shutil.which("docker") is not None


class Grants:
    """Default-deny capabilities handed to a single action."""
    def __init__(self, network=False, cpu_s=15, fsize_mb=25, nofile=64):
        self.network = network
        self.cpu_s = cpu_s
        self.fsize_mb = fsize_mb
        self.nofile = nofile

    def as_dict(self):
        return dict(self.__dict__)


class SandboxExecutor:
    def __init__(self, work_dir, mode="hard", timeout_seconds=5, enable_probes=False, grants=None):
        self.work_dir = os.path.abspath(work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        self.mode = mode
        self.timeout = timeout_seconds
        self.enable_probes = enable_probes
        self.grants = grants or Grants()

    # --- honest self-description --------------------------------------------
    def describe(self):
        if self.mode == "hard":
            if docker_available():
                return {"mode": "hard", "tier": "hard", "hard_boundary": True,
                        "enforced": ["container", "network-none", "read-only-root",
                                     "non-root", "pids/memory caps", "secret-env-scrub"]}
            return {"mode": "hard", "tier": "unavailable", "hard_boundary": False,
                    "reason": "Docker not available; hard boundary cannot be established (fail-closed)",
                    "enforced": []}
        return {"mode": "native", "tier": "native", "hard_boundary": False,
                "warning": "native is a soft boundary (kernel rlimits + realpath jail + "
                           "network/spawn guards + secret-env scrub), not a hard jail",
                "enforced": ["cwd-jail", "realpath-guard", "RLIMIT_FSIZE", "RLIMIT_CPU",
                             "network-deny", "subprocess-deny", "secret-env-scrub"]}

    # --- execution ----------------------------------------------------------
    def execute(self, tool, args):
        job = {"tool": tool, "args": args or {}, "jail": self.work_dir,
               "grants": self.grants.as_dict(), "enable_probes": self.enable_probes}
        if self.mode == "hard":
            if not docker_available():
                return {"ok": False, "status": "blocked",
                        "result": {"error": "hard sandbox unavailable: Docker not found (fail-closed)"},
                        "enforcement": {"selected": "unavailable", "hard_boundary": False,
                                        "reason": "docker-missing"}}
            return self._run_docker(job)
        return self._run_native(job)

    def _finish(self, proc, tier, hard):
        out = [l for l in proc.stdout.splitlines() if l.strip()]
        if proc.returncode != 0 or not out:
            return {"ok": False, "status": "blocked",
                    "result": {"error": "worker terminated by boundary (fail-closed), rc=%d" % proc.returncode},
                    "enforcement": {"selected": tier, "hard_boundary": hard, "reason": "worker-killed"}}
        try:
            res = json.loads(out[-1])
        except json.JSONDecodeError:
            return {"ok": False, "status": "error",
                    "result": {"error": "unparseable worker output"},
                    "enforcement": {"selected": tier, "hard_boundary": hard}}
        ok = res.get("status") == "EXECUTED"
        return {"ok": ok, "status": "ok" if ok else "blocked",
                "result": res.get("result", {}),
                "enforcement": {"selected": tier, "hard_boundary": hard,
                                "confinement": res.get("confinement", {})}}

    def _run_native(self, job):
        try:
            proc = subprocess.run([sys.executable, "-I", WORKER],
                                  input=json.dumps(job), capture_output=True, text=True,
                                  timeout=self.timeout, env=scrubbed_env(), cwd=self.work_dir)
        except subprocess.TimeoutExpired:
            return {"ok": False, "status": "blocked",
                    "result": {"error": "action timed out (fail-closed)"},
                    "enforcement": {"selected": "native", "hard_boundary": False, "reason": "timeout"}}
        return self._finish(proc, "native", False)

    def _run_docker(self, job):
        cjob = dict(job)
        cjob["jail"] = "/workspace"                 # the bind mount inside the container
        cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
               "--tmpfs", "/tmp", "--pids-limit", "64", "--memory", "256m",
               "-v", "%s:/workspace:rw" % self.work_dir, SANDBOX_IMAGE]
        try:
            proc = subprocess.run(cmd, input=json.dumps(cjob), capture_output=True,
                                  text=True, timeout=self.timeout)   # no host env passed
        except subprocess.TimeoutExpired:
            return {"ok": False, "status": "blocked",
                    "result": {"error": "action timed out in container (fail-closed)"},
                    "enforcement": {"selected": "hard", "hard_boundary": True, "reason": "timeout"}}
        return self._finish(proc, "hard", True)
