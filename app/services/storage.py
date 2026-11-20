import os
import datetime
import logging
import shutil
import cv2
import re
import uuid
from typing import List

logger = logging.getLogger(__name__)


class Storage:
    DEFAULT_SAMPLE_BYTES = 512 * 1024
    WRITE_HEADROOM_BYTES = 5 * 1024 * 1024

    def __init__(self, base_dir: str, minimum_free_bytes: int = 0) -> None:
        self.base_dir = base_dir
        self.minimum_free_bytes = max(0, int(minimum_free_bytes))
        os.makedirs(self.base_dir, exist_ok=True)

    def average_sample_size(self) -> float:
        sizes = []
        for root, _dirs, files in os.walk(self.base_dir):
            for name in files:
                if not name.lower().endswith(".jpg") or name == "latest.jpg":
                    continue
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
                if size > 0:
                    sizes.append(size)
        if not sizes:
            return float(self.DEFAULT_SAMPLE_BYTES)
        return sum(sizes) / len(sizes)

    def has_capacity(self) -> bool:
        try:
            return (
                shutil.disk_usage(self.base_dir).free
                > self.minimum_free_bytes + self.WRITE_HEADROOM_BYTES
            )
        except OSError:
            logger.exception("Unable to inspect free space for %s", self.base_dir)
            return False

    def save_sample(self, frame, camera_name: str) -> str:
        if not self.has_capacity():
            raise OSError(
                f"sampling stopped to preserve {self.minimum_free_bytes} bytes of free space"
            )
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(camera_name)).strip("._") or "camera"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        filename = f"{safe_name}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        path = os.path.join(self.base_dir, filename)
        if not cv2.imwrite(path, frame):
            raise OSError(f"failed to encode/write snapshot: {path}")

        latest_path = os.path.join(self.base_dir, "latest.jpg")
        if not cv2.imwrite(latest_path, frame):
            logger.warning("Failed to update latest snapshot: %s", latest_path)
        logger.info("Saved snapshot: %s", path)
        return path

    def list_recent(self, limit: int) -> list:
        if limit <= 0:
            return []

        candidates = []
        for root, _dirs, files in os.walk(self.base_dir):
            for name in files:
                if not name.lower().endswith(".jpg"):
                    continue
                if name == "latest.jpg":
                    continue
                full_path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    continue
                rel_path = os.path.relpath(full_path, self.base_dir)
                candidates.append((mtime, rel_path))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [rel for _mtime, rel in candidates[:limit]]

    def delete_samples(self, rel_paths: List[str]) -> List[str]:
        deleted: List[str] = []
        base_abs = os.path.abspath(self.base_dir)
        for rel_path in rel_paths:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            if rel_path == "latest.jpg":
                continue

            norm_rel = os.path.normpath(rel_path).lstrip("/\\")
            full_path = os.path.abspath(os.path.join(self.base_dir, norm_rel))
            if not full_path.startswith(base_abs + os.sep):
                continue
            if not full_path.lower().endswith(".jpg"):
                continue

            try:
                os.remove(full_path)
                deleted.append(norm_rel)
                logger.info("Deleted snapshot: %s", full_path)
            except FileNotFoundError:
                continue
            except OSError:
                logger.exception("Failed deleting snapshot: %s", full_path)
        return deleted
