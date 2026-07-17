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

## 3. Preflight the key and model before generating anything
```powershell
# On this machine; otherwise use the folder that contains this release.
cd "C:\RegimeOS\release\agent-ledger-tower-v5"
$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
& $py gemini_preflight.py
& $py gemini_preflight.py --live
```
The first command performs no network request. The second calls Google's model-list
endpoint only: it does not send a prompt, consume generation output, or print your key.
It must report `"status": "ready"` before you run the agent or the human benchmark.

If `py -3.13` works on your machine, you can use it instead of `$py`. The package
also falls back to this Python 3.13 location in its PowerShell launchers.

On Windows, Python first uses its normal certificate-verifying HTTPS context. If
and only if Python rejects a local CA because its Basic Constraints extension is
not marked critical while Windows trusts it, the package retries through
`windows_native_http.ps1`. That helper uses Windows' native certificate verifier,
accepts only the Gemini HTTPS host and `/v1beta/models` path, disables redirects,
reads request JSON from standard input, and receives the key only through the
child-process environment. It does not disable TLS or expose the key in command
arguments.

## 4. Run the agent
```powershell
& $py agent_loop.py
```
The default is `gemini-3.1-flash-lite`, verified against the live model catalog
and a harmless generation fixture on 2026-07-16. Set `GEMINI_MODEL`, `AGENT_MODEL`,
or `CHAT_MODEL` only when you intentionally need a different model.

If it prints `LIVE Gemini -> ...`, real Gemini drove the run and every action it took was
recorded in the tamper-evident ledger. Then cross-check the trace in C#:
```powershell
dotnet run --project xrt_verify -- agent_loop_ledger.jsonl
```

## If you get a certificate / SSL error
Your network may inspect encrypted traffic, so Python may not trust the connection. Safe fixes:
- The package first imports the Windows trusted-root store into Python's normal
  certificate-verifying context. If your network root is already trusted by Windows,
  rerun `gemini_preflight.py --live` after updating this package.
- If your network administrator provides a correctly issued PEM root certificate, point Python
  at it with `setx SSL_CERT_FILE "C:\path\to\your-corp-root.pem"` (new window after), **or**
- Run it from a normal network (home wifi / phone hotspot).

If the error mentions `Basic Constraints of CA cert not marked critical`, the
Windows-native compatibility path should be attempted automatically. If it also
fails, update or reinstall that security/network certificate with its
administrator, or use a normal trusted network.

There is intentionally no TLS-bypass setting in this package. Do not disable certificate
verification to make an API call succeed: doing so exposes your Gemini key and model traffic.

## Security
- The key lives in your Windows profile, never in a `.py` file or the README.
- If a key is ever exposed anywhere shared, **rotate it in AI Studio immediately** — exposed keys are burned.
- Read-only evidence chat saves the exact retrieved source packet locally before a
  model request. Those `evidence_packets/` files are Git-ignored and contain no
  API key, user question, or model output, but they can contain excerpts from
  your selected source files. They are not encrypted by this package: keep them
  private, rely on your Windows account/disk encryption if needed, or delete
  them when no longer needed.
