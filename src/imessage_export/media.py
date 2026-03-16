"""Three-tier media recovery: disk, Photos export, Photos derivatives."""
import sqlite3
import subprocess
import os
import shutil
import glob
from datetime import datetime, timedelta
from typing import Optional

from .messages import APPLE_EPOCH, apple_ts_to_dt

PHOTOS_DB = os.path.expanduser("~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite")
PHOTOS_LIB = os.path.expanduser("~/Pictures/Photos Library.photoslibrary")

VIDEO_EXTENSIONS = {'.mov', '.mp4', '.m4v', '.avi', '.webm'}


class PhotosIndex:
    """Index of Photos library for matching by original filename + date."""

    def __init__(self):
        self.photos_map = {}  # stem -> [{uuid, guid, date}]
        self._build()

    def _build(self):
        if not os.path.exists(PHOTOS_DB):
            return
        conn = sqlite3.connect(PHOTOS_DB)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("""
            SELECT aa.ZORIGINALFILENAME, a.ZUUID, a.ZCLOUDASSETGUID, a.ZDATECREATED
            FROM ZASSET a
            JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
            WHERE aa.ZORIGINALFILENAME IS NOT NULL
        """):
            stem = os.path.splitext(row["ZORIGINALFILENAME"])[0].upper()
            if stem not in self.photos_map:
                self.photos_map[stem] = []
            self.photos_map[stem].append({
                "uuid": row["ZUUID"],
                "guid": row["ZCLOUDASSETGUID"],
                "date": row["ZDATECREATED"],
            })
        conn.close()

    def find_best_match(self, filename: str, msg_date_ts: int,
                        max_days: int = 90) -> Optional[str]:
        """Find best matching photo GUID by filename + date proximity."""
        stem = os.path.splitext(filename)[0].upper()
        candidates = self.photos_map.get(stem, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]["guid"]

        msg_dt = apple_ts_to_dt(msg_date_ts) if msg_date_ts else None
        if not msg_dt:
            return candidates[0]["guid"]

        best = None
        best_diff = timedelta(days=9999)
        for c in candidates:
            if c["date"]:
                photo_dt = datetime.fromtimestamp(c["date"] + APPLE_EPOCH)
                diff = abs(photo_dt - msg_dt)
                if diff < best_diff:
                    best_diff = diff
                    best = c

        if best and best_diff < timedelta(days=max_days):
            return best["guid"]
        return None

    def find_file_for_guid(self, guid: str) -> Optional[str]:
        """Find the best available file on disk for a Photos asset GUID."""
        if not guid:
            return None
        # Try originals first, then derivatives
        search_paths = [
            (f"{PHOTOS_LIB}/originals", [f"*/{guid}.*", f"*/{guid}_*"]),
            (f"{PHOTOS_LIB}/resources/derivatives/masters", [f"*/{guid}_*"]),
            (f"{PHOTOS_LIB}/resources/derivatives", [f"*/{guid}_*"]),
            (f"{PHOTOS_LIB}/resources/derivatives/cvt", [f"*/{guid}/*"]),
        ]
        for base, patterns in search_paths:
            for pat in patterns:
                matches = glob.glob(os.path.join(base, pat))
                if matches:
                    return max(matches, key=os.path.getsize)
        return None

    def find_uuids_for_stems(self, stems: list) -> dict:
        """Find Photos UUIDs for a list of filename stems (for batch AppleScript export)."""
        result = {}
        for stem in stems:
            candidates = self.photos_map.get(stem.upper(), [])
            if candidates:
                result[stem] = candidates[0]["uuid"]
        return result


def export_from_photos_app(uuid: str, output_dir: str) -> Optional[str]:
    """Export an original from Photos.app via AppleScript. Returns output path."""
    os.makedirs(output_dir, exist_ok=True)
    before = set(os.listdir(output_dir))
    script = f'''
    tell application "Photos"
        set targetFolder to POSIX file "{output_dir}/"
        set theItem to media item id "{uuid}"
        export {{theItem}} to targetFolder with using originals
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return None
        after = set(os.listdir(output_dir))
        new_files = after - before
        if new_files:
            return os.path.join(output_dir, new_files.pop())
        return None
    except (subprocess.TimeoutExpired, Exception):
        return None


def batch_export_from_photos(uuids: dict, output_dir: str,
                             progress_fn=None) -> dict:
    """Export multiple originals from Photos.app.
    
    Args:
        uuids: {stem: uuid} mapping
        output_dir: where to save exports
        progress_fn: optional callback(stem, i, total, success)
    
    Returns: {stem: output_path} for successful exports
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    total = len(uuids)
    for i, (stem, uuid) in enumerate(uuids.items()):
        path = export_from_photos_app(uuid, output_dir)
        success = path is not None
        if success:
            results[stem] = path
        if progress_fn:
            progress_fn(stem, i + 1, total, success)
    return results


def recover_attachment(transfer_name: str, db_filename: str, msg_date: int,
                       photos_index: PhotosIndex, exported_media: dict,
                       media_dir: str, att_idx: int) -> tuple:
    """Try to recover an attachment from all sources.
    
    Returns: (final_filename, is_video, success)
    """
    safe_base = f"{att_idx:04d}_{transfer_name}".replace("/", "_")
    dst = os.path.join(media_dir, safe_base)
    stem = os.path.splitext(transfer_name)[0].upper()

    # Tier 1: Direct file on disk
    if db_filename:
        real_src = db_filename.replace("~", os.path.expanduser("~"))
        if os.path.isfile(real_src):
            try:
                shutil.copy2(real_src, dst)
                ext = os.path.splitext(real_src)[1].lower()
                return safe_base, ext in VIDEO_EXTENSIONS, True
            except Exception:
                pass

    # Tier 2: Previously exported media (from Photos.app AppleScript)
    if stem in exported_media:
        src = exported_media[stem]
        ext = os.path.splitext(src)[1]
        final = f"{att_idx:04d}_{os.path.splitext(transfer_name)[0]}{ext}".replace("/", "_")
        dst = os.path.join(media_dir, final)
        try:
            shutil.copy2(src, dst)
            return final, ext.lower() in VIDEO_EXTENSIONS, True
        except Exception:
            pass

    # Tier 3: Photos library derivatives (with date matching)
    guid = photos_index.find_best_match(transfer_name, msg_date)
    if guid:
        pf = photos_index.find_file_for_guid(guid)
        if pf:
            ext = os.path.splitext(pf)[1]
            final = f"{att_idx:04d}_{os.path.splitext(transfer_name)[0]}{ext}".replace("/", "_")
            dst = os.path.join(media_dir, final)
            try:
                shutil.copy2(pf, dst)
                return final, ext.lower() in VIDEO_EXTENSIONS, True
            except Exception:
                pass

    return safe_base, False, False
