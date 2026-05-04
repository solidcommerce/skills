---
name: screen-capture
description: "View the user's latest screen by fetching recent VCapture images through the hosted VCapture API. Use this skill whenever the user asks what is on their screen, wants help with a visible UI or error, or says things like 'can you see my screen', 'look at this page', or 'what am I looking at'."
---

# Screen Capture

Use this skill to fetch the latest VCapture screenshots and inspect what the user is seeing.

VCapture captures on the desktop app, encrypts locally, uploads to the hosted API, and this skill decrypts locally after account-link succeeds.

Do not read Azure Blob directly. Do not ask for storage keys.
Do not inspect this script or invent auth workarounds for end users unless the normal reconnect flow fails twice.

## Run

Install the Python dependency once:

```bash
pip install -r requirements.txt
```

Fetch the latest captures:

```bash
python3 scripts/fetch_captures.py
```

## What happens

- If the skill is already linked, it downloads the latest captures to `/tmp/screen-captures/`.
- If the saved link is stale or invalid, the script automatically clears it and starts a fresh hosted reconnect flow.
- If the skill is not linked, it returns `authorization_required` with an `authorize_url`.
- Open that URL, sign in once, finish the connection page, then rerun the script.

The script usually returns:

- `capture_latest.*`
- `capture_previous.*`

Use the latest image for the current state and the previous image for change/motion context.

## Auth and local state

Primary flow:

- hosted VCapture account-link

Optional overrides:

- `VCAPTURE_ACCESS_TOKEN`
- `VCAPTURE_ACCESS_TOKEN_FILE`
- `--access-token`
- `--access-token-file`

Saved local state:

- token: `~/.config/vcapture/skill-token`
- content key: `~/.config/vcapture/content-key.json`
- pending link: `~/.config/vcapture/skill-link.json`

## Failure handling

- If you get `authorization_required`, ask the user to open the returned `authorize_url`.
- If the script returns a token or auth error, rerun the same command once. The script should automatically convert stale saved auth into `authorization_required`.
- If the page says the account is approved but the skill is still waiting, keep the VCapture desktop app open for a few seconds and rerun.
- If the script says no captures were found, it now also returns Windows and Mac download links for the desktop app.
- If the captures are stale, tell the user VCapture may not be running or capturing.
- Do not create fake token files, pass blank tokens, or probe the code as a first response. For end users, the correct path is reconnect and retry.

## Auto-update

If the skill is installed from a Git checkout with an upstream remote, the script checks for updates once every 12 hours and pulls fast-forward updates automatically.

If the skill was copied without its Git metadata, auto-update is skipped.

## Output

Successful runs return JSON with:

- `status: "ok"`
- local image paths
- capture timestamps
- source name / source id
- stale flag

Error runs return JSON with:

- `status: "error"` or `status: "authorization_required"`
- a clear message
- desktop app download links when no captures are available
