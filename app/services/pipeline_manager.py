from typing import Dict

from app.config import AppConfig
from app.services.pipeline import DeepStreamPipeline
from app.services.sampling import SamplingPolicy
from app.services.storage import Storage


class PipelineManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.pipelines: Dict[str, DeepStreamPipeline] = {}

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
                recent_samples_limit=camera.recent_samples_limit,
            )
            self.pipelines[camera.id] = pipeline

    def start_all(self) -> None:
        for pipeline in self.pipelines.values():
            pipeline.start()

    def stop_all(self) -> None:
        for pipeline in self.pipelines.values():
            pipeline.stop()

    def get_pipeline(self, camera_id: str) -> DeepStreamPipeline:
        return self.pipelines[camera_id]

    def list_status(self) -> list:
        return [pipeline.get_status() for pipeline in self.pipelines.values()]
