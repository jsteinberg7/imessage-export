"""Query iMessage chat.db for chats and messages."""
import sqlite3
import os
from datetime import datetime
from typing import Optional

MESSAGES_DB = os.path.expanduser("~/Library/Messages/chat.db")
APPLE_EPOCH = 978307200


def apple_ts_to_dt(ts: int) -> Optional[datetime]:
    """Convert Apple timestamp to datetime."""
    if not ts:
        return None
    if ts > 1e15:
        ts = ts / 1e9
    elif ts > 1e12:
        ts = ts / 1e6
    return datetime.fromtimestamp(ts + APPLE_EPOCH)


def extract_attributed_text(blob: bytes) -> str:
    """Extract plain text from NSAttributedString streamtyped binary.
    
    The binary format stores text after an NSString marker:
    ... NSString <flags> 0x2b <length> <utf8-text> ...
    
    Length encoding:
    - 0x81 NN: 1-byte length (NN)
    - 0x82 HH LL: 2-byte big-endian length
    - 0x83 HH MM LL: 3-byte length
    - <0x80: literal length value
    """
    if not blob:
        return ""
    data = bytes(blob)
    for marker in [b'NSString', b'NSMutableString']:
        idx = data.find(marker)
        if idx == -1:
            continue
        search_start = idx + len(marker)
        plus_idx = data.find(b'\x2b', search_start)
        if plus_idx == -1 or plus_idx > search_start + 10:
            continue
        pos = plus_idx + 1
        if pos >= len(data):
            continue
        first = data[pos]
        if first == 0x81:
            if pos + 2 >= len(data): continue
            length = data[pos + 1]
            pos += 3  # skip 0x81 + length byte + 0x00 padding
        elif first == 0x82:
            if pos + 3 >= len(data): continue
            length = (data[pos + 1] << 8) | data[pos + 2]
            pos += 4  # skip 0x82 + 2 length bytes + 0x00 padding
        elif first == 0x83:
            if pos + 4 >= len(data): continue
            length = (data[pos + 1] << 16) | (data[pos + 2] << 8) | data[pos + 3]
            pos += 5  # skip 0x83 + 3 length bytes + 0x00 padding
        elif first < 0x80:
            length = first
            pos += 1  # no padding for single-byte lengths
        else:
            continue
        if pos + length > len(data):
            length = len(data) - pos
        try:
            text = data[pos:pos + length].decode('utf-8').rstrip('\x00')
            return text
        except Exception:
            continue
    return ""


def find_chat(name: str, db_path: str = MESSAGES_DB) -> Optional[dict]:
    """Find a chat by display name. Returns dict with ROWID, guid, display_name, participant_count."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Search by display_name (case-insensitive partial match)
    rows = conn.execute("""
        SELECT c.ROWID, c.guid, c.display_name, c.chat_identifier,
               COUNT(DISTINCT ch.handle_id) as participant_count
        FROM chat c
        LEFT JOIN chat_handle_join ch ON ch.chat_id = c.ROWID
        WHERE c.display_name LIKE ?
        GROUP BY c.ROWID
        ORDER BY participant_count DESC
    """, (f"%{name}%",)).fetchall()
    conn.close()
    if not rows:
        return None
    # Prefer exact match, then largest group
    for row in rows:
        if row["display_name"] and row["display_name"].lower() == name.lower():
            return dict(row)
    return dict(rows[0])


def list_chats(db_path: str = MESSAGES_DB, min_participants: int = 0) -> list:
    """List all chats, optionally filtering by minimum participants."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT c.ROWID, c.guid, c.display_name, c.chat_identifier,
               COUNT(DISTINCT ch.handle_id) as participant_count
        FROM chat c
        LEFT JOIN chat_handle_join ch ON ch.chat_id = c.ROWID
        GROUP BY c.ROWID
        HAVING participant_count >= ?
        ORDER BY c.display_name
    """, (min_participants,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_messages(chat_rowid: int, db_path: str = MESSAGES_DB) -> list:
    """Get all messages for a chat with handle info and attributedBody."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    messages = conn.execute("""
        SELECT m.ROWID, m.guid, m.text, m.date, m.is_from_me, m.item_type,
               m.associated_message_type, m.group_title,
               m.attributedBody,
               h.id as handle_id
        FROM chat_message_join cmj
        JOIN message m ON m.ROWID = cmj.message_id
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
        ORDER BY m.date ASC
    """, (chat_rowid,)).fetchall()
    result = []
    for msg in messages:
        d = dict(msg)
        # Extract text from attributedBody if text is missing
        if not d["text"] and d["attributedBody"]:
            d["text"] = extract_attributed_text(d["attributedBody"])
        result.append(d)
    conn.close()
    return result


def get_attachments(chat_rowid: int, db_path: str = MESSAGES_DB) -> dict:
    """Get attachments grouped by message ROWID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT maj.message_id, a.filename, a.mime_type, a.transfer_name
        FROM chat_message_join cmj
        JOIN message m ON m.ROWID = cmj.message_id
        JOIN message_attachment_join maj ON maj.message_id = m.ROWID
        JOIN attachment a ON a.ROWID = maj.attachment_id
        WHERE cmj.chat_id = ?
    """, (chat_rowid,)).fetchall()
    conn.close()
    att_map = {}
    for r in rows:
        mid = r["message_id"]
        if mid not in att_map:
            att_map[mid] = []
        att_map[mid].append(dict(r))
    return att_map


REACTION_EMOJI = {
    2000: "❤️",   # Loved
    2001: "👍",   # Liked
    2002: "👎",   # Disliked
    2003: "😂",   # Laughed
    2004: "‼️",   # Emphasized
    2005: "❓",   # Questioned
    # 3000+ are removal of reactions — ignore
}


def get_reactions(chat_rowid: int, db_path: str = MESSAGES_DB) -> dict:
    """Get reactions grouped by parent message GUID.
    
    Returns: {parent_guid: [{emoji, sender_handle, is_from_me}]}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.associated_message_guid, m.associated_message_type,
               m.is_from_me, h.id as handle_id
        FROM chat_message_join cmj
        JOIN message m ON m.ROWID = cmj.message_id
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
          AND m.associated_message_type IS NOT NULL
          AND m.associated_message_type >= 2000
          AND m.associated_message_type < 3000
    """, (chat_rowid,)).fetchall()
    conn.close()

    reactions = {}
    for r in rows:
        guid_raw = r["associated_message_guid"] or ""
        # Strip "p:X/" prefix to get the actual message guid
        if "/" in guid_raw:
            parent_guid = guid_raw.split("/", 1)[1]
        else:
            parent_guid = guid_raw
        
        emoji = REACTION_EMOJI.get(r["associated_message_type"], "")
        if not emoji:
            continue

        if parent_guid not in reactions:
            reactions[parent_guid] = []
        reactions[parent_guid].append({
            "emoji": emoji,
            "handle": r["handle_id"] or "",
            "is_from_me": r["is_from_me"],
        })
    return reactions


def get_handles(chat_rowid: int, db_path: str = MESSAGES_DB) -> list:
    """Get all unique phone numbers/handles in a chat."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT DISTINCT h.id
        FROM chat_message_join cmj
        JOIN message m ON m.ROWID = cmj.message_id
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
        ORDER BY h.id
    """, (chat_rowid,)).fetchall()
    conn.close()
    return [r[0] for r in rows]
