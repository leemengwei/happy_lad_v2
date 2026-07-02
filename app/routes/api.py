import yaml
from flask import Blueprint, current_app, jsonify, request

from app.services.sampling import SamplingPolicy

api_bp = Blueprint("api", __name__)


def _get_manager():
    return current_app.config["PIPELINE_MANAGER"]


def _get_config_path() -> str:
    return current_app.config["CONFIG_PATH"]


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
    payload = request.get_json(force=True)
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
        target["name"] = payload["name"]
    if "sampling" in payload:
        target.setdefault("sampling", {})
        sampling_payload = payload["sampling"]
        if "time_span_years" in sampling_payload:
            target["sampling"]["time_span_years"] = float(sampling_payload["time_span_years"])
        if "cooldown_hours" in sampling_payload:
            target["sampling"]["cooldown_hours"] = float(sampling_payload["cooldown_hours"])
    if "recent_samples_limit" in payload:
        target["recent_samples_limit"] = int(payload["recent_samples_limit"])

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

    return jsonify({"status": "updated"})


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
