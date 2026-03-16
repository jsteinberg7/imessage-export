"""Generate styled HTML export that looks like iMessage."""
import html as html_mod
import os
from datetime import datetime
from typing import Optional

from .messages import apple_ts_to_dt

COLORS = [
    "#34C759", "#FF9500", "#AF52DE", "#FF3B30", "#5AC8FA",
    "#FF2D55", "#FFCC00", "#64D2FF", "#30B0C7", "#A2845E",
    "#FF6482", "#BF5AF2", "#32D74B", "#FF9F0A", "#007AFF",
]


def _assign_colors(contacts: dict) -> dict:
    """Assign consistent colors to contacts."""
    color_map = {}
    for i, handle in enumerate(sorted(contacts.keys())):
        color_map[handle] = COLORS[i % len(COLORS)]
    return color_map


def generate_html(messages: list, att_map: dict, contacts: dict,
                  media_results: dict, chat_name: str,
                  your_name: str = "You",
                  reactions: dict = None) -> str:
    """Generate the full HTML export.
    
    Args:
        messages: list of message dicts from get_messages()
        att_map: {msg_rowid: [{transfer_name, ...}]} from get_attachments()
        contacts: {phone: name} mapping
        media_results: {msg_rowid: [{filename, is_video, success, transfer_name}]}
        chat_name: display name of the chat
        your_name: name to use for "is_from_me" messages
        reactions: {parent_guid: [{emoji, handle, is_from_me}]} from get_reactions()
    """
    if reactions is None:
        reactions = {}
    color_map = _assign_colors(contacts)
    bubbles = []
    last_date = None
    
    # Determine date range
    dates = [apple_ts_to_dt(m["date"]) for m in messages if m.get("date")]
    dates = [d for d in dates if d]
    date_range = ""
    if dates:
        first, last = min(dates), max(dates)
        if first.year == last.year and first.month == last.month:
            date_range = first.strftime("%B %Y")
        elif first.year == last.year:
            date_range = f"{first.strftime('%B')}–{last.strftime('%B %Y')}"
        else:
            date_range = f"{first.strftime('%B %Y')}–{last.strftime('%B %Y')}"

    for msg in messages:
        dt = apple_ts_to_dt(msg["date"])
        if not dt:
            continue

        date_str = dt.strftime("%B %d, %Y")
        if date_str != last_date:
            bubbles.append(f'<div class="date-sep">{date_str}</div>')
            last_date = date_str

        is_me = msg["is_from_me"]
        handle = msg["handle_id"] or ""
        sender = your_name if is_me else contacts.get(handle, handle)
        text = msg["text"] or ""
        time_str = dt.strftime("%-I:%M %p")

        # Skip standalone reaction messages — they're shown as badges on parent
        if msg.get("associated_message_type") and msg["associated_message_type"] != 0:
            continue

        # Group title changes
        if msg["item_type"] == 1 and msg.get("group_title"):
            bubbles.append(
                f'<div class="system">Group name changed to '
                f'"{html_mod.escape(msg["group_title"])}"</div>'
            )
            continue
        if msg["item_type"] != 0 and not text:
            continue

        # Media
        media_html = ""
        msg_media = media_results.get(msg["ROWID"], [])
        for m in msg_media:
            if m["success"]:
                if m["is_video"]:
                    media_html += (
                        f'<video controls class="media">'
                        f'<source src="media/{html_mod.escape(m["filename"])}" type="video/mp4">'
                        f'</video>'
                    )
                else:
                    media_html += (
                        f'<a href="media/{html_mod.escape(m["filename"])}" target="_blank">'
                        f'<img class="media" src="media/{html_mod.escape(m["filename"])}" loading="lazy">'
                        f'</a>'
                    )
            else:
                media_html += (
                    f'<div class="missing">📎 {html_mod.escape(m["transfer_name"])} '
                    f'(unavailable)</div>'
                )

        if not text and not media_html:
            continue

        # Build reaction badges for this message
        msg_guid = msg.get("guid", "")
        msg_reactions = reactions.get(msg_guid, [])
        reaction_html = ""
        if msg_reactions:
            # Group by emoji and count
            emoji_counts = {}
            for r in msg_reactions:
                e = r["emoji"]
                if e not in emoji_counts:
                    emoji_counts[e] = []
                name = your_name if r["is_from_me"] else contacts.get(r["handle"], r["handle"])
                emoji_counts[e].append(name)
            badges = []
            for emoji, names in emoji_counts.items():
                tooltip = ", ".join(names)
                count = f" {len(names)}" if len(names) > 1 else ""
                badges.append(f'<span class="reaction-badge" data-who="{html_mod.escape(tooltip)}">{emoji}{count}</span>')
            reaction_html = f'<div class="reaction-bar">{"".join(badges)}</div>'

        side = "right" if is_me else "left"
        bg = "#007AFF" if is_me else "#E9E9EB"
        fg = "white" if is_me else "black"
        name_color = "#007AFF" if is_me else color_map.get(handle, "#8E8E93")
        text_html = html_mod.escape(text).replace("\n", "<br>") if text else ""

        bubble = f'''<div class="msg {side}">
            <div class="sender" style="color:{name_color}">{html_mod.escape(sender)}</div>
            <div class="bubble" style="background:{bg};color:{fg}">
                {media_html}
                {f'<div class="text">{text_html}</div>' if text_html else ''}
            </div>
            {reaction_html}
            <div class="time">{time_str}</div>
        </div>'''
        bubbles.append(bubble)

    escaped_name = html_mod.escape(chat_name)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escaped_name}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif;
       background: #fff; max-width: 800px; margin: 0 auto; padding: 20px; }}
h1 {{ text-align: center; font-size: 1.4em; color: #333; margin: 20px 0; }}
.subtitle {{ text-align: center; color: #8E8E93; font-size: 0.85em; margin-bottom: 30px; }}
.date-sep {{ text-align: center; color: #8E8E93; font-size: 0.8em; margin: 25px 0 15px;
             font-weight: 600; }}
.system {{ text-align: center; color: #8E8E93; font-size: 0.8em; font-style: italic;
           margin: 10px 0; }}
.msg {{ margin: 4px 0; display: flex; flex-direction: column; }}
.msg.right {{ align-items: flex-end; }}
.msg.left {{ align-items: flex-start; }}
.sender {{ font-size: 0.75em; font-weight: 600; margin: 8px 8px 2px; }}
.bubble {{ max-width: 70%; padding: 8px 12px; border-radius: 18px; word-wrap: break-word; }}
.msg.right .bubble {{ border-bottom-right-radius: 4px; }}
.msg.left .bubble {{ border-bottom-left-radius: 4px; }}
.text {{ font-size: 0.95em; line-height: 1.4; }}
.time {{ font-size: 0.65em; color: #8E8E93; margin: 1px 8px 0; }}
.media {{ max-width: 100%; max-height: 400px; border-radius: 12px; margin: 4px 0;
          display: block; }}
video.media {{ max-width: 100%; border-radius: 12px; }}
.missing {{ font-size: 0.8em; color: #8E8E93; font-style: italic; padding: 4px 0; }}
.reaction-bar {{ display: flex; gap: 2px; margin-top: -6px; margin-bottom: 2px; padding-left: 12px; }}
.msg.right .reaction-bar {{ justify-content: flex-end; padding-right: 12px; padding-left: 0; }}
.reaction-badge {{ background: #F0F0F0; border: 1px solid #E0E0E0; border-radius: 12px;
                   padding: 1px 6px; font-size: 0.75em; cursor: default;
                   box-shadow: 0 1px 2px rgba(0,0,0,0.1); position: relative; }}
.reaction-badge:hover::after {{ content: attr(data-who); position: absolute; bottom: 100%;
                                left: 50%; transform: translateX(-50%); background: #333;
                                color: white; padding: 4px 8px; border-radius: 6px;
                                font-size: 0.85em; white-space: nowrap; z-index: 10;
                                margin-bottom: 4px; }}
</style>
</head>
<body>
<h1>💬 {escaped_name}</h1>
<div class="subtitle">{len(messages)} messages{f" · {date_range}" if date_range else ""} · Exported {datetime.now().strftime("%B %d, %Y")}</div>
{"".join(bubbles)}
</body>
</html>'''
