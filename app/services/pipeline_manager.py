import logging
import os
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
            except Exception:
                logger.exception("Watchdog loop crashed unexpectedly; continuing")
