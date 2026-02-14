import yaml
from dataclasses import dataclass
from typing import List


@dataclass
class SamplingConfig:
    time_span_years: float
    cooldown_hours: float


@dataclass
class CameraConfig:
    id: str
    name: str
    device: str
    width: int
    height: int
    fps: int
    model_config: str
    storage_dir: str
    recent_samples_limit: int
    sampling: SamplingConfig


@dataclass
class AppConfig:
    cameras: List[CameraConfig]


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    cameras = []
    for raw in data.get("cameras", []):
        sampling = raw.get("sampling", {})
        cameras.append(
            CameraConfig(
                id=raw["id"],
                name=raw.get("name", raw["id"]),
                device=raw["device"],
                width=int(raw.get("width", 1920)),
                height=int(raw.get("height", 1080)),
                fps=int(raw.get("fps", 30)),
                model_config=raw["model_config"],
                storage_dir=raw["storage_dir"],
                recent_samples_limit=max(0, int(raw.get("recent_samples_limit", 16))),
                sampling=SamplingConfig(
                    time_span_years=float(sampling.get("time_span_years", 10)),
                    cooldown_hours=float(sampling.get("cooldown_hours", 24)),
                ),
            )
        )

    return AppConfig(cameras=cameras)
