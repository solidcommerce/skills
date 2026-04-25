---
name: screen-capture
description: "View the user's screen by fetching recent screen captures from Azure Blob Storage. Use this skill whenever the user asks you to look at their screen, see what's happening, check a visual element, or references something visible on their display. Also trigger when the user mentions 'the error on screen', 'that dialog box', 'what I'm looking at', 'my screen', 'can you see', or any context where seeing the user's current screen state would help you assist them. This skill is your eyes — use it proactively whenever visual context would improve your response."
---

# Screen Capture Viewer

This skill lets you see what's on the user's screen by fetching the latest screen captures from Azure Blob Storage. A separate application (AVCapture) runs on the user's machine, capturing screenshots every ~3 seconds and uploading them as JPEGs.

## How it works

1. Run the fetch script to download the latest captures
2. Read the downloaded images to see what's on screen
3. Use what you see to help the user

## Step-by-step usage

### 1. Fetch the latest captures

Run the fetch script from this skill's directory:

```bash
python3 /data/azureuser-prod/.claude/skills/screen-capture/scripts/fetch_captures.py
```

The script will:
- Connect to Azure Blob Storage using the `AVCAPTURE_CONNECTION_STRING` environment variable
- If the env var is not set, it falls back to fetching the connection string from Key Vault (`coding-agent-keyvault`, secret `avcapture-blob-connection-string`)
- Download the 2 most recent captures to `/tmp/screen-captures/`
- Print a JSON summary with file paths, timestamps, and staleness info

### 2. Check the output

The script outputs JSON like this:
```json
{
  "status": "ok",
  "captures": [
    {"path": "/tmp/screen-captures/capture_latest.jpg", "timestamp": "2026-04-08T23:03:37Z", "age_seconds": 5},
    {"path": "/tmp/screen-captures/capture_previous.jpg", "timestamp": "2026-04-08T23:03:35Z", "age_seconds": 7}
  ],
  "stale": false
}
```

### 3. Handle staleness

- If `stale` is `true` (latest capture is older than 60 seconds), tell the user:
  > "The screen captures appear to be stale (last capture was X seconds ago). Please make sure AVCapture is running on your machine."
- If `status` is `"error"`, report the error message to the user.
- If `stale` is `false`, proceed to read the images.

### 4. View the captures

Use the Read tool to view each downloaded image:

```
Read /tmp/screen-captures/capture_latest.jpg
Read /tmp/screen-captures/capture_previous.jpg
```

The latest capture shows the current screen state. The previous capture (taken ~3 seconds earlier) provides context for any changes or animations.

### 5. Describe what you see

After viewing the images, describe what you observe and use it to help the user with their request. Be specific about UI elements, text, errors, or anything relevant to what they asked.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `AVCAPTURE_CONNECTION_STRING not set` and Key Vault fallback fails | No credentials available | Ask user to set `AVCAPTURE_CONNECTION_STRING` env var |
| `No captures found` | No images in blob storage | Ask user to verify AVCapture is running and capturing |
| `stale: true` | AVCapture stopped or paused | Ask user to start/resume AVCapture |
| Images look blank or corrupted | Capture issue on user's end | Ask user to check AVCapture settings |

## Important notes

- The captures are JPEG images from the user's screen — they may show any application, browser, terminal, or desktop
- There can be multiple capture sources (different windows/monitors) identified by folder names like `window_XXXXX_N`
- The script automatically picks the most recently active source
- Captures happen every ~3 seconds, so two consecutive captures show nearly the same moment in time
- Always fetch fresh captures rather than relying on previously downloaded ones — the screen changes constantly
