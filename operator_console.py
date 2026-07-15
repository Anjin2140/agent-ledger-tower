#!/usr/bin/env python3
"""
operator_console.py — live control-tower console for the agent fleet.

Serves a localhost web page that shows every agent's status, re-verified from its
tamper-evident ledger on every refresh, and lets an operator KILL an agent or
relaunch the fleet. Stdlib only (http.server). Binds to 127.0.0.1, so the console
is never exposed on the network.

    python operator_console.py
    # then open http://127.0.0.1:8765 in a browser
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import fleet_tower
from agent_ledger import decode_record
from policy_gate import load_policy

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = fleet_tower.FLEET
POLICY_PATH = os.path.join(HERE, "default_policy.json")


def fleet_report():
    policy = load_policy(POLICY_PATH)
    agents = []
    if os.path.isdir(FLEET):
        for aid in sorted(os.listdir(FLEET)):
            ledger = os.path.join(FLEET, aid, "ledger.jsonl")
            notary = os.path.join(FLEET, aid, "notary.log")
            if not os.path.exists(ledger):
                continue
            killed = fleet_tower.is_killed(aid)
            r = fleet_tower.audit_agent(ledger, notary, policy)
            recent, tail = [], ""
            try:
                blocks = [json.loads(l) for l in open(ledger, encoding="utf-8") if l.strip()]
                tail = blocks[-1]["blockHash"][:12] if blocks else ""
                for b in blocks[-6:]:
                    rec = decode_record(bytes.fromhex(b["stateRcsHex"]))
                    recent.append({"step": rec["step"], "tool": rec["tool"],
                                   "decision": rec["decision"], "rule": rec["rule"],
                                   "status": rec["status"]})
            except Exception:
                pass
            if killed:
                status, detail = "KILLED", "grounded by operator"
            else:
                status = r["status"]
                detail = r["reason"] if r["status"] == "FLAG" else \
                    (str(r.get("n", "?")) + " actions" + ((", " + str(r["denied"]) + " denied-blocked") if r.get("denied") else ""))
            agents.append({"id": aid, "status": status, "detail": detail,
                           "killed": killed, "tail": tail, "recent": recent})
    return {"agents": agents,
            "clear": sum(1 for a in agents if a["status"] == "OK"),
            "flagged": sum(1 for a in agents if a["status"] == "FLAG"),
            "killed": sum(1 for a in agents if a["status"] == "KILLED")}


HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Fleet Control Tower</title>
<style>
 body{margin:0;background:#0b0f14;color:#cbd5e1;font:14px/1.5 ui-monospace,Consolas,monospace}
 header{padding:14px 20px;border-bottom:1px solid #1e2a38;display:flex;align-items:center;gap:18px}
 h1{font-size:16px;margin:0;letter-spacing:2px;color:#e2e8f0}
 .live{width:9px;height:9px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:p 1.5s infinite}
 @keyframes p{50%{opacity:.35}}
 .counts span{margin-right:14px}.g{color:#22c55e}.r{color:#ef4444}.k{color:#94a3b8}
 button{background:#152233;color:#cbd5e1;border:1px solid #2b3a4d;border-radius:6px;padding:5px 10px;cursor:pointer;font:inherit}
 button:hover{background:#1c2c40}
 .relaunch{margin-left:auto;border-color:#3b5573}
 table{width:100%;border-collapse:collapse}
 th,td{text-align:left;padding:10px 20px;border-bottom:1px solid #131c26;vertical-align:top}
 th{color:#64748b;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:1px}
 .pill{padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700}
 .OK{background:#0f2a1a;color:#4ade80}.FLAG{background:#2c1416;color:#f87171}.KILLED{background:#1c232c;color:#94a3b8}
 .tail{color:#5b7089;font-size:12px}
 .feed{color:#7c8ba0;font-size:12px}
 .feed .deny{color:#f87171}.feed .halt{color:#94a3b8}
 .kill{border-color:#5b2226;color:#f87171}
</style></head><body>
<header>
 <div class="live"></div><h1>FLEET CONTROL TOWER</h1>
 <div class="counts" id="counts"></div>
 <button class="relaunch" onclick="act('/api/launch')">Relaunch fleet</button>
</header>
<table><thead><tr><th>Agent</th><th>Status</th><th>Detail</th><th>Verified tail</th><th>Recent actions</th><th></th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
async function load(){
 const r = await fetch('/api/fleet'); const d = await r.json();
 document.getElementById('counts').innerHTML =
   '<span class="g">'+d.clear+' clear</span><span class="r">'+d.flagged+' flagged</span><span class="k">'+d.killed+' killed</span>';
 document.getElementById('rows').innerHTML = d.agents.map(a=>{
   const feed = a.recent.map(x=>{
     const cls = x.status==='denied'?'deny':(x.status==='halted'?'halt':'');
     return '<span class="'+cls+'">'+x.tool+':'+x.decision+'</span>';
   }).join(' &middot; ');
   const btn = a.status==='KILLED'
     ? '<button onclick="act(\'/api/clear?agent='+a.id+'\')">Revive</button>'
     : '<button class="kill" onclick="act(\'/api/kill?agent='+a.id+'\')">Kill</button>';
   return '<tr><td>'+a.id+'</td>'
     +'<td><span class="pill '+a.status+'">'+a.status+'</span></td>'
     +'<td>'+a.detail+'</td>'
     +'<td class="tail">'+(a.tail||'')+'…</td>'
     +'<td class="feed">'+feed+'</td>'
     +'<td>'+btn+'</td></tr>';
 }).join('');
}
async function act(url){ await fetch(url,{method:'POST'}); await load(); }
load(); setInterval(load, 1500);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif path == "/api/fleet":
            self._send(200, "application/json", json.dumps(fleet_report()).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        aid = (q.get("agent") or [""])[0]
        if u.path == "/api/kill" and aid:
            os.makedirs(os.path.join(FLEET, aid), exist_ok=True)
            with open(fleet_tower.kill_path(aid), "w", encoding="utf-8") as f:
                f.write("killed by operator")
            self._send(200, "application/json", b'{"ok":true}')
        elif u.path == "/api/clear" and aid:
            try:
                os.remove(fleet_tower.kill_path(aid))
            except OSError:
                pass
            self._send(200, "application/json", b'{"ok":true}')
        elif u.path == "/api/launch":
            fleet_tower.launch()
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"not found")


def main():
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    if not os.path.isdir(FLEET) or not os.listdir(FLEET):
        fleet_tower.launch()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("operator console -> http://127.0.0.1:%d   (Ctrl+C to stop)" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
