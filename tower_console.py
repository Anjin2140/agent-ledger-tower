#!/usr/bin/env python3
"""One local interface for evidence chat and verifiable fleet oversight.

The page binds to 127.0.0.1 only. Conversation text is handled by the
provenance-first chat service; fleet mutations use the already-hardened operator
actions. No fleet starts merely because this console opens.
"""
from __future__ import annotations

import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, urlparse

from chat_console import ChatService, MAX_MESSAGE_CHARS
from component_review import load_registry, load_release_files, validate_registry
from gemini_config import preflight
from operator_console import apply_fleet_action, fleet_report


HERE = Path(__file__).resolve().parent


def release_review(root: Path = HERE) -> dict[str, Any]:
    """Return local file-review evidence without indexing, network, or model work."""
    try:
        registry = load_registry(root / "component_review_registry.json")
        allowlist = load_release_files(root / "release_files.json", root)
        return validate_registry(registry, allowlist).as_json()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema": "agent-ledger-tower-component-review-v1",
            "ok": False,
            "errors": [f"release review unavailable: {type(exc).__name__}"],
        }


class TowerService:
    """Compose read-only evidence chat with shared fleet-control functions."""

    def __init__(
        self,
        db_path: str | Path,
        ledger_path: str | Path,
        sources: Sequence[str | Path],
        report_fn: Callable[[], dict[str, Any]] = fleet_report,
        action_fn: Callable[[str, str], None] = apply_fleet_action,
        preflight_fn: Callable[..., dict[str, Any]] = preflight,
        review_fn: Callable[[], dict[str, Any]] = release_review,
    ) -> None:
        self.chat = ChatService(db_path, ledger_path, sources)
        self._report = report_fn
        self._action = action_fn
        self._preflight = preflight_fn
        self._review = review_fn
        self._lock = threading.RLock()

    def close(self) -> None:
        self.chat.close()

    def index_sources(self) -> dict[str, Any]:
        return self.chat.index_sources()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"fleet": self._report(), "chat": self.chat.status(), "model": self._preflight(live=False)}

    def respond(self, message: str) -> dict[str, Any]:
        with self._lock:
            return self.chat.respond(message)

    def fleet_action(self, action: str, agent_id: str = "") -> dict[str, Any]:
        with self._lock:
            self._action(action, agent_id)
            return self._report()

    def model_preflight(self) -> dict[str, Any]:
        """Run an explicit, prompt-free model-list check on operator request."""
        with self._lock:
            return self._preflight(live=True)

    def review_release(self) -> dict[str, Any]:
        """Run an explicit local release-coverage check on operator request."""
        with self._lock:
            return self._review()


def html_page(token: str) -> bytes:
    """Render a dependency-free UI. Fleet text uses DOM APIs, not innerHTML."""
    page = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Agent Ledger Tower</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b1017;color:#d6e2ee;font:14px/1.45 system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid #243244;display:flex;gap:14px;align-items:center;flex-wrap:wrap}h1{font-size:18px;margin:0}.sub{color:#91a4b7;font-size:12px}.counts{margin-left:auto;color:#9db3c8;font:12px ui-monospace,Consolas,monospace}
main{max-width:1200px;margin:auto;padding:20px}.tabs{display:flex;gap:8px;border-bottom:1px solid #243244;margin-bottom:16px}.tabs button{border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent}.tabs button.active{border-color:#5db8f6;color:#dceeff}.panel{display:none}.panel.active{display:block}
button{background:#205b87;color:#fff;border:1px solid #3676a6;border-radius:7px;padding:8px 12px;font:inherit;cursor:pointer}button.secondary{background:#1b2938;color:#cbd5e1;border-color:#34485d}button.danger{background:#4a2024;border-color:#8f3b43}.tools{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
#feed{min-height:360px;border:1px solid #243244;background:#0e1621;border-radius:10px;padding:14px;overflow:auto}.msg{margin:11px 0;padding:10px 12px;border-radius:8px;white-space:pre-wrap;max-width:92%}.user{margin-left:auto;background:#1e3854}.system{background:#16212e}.model{background:#242037}.label{font-size:12px;font-weight:700;color:#89c8ff;margin-bottom:5px}.cite{font:12px ui-monospace,Consolas,monospace;color:#9db3c8;margin-top:8px}
form{display:flex;gap:9px;margin-top:14px}textarea{flex:1;min-height:54px;resize:vertical;background:#0e1621;color:#e5eef7;border:1px solid #31465d;border-radius:8px;padding:10px;font:inherit}
table{width:100%;border-collapse:collapse;background:#0e1621;border:1px solid #243244;border-radius:10px;overflow:hidden}th,td{text-align:left;padding:10px;border-bottom:1px solid #1a2734;vertical-align:top}th{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#91a4b7}.pill{padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700}.OK{background:#10321e;color:#5de18b}.FLAG{background:#35191c;color:#ff8b93}.KILLED{background:#24303d;color:#afbecd}.tail,.recent{font:12px ui-monospace,Consolas,monospace;color:#9db3c8}.note{color:#9db3c8;font-size:12px}.empty{padding:26px;text-align:center;color:#9db3c8;border:1px solid #243244;border-radius:10px}
</style></head><body><header><div><h1>Agent Ledger Tower</h1><div class="sub">Evidence-first chat · policy-gated actions · local-only control</div></div><div class="counts" id="counts">loading…</div></header><main>
<div class="tabs"><button class="active" data-tab="chat">Evidence chat</button><button data-tab="fleet">Fleet control</button><button data-tab="system">System</button></div>
<section class="panel active" id="chat"><div id="feed"></div><form id="form"><textarea id="input" placeholder="Ask about indexed sources, or use /help"></textarea><button>Send</button></form><div class="tools"><button class="secondary" data-chat="/help">Help</button><button class="secondary" data-chat="/status">Status</button><button class="secondary" data-chat="/verify">Verify chat log</button><button class="secondary" data-chat="/index">Refresh sources</button></div><p class="note">Chat is read-only. A model may propose text, but it cannot execute a tool here.</p></section>
<section class="panel" id="fleet"><div class="tools"><button id="launch">Launch demo fleet</button><button class="secondary" id="refresh">Refresh</button></div><p class="note">Launch is explicit. Kill and revive write local operator sentinels; the next agent launch honors them.</p><div id="fleetBody"></div></section>
<section class="panel" id="system"><div class="tools"><button class="secondary" id="reviewCheck">Check release review</button><button class="secondary" id="modelCheck">Check Gemini connection</button></div><pre id="systemBody" class="recent"></pre><p class="note">Release review reads only the local allowlist and review registry. The Gemini check calls a model-list endpoint only: no prompt, no generated text, and no displayed API key. This page is bound to 127.0.0.1 and POST actions require a per-process request token.</p></section>
</main><script>
const token=__TOKEN__, feed=document.getElementById('feed'), input=document.getElementById('input'); let latest=null;
function tab(name){document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===name));}
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
function add(label,text,kind,cites=[],block='',quality=null,evidence=null){const box=document.createElement('div');box.className='msg '+kind;const title=document.createElement('div');title.className='label';title.textContent=label;box.appendChild(title);const body=document.createElement('div');body.textContent=text;box.appendChild(body);if(cites.length){const c=document.createElement('div');c.className='cite';c.textContent='Sources: '+cites.join(' | ');box.appendChild(c)}if(quality){const c=document.createElement('div');c.className='cite';c.textContent='Response audit: '+quality.verdict+(quality.flags&&quality.flags.length?' — '+quality.flags.join(', '):'');box.appendChild(c)}if(evidence&&evidence.sha256){const c=document.createElement('div');c.className='cite';c.textContent='Evidence packet: '+evidence.sha256+' · local snapshot: '+(evidence.snapshot||'not saved');box.appendChild(c);if(['saved','existing'].includes(evidence.snapshot)){const b=document.createElement('button');b.className='secondary';b.textContent='View saved evidence';b.addEventListener('click',()=>send('/evidence '+evidence.sha256));box.appendChild(b)}}if(block){const c=document.createElement('div');c.className='cite';c.textContent='Chat ledger block: '+block;box.appendChild(c)}feed.appendChild(box);feed.scrollTop=feed.scrollHeight;}
async function post(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Tower-Token':token},body:payload?JSON.stringify(payload):undefined});const d=await r.json();if(!r.ok)throw new Error(d.error||'Local request failed');return d;}
async function send(message){if(!message.trim())return;add('You',message,'user');input.value='';try{const d=await post('/api/message',{message});add(d.mode||'response',d.text||d.error||'No response.','system',d.citations||[],d.ledger_block||'',d.quality||null,d.evidence||null);await refreshStatus();}catch(e){add('Local error',e.message,'system');}}
document.getElementById('form').addEventListener('submit',e=>{e.preventDefault();send(input.value)});input.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();send(input.value)}});document.querySelectorAll('[data-chat]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.chat)));
function cell(row,text,klass=''){const td=document.createElement('td');td.className=klass;td.textContent=text;row.appendChild(td);return td;}
function renderFleet(report){const host=document.getElementById('fleetBody');host.replaceChildren();if(!report.agents.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='No fleet exists yet. Use “Launch demo fleet” to create the deliberately mixed verification scenario.';host.appendChild(empty);return;}const table=document.createElement('table'),head=document.createElement('thead'),hr=document.createElement('tr');for(const name of ['Agent','Status','Detail','Verified tail','Recent actions','Control']){const th=document.createElement('th');th.textContent=name;hr.appendChild(th)}head.appendChild(hr);table.appendChild(head);const body=document.createElement('tbody');for(const agent of report.agents){const row=document.createElement('tr');cell(row,agent.id);const status=cell(row,'');const pill=document.createElement('span');pill.className='pill '+agent.status;pill.textContent=agent.status;status.appendChild(pill);cell(row,agent.detail);cell(row,agent.tail?agent.tail+'…':'','tail');cell(row,agent.recent.map(x=>x.tool+':'+x.decision+(x.boundary?' @'+x.boundary:'')).join(' · '),'recent');const control=document.createElement('td'),button=document.createElement('button');button.textContent=agent.status==='KILLED'?'Revive':'Kill';button.className=agent.status==='KILLED'?'secondary':'danger';button.addEventListener('click',async()=>{try{await post('/api/fleet/'+(agent.status==='KILLED'?'clear':'kill')+'?agent='+encodeURIComponent(agent.id));await refreshStatus();}catch(e){alert(e.message)}});control.appendChild(button);row.appendChild(control);body.appendChild(row)}table.appendChild(body);host.appendChild(table);}
function renderSystem(){if(!latest)return;const f=latest.fleet;document.getElementById('systemBody').textContent=JSON.stringify({chat:latest.chat,review:latest.review||null,model:latest.model,fleet:{clear:f.clear,flagged:f.flagged,killed:f.killed}},null,2);}
async function refreshStatus(){try{latest=await fetch('/api/status').then(r=>r.json());const f=latest.fleet;document.getElementById('counts').textContent=f.clear+' clear · '+f.flagged+' flagged · '+f.killed+' killed';renderFleet(f);renderSystem();}catch(e){document.getElementById('counts').textContent='status unavailable';}}
document.getElementById('launch').addEventListener('click',async()=>{try{await post('/api/fleet/launch');await refreshStatus()}catch(e){alert(e.message)}});document.getElementById('refresh').addEventListener('click',refreshStatus);add('System','Type /help for chat commands. Fleet launch is explicit. Ctrl+Enter sends.','system');refreshStatus();setInterval(refreshStatus,1500);
document.getElementById('reviewCheck').addEventListener('click',async()=>{try{latest.review=await post('/api/review');renderSystem();}catch(e){alert(e.message)}});
document.getElementById('modelCheck').addEventListener('click',async()=>{try{latest.model=await post('/api/model/preflight');renderSystem();}catch(e){alert(e.message)}});
</script></body></html>"""
    return page.replace("__TOKEN__", json.dumps(token)).encode("utf-8")


class TowerHandler(BaseHTTPRequestHandler):
    service: TowerService
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

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Tower-Token", ""), self.token)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(200, html_page(self.token), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send(200, self.service.status())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(403, {"error": "local request token required"})
            return
        url = urlparse(self.path)
        try:
            if url.path == "/api/message":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_MESSAGE_CHARS + 128:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length))
                self._send(200, self.service.respond(payload.get("message")))
            elif url.path in {"/api/fleet/kill", "/api/fleet/clear"}:
                agent = (parse_qs(url.query).get("agent") or [""])[0]
                action = "kill" if url.path.endswith("/kill") else "clear"
                self._send(200, {"ok": True, "fleet": self.service.fleet_action(action, agent)})
            elif url.path == "/api/fleet/launch":
                self._send(200, {"ok": True, "fleet": self.service.fleet_action("launch")})
            elif url.path == "/api/model/preflight":
                self._send(200, self.service.model_preflight())
            elif url.path == "/api/review":
                self._send(200, self.service.review_release())
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception:
            self._send(500, {"error": "local tower request failed"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified local evidence chat and fleet control tower")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--db", default=str(HERE / "tower_memory.sqlite3"))
    parser.add_argument("--ledger", default=str(HERE / "tower_ledger.jsonl"))
    parser.add_argument("--source", action="append", default=[], help="Folder to index; may be specified more than once")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sources = args.source or [str(HERE)]
    service = TowerService(args.db, args.ledger, sources)
    stats = service.index_sources()
    TowerHandler.service = service
    TowerHandler.token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), TowerHandler)
    print(f"unified tower -> http://127.0.0.1:{args.port}")
    print("indexed:", json.dumps(stats, sort_keys=True))
    print("fleet: starts only after an explicit Launch demo fleet action")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
