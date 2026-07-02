import time
from flask import Blueprint, current_app, render_template, Response, abort, send_from_directory, url_for


dashboard_bp = Blueprint("dashboard", __name__)


def _get_manager():
    return current_app.config["PIPELINE_MANAGER"]




@dashboard_bp.route("/")
def dashboard():
    manager = _get_manager()
    status_list = manager.list_status()
    return render_template("dashboard.html", cameras=status_list)


@dashboard_bp.route("/diagnostics")
def diagnostics():
    manager = _get_manager()
    status_list = manager.list_status()
    stale_threshold_seconds = 20
    stale_cameras = [
        item
        for item in status_list
        if item.get("last_frame_age_seconds") is not None
        and item["last_frame_age_seconds"] > stale_threshold_seconds
    ]
    return render_template(
        "diagnostics.html",
        cameras=status_list,
        stale_threshold_seconds=stale_threshold_seconds,
        stale_cameras=stale_cameras,
    )


@dashboard_bp.route("/camera/<camera_id>")
def camera_detail(camera_id: str):
    manager = _get_manager()
    if camera_id not in manager.pipelines:
        abort(404)
    pipeline = manager.get_pipeline(camera_id)
    limit = max(0, int(getattr(pipeline, "recent_samples_limit", 16)))
    recent = pipeline.storage.list_recent(limit)
    recent_items = [
        {
            "filename": path,
            "url": url_for("dashboard.sample_media", camera_id=camera_id, filename=path),
        }
        for path in recent
    ]
    return render_template(
        "camera.html",
        camera=pipeline.get_status(),
        recent_samples=recent_items,
    )


@dashboard_bp.route("/stream/<camera_id>")
def camera_stream(camera_id: str):
    manager = _get_manager()
    if camera_id not in manager.pipelines:
        abort(404)
    pipeline = manager.get_pipeline(camera_id)

    def generate():
        while True:
            frame = pipeline.get_latest_jpeg()
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@dashboard_bp.route("/media/<camera_id>/<path:filename>")
def sample_media(camera_id: str, filename: str):
    manager = _get_manager()
    if camera_id not in manager.pipelines:
        abort(404)
    pipeline = manager.get_pipeline(camera_id)
    return send_from_directory(pipeline.storage.base_dir, filename)
