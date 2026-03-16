"""CLI entry point for imessage-export."""
import click
import os
import shutil
import sys

from . import __version__


@click.command()
@click.argument("chat_name")
@click.option("--output", "-o", default=None, help="Output directory (default: ./<chat-name>-export)")
@click.option("--format", "fmt", type=click.Choice(["html", "txt"]), default="html", help="Export format")
@click.option("--your-name", default="You", help="Name to display for your messages")
@click.option("--no-media", is_flag=True, help="Skip media recovery (text only)")
@click.option("--no-contacts", is_flag=True, help="Skip contact name resolution")
@click.option("--no-photos-export", is_flag=True, help="Skip AppleScript Photos export (faster, may miss videos)")
@click.option("--bb-url", default=None, help="BlueBubbles server URL for contact resolution")
@click.option("--bb-password", default=None, help="BlueBubbles password")
@click.version_option(__version__)
def main(chat_name, output, fmt, your_name, no_media, no_contacts,
         no_photos_export, bb_url, bb_password):
    """Export an iMessage chat as a styled HTML time capsule.
    
    CHAT_NAME is the display name of the chat to export (partial match supported).
    
    Requires macOS with Full Disk Access granted to your terminal.
    """
    from .messages import find_chat, get_messages, get_attachments, get_handles, get_reactions
    from .contacts import resolve_contacts
    from .media import PhotosIndex, recover_attachment, batch_export_from_photos
    from .html_export import generate_html

    # Find the chat
    click.echo(f"🔍 Searching for chat: {chat_name}")
    chat = find_chat(chat_name)
    if not chat:
        click.echo(f"❌ No chat found matching '{chat_name}'", err=True)
        click.echo("Tip: Use --list to see available chats", err=True)
        sys.exit(1)

    click.echo(f"✅ Found: {chat['display_name'] or chat['chat_identifier']} "
               f"({chat['participant_count']} participants)")

    # Set up output directory
    if not output:
        safe_name = (chat["display_name"] or chat_name).replace(" ", "-").replace("'", "")
        output = f"./{safe_name}-export"
    media_dir = os.path.join(output, "media")
    if os.path.exists(media_dir):
        shutil.rmtree(media_dir)
    os.makedirs(media_dir, exist_ok=True)

    # Get messages
    click.echo("📨 Fetching messages...")
    messages = get_messages(chat["ROWID"])
    att_map = get_attachments(chat["ROWID"])
    total_atts = sum(len(v) for v in att_map.values())
    click.echo(f"   {len(messages)} messages, {total_atts} attachments")

    # Resolve contacts
    contacts = {}
    if not no_contacts:
        click.echo("👤 Resolving contacts...")
        handles = get_handles(chat["ROWID"])
        contacts = resolve_contacts(handles, bb_url, bb_password)
        resolved = sum(1 for h in handles if h in contacts)
        click.echo(f"   Resolved {resolved}/{len(handles)} contacts")

    # Recover media
    media_results = {}  # msg_rowid -> [{filename, is_video, success, transfer_name}]
    exported_media = {}  # stem -> path

    if not no_media and total_atts > 0:
        click.echo("📸 Building Photos library index...")
        photos_index = PhotosIndex()
        click.echo(f"   Indexed {len(photos_index.photos_map)} photo filenames")

        # Phase 1: Export videos from Photos.app (if enabled)
        if not no_photos_export:
            # Find which attachments are videos that need Photos export
            video_stems = set()
            video_dates = {}  # stem -> msg_date for date matching
            for msg in messages:
                for att in att_map.get(msg["ROWID"], []):
                    name = att.get("transfer_name", "")
                    if not name:
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if ext in {'.mov', '.mp4', '.m4v', '.avi'}:
                        stem = os.path.splitext(name)[0].upper()
                        video_stems.add(stem)
                        if stem not in video_dates:
                            video_dates[stem] = msg.get("date", 0)

            uuids = photos_index.find_uuids_for_stems(list(video_stems), video_dates)
            if uuids:
                click.echo(f"🎥 Exporting {len(uuids)} videos from Photos.app...")
                export_dir = os.path.join(output, ".photos_export")

                def progress(stem, i, total, success):
                    icon = "✓" if success else "✗"
                    click.echo(f"   [{i}/{total}] {stem} {icon}")

                results = batch_export_from_photos(uuids, export_dir, progress)
                for stem, path in results.items():
                    exported_media[stem] = path
                click.echo(f"   Exported {len(results)}/{len(uuids)} videos")

        # Phase 2: Recover all attachments
        click.echo("📎 Recovering attachments...")
        att_idx = 0
        stats = {"disk": 0, "exported": 0, "photos": 0, "failed": 0}

        for msg in messages:
            msg_atts = att_map.get(msg["ROWID"], [])
            if not msg_atts:
                continue
            media_results[msg["ROWID"]] = []
            for att in msg_atts:
                transfer_name = att.get("transfer_name") or "unknown"
                filename, is_video, success = recover_attachment(
                    transfer_name=transfer_name,
                    db_filename=att.get("filename"),
                    msg_date=msg.get("date", 0),
                    photos_index=photos_index,
                    exported_media=exported_media,
                    media_dir=media_dir,
                    att_idx=att_idx,
                )
                media_results[msg["ROWID"]].append({
                    "filename": filename,
                    "is_video": is_video,
                    "success": success,
                    "transfer_name": transfer_name,
                })
                if success:
                    stats["disk"] += 1  # simplified — actual source tracking is internal
                else:
                    stats["failed"] += 1
                att_idx += 1

        recovered = total_atts - stats["failed"]
        click.echo(f"   Recovered {recovered}/{total_atts} attachments "
                    f"({stats['failed']} unavailable)")

    # Get reactions
    click.echo("💬 Collecting reactions...")
    reaction_map = get_reactions(chat["ROWID"])
    click.echo(f"   {sum(len(v) for v in reaction_map.values())} reactions on {len(reaction_map)} messages")

    # Generate output
    if fmt == "html":
        click.echo("🎨 Generating HTML...")
        html_content = generate_html(
            messages=messages,
            att_map=att_map,
            contacts=contacts,
            media_results=media_results,
            chat_name=chat["display_name"] or chat_name,
            your_name=your_name,
            reactions=reaction_map,
        )
        out_path = os.path.join(output, "chat.html")
        with open(out_path, "w") as f:
            f.write(html_content)
    else:
        click.echo("📝 Generating text export...")
        from .messages import apple_ts_to_dt
        lines = [f"# {chat['display_name'] or chat_name} - Chat Export", ""]
        for msg in messages:
            dt = apple_ts_to_dt(msg["date"])
            ts = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "Unknown"
            sender = your_name if msg["is_from_me"] else contacts.get(msg["handle_id"] or "", msg.get("handle_id", "Unknown"))
            text = msg["text"] or ""
            if text:
                lines.append(f"[{ts}] {sender}: {text}")
        out_path = os.path.join(output, "chat.txt")
        with open(out_path, "w") as f:
            f.write("\n".join(lines))

    # Summary
    click.echo(f"\n✅ Export complete!")
    click.echo(f"   📁 {output}/")
    click.echo(f"   📄 {os.path.basename(out_path)}")
    if not no_media:
        media_count = len(os.listdir(media_dir))
        media_size = sum(
            os.path.getsize(os.path.join(media_dir, f))
            for f in os.listdir(media_dir)
        )
        click.echo(f"   🖼  {media_count} media files ({media_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
