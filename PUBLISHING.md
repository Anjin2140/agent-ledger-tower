# Publishing Handoff

This file describes the manual step from a locally verified package to a public
repository. The package does not authenticate, commit, or push automatically.

## Before publishing

Run the local proof from this directory:

```powershell
powershell -ExecutionPolicy Bypass -File run_all.ps1 -BuildSandbox
```

Treat a nonzero result as a failed release. Confirm that the release review and
hygiene checks report 70/70 files and that no runtime artifacts, credentials, or
historical archive files are in the staged set.

## Authenticate without putting a key in source

Use the GitHub CLI's browser flow:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth status
```

Do not put a GitHub token, Gemini key, `.env` file, ledger, anchor, SQLite
database, or generated workspace into this repository.

## Choose the destination carefully

The existing `Anjin2140/agent-ledger-tower` repository contains an earlier
prototype. Do not overwrite it by accident. The safer path is to create a new
repository for this reviewed package, such as `agent-ledger-tower-v5`, and then
add its URL as `origin`:

```powershell
git remote add origin https://github.com/Anjin2140/agent-ledger-tower-v5.git
git remote -v
```

If the existing repository is intentionally selected instead, stop and confirm
the branch and history before adding a remote or pushing.

## Commit and push deliberately

The local package is already staged. Inspect it before committing:

```powershell
git status --short
git diff --cached --check
git diff --cached --stat
git commit -m "Publish verifiable agent control tower prototype"
git push -u origin main
```

These commands are intentionally not run by the package or its verification
script. A human must decide that the destination and staged contents are right.

## Verify hosted evidence

After the push, inspect the first workflow run and wait for it to finish:

```powershell
gh run list --limit 5
gh run watch <RUN_ID> --exit-status
```

Only after a successful hosted run should the project claim hosted CI coverage.
The local proof remains a reference implementation and does not establish a
production security boundary, factuality guarantee, or tamper-proof ledger.
