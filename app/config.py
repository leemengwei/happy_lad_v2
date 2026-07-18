import yaml
from dataclasses import dataclass
from typing import List, Optional


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
    sample_sound_file: str
    sample_sound_volume: float
    recent_samples_limit: int
    sampling: SamplingConfig


@dataclass
class SystemConfig:
    abnormal_min_active_streams: int
    abnormal_reboot_after_hours: float
    auto_reboot_enabled: bool
    reboot_command: List[str]
    reboot_sudo_password: Optional[str]


@dataclass
class AppConfig:
    cameras: List[CameraConfig]
    system: SystemConfig


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
                sample_sound_file=raw.get(
                    "sample_sound_file",
                    "/usr/share/sounds/alsa/Front_Center.wav",
                ),
                sample_sound_volume=min(1.0, max(0.0, float(raw.get("sample_sound_volume", 1.0)))),
                recent_samples_limit=max(0, int(raw.get("recent_samples_limit", 16))),
                sampling=SamplingConfig(
                    time_span_years=float(sampling.get("time_span_years", 10)),
                    cooldown_hours=float(sampling.get("cooldown_hours", 24)),
                ),
            )
        )

    raw_system = data.get("system", {}) or {}
    reboot_command = raw_system.get("reboot_command", ["sudo", "-n", "systemctl", "reboot"])
    if not isinstance(reboot_command, list) or not reboot_command:
        reboot_command = ["sudo", "-n", "systemctl", "reboot"]

    system = SystemConfig(
        abnormal_min_active_streams=max(0, int(raw_system.get("abnormal_min_active_streams", 2))),
        abnormal_reboot_after_hours=max(0.0, float(raw_system.get("abnormal_reboot_after_hours", 3.0))),
        auto_reboot_enabled=bool(raw_system.get("auto_reboot_enabled", True)),
        reboot_command=[str(item) for item in reboot_command],
        reboot_sudo_password=(
            str(raw_system.get("reboot_sudo_password")).strip()
            if raw_system.get("reboot_sudo_password") is not None
            else None
        ),
    )

    return AppConfig(cameras=cameras, system=system)
