import os
import datetime
import logging
import cv2
from typing import List

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def save_sample(self, frame, camera_name: str) -> str:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{camera_name}_{timestamp}.jpg"
        path = os.path.join(self.base_dir, filename)
        cv2.imwrite(path, frame)

        latest_path = os.path.join(self.base_dir, "latest.jpg")
        cv2.imwrite(latest_path, frame)
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
