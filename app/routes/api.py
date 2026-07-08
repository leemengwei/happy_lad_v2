import yaml
import os
import datetime
from flask import Blueprint, current_app, jsonify, request, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ExifTags
import cv2

from app.services.sampling import SamplingPolicy

api_bp = Blueprint("api", __name__)

ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif",
    ".mp4", ".mov", ".m4v", ".3gp", ".hevc",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp", ".hevc"}

EXIF_DATETIME_KEYS = {"DateTimeOriginal", "DateTimeDigitized", "DateTime"}


def _get_manager():
    return current_app.config["PIPELINE_MANAGER"]


def _get_config_path() -> str:
    return current_app.config["CONFIG_PATH"]


def _bad_request(message: str):
    return jsonify({"error": message}), 400


def _parse_exif_datetime(value: str):
    if not value:
        return None
    value = str(value).strip()
    try:
        return datetime.datetime.strptime(value, "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:
        return None


def _extract_captured_at(abs_path: str, ext: str, media_type: str):
    if media_type != "image":
        return None
    try:
        with Image.open(abs_path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag_id, raw in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag_name in EXIF_DATETIME_KEYS:
                    parsed = _parse_exif_datetime(raw)
                    if parsed:
                        return parsed
    except Exception:
        return None
    return None


def _generate_video_poster(abs_video_path: str, rel_video_path: str):
    rel_root, _ext = os.path.splitext(rel_video_path)
    poster_rel_path = f"{rel_root}_poster.jpg"
    uploads_dir = current_app.config["UPLOADS_DIR"]
    poster_abs_path = os.path.join(uploads_dir, poster_rel_path)
    os.makedirs(os.path.dirname(poster_abs_path), exist_ok=True)
    try:
        cap = cv2.VideoCapture(abs_video_path)
        if not cap.isOpened():
            return None, None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        if fps > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * 0.2))
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, 200)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return None, None
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return None, None
        with open(poster_abs_path, "wb") as file:
            file.write(encoded.tobytes())
        poster_url = url_for("dashboard.uploaded_media", filename=poster_rel_path)
        return poster_rel_path, poster_url
    except Exception:
        return None, None


def _normalize_uploaded_name(original_name: str, ext: str, generated_stored_name: str) -> str:
    # Some mobile camera captures are always named image.png / image.jpg / video.mov.
    # Replace those generic names to reduce collisions and make albums easier to scan.
    base = os.path.basename(original_name or "")
    lowered = base.lower()
    if lowered in {"image.png", "image.jpg", "image.jpeg", "video.mov", "video.mp4"}:
        stem, _ext = os.path.splitext(generated_stored_name)
        return f"camera_{stem}{ext}"
    return original_name


def _get_pipeline_or_error(camera_id: str):
    manager = _get_manager()
    pipeline = manager.pipelines.get(camera_id)
    if pipeline is None:
        return None, (jsonify({"error": "camera not found"}), 404)
    return pipeline, None


@api_bp.get("/cameras")
def list_cameras():
    manager = _get_manager()
    return jsonify(manager.list_status())


@api_bp.post("/cameras/<camera_id>/snapshot")
def force_snapshot(camera_id: str):
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    pipeline.force_snapshot()
    return jsonify({"status": "ok"})


@api_bp.post("/cameras/<camera_id>/snooze")
def add_camera_snooze(camera_id: str):
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    snooze_until = pipeline.add_snooze(minutes=10)
    return jsonify(
        {
            "status": "ok",
            "snoozing": True,
            "snooze_until": snooze_until.isoformat(),
        }
    )


@api_bp.post("/cameras/<camera_id>/snooze/cancel")
def cancel_camera_snooze(camera_id: str):
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    pipeline.cancel_snooze()
    return jsonify({"status": "ok", "snoozing": False, "snooze_until": None})


@api_bp.post("/cameras/<camera_id>/config")
def update_camera_config(camera_id: str):
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return _bad_request("invalid json payload")
    config_path = _get_config_path()

    with open(config_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    cameras = data.get("cameras", [])
    target = None
    for camera in cameras:
        if camera.get("id") == camera_id:
            target = camera
            break

    if target is None:
        return jsonify({"error": "camera not found"}), 404

    if "name" in payload:
        if not isinstance(payload["name"], str):
            return _bad_request("name must be string")
        target["name"] = payload["name"]
    if "sampling" in payload:
        if not isinstance(payload["sampling"], dict):
            return _bad_request("sampling must be object")
        target.setdefault("sampling", {})
        sampling_payload = payload["sampling"]
        if "time_span_years" in sampling_payload:
            try:
                target["sampling"]["time_span_years"] = float(sampling_payload["time_span_years"])
            except (TypeError, ValueError):
                return _bad_request("sampling.time_span_years must be number")
        if "cooldown_hours" in sampling_payload:
            try:
                target["sampling"]["cooldown_hours"] = float(sampling_payload["cooldown_hours"])
            except (TypeError, ValueError):
                return _bad_request("sampling.cooldown_hours must be number")
    if "recent_samples_limit" in payload:
        try:
            target["recent_samples_limit"] = int(payload["recent_samples_limit"])
        except (TypeError, ValueError):
            return _bad_request("recent_samples_limit must be integer")
    if "sample_sound_file" in payload:
        target["sample_sound_file"] = str(payload["sample_sound_file"]).strip()
    if "sample_sound_volume" in payload:
        try:
            target["sample_sound_volume"] = min(1.0, max(0.0, float(payload["sample_sound_volume"])))
        except (TypeError, ValueError):
            return _bad_request("sample_sound_volume must be number")

    with open(config_path, "w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True)

    manager = _get_manager()
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    sampling = target.get("sampling", {})
    pipeline.sampling_policy = SamplingPolicy(
        time_span_years=float(sampling.get("time_span_years", 10)),
        cooldown_hours=float(sampling.get("cooldown_hours", 24)),
    )
    if "name" in payload:
        pipeline.camera_name = payload["name"]
    if "recent_samples_limit" in payload:
        pipeline.recent_samples_limit = max(0, int(payload["recent_samples_limit"]))
    if "sample_sound_file" in payload:
        pipeline.sample_sound_file = str(payload["sample_sound_file"]).strip()
    if "sample_sound_volume" in payload:
        pipeline.sample_sound_volume = min(1.0, max(0.0, float(payload["sample_sound_volume"])))

    return jsonify({"status": "updated"})


@api_bp.post("/cameras/<camera_id>/sample-sound/test")
def test_camera_sample_sound(camera_id: str):
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    ok = pipeline.test_sample_sound()
    return jsonify({"status": "ok" if ok else "failed", "played": bool(ok)}), (200 if ok else 500)


@api_bp.post("/cameras/<camera_id>/samples/delete")
def delete_camera_samples(camera_id: str):
    pipeline, error = _get_pipeline_or_error(camera_id)
    if error:
        return error
    payload = request.get_json(force=True, silent=True) or {}
    files = payload.get("files", [])
    if not isinstance(files, list):
        return jsonify({"error": "files must be an array"}), 400

    deleted = pipeline.storage.delete_samples(files)
    return jsonify({"status": "ok", "deleted": deleted, "deleted_count": len(deleted)})


@api_bp.get("/health")
def health_status():
    statuses = _get_manager().list_status()
    stale_threshold_seconds = 20
    stale = [
        item["camera_id"]
        for item in statuses
        if item.get("last_frame_age_seconds") is not None
        and item["last_frame_age_seconds"] > stale_threshold_seconds
    ]
    return jsonify(
        {
            "status": "degraded" if stale else "ok",
            "camera_count": len(statuses),
            "stale_cameras": stale,
            "stale_threshold_seconds": stale_threshold_seconds,
            "cameras": statuses,
        }
    )


@api_bp.post("/uploader/upload")
def upload_media():
    media_library = current_app.config["MEDIA_LIBRARY"]
    file = request.files.get("file")
    if file is None or not file.filename:
        return _bad_request("missing file")

    original_name = secure_filename(file.filename)
    _root, ext = os.path.splitext(original_name.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return _bad_request("unsupported file extension")

    generated = media_library.generate_storage_path(ext)
    file.save(generated["abs_path"])
    size_bytes = os.path.getsize(generated["abs_path"])
    media_type = "image" if ext in IMAGE_EXTENSIONS else "video"
    media_url = url_for("dashboard.uploaded_media", filename=generated["rel_path"])
    poster_path = None
    poster_url = None
    if media_type == "video":
        poster_path, poster_url = _generate_video_poster(generated["abs_path"], generated["rel_path"])

    normalized_name = _normalize_uploaded_name(original_name, ext, generated["stored_name"])

    media_id = media_library.save_media(
        original_name=normalized_name,
        stored_name=generated["stored_name"],
        ext=ext,
        mime_type=(file.mimetype or "application/octet-stream"),
        size_bytes=size_bytes,
        media_type=media_type,
        storage_path=generated["rel_path"],
        media_url=media_url,
        poster_path=poster_path,
        poster_url=poster_url,
        captured_at=_extract_captured_at(generated["abs_path"], ext, media_type),
    )
    return jsonify(
        {
            "status": "ok",
            "id": media_id,
            "original_name": normalized_name,
            "media_type": media_type,
            "size_bytes": size_bytes,
            "storage_path": generated["rel_path"],
            "media_url": media_url,
            "poster_url": poster_url,
        }
    )


@api_bp.get("/uploader/media")
def list_uploaded_media():
    media_library = current_app.config["MEDIA_LIBRARY"]
    try:
        per_page = int(request.args.get("per_page", request.args.get("limit", 200)))
    except ValueError:
        per_page = 200
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    sort_by = request.args.get("sort_by", "uploaded")
    sort_order = request.args.get("sort_order", "desc")
    per_page = max(1, min(per_page, 500))
    result = media_library.list_media_paginated(
        page=max(1, page),
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = max(1, (result["total"] + result["per_page"] - 1) // result["per_page"])
    return jsonify(
        {
            "items": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": total_pages,
            "sort_by": result["sort_by"],
            "sort_order": result["sort_order"],
        }
    )


@api_bp.post("/uploader/delete")
def delete_uploaded_media():
    payload = request.get_json(force=True, silent=True) or {}
    media_id = payload.get("id")
    if media_id is None:
        return _bad_request("id is required")
    try:
        media_id = int(media_id)
    except (TypeError, ValueError):
        return _bad_request("id must be integer")

    media_library = current_app.config["MEDIA_LIBRARY"]
    result = media_library.delete_media(media_id)
    if not result.get("deleted"):
        return jsonify({"error": "media not found"}), 404
    return jsonify({"status": "ok", "id": media_id})
