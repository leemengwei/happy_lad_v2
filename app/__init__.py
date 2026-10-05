from flask import Flask
from app.routes.dashboard import dashboard_bp
from app.routes.api import api_bp
from app.services.media_library import MediaLibrary
import os


def create_app(pipeline_manager):
    app = Flask(__name__)
    app.secret_key = "happy_lad_v2"
    app.config["PIPELINE_MANAGER"] = pipeline_manager
    app.config["REMOTE_ALBUM_SERVER"] = "root@192.168.0.110"
    app.config["REMOTE_ALBUM_PATH"] = "/root/nvme/album_service"

    external_base = "/mnt/external_us/happy_lad_uploader"
    mount_point = "/mnt/external_us"

    app.config["UPLOADER_STORAGE_READY"] = False
    app.config["UPLOADER_STORAGE_ERROR"] = ""
    app.config["UPLOADS_DIR"] = ""
    app.config["MEDIA_DB_PATH"] = ""
    app.config["MEDIA_LIBRARY"] = None
    app.config["FEEDBACK_LIBRARY"] = None

    feedback_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "feedback.db")
    os.makedirs(os.path.dirname(feedback_db), exist_ok=True)
    app.config["FEEDBACK_LIBRARY"] = MediaLibrary(db_path=feedback_db, uploads_dir=os.path.join(os.path.dirname(feedback_db), "feedback_uploads"))

    if not os.path.ismount(mount_point):
        app.config["UPLOADER_STORAGE_ERROR"] = f"相册存储盘不可用：挂载点 {mount_point} 未挂载。"
    else:
        os.makedirs(external_base, exist_ok=True)
        if not os.access(external_base, os.W_OK):
            app.config["UPLOADER_STORAGE_ERROR"] = f"相册存储盘不可用：目录 {external_base} 不可写。"
        else:
            app.config["UPLOADS_DIR"] = os.path.join(external_base, "uploads")
            app.config["MEDIA_DB_PATH"] = os.path.join(external_base, "data", "media.db")
            os.makedirs(os.path.dirname(app.config["MEDIA_DB_PATH"]), exist_ok=True)
            app.config["MEDIA_LIBRARY"] = MediaLibrary(
                db_path=app.config["MEDIA_DB_PATH"],
                uploads_dir=app.config["UPLOADS_DIR"],
            )
            app.config["UPLOADER_STORAGE_READY"] = True

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    return app
