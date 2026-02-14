import argparse
import logging

from app import create_app
from app.config import load_config
from app.services.pipeline_manager import PipelineManager


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/cameras.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = get_args()
    config = load_config(args.config)
    manager = PipelineManager(config)
    manager.start_all()

    app = create_app(manager)
    app.config["CONFIG_PATH"] = args.config
    app.run(debug=False, host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
