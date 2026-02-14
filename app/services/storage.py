import os
import datetime
import logging
import cv2

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
