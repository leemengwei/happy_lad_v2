import datetime
import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SamplingState:
    last_sample_time: datetime.datetime
    force_snapshot: bool = False


class SamplingPolicy:
    def __init__(self, time_span_years: float, cooldown_hours: float) -> None:
        self.time_span_years = max(time_span_years, 0.1)
        self.cooldown_seconds = max(cooldown_hours, 0.0) * 3600
        self.sample_chance = (200 * 1024 * 2) / (
            self.time_span_years * 365 * 24 * 3600 * 30
        )

    def should_sample(
        self,
        state: SamplingState,
        person_count: int,
    ) -> bool:
        now = datetime.datetime.now()
        elapsed = (now - state.last_sample_time).total_seconds()
        if elapsed >= self.cooldown_seconds:
            state.force_snapshot = True

        not_sample_chance = max(0.0, 1.0 - self.sample_chance * person_count)

        if state.force_snapshot:
            logger.info(
                "Force snapshot triggered (elapsed=%.2fs, person_count=%d)",
                elapsed,
                person_count,
            )
            state.force_snapshot = False
            state.last_sample_time = now
            return True

        lottery = random.random()
        if lottery >= not_sample_chance:
            logger.info(
                "Lottery snapshot (chance=%.4f, threshold=%.4f, person_count=%d)",
                lottery,
                not_sample_chance,
                person_count,
            )
            state.last_sample_time = now
            return True

        logger.debug(
            "Skip snapshot (chance=%.4f, threshold=%.4f, person_count=%d)",
            lottery,
            not_sample_chance,
            person_count,
        )

        return False
