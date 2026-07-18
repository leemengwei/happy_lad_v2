import datetime
import os
import shutil
import sqlite3
import uuid
from typing import Dict, List


class MediaLibrary:
    TRASH_RETENTION_DAYS = 7

    def __init__(self, db_path: str, uploads_dir: str) -> None:
        self.db_path = db_path
        self.uploads_dir = uploads_dir
        os.makedirs(self.uploads_dir, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    ext TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    media_url TEXT NOT NULL,
                    poster_path TEXT,
                    poster_url TEXT,
                    captured_at TEXT,
                    latitude REAL,
                    longitude REAL,
                    location_text TEXT,
                    deleted_at TEXT,
                    purge_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = [row[1] for row in conn.execute("PRAGMA table_info(media)").fetchall()]
            if "captured_at" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN captured_at TEXT")
            if "poster_path" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN poster_path TEXT")
            if "poster_url" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN poster_url TEXT")
            if "latitude" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN latitude REAL")
            if "longitude" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN longitude REAL")
            if "location_text" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN location_text TEXT")
            if "deleted_at" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN deleted_at TEXT")
            if "purge_at" not in columns:
                conn.execute("ALTER TABLE media ADD COLUMN purge_at TEXT")
            conn.commit()
        finally:
            conn.close()

    def generate_storage_path(self, ext: str) -> Dict[str, str]:
        now = datetime.datetime.now()
        rel_dir = os.path.join(now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
        abs_dir = os.path.join(self.uploads_dir, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        stored_name = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        rel_path = os.path.join(rel_dir, stored_name)
        abs_path = os.path.join(self.uploads_dir, rel_path)
        return {
            "stored_name": stored_name,
            "rel_path": rel_path.replace("\\", "/"),
            "abs_path": abs_path,
        }

    def save_media(
        self,
        *,
        original_name: str,
        stored_name: str,
        ext: str,
        mime_type: str,
        size_bytes: int,
        media_type: str,
        storage_path: str,
        media_url: str,
        poster_path: str = None,
        poster_url: str = None,
        captured_at: str = None,
        latitude: float = None,
        longitude: float = None,
        location_text: str = None,
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO media (
                    original_name, stored_name, ext, mime_type, size_bytes,
                    media_type, storage_path, media_url, poster_path, poster_url, captured_at,
                    latitude, longitude, location_text, deleted_at, purge_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                """,
                (
                    original_name,
                    stored_name,
                    ext,
                    mime_type,
                    size_bytes,
                    media_type,
                    storage_path,
                    media_url,
                    poster_path,
                    poster_url,
                    captured_at,
                    latitude,
                    longitude,
                    location_text,
                    datetime.datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def list_media(self, limit: int = 100) -> List[Dict]:
        result = self.list_media_paginated(page=1, per_page=limit, sort_by="uploaded", sort_order="desc")
        return result["items"]

    def list_media_paginated(
        self,
        *,
        page: int,
        per_page: int,
        sort_by: str = "uploaded",
        sort_order: str = "desc",
    ) -> Dict:
        safe_page = max(1, int(page))
        safe_per_page = max(1, int(per_page))
        offset = (safe_page - 1) * safe_per_page
        safe_sort_by = (sort_by or "uploaded").lower()
        safe_sort_order = "ASC" if (sort_order or "").lower() == "asc" else "DESC"

        sort_column_map = {
            "uploaded": "created_at",
            "captured": "COALESCE(captured_at, created_at)",
            "size": "size_bytes",
            "name": "original_name",
        }
        order_expr = sort_column_map.get(safe_sort_by, "created_at")

        self.purge_expired_deleted()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            total = int(
                conn.execute("SELECT COUNT(*) AS c FROM media WHERE deleted_at IS NULL").fetchone()["c"]
            )
            rows = conn.execute(
                f"""
                SELECT id, original_name, stored_name, ext, mime_type, size_bytes, media_type,
                       storage_path, media_url, poster_path, poster_url, captured_at,
                       latitude, longitude, location_text, created_at
                FROM media
                WHERE deleted_at IS NULL
                ORDER BY {order_expr} {safe_sort_order}, id DESC
                LIMIT ? OFFSET ?
                """,
                (safe_per_page, offset),
            ).fetchall()
            return {
                "items": [dict(row) for row in rows],
                "total": total,
                "page": safe_page,
                "per_page": safe_per_page,
                "sort_by": safe_sort_by,
                "sort_order": safe_sort_order.lower(),
            }
        finally:
            conn.close()

    def move_to_trash(self, media_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, deleted_at FROM media WHERE id = ?",
                (int(media_id),),
            ).fetchone()
            if row is None:
                return {"moved": False, "reason": "not_found"}
            if row["deleted_at"]:
                return {"moved": False, "reason": "already_deleted"}

            deleted_at = datetime.datetime.now()
            purge_at = deleted_at + datetime.timedelta(days=self.TRASH_RETENTION_DAYS)
            conn.execute(
                "UPDATE media SET deleted_at = ?, purge_at = ? WHERE id = ?",
                (deleted_at.isoformat(), purge_at.isoformat(), int(media_id)),
            )
            conn.commit()
            return {"moved": True, "id": int(media_id), "purge_at": purge_at.isoformat()}
        finally:
            conn.close()

    def list_trash(self, limit: int = 200) -> List[Dict]:
        self.purge_expired_deleted()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, original_name, media_type, media_url, poster_url,
                       captured_at, created_at, deleted_at, purge_at, latitude, longitude, location_text
                FROM media
                WHERE deleted_at IS NOT NULL
                ORDER BY deleted_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def restore_from_trash(self, media_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, deleted_at FROM media WHERE id = ?",
                (int(media_id),),
            ).fetchone()
            if row is None:
                return {"restored": False, "reason": "not_found"}
            if not row["deleted_at"]:
                return {"restored": False, "reason": "not_in_trash"}
            conn.execute(
                "UPDATE media SET deleted_at = NULL, purge_at = NULL WHERE id = ?",
                (int(media_id),),
            )
            conn.commit()
            return {"restored": True, "id": int(media_id)}
        finally:
            conn.close()

    def permanently_delete(self, media_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, storage_path, poster_path FROM media WHERE id = ?",
                (int(media_id),),
            ).fetchone()
            if row is None:
                return {"deleted": False, "reason": "not_found"}
            self._remove_media_files(row["storage_path"], row["poster_path"])
            conn.execute("DELETE FROM media WHERE id = ?", (int(media_id),))
            conn.commit()
            return {"deleted": True, "id": int(media_id)}
        finally:
            conn.close()

    def purge_expired_deleted(self) -> int:
        now_iso = datetime.datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, storage_path, poster_path
                FROM media
                WHERE deleted_at IS NOT NULL AND purge_at IS NOT NULL AND purge_at <= ?
                """,
                (now_iso,),
            ).fetchall()
            if not rows:
                return 0
            ids = []
            for row in rows:
                self._remove_media_files(row["storage_path"], row["poster_path"])
                ids.append(int(row["id"]))
            conn.executemany("DELETE FROM media WHERE id = ?", [(media_id,) for media_id in ids])
            conn.commit()
            return len(ids)
        finally:
            conn.close()

    def _remove_media_files(self, storage_path: str, poster_path: str = None) -> None:
        abs_path = os.path.join(self.uploads_dir, storage_path)
        try:
            os.remove(abs_path)
        except FileNotFoundError:
            pass
        if poster_path:
            poster_abs_path = os.path.join(self.uploads_dir, poster_path)
            try:
                os.remove(poster_abs_path)
            except FileNotFoundError:
                pass

    def list_videos_missing_poster(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT id, storage_path, media_url
                FROM media
                WHERE media_type = 'video' AND (poster_path IS NULL OR poster_path = '')
                ORDER BY id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def update_media_poster(self, media_id: int, poster_path: str, poster_url: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE media SET poster_path = ?, poster_url = ? WHERE id = ?",
                (poster_path, poster_url, int(media_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_storage_stats(self) -> Dict:
        self.purge_expired_deleted()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS total_count,
                    SUM(CASE WHEN deleted_at IS NULL AND media_type = 'image' THEN 1 ELSE 0 END) AS image_count,
                    SUM(CASE WHEN deleted_at IS NULL AND media_type = 'video' THEN 1 ELSE 0 END) AS video_count,
                    COALESCE(SUM(CASE WHEN deleted_at IS NULL AND media_type = 'image' THEN size_bytes ELSE 0 END), 0) AS image_bytes,
                    COALESCE(SUM(CASE WHEN deleted_at IS NULL AND media_type = 'video' THEN size_bytes ELSE 0 END), 0) AS video_bytes,
                    COALESCE(SUM(CASE WHEN deleted_at IS NULL THEN size_bytes ELSE 0 END), 0) AS total_bytes,
                    SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS trash_count
                FROM media
                """
            ).fetchone()
        finally:
            conn.close()

        usage = shutil.disk_usage(self.uploads_dir)
        return {
            "total_count": int(counts["total_count"] or 0),
            "image_count": int(counts["image_count"] or 0),
            "video_count": int(counts["video_count"] or 0),
            "image_bytes": int(counts["image_bytes"] or 0),
            "video_bytes": int(counts["video_bytes"] or 0),
            "total_bytes": int(counts["total_bytes"] or 0),
            "trash_count": int(counts["trash_count"] or 0),
            "disk_free_bytes": int(usage.free),
            "disk_total_bytes": int(usage.total),
        }
