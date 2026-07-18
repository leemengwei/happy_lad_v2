import datetime
import logging
import os
import subprocess
import threading
import time
from typing import Dict, Optional

from app.config import AppConfig
from app.services.pipeline import DeepStreamPipeline
from app.services.sampling import SamplingPolicy
from app.services.storage import Storage

logger = logging.getLogger(__name__)


class PipelineManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.pipelines: Dict[str, DeepStreamPipeline] = {}
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._abnormal_since: Optional[datetime.datetime] = None
        self._last_reboot_attempt_at: Optional[datetime.datetime] = None

        for camera in config.cameras:
            sampling_policy = SamplingPolicy(
                time_span_years=camera.sampling.time_span_years,
                cooldown_hours=camera.sampling.cooldown_hours,
            )
            storage = Storage(camera.storage_dir)
            pipeline = DeepStreamPipeline(
                camera_id=camera.id,
                camera_name=camera.name,
                device=camera.device,
                width=camera.width,
                height=camera.height,
                fps=camera.fps,
                model_config=camera.model_config,
                sampling_policy=sampling_policy,
                storage=storage,
                sample_sound_file=camera.sample_sound_file,
                sample_sound_volume=camera.sample_sound_volume,
                recent_samples_limit=camera.recent_samples_limit,
            )
            self.pipelines[camera.id] = pipeline

    def start_all(self) -> None:
        for pipeline in self.pipelines.values():
            pipeline.start()
        self._start_watchdog()

    def stop_all(self) -> None:
        self._watchdog_stop.set()
        for pipeline in self.pipelines.values():
            pipeline.stop()

    def get_pipeline(self, camera_id: str) -> DeepStreamPipeline:
        return self.pipelines[camera_id]

    def list_status(self) -> list:
        return [pipeline.get_status() for pipeline in self.pipelines.values()]

    def _start_watchdog(self) -> None:
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="pipeline-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(10):
            try:
                for pipeline in self.pipelines.values():
                    try:
                        if not pipeline._running:
                            if os.path.exists(pipeline.device):
                                logger.warning(
                                    "Watchdog detected stopped stream for %s with device present, restarting.",
                                    pipeline.camera_id,
                                )
                                pipeline.restart()
                            else:
                                logger.warning(
                                    "Watchdog detected stopped stream for %s, device missing: %s",
                                    pipeline.camera_id,
                                    pipeline.device,
                                )
                            continue

                        if pipeline.is_stalled(timeout_seconds=30):
                            logger.warning(
                                "Watchdog detected stalled stream for %s, restarting.",
                                pipeline.camera_id,
                            )
                            pipeline.restart()
                    except Exception:
                        logger.exception(
                            "Watchdog failed while handling camera %s",
                            pipeline.camera_id,
                        )
                self._handle_system_abnormality()
            except Exception:
                logger.exception("Watchdog loop crashed unexpectedly; continuing")

    def _count_healthy_streams(self, stale_seconds: int = 30) -> int:
        healthy = 0
        for pipeline in self.pipelines.values():
            status = pipeline.get_status()
            age = status.get("last_frame_age_seconds")
            if status.get("running") and age is not None and age <= stale_seconds:
                healthy += 1
        return healthy

    def _handle_system_abnormality(self) -> None:
        min_active = self.config.system.abnormal_min_active_streams
        healthy = self._count_healthy_streams(stale_seconds=30)
        now = datetime.datetime.now()

        if healthy >= min_active:
            if self._abnormal_since is not None:
                logger.info(
                    "System stream health recovered: healthy=%s threshold=%s",
                    healthy,
                    min_active,
                )
            self._abnormal_since = None
            self._last_reboot_attempt_at = None
            return

        if self._abnormal_since is None:
            self._abnormal_since = now
            logger.warning(
                "System abnormal started: healthy=%s threshold=%s",
                healthy,
                min_active,
            )
            return

        elapsed_seconds = (now - self._abnormal_since).total_seconds()
        reboot_after_seconds = self.config.system.abnormal_reboot_after_hours * 3600
        if elapsed_seconds < reboot_after_seconds:
            return

        if not self.config.system.auto_reboot_enabled:
            logger.warning(
                "System abnormal persisted %.0fs but auto reboot disabled.",
                elapsed_seconds,
            )
            return

        if (
            self._last_reboot_attempt_at is not None
            and (now - self._last_reboot_attempt_at).total_seconds() < 600
        ):
            return

        self._last_reboot_attempt_at = now
        logger.critical(
            "System abnormal persisted %.0fs (healthy=%s < %s). Triggering reboot.",
            elapsed_seconds,
            healthy,
            min_active,
        )
        self._trigger_system_reboot()

    def _trigger_system_reboot(self) -> None:
        command = list(self.config.system.reboot_command)
        if not command:
            logger.error("Auto reboot skipped: reboot_command is empty.")
            return

        password = self.config.system.reboot_sudo_password
        input_text = None
        if password and command[0] == "sudo" and "-S" not in command:
            command.insert(1, "-S")
        if password and "sudo" in command:
            input_text = f"{password}\n"

        try:
            result = subprocess.run(
                command,
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(
                    "Auto reboot command failed (code=%s): %s stderr=%s",
                    result.returncode,
                    " ".join(command),
                    (result.stderr or "").strip(),
                )
            else:
                logger.critical("Auto reboot command succeeded: %s", " ".join(command))
        except Exception:
            logger.exception("Auto reboot command crashed: %s", " ".join(command))
