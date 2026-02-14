from flask import Flask
from app.routes.dashboard import dashboard_bp
from app.routes.api import api_bp


def create_app(pipeline_manager):
    app = Flask(__name__)
    app.secret_key = "happy_lad_v2"
    app.config["PIPELINE_MANAGER"] = pipeline_manager

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    return app
