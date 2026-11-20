import datetime
import logging
import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class SamplingBudget:
    """Shared available-byte cap for cameras on one filesystem."""

    def __init__(self, target_bytes: float, minimum_free_bytes: int) -> None:
        self.remaining_bytes = max(0.0, float(target_bytes))
        self.minimum_free_bytes = max(0, int(minimum_free_bytes))
        self._lock = threading.Lock()

    def consume(self, sample_size_bytes: int) -> None:
        if sample_size_bytes <= 0:
            return
        with self._lock:
            self.remaining_bytes = max(
                0.0, self.remaining_bytes - sample_size_bytes
            )


@dataclass
class SamplingState:
    last_sample_time: datetime.datetime
    force_snapshot: bool = False
    force_reason: Optional[str] = None
    last_decision_monotonic: Optional[float] = None


class SamplingPolicy:
    def __init__(
        self,
        cooldown_hours: float,
        target_bytes: float,
        minimum_free_bytes: int,
        average_sample_bytes: float,
        sampling_budget: Optional[SamplingBudget] = None,
        camera_id: str = "camera",
        expected_samples_per_person_hour: float = 1.0,
    ) -> None:
        if not math.isfinite(cooldown_hours):
            raise ValueError("cooldown_hours must be finite")
        if not math.isfinite(target_bytes) or target_bytes < 0:
            raise ValueError("target_bytes must be finite and non-negative")
        if not math.isfinite(average_sample_bytes) or average_sample_bytes <= 0:
            raise ValueError("average_sample_bytes must be finite and positive")
        if not math.isfinite(expected_samples_per_person_hour) or expected_samples_per_person_hour < 0:
            raise ValueError("expected_samples_per_person_hour must be finite and non-negative")
        self.cooldown_seconds = max(cooldown_hours, 0.0) * 3600
        self.budget = sampling_budget or SamplingBudget(
            target_bytes, minimum_free_bytes
        )
        self.camera_id = camera_id
        self.minimum_free_bytes = max(0, int(minimum_free_bytes))
        self.average_sample_bytes = float(average_sample_bytes)
        self.expected_samples_per_person_hour = float(expected_samples_per_person_hour)
        self.last_decision_interval_seconds: Optional[float] = None
        self._space_warning_logged = False
        self._activity_lock = threading.Lock()
        self._activity = {
            "decision_frames": 0,
            "human_decision_frames": 0,
            "lottery_trials": 0,
            "lottery_hits": 0,
            "cooldown_fallbacks": 0,
            "saved_samples": 0,
            "save_failures": 0,
        }
        self._last_activity_log_at = time.monotonic()
        self._last_activity_log = dict(self._activity)
        logger.info(
            "Sampling policy configured (expected_samples_per_person_hour=%.3f, cooldown_hours=%.2f, available_bytes=%.0f, average_sample_bytes=%.1f)",
            self.expected_samples_per_person_hour,
            self.cooldown_seconds / 3600,
            self.target_bytes,
            self.average_sample_bytes,
        )

    @property
    def target_bytes(self) -> float:
        return self.budget.remaining_bytes

    @property
    def decision_fps(self) -> Optional[float]:
        interval = self.last_decision_interval_seconds
        return 1.0 / interval if interval and interval > 0 else None

    @property
    def sample_probability_if_human_frame(self) -> Optional[float]:
        interval = self.last_decision_interval_seconds
        if interval is None:
            return None
        if self.target_bytes <= 0:
            return 0.0
        return min(
            1.0,
            self.expected_samples_per_person_hour * interval / 3600.0,
        )

    def probability_for_interval(
        self, person_count: int, decision_interval_seconds: float
    ) -> float:
        if person_count <= 0 or decision_interval_seconds <= 0:
            return 0.0
        if self.target_bytes <= 0 or self.expected_samples_per_person_hour <= 0:
            return 0.0
        # Each saved image includes every person visible in this decision
        # frame. For a continuously visible person, this rate yields the
        # configured number of sampled images per hour.
        return min(
            1.0,
            self.expected_samples_per_person_hour * decision_interval_seconds / 3600.0,
        )

    def record_sample_size(self, sample_size_bytes: int) -> None:
        if sample_size_bytes <= 0:
            return
        self.budget.consume(sample_size_bytes)
        self.average_sample_bytes += (sample_size_bytes - self.average_sample_bytes) / 100.0

    def record_save_result(self, success: bool) -> None:
        key = "saved_samples" if success else "save_failures"
        with self._activity_lock:
            self._activity[key] += 1

    def get_activity(self) -> dict:
        with self._activity_lock:
            activity = dict(self._activity)
        decisions = activity["decision_frames"]
        activity["human_frame_fraction_since_start"] = (
            activity["human_decision_frames"] / decisions if decisions else None
        )
        return activity

    def copy_activity_from(self, other: "SamplingPolicy") -> None:
        with other._activity_lock:
            activity = dict(other._activity)
        with self._activity_lock:
            self._activity = activity
            self._last_activity_log = dict(activity)
            self._last_activity_log_at = time.monotonic()

    def _count_decision(self, person_count: int) -> None:
        with self._activity_lock:
            self._activity["decision_frames"] += 1
            if person_count > 0:
                self._activity["human_decision_frames"] += 1
        self._log_activity_if_due()

    def _log_activity_if_due(self) -> None:
        now = time.monotonic()
        with self._activity_lock:
            interval = now - self._last_activity_log_at
            if interval < 60:
                return
            current = dict(self._activity)
            previous = dict(self._last_activity_log)
            self._last_activity_log = current
            self._last_activity_log_at = now
        decision_delta = current["decision_frames"] - previous["decision_frames"]
        human_delta = current["human_decision_frames"] - previous["human_decision_frames"]
        logger.info(
            "Sampling activity (camera=%s, window_seconds=%.1f, decisions=%d, human_frames=%d, empty_frames=%d, human_frame_fraction=%.6f, lottery_trials=%d, lottery_hits=%d, cooldown_fallbacks=%d, saved_samples=%d, save_failures=%d, human_frame_probability=%.10g, available_bytes=%.0f)",
            self.camera_id,
            interval,
            decision_delta,
            human_delta,
            decision_delta - human_delta,
            human_delta / decision_delta if decision_delta else 0.0,
            current["lottery_trials"] - previous["lottery_trials"],
            current["lottery_hits"] - previous["lottery_hits"],
            current["cooldown_fallbacks"] - previous["cooldown_fallbacks"],
            current["saved_samples"] - previous["saved_samples"],
            current["save_failures"] - previous["save_failures"],
            self.sample_probability_if_human_frame or 0.0,
            self.target_bytes,
        )

    def _finish_decision(self, should_sample: bool) -> bool:
        self._log_activity_if_due()
        return should_sample

    def should_sample(
        self,
        state: SamplingState,
        person_count: int,
        can_capture: bool = True,
    ) -> bool:
        self._count_decision(person_count)
        now = datetime.datetime.now()
        monotonic_now = time.monotonic()
        if state.last_decision_monotonic is None:
            decision_interval = 0.0
        else:
            decision_interval = max(
                0.0, monotonic_now - state.last_decision_monotonic
            )
        state.last_decision_monotonic = monotonic_now
        self.last_decision_interval_seconds = decision_interval

        elapsed = (now - state.last_sample_time).total_seconds()
        # Cooldown is a fallback for sparse human scenes, not a reason to
        # store an empty frame. Manual requests remain explicit overrides.
        fallback_after = max(
            self.cooldown_seconds,
            4.0 * 3600.0 / self.expected_samples_per_person_hour
            if self.expected_samples_per_person_hour > 0
            else float("inf"),
        )
        if (
            fallback_after > 0
            and elapsed >= fallback_after
            and person_count > 0
            and self.target_bytes > 0
        ):
            state.force_snapshot = True
            state.force_reason = "cooldown"

        if not can_capture:
            if not self._space_warning_logged:
                logger.warning(
                    "Sampling paused at disk reserve (target_bytes=%.0f, minimum_free_bytes=%d)",
                    self.target_bytes,
                    self.minimum_free_bytes,
                )
                self._space_warning_logged = True
            return self._finish_decision(False)

        if state.force_snapshot:
            reason = state.force_reason or "requested"
            if reason == "cooldown":
                with self._activity_lock:
                    self._activity["cooldown_fallbacks"] += 1
            logger.info(
                "Force snapshot triggered (reason=%s, elapsed=%.2fs, person_count=%d)",
                reason,
                elapsed,
                person_count,
            )
            state.force_snapshot = False
            state.force_reason = None
            state.last_sample_time = now
            return self._finish_decision(True)

        sample_probability = self.probability_for_interval(
            person_count, decision_interval
        )
        if sample_probability <= 0.0:
            return self._finish_decision(False)

        with self._activity_lock:
            self._activity["lottery_trials"] += 1
        lottery = random.random()
        if lottery < sample_probability:
            with self._activity_lock:
                self._activity["lottery_hits"] += 1
            logger.info(
                "Lottery snapshot (draw=%.8f, sample_probability=%.10g, person_count=%d, decision_interval=%.6fs, effective_decision_fps=%.4f)",
                lottery,
                sample_probability,
                person_count,
                decision_interval,
                self.decision_fps or 0.0,
            )
            state.last_sample_time = now
            return self._finish_decision(True)

        return self._finish_decision(False)
