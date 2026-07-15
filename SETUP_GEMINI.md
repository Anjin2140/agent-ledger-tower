# Run the agent loop against real Gemini

Good news: the code now calls Gemini using only Python's built-in networking, so
**there is nothing to `pip install`** — the litellm/Rust build error no longer
applies. You need two things: a key, and to tell your machine about it.

Windows / PowerShell. The key never goes in code and never gets committed.

---

## 1. Get a Gemini API key
Go to **Google AI Studio** → sign in → **Create API key** → copy it. Treat it like a password.

## 2. Give your machine the key (privately)
In PowerShell (press Windows key, type `powershell`, Enter), paste this — replace only
the part in quotes with your key:
```powershell
setx GEMINI_API_KEY "paste-your-key-here"
```
Then **close that window and open a new PowerShell** (setx only takes effect in a fresh one).
The key is stored in your Windows user profile — not in any file in this project — and the
program reads it from there automatically.

## 3. Run it
```powershell
cd "C:\RegimeOS\Code\tools\agent_ledger_demo"
python agent_loop.py
```
If it prints `LIVE Gemini -> ...`, real Gemini drove the run and every action it took was
recorded in the tamper-evident ledger. Then cross-check the trace in C#:
```powershell
dotnet run --project xrt_verify -- agent_loop_ledger.jsonl
```

## If you get a certificate / SSL error
Your network inspects encrypted traffic, so Python may not trust the connection. Two safe fixes:
- Point Python at your network's root certificate:
  `setx SSL_CERT_FILE "C:\path\to\your-corp-root.pem"` (new window after), **or**
- Run it from a normal network (home wifi / phone hotspot).

There is a last-resort switch, `AGENT_INSECURE_TLS=1`, that turns verification off. It prints a
loud warning and **should never be used with your real key on an untrusted network** — anyone on
the path could read the key. Prefer one of the two fixes above.

## Security
- The key lives in your Windows profile, never in a `.py` file or the README.
- If a key is ever exposed anywhere shared, **rotate it in AI Studio immediately** — exposed keys are burned.
