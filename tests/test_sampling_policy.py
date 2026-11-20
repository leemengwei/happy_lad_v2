import datetime
import unittest
from unittest.mock import patch

from app.services.sampling import SamplingPolicy, SamplingState


class SamplingPolicyTests(unittest.TestCase):
    def make_policy(self, expected=1.0, cooldown_hours=24):
        return SamplingPolicy(
            cooldown_hours=cooldown_hours,
            target_bytes=1_000_000,
            minimum_free_bytes=5_000,
            average_sample_bytes=500_000,
            expected_samples_per_person_hour=expected,
        )

    def test_probability_gives_expected_samples_per_continuous_person_hour(self):
        policy = self.make_policy(expected=1)
        for interval in (1.0, 0.5, 2.0):
            probability = policy.probability_for_interval(1, interval)
            decisions_per_hour = 3600 / interval
            self.assertAlmostEqual(decisions_per_hour * probability, 1.0)

    def test_probability_scales_linearly_with_expectation(self):
        policy = self.make_policy(expected=2.5)
        self.assertAlmostEqual(policy.probability_for_interval(1, 1), 2.5 / 3600)
        self.assertAlmostEqual(policy.probability_for_interval(1, 0.5), 1.25 / 3600)

    def test_probability_is_capped_when_target_exceeds_detection_rate(self):
        policy = self.make_policy(expected=10_000)
        self.assertEqual(policy.probability_for_interval(1, 1), 1.0)

    def test_real_time_probability_uses_latest_decision_rate(self):
        policy = self.make_policy(expected=2)
        policy.last_decision_interval_seconds = 1.0
        self.assertAlmostEqual(policy.sample_probability_if_human_frame, 2 / 3600)
        policy.expected_samples_per_person_hour = 4
        self.assertAlmostEqual(policy.sample_probability_if_human_frame, 4 / 3600)

    def test_empty_scene_never_auto_samples_even_after_cooldown(self):
        policy = self.make_policy()
        state = SamplingState(
            last_sample_time=datetime.datetime.now() - datetime.timedelta(days=3),
            last_decision_monotonic=99.0,
        )
        with patch("app.services.sampling.time.monotonic", return_value=100.0):
            with patch("app.services.sampling.random.random", return_value=0.0):
                self.assertFalse(policy.should_sample(state, person_count=0))

    def test_cooldown_fallback_samples_a_person_after_a_long_miss(self):
        policy = self.make_policy(expected=1, cooldown_hours=24)
        state = SamplingState(
            last_sample_time=datetime.datetime.now() - datetime.timedelta(hours=25),
            last_decision_monotonic=99.0,
        )
        with patch("app.services.sampling.time.monotonic", return_value=100.0):
            self.assertTrue(policy.should_sample(state, person_count=1))

    def test_zero_expectation_disables_automatic_and_cooldown_sampling(self):
        policy = self.make_policy(expected=0, cooldown_hours=1)
        state = SamplingState(
            last_sample_time=datetime.datetime.now() - datetime.timedelta(days=2),
            last_decision_monotonic=99.0,
        )
        with patch("app.services.sampling.time.monotonic", return_value=100.0):
            with patch("app.services.sampling.random.random", return_value=0.0):
                self.assertFalse(policy.should_sample(state, person_count=1))

    def test_storage_cap_stops_sampling(self):
        policy = self.make_policy()
        policy.record_sample_size(1_000_000)
        state = SamplingState(
            last_sample_time=datetime.datetime.now() - datetime.timedelta(days=2),
            last_decision_monotonic=99.0,
        )
        with patch("app.services.sampling.time.monotonic", return_value=100.0):
            self.assertFalse(policy.should_sample(state, person_count=1))

    def test_saved_image_consumes_shared_disk_budget(self):
        policy = self.make_policy()
        policy.record_sample_size(600_000)
        self.assertEqual(policy.target_bytes, 400_000)
        self.assertAlmostEqual(policy.average_sample_bytes, 501_000)


if __name__ == "__main__":
    unittest.main()
