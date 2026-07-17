#!/usr/bin/env python3
"""Local, provenance-first chat console for the Agent Ledger Tower.

The console binds only to 127.0.0.1. It has three deliberately separate paths:

- /search retrieves source-hashed local excerpts from SQLite FTS5;
- /math evaluates a restricted exact-rational expression without Python eval;
- ordinary text optionally calls Gemini for a read-only answer, with retrieved
  excerpts attached and displayed as citations.

A model response cannot execute a tool through this console. Privileged actions
remain in agent_loop.py, where policy and the OS sandbox mediate every action.
The conversation ledger stores hashes and citations, not raw conversation text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from agent_ledger import GENESIS, block_hash, canon, encode_record, verify_chain
from exact_math_tool import MathSyntaxError, evaluate
from gemini_config import configured_model, gemini_json_request, get_api_key, safe_model_error
from memory_index import ContextPacket, IndexStats, MemoryIndex, SearchHit
from operator_console import fleet_report
from response_quality import audit_response


HERE = Path(__file__).resolve().parent
MAX_MESSAGE_CHARS = 8_000
MODEL = configured_model("CHAT_MODEL")
EVIDENCE_PACKET_SCHEMA = "agent-ledger-tower-evidence-packet-v1"
EVIDENCE_PACKET_ID = re.compile(r"[0-9a-f]{64}\Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EvidencePacketStore:
    """Private local snapshots of the exact retrieved evidence sent to a model.

    Snapshots deliberately exclude the user question and model output. They are
    runtime artifacts, not ledger payloads or release files: the ledger keeps
    only the packet digest and metadata. A corrupt existing snapshot is an
    error, never something silently replaced.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_id(packet_id: str) -> str:
        if not isinstance(packet_id, str) or not EVIDENCE_PACKET_ID.fullmatch(packet_id):
            raise ValueError("evidence packet id must be a 64-character lowercase SHA-256 hex value")
        return packet_id

    def _path(self, packet_id: str) -> Path:
        return self.root / f"{self._validate_id(packet_id)}.json"

    @staticmethod
    def _payload(packet: ContextPacket) -> dict[str, Any]:
        return {
            "schema": EVIDENCE_PACKET_SCHEMA,
            "sha256": packet.sha256,
            "chars": len(packet.text),
            "source_count": len(packet.hits),
            "citations": [hit.citation() for hit in packet.hits],
            "sources": [
                {
                    "path": hit.path,
                    "sha256": hit.sha256,
                    "start_line": hit.start_line,
                    "end_line": hit.end_line,
                }
                for hit in packet.hits
            ],
            "packet": packet.text,
        }

    @staticmethod
    def _validated_payload(payload: Any, packet_id: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema") != EVIDENCE_PACKET_SCHEMA:
            raise RuntimeError("evidence snapshot has an unsupported schema")
        packet = payload.get("packet")
        if not isinstance(packet, str) or sha256_text(packet) != packet_id or payload.get("sha256") != packet_id:
            raise RuntimeError("evidence snapshot digest does not match its packet")
        citations_value = payload.get("citations")
        if not isinstance(citations_value, list) or not all(isinstance(item, str) for item in citations_value):
            raise RuntimeError("evidence snapshot citations are invalid")
        return payload

    def save(self, packet: ContextPacket) -> str:
        packet_id = self._validate_id(packet.sha256)
        if sha256_text(packet.text) != packet_id:
            raise RuntimeError("refusing to save an evidence packet with a mismatched digest")
        target = self._path(packet_id)
        with self._lock:
            if target.exists():
                self.load(packet_id)
                return "existing"
            payload = self._payload(packet)
            temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
            try:
                temporary.write_text(
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return "saved"

    def load(self, packet_id: str) -> dict[str, Any]:
        packet_id = self._validate_id(packet_id)
        target = self._path(packet_id)
        with self._lock:
            if not target.is_file():
                raise FileNotFoundError("no local evidence snapshot exists for that packet id")
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError("evidence snapshot cannot be read") from exc
        return self._validated_payload(payload, packet_id)

    def count(self) -> int:
        with self._lock:
            return sum(1 for path in self.root.glob("*.json") if path.is_file())


class ConversationLedger:
    """Append-only metadata ledger. Message and response contents remain private."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def append(
        self,
        message: str,
        reply: dict[str, Any],
        citations: list[str],
        status: str = "ok",
    ) -> str:
        with self._lock:
            if self.path.exists() and self.path.stat().st_size:
                valid, _, reason = verify_chain(str(self.path))
                if not valid:
                    raise RuntimeError(f"chat ledger is invalid: {reason}")
                blocks = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
                index = len(blocks)
                previous = blocks[-1]["blockHash"]
            else:
                index, previous = 0, GENESIS

            result = {
                "response_sha256": sha256_text(reply["text"]),
                "citations": citations,
                "source_count": len(citations),
            }
            evidence = reply.get("evidence")
            if isinstance(evidence, dict):
                result["evidence_packet"] = {
                    "sha256": str(evidence.get("sha256", "")),
                    "chars": int(evidence.get("chars", 0)),
                    "source_count": int(evidence.get("source_count", 0)),
                    "snapshot": str(evidence.get("snapshot", "not_saved")),
                }
            quality = reply.get("quality")
            if isinstance(quality, dict):
                result["response_quality"] = {
                    "contract": str(quality.get("contract", "")),
                    "verdict": str(quality.get("verdict", "")),
                    "flags": [str(flag) for flag in quality.get("flags", [])],
                }

            record = {
                "step": index,
                "tool": "chat_turn",
                "args": canon({"message_sha256": sha256_text(message), "mode": reply["mode"]}),
                "result": canon(result),
                "status": status,
            }
            payload = encode_record(record)
            timestamp = time.time_ns() // 1_000_000
            digest = block_hash(index, timestamp, previous, payload)
            block = {
                "index": index,
                "timestampMs": timestamp,
                "prevHash": previous,
                "stateKind": "chat_turn",
                "stateRcsHex": payload.hex(),
                "blockHash": digest,
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(block, separators=(",", ":")) + "\n")
            return digest

    def verify(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"ok": True, "reason": "no chat turns recorded", "blocks": 0}
        ok, _index, reason = verify_chain(str(self.path))
        return {"ok": ok, "reason": reason}


def citations(hits: list[SearchHit]) -> list[str]:
    return [hit.citation() for hit in hits]


def gemini_answer(question: str, context: str) -> tuple[str | None, str | None]:
    """Read-only model answer. Returns (answer, safe_error)."""
    api_key = get_api_key()
    if not api_key:
        return None, "No Gemini key is configured. Use /search or /math, or set GEMINI_API_KEY for read-only model answers."

    instruction = (
        "You are a read-only research assistant inside a local control tower. "
        "You cannot execute tools or claim that any action occurred. "
        "Use this exact response structure: Evidence:, Inference:, Unknown:. "
        "In Evidence, copy at least one supplied citation identifier verbatim "
        "for every source-backed claim. If no source supports a claim, say so "
        "under Unknown. Never claim that you wrote, sent, changed, executed, "
        "or accessed anything. Keep the answer concise."
    )
    if not context:
        return None, "No evidence packet was supplied. No model request was made."
    source_context = context
    payload = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{"text": f"Question:\n{question}\n\nSource excerpts:\n{source_context}"}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 900},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    try:
        body = gemini_json_request(url, api_key, payload, timeout=30)
        parts = body["candidates"][0]["content"]["parts"]
        answer = "".join(part.get("text", "") for part in parts).strip()
        if not answer:
            return None, "Gemini returned a successful response with no text. No action was taken; local search and exact math remain available."
        return answer, None
    except (KeyError, IndexError, ValueError, TimeoutError, ssl.SSLError, OSError) as exc:
        return None, safe_model_error(exc)


class ChatService:
    def __init__(
        self,
        db_path: str | Path,
        ledger_path: str | Path,
        sources: Sequence[str | Path],
        evidence_dir: str | Path | None = None,
    ):
        self.memory = MemoryIndex(db_path)
        self.ledger = ConversationLedger(ledger_path)
        self.evidence_packets = EvidencePacketStore(evidence_dir or Path(db_path).parent / "evidence_packets")
        self.sources = [Path(source).resolve() for source in sources if Path(source).is_dir()]
        self._lock = threading.RLock()

    def close(self) -> None:
        self.memory.close()

    def index_sources(self) -> dict[str, Any]:
        total = IndexStats()
        with self._lock:
            for source in self.sources:
                stats = self.memory.index_root(source)
                for key, value in vars(stats).items():
                    setattr(total, key, getattr(total, key) + value)
        return vars(total)

    def status(self) -> dict[str, Any]:
        return {
            "model_configured": bool(get_api_key()),
            "sources": [str(source) for source in self.sources],
            "ledger": self.ledger.verify(),
            "evidence_snapshots": self.evidence_packets.count(),
        }

    def respond(self, message: str) -> dict[str, Any]:
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message exceeds {MAX_MESSAGE_CHARS} characters")

        if message == "/help":
            reply = {
                "mode": "help",
                "text": (
                    "Commands:\n"
                    "/search <words>  — retrieve source-hashed local excerpts\n"
                    "/math <expression>  — exact rational arithmetic; e.g. /math 0.1 + 0.2 - 0.3\n"
                    "/status  — fleet and chat-ledger status\n"
                    "/verify  — verify the chat metadata ledger\n"
                    "/index  — refresh only the source folders chosen when this console started\n"
                    "/evidence <sha256>  — inspect a saved private evidence packet\n"
                    "\nOrdinary text is read-only: if GEMINI_API_KEY is set, Gemini may answer using retrieved excerpts. "
                    "The exact evidence packet is saved locally before any model request. Its response is structurally audited for citations, unknowns, and impossible action claims. "
                    "This console cannot execute tools."
                ),
                "citations": [],
            }
        elif message.startswith("/math"):
            expression = message[5:].strip()
            try:
                result = evaluate(expression)
                reply = {
                    "mode": "exact_math",
                    "text": f"Exact result\nFraction: {result.fraction}\nDecimal: {result.decimal}",
                    "citations": [],
                }
            except (MathSyntaxError, ZeroDivisionError) as exc:
                reply = {"mode": "exact_math_error", "text": f"Math input rejected: {exc}", "citations": []}
        elif message.startswith("/search"):
            query = message[7:].strip()
            hits = self.memory.search(query)
            if hits:
                excerpts = "\n\n".join(f"[{hit.citation()}]\n{hit.text}" for hit in hits)
                reply = {"mode": "retrieval", "text": excerpts, "citations": citations(hits)}
            else:
                reply = {"mode": "retrieval", "text": "No indexed source excerpt matched that query.", "citations": []}
        elif message == "/status":
            report = fleet_report()
            reply = {
                "mode": "status",
                "text": (
                    f"Fleet: {report['clear']} clear, {report['flagged']} flagged, {report['killed']} killed.\n"
                    f"Chat ledger: {self.ledger.verify()['reason']}\n"
                    f"Indexed source roots: {len(self.sources)}"
                ),
                "citations": [],
            }
        elif message == "/verify":
            result = self.ledger.verify()
            reply = {"mode": "verification", "text": f"Chat metadata ledger: {'OK' if result['ok'] else 'FAIL'} — {result['reason']}", "citations": []}
        elif message == "/index":
            stats = self.index_sources()
            reply = {"mode": "index", "text": "Index refreshed:\n" + json.dumps(stats, indent=2), "citations": []}
        elif message == "/evidence" or message.startswith("/evidence "):
            packet_id = message[len("/evidence"):].strip().lower()
            try:
                snapshot = self.evidence_packets.load(packet_id)
                snapshot_citations = [str(value) for value in snapshot["citations"]]
                reply = {
                    "mode": "evidence_snapshot",
                    "text": (
                        f"Saved evidence packet {packet_id}\n"
                        "This is the exact retrieved source context saved before a model request. "
                        "It does not contain the user question or model response.\n\n"
                        + str(snapshot["packet"])
                    ),
                    "citations": snapshot_citations,
                    "evidence": {
                        "sha256": packet_id,
                        "chars": int(snapshot["chars"]),
                        "source_count": int(snapshot["source_count"]),
                        "snapshot": "loaded",
                    },
                }
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                reply = {
                    "mode": "evidence_snapshot_error",
                    "text": f"Evidence packet unavailable: {exc}",
                    "citations": [],
                }
        else:
            hits = self.memory.search(message)
            packet = self.memory.context_packet_for_hits(hits)
            packet_citations = citations(list(packet.hits))
            evidence = {
                "sha256": packet.sha256,
                "chars": len(packet.text),
                "source_count": len(packet.hits),
            }
            try:
                evidence["snapshot"] = self.evidence_packets.save(packet)
            except (OSError, RuntimeError, ValueError) as exc:
                reply = {
                    "mode": "evidence_snapshot_error",
                    "text": (
                        "The retrieved evidence packet could not be saved locally, so no model request was made. "
                        f"Snapshot error: {type(exc).__name__}."
                    ),
                    "citations": packet_citations,
                    "evidence": evidence | {"snapshot": "unavailable"},
                }
            else:
                answer, error = gemini_answer(message, packet.text)
                if answer is None:
                    fallback = (
                        error + "\n\n"
                        "Retrieved local evidence:\n" +
                        ("\n".join(f"- {hit.citation()}" for hit in packet.hits) if packet.hits else "(none)")
                    )
                    reply = {"mode": "offline", "text": fallback, "citations": packet_citations, "evidence": evidence}
                else:
                    quality = audit_response(answer, packet_citations)
                    if quality["verdict"] == "pass":
                        prefix = "Model response — structurally reviewable but unverified; inspect the citations below."
                        mode = "model_unverified"
                    else:
                        prefix = (
                            "Model response — FLAGGED by the local evidence contract; do not rely on it until reviewed.\n"
                            "Flags: " + ", ".join(quality["flags"])
                        )
                        mode = "model_flagged"
                    reply = {
                        "mode": mode,
                        "text": prefix + "\n\n" + answer,
                        "citations": packet_citations,
                        "quality": quality,
                        "evidence": evidence,
                    }

        try:
            status = "warning" if reply.get("quality", {}).get("verdict") == "flagged" else "ok"
            block_hash_value = self.ledger.append(message, reply, reply["citations"], status=status)
            reply["ledger_block"] = block_hash_value[:12]
        except RuntimeError as exc:
            reply["ledger_block"] = None
            reply["ledger_error"] = str(exc)
        return reply


def html_page(token: str) -> bytes:
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Agent Ledger Tower — Local Evidence Chat</title>
<style>
:root{{color-scheme:dark}} body{{margin:0;background:#0b1017;color:#d6e2ee;font:15px/1.45 system-ui,sans-serif}}
main{{max-width:980px;margin:auto;padding:22px}} h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#91a4b7;margin:0 0 18px}}
#feed{{min-height:430px;border:1px solid #243244;background:#0e1621;border-radius:10px;padding:14px;overflow:auto}}
.msg{{margin:11px 0;padding:10px 12px;border-radius:8px;white-space:pre-wrap;max-width:90%}}
.user{{margin-left:auto;background:#1e3854}} .system{{background:#16212e}} .model{{background:#242037}}
.label{{font-size:12px;font-weight:700;color:#89c8ff;margin-bottom:5px}} .cite{{font:12px ui-monospace,Consolas,monospace;color:#9db3c8;margin-top:8px}}
form{{display:flex;gap:9px;margin-top:14px}} textarea{{flex:1;min-height:54px;resize:vertical;background:#0e1621;color:#e5eef7;border:1px solid #31465d;border-radius:8px;padding:10px;font:inherit}}
button{{background:#205b87;color:#fff;border:0;border-radius:8px;padding:10px 14px;font:inherit;cursor:pointer}} button.secondary{{background:#283745}} .tools{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}}
.note{{font-size:12px;color:#9db3c8;margin-top:8px}}
</style></head><body><main>
<h1>Local Evidence Chat</h1>
<p class="sub">Read-only conversation • source-hashed retrieval • exact math • no direct tool execution</p>
<div id="feed"></div>
<form id="form"><textarea id="input" placeholder="Ask a question, or try /help"></textarea><button>Send</button></form>
<div class="tools"><button class="secondary" onclick="quick('/help')">Help</button><button class="secondary" onclick="quick('/status')">Status</button><button class="secondary" onclick="quick('/verify')">Verify chat log</button><button class="secondary" onclick="quick('/index')">Refresh sources</button></div>
<div class="note">A model may propose text only. Tool execution remains in the separate policy-gated workflow.</div>
<script>
const token = {json.dumps(token)};
const feed = document.getElementById('feed'), input = document.getElementById('input');
function add(label, text, kind, cites=[], block='', quality=null, evidence=null){{
  const box=document.createElement('div'); box.className='msg '+kind;
  const title=document.createElement('div'); title.className='label'; title.textContent=label; box.appendChild(title);
  const body=document.createElement('div'); body.textContent=text; box.appendChild(body);
  if(cites.length){{const c=document.createElement('div');c.className='cite';c.textContent='Sources: '+cites.join(' | ');box.appendChild(c)}}
  if(quality){{const c=document.createElement('div');c.className='cite';c.textContent='Response audit: '+quality.verdict+(quality.flags&&quality.flags.length?' — '+quality.flags.join(', '):'');box.appendChild(c)}}
  if(evidence&&evidence.sha256){{const c=document.createElement('div');c.className='cite';c.textContent='Evidence packet: '+evidence.sha256+' · local snapshot: '+(evidence.snapshot||'not saved');box.appendChild(c);if(['saved','existing'].includes(evidence.snapshot)){{const b=document.createElement('button');b.className='secondary';b.textContent='View saved evidence';b.addEventListener('click',()=>send('/evidence '+evidence.sha256));box.appendChild(b)}}}}
  if(block){{const c=document.createElement('div');c.className='cite';c.textContent='Chat ledger block: '+block;box.appendChild(c)}}
  feed.appendChild(box); feed.scrollTop=feed.scrollHeight;
}}
async function send(message){{
  if(!message.trim()) return;
  add('You',message,'user'); input.value='';
  const r=await fetch('/api/message',{{method:'POST',headers:{{'Content-Type':'application/json','X-Tower-Token':token}},body:JSON.stringify({{message}})}});
  const d=await r.json();
  add(d.mode||'response',d.text||d.error||'No response.','system',d.citations||[],d.ledger_block||'',d.quality||null,d.evidence||null);
}}
document.getElementById('form').addEventListener('submit',e=>{{e.preventDefault();send(input.value)}});
input.addEventListener('keydown',e=>{{if(e.ctrlKey&&e.key==='Enter'){{e.preventDefault();send(input.value)}}}});
function quick(x){{send(x)}} add('System','Type /help for commands. Ctrl+Enter sends.','system');
</script></main></body></html>"""
    return page.encode("utf-8")


class ChatHandler(BaseHTTPRequestHandler):
    service: ChatService
    token: str

    def log_message(self, *_args: Any) -> None:
        pass

    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path in {"/", "/index.html"}:
            self._send(200, html_page(self.token), "text/html; charset=utf-8")
        elif urlparse(self.path).path == "/api/status":
            self._send(200, self.service.status())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.headers.get("X-Tower-Token") != self.token:
            self._send(403, {"error": "local request token required"})
            return
        if urlparse(self.path).path != "/api/message":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_MESSAGE_CHARS + 128:
                raise ValueError("invalid request size")
            data = json.loads(self.rfile.read(length))
            reply = self.service.respond(data.get("message"))
            self._send(200, reply)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception:
            self._send(500, {"error": "local chat request failed"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local evidence-first chat console")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--db", default=str(HERE / "chat_memory.sqlite3"))
    parser.add_argument("--ledger", default=str(HERE / "chat_ledger.jsonl"))
    parser.add_argument("--source", action="append", default=[], help="Folder to index; may be specified more than once")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # A standalone export can run without the historical workspace. When
    # no source folder is supplied, index this reviewed package itself.
    sources = args.source or [str(HERE)]
    service = ChatService(args.db, args.ledger, sources)
    stats = service.index_sources()
    token = secrets.token_urlsafe(24)
    ChatHandler.service = service
    ChatHandler.token = token
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ChatHandler)
    print(f"local evidence chat -> http://127.0.0.1:{args.port}")
    print("indexed:", json.dumps(stats, sort_keys=True))
    print("model:", "configured" if get_api_key() else "not configured (search and math still work)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
