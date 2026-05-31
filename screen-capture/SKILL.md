---
name: screen-capture
description: "View the user's latest screen by fetching recent VCapture images through the hosted VCapture API. Use this skill whenever the user asks what is on their screen, wants help with a visible UI or error, or says things like 'can you see my screen', 'look at this page', or 'what am I looking at'."
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

## Container Isolation

The skill stores bearer tokens, pending link secrets, and content keys in a private context directory. It no longer uses the legacy flat `~/.config/vcapture` path by default, because that path can be shared by multiple containers on the same host.

Default behavior:

- In containers, auth state goes under `$XDG_RUNTIME_DIR/vcapture-screen-capture/state/<context>` when available, otherwise `/tmp/vcapture-screen-capture-state/<context>`.
- Outside containers, auth state goes under `~/.config/vcapture/screen-capture/<context>`.
- Decrypted capture output goes under `/tmp/vcapture-screen-captures/<context>`.
- `<context>` is either the explicit context id or a hash derived from the OS user, home path, host/container identity, and Linux namespace ids.

For managed multi-user container infrastructure, set stable per-user or per-session values:

```bash
export VCAPTURE_CONTEXT_ID="$TENANT_OR_SESSION_ID"
export VCAPTURE_STATE_DIR="/private/vcapture/state/$TENANT_OR_SESSION_ID"
export VCAPTURE_OUTPUT_DIR="/private/vcapture/output/$TENANT_OR_SESSION_ID"
```

Use `VCAPTURE_STATE_ROOT` and `VCAPTURE_OUTPUT_ROOT` if the script should append the context id automatically. `AVCAPTURE_*` aliases are also accepted.

Never mount the same state or output directory into multiple user containers. Legacy files in `~/.config/vcapture/skill-token`, `content-key.json`, and `skill-link.json` are intentionally not migrated; revoke/delete them before relinking users.

## Auto-update

If installed from a Git checkout with an upstream remote, the script self-updates fast-forward at most every 12 hours outside containers. Skipped silently otherwise.

In managed containers, update the skill during image build or deployment. Set `VCAPTURE_SKILL_AUTO_UPDATE=1` only when each container has a private writable skill checkout.
