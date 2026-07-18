import time
import io
import ipaddress
import socket
import urllib.parse
import urllib.request
import datetime
from flask import Blueprint, current_app, render_template, Response, abort, send_from_directory, url_for, request
from PIL import Image, ImageDraw


dashboard_bp = Blueprint("dashboard", __name__)
BABY_BIRTHDAY_TEXT = "2026-06-29"


def _get_manager():
    return current_app.config["PIPELINE_MANAGER"]


def _format_bytes(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    while value >= 1024 and unit_idx < len(units) - 1:
        value /= 1024
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(value)} {units[unit_idx]}"
    return f"{value:.1f} {units[unit_idx]}"


def _compute_age_text(start_date: datetime.date, end_date: datetime.date) -> str:
    years = end_date.year - start_date.year
    months = end_date.month - start_date.month
    days = end_date.day - start_date.day
    if days < 0:
        months -= 1
        prev_month_last_day = (end_date.replace(day=1) - datetime.timedelta(days=1)).day
        days += prev_month_last_day
    if months < 0:
        years -= 1
        months += 12
    if years < 0:
        return "未出生"
    return f"{years}岁{months}个月{days}天"


def _parse_media_time(item: dict) -> datetime.datetime:
    raw = item.get("captured_at") or item.get("created_at")
    if not raw:
        return datetime.datetime.min
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return datetime.datetime.min


def _build_timeline_groups(items: list, *, birth_date: datetime.date) -> list:
    groups = []
    by_day = {}
    for item in items:
        dt = _parse_media_time(item)
        day_key = dt.date().isoformat() if dt != datetime.datetime.min else "未知日期"
        if day_key not in by_day:
            day_label = day_key if day_key == "未知日期" else dt.strftime("%Y-%m-%d")
            age_text = "未知"
            if day_key != "未知日期":
                age_text = _compute_age_text(birth_date, dt.date())
            by_day[day_key] = {
                "day_key": day_key,
                "day_label": day_label,
                "age_text": age_text,
                "items": [],
                "item_count": 0,
            }
            groups.append(by_day[day_key])
        by_day[day_key]["items"].append(item)
        by_day[day_key]["item_count"] += 1
    return groups


def _detect_lan_ip() -> str:
    # Prefer the outbound interface address (works without sending traffic).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            ipaddress.ip_address(ip)
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass

    # Fallback to hostname resolution if needed.
    try:
        ip = socket.gethostbyname(socket.gethostname())
        ipaddress.ip_address(ip)
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"




@dashboard_bp.route("/")
def dashboard():
    manager = _get_manager()
    status_list = manager.list_status()
    media_items = current_app.config["MEDIA_LIBRARY"].list_media(limit=12)
    return render_template("dashboard.html", cameras=status_list, media_items=media_items)


@dashboard_bp.route("/qr/home.png")
def home_qr_png():
    host = request.host or ""
    if ":" in host and host.count(":") == 1:
        _host_name, host_port = host.rsplit(":", 1)
    else:
        host_port = ""

    resolved_host = _detect_lan_ip()
    netloc = f"{resolved_host}:{host_port}" if host_port else resolved_host
    target = f"{request.scheme}://{netloc}{url_for('dashboard.dashboard')}"
    qr_url = (
        "https://api.qrserver.com/v1/create-qr-code/"
        f"?size=240x240&margin=0&data={urllib.parse.quote(target, safe='')}"
    )
    try:
        with urllib.request.urlopen(qr_url, timeout=5) as response:
            body = response.read()
            if body:
                return Response(body, mimetype="image/png")
    except Exception:
        pass

    # Fallback placeholder if upstream QR service is temporarily unavailable.
    image = Image.new("RGB", (240, 240), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 239, 239), outline=(160, 160, 160), width=2)
    draw.text((20, 108), "QR Unavailable", fill=(80, 80, 80))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


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


@dashboard_bp.route("/uploader")
def uploader():
    media_library = current_app.config["MEDIA_LIBRARY"]
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 50))
    except Exception:
        per_page = 50
    per_page = max(20, min(per_page, 1000))
    sort_by = request.args.get("sort_by", "captured")
    sort_order = request.args.get("sort_order", "desc")

    result = media_library.list_media_paginated(
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    birth_date = datetime.date(2026, 6, 29)
    today_age_text = _compute_age_text(birth_date, datetime.date.today())
    timeline_mode = result["sort_by"] == "captured"
    timeline_groups = _build_timeline_groups(result["items"], birth_date=birth_date) if timeline_mode else []
    trash_items = media_library.list_trash(limit=120)
    stats = media_library.get_storage_stats()
    total = result["total"]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, result["page"]), total_pages)
    if page != result["page"]:
        result = media_library.list_media_paginated(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    return render_template(
        "uploader.html",
        media_items=result["items"],
        timeline_mode=timeline_mode,
        timeline_groups=timeline_groups,
        trash_items=trash_items,
        total=total,
        baby_birthday_text=BABY_BIRTHDAY_TEXT,
        today_age_text=today_age_text,
        stats=stats,
        stats_text={
            "image_bytes": _format_bytes(stats["image_bytes"]),
            "video_bytes": _format_bytes(stats["video_bytes"]),
            "total_bytes": _format_bytes(stats["total_bytes"]),
            "disk_free_bytes": _format_bytes(stats["disk_free_bytes"]),
        },
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=result["sort_by"],
        sort_order=result["sort_order"],
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


@dashboard_bp.route("/uploads/<path:filename>")
def uploaded_media(filename: str):
    return send_from_directory(current_app.config["UPLOADS_DIR"], filename)
