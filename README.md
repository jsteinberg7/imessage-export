# imessage-export

Export iMessage chats as styled HTML time capsules — complete with media, contact names, and iMessage-style chat bubbles.

![macOS only](https://img.shields.io/badge/platform-macOS-lightgrey)
![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## What it does

- Exports any iMessage/SMS/MMS group chat or 1:1 conversation
- Generates a styled HTML page that looks like the iMessage app
- **Three-tier media recovery**: pulls photos and videos from the Messages cache, Photos.app originals (via AppleScript), and Photos library derivatives
- Resolves phone numbers to contact names (via macOS Contacts or BlueBubbles)
- Handles the tricky `attributedBody` binary format for messages with missing text
- Outputs a self-contained folder you can open in any browser

## Requirements

- **macOS** (reads the iMessage database directly)
- **Python 3.9+**
- **Full Disk Access** for your terminal app (System Settings → Privacy & Security → Full Disk Access)
- Optional: [BlueBubbles](https://bluebubbles.app) for better contact resolution

## Install

```bash
pip install .
```

Or for development:

```bash
pip install -e .
```

## Usage

```bash
# Basic export
imessage-export "Family Chat"

# Specify output directory and your display name
imessage-export "Family Chat" -o ~/Desktop/family-export --your-name "Jason"

# Text-only export (skip media recovery)
imessage-export "Work Group" --format txt --no-media

# Skip the slow Photos.app video export
imessage-export "Trip Photos" --no-photos-export

# Use BlueBubbles for contact resolution
imessage-export "Friends" --bb-url http://localhost:1234 --bb-password yourpass
```

## How media recovery works

iMessage attachments can be tricky to recover, especially for MMS group chats where macOS stores files in temp directories that get cleaned up. This tool tries three sources:

1. **Direct disk path** — The path stored in `chat.db`. Works for recent messages and iMessage (not MMS).
2. **Photos.app export** — For photos/videos you sent, the originals are likely in your Photos library. The tool uses AppleScript to export originals from Photos.app, matching by filename and date to avoid wrong matches.
3. **Photos library derivatives** — Falls back to thumbnail/derivative versions stored in the Photos library on disk.

For best results:
- Open the chat in Messages.app and manually download any iCloud attachments before exporting
- Keep your Photos library accessible (don't have "Optimize Mac Storage" for best results, though the tool works around it)

## Permissions

The tool needs to read:
- `~/Library/Messages/chat.db` — the iMessage database
- `~/Pictures/Photos Library.photoslibrary/` — for media recovery
- Photos.app (via AppleScript) — for exporting video originals

Grant **Full Disk Access** to your terminal app in System Settings. You may need to restart your terminal after granting it.

## License

MIT
