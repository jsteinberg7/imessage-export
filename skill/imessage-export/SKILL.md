---
name: imessage-export
description: Export iMessage/SMS/MMS chats as styled HTML time capsules with media recovery. Use when the user wants to export, back up, or archive an iMessage conversation, group chat, or text thread — including photos, videos, and contact names.
---

# iMessage Export

Export any iMessage chat as a self-contained HTML page with inline media, styled like iMessage.

## Prerequisites

- macOS with Full Disk Access for the terminal/node process
- Python 3.9+ with the `imessage-export` CLI installed

## Setup

Check if installed:

```bash
imessage-export --version
```

If not installed:

```bash
pip install git+https://github.com/jsteinberg7/imessage-export.git
```

## Usage

Run the CLI directly via `exec`:

```bash
imessage-export "Chat Name" -o ./export-folder --your-name "UserName"
```

### Key flags

- `--your-name NAME` — display name for the user's sent messages (default: "You")
- `--no-media` — text-only export (fast, no media recovery)
- `--no-photos-export` — skip AppleScript Photos.app export (faster, but may miss videos)
- `--no-contacts` — skip contact name resolution
- `--bb-url URL --bb-password PASS` — use BlueBubbles for contact resolution
- `--format txt` — plain text instead of HTML

### Typical invocation

```bash
imessage-export "Family Chat" -o ~/Desktop/family-export --your-name "Jason" --bb-url http://localhost:1234
```

## How it works

1. Finds the chat in `~/Library/Messages/chat.db` by display name (partial match)
2. Extracts all messages including hidden text in `attributedBody` binary fields
3. Resolves phone numbers to contact names (via BlueBubbles or macOS Contacts)
4. Recovers media from 3 sources: Messages cache on disk, Photos.app originals (via AppleScript), Photos library derivatives
5. Converts HEIC → JPEG for browser compatibility
6. Generates styled HTML with chat bubbles, inline media, reaction badges, and date separators

## Troubleshooting

- **"authorization denied" on chat.db** — Full Disk Access not granted. Add the terminal app or `/opt/homebrew/bin/node` in System Settings → Privacy & Security → Full Disk Access, then restart.
- **Wrong photos matched** — The tool matches by filename + date proximity. If photos from a different trip have the same `IMG_XXXX` number, they may collide. The 90-day window helps but isn't perfect.
- **Videos not playing in HTML** — `.mov` files play natively in Safari. In Chrome, some QuickTime-only codecs may not play. Try opening in Safari.
- **Missing media** — MMS attachments stored in iCloud may expire. Download them manually in Messages.app before exporting.
