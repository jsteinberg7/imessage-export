"""Resolve phone numbers to contact names via macOS Contacts or BlueBubbles."""
import subprocess
import json
import os
from typing import Optional


def resolve_via_contacts_framework(handles: list) -> dict:
    """Resolve phone numbers using macOS Contacts via AppleScript."""
    result = {}
    # Batch resolve via a single AppleScript call
    handle_list = ", ".join(f'"{h}"' for h in handles)
    script = f'''
    set handleList to {{{handle_list}}}
    set output to ""
    tell application "Contacts"
        repeat with h in handleList
            set matchedName to ""
            try
                set matchedPeople to (every person whose value of phones contains h)
                if (count of matchedPeople) > 0 then
                    set matchedName to name of item 1 of matchedPeople
                end if
            end try
            set output to output & h & "|" & matchedName & linefeed
        end repeat
    end tell
    return output
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                if "|" in line:
                    phone, name = line.split("|", 1)
                    if name.strip():
                        result[phone.strip()] = name.strip()
    except Exception:
        pass
    return result


def resolve_via_bluebubbles(handles: list, server_url: str = None,
                            password: str = None) -> dict:
    """Resolve phone numbers via BlueBubbles REST API."""
    if not server_url or not password:
        # Try to read from OpenClaw config
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    config = json.load(f)
                bb = config.get("channels", {}).get("bluebubbles", {})
                server_url = server_url or bb.get("serverUrl")
                password = password or bb.get("password")
            except Exception:
                pass
    
    if not server_url or not password:
        return {}

    try:
        import urllib.request
        url = f"{server_url}/api/v1/contact?password={password}&limit=500"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        
        # Normalize phone numbers for matching
        lookup = {}
        for contact in data.get("data", []):
            name = contact.get("displayName", "")
            if not name:
                continue
            for phone in contact.get("phoneNumbers", []):
                addr = phone.get("address", "").replace(" ", "").replace("-", "")
                addr = addr.replace("(", "").replace(")", "")
                if not addr.startswith("+"):
                    if len(addr) == 10:
                        addr = "+1" + addr
                    elif len(addr) == 11 and addr.startswith("1"):
                        addr = "+" + addr
                lookup[addr] = name

        result = {}
        for handle in handles:
            if handle in lookup:
                result[handle] = lookup[handle]
        return result
    except Exception:
        return {}


def resolve_contacts(handles: list, bb_url: str = None,
                     bb_password: str = None) -> dict:
    """Resolve phone numbers to names, trying multiple sources."""
    # Try BlueBubbles first (tends to have more contacts)
    contacts = resolve_via_bluebubbles(handles, bb_url, bb_password)
    
    # Fill gaps with macOS Contacts
    remaining = [h for h in handles if h not in contacts]
    if remaining:
        mac_contacts = resolve_via_contacts_framework(remaining)
        contacts.update(mac_contacts)
    
    return contacts
