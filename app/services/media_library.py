import datetime
import os
import sqlite3
import uuid
from typing import Dict, List


class MediaLibrary:
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
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO media (
                    original_name, stored_name, ext, mime_type, size_bytes,
                    media_type, storage_path, media_url, poster_path, poster_url, captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            total = int(conn.execute("SELECT COUNT(*) AS c FROM media").fetchone()["c"])
            rows = conn.execute(
                f"""
                SELECT id, original_name, stored_name, ext, mime_type, size_bytes,
                       media_type, storage_path, media_url, poster_path, poster_url, captured_at, created_at
                FROM media
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

    def delete_media(self, media_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT id, storage_path, poster_path FROM media WHERE id = ?",
                (int(media_id),),
            ).fetchone()
            if row is None:
                return {"deleted": False, "reason": "not_found"}

            storage_path = row["storage_path"]
            abs_path = os.path.join(self.uploads_dir, storage_path)
            try:
                os.remove(abs_path)
            except FileNotFoundError:
                pass
            poster_path = row["poster_path"]
            if poster_path:
                poster_abs_path = os.path.join(self.uploads_dir, poster_path)
                try:
                    os.remove(poster_abs_path)
                except FileNotFoundError:
                    pass

            conn.execute("DELETE FROM media WHERE id = ?", (int(media_id),))
            conn.commit()
            return {"deleted": True, "id": int(media_id)}
        finally:
            conn.close()

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
