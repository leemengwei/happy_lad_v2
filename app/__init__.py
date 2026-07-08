from flask import Flask
from app.routes.dashboard import dashboard_bp
from app.routes.api import api_bp
from app.services.media_library import MediaLibrary
import os


def create_app(pipeline_manager):
    app = Flask(__name__)
    app.secret_key = "happy_lad_v2"
    app.config["PIPELINE_MANAGER"] = pipeline_manager

    external_base = "/mnt/external_us/happy_lad_uploader"
    mount_point = "/mnt/external_us"
    if not os.path.ismount(mount_point):
        raise RuntimeError(
            f"Uploader storage unavailable: {mount_point} is not mounted. "
            "Refusing to fall back to local disk."
        )
    if not os.path.isdir(external_base):
        os.makedirs(external_base, exist_ok=True)

    app.config["UPLOADS_DIR"] = os.path.join(external_base, "uploads")
    app.config["MEDIA_DB_PATH"] = os.path.join(external_base, "data", "media.db")

    os.makedirs(os.path.dirname(app.config["MEDIA_DB_PATH"]), exist_ok=True)
    if not os.access(external_base, os.W_OK):
        raise RuntimeError(
            f"Uploader storage unavailable: {external_base} is not writable. "
            "Refusing to fall back to local disk."
        )
    app.config["MEDIA_LIBRARY"] = MediaLibrary(
        db_path=app.config["MEDIA_DB_PATH"],
        uploads_dir=app.config["UPLOADS_DIR"],
    )

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    return app
