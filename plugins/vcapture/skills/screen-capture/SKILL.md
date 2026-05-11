---
description: View the user's latest screen by fetching recent VCapture images through the hosted VCapture API. Use this when the user asks what is on their screen, wants help with a visible UI or error, or says things like 'can you see my screen' or 'look at this page'.
---

# Screen Capture

Fetch the latest VCapture screenshots so you can inspect what the user is seeing.

VCapture captures on the desktop, encrypts locally, uploads to the hosted API, and this skill decrypts after account-link succeeds. Do not ask for storage keys, fabricate tokens, or probe internals — the reconnect flow is the only correct path.

## Run

One-time install:

```bash
pip install -q -r "${CLAUDE_SKILL_DIR}/requirements.txt"
```

Fetch the latest captures:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/fetch_captures.py"
```

The script prints JSON. On success (`status: "ok"`), use the **Read** tool on each `path` in the `captures` array to view the images. Use `capture_latest` for current state and `capture_previous` for change/motion context.

> If running outside Claude Code (e.g., on Codex), `cd` into the skill directory first, then run `pip install -q -r requirements.txt` and `python3 scripts/fetch_captures.py`.

## Outcomes

- `status: "ok"` — Read the image paths and answer the user.
- `status: "authorization_required"` — give the user the `authorize_url` to approve, then rerun.
- `status: "error"` with no captures — VCapture may not be installed or running. The JSON includes desktop-app download links; share those.
- `stale: true` — VCapture is linked but not capturing recent frames. Tell the user to check the desktop app.
- Token / auth error — rerun once. The script auto-clears stale auth and falls back to `authorization_required`.

## Auto-update

If installed from a Git checkout with an upstream remote, the script self-updates fast-forward at most every 12 hours. Skipped silently otherwise.
