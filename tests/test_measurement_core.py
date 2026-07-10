import os
import sys
import unittest


MOTOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "motor", "delay_audio"))
if MOTOR_ROOT not in sys.path:
    sys.path.insert(0, MOTOR_ROOT)

from measurement_core import build_measurement_core, core_zone_start, fit_timeline_model  # noqa: E402


def anchors(delays_ms, ref_times=None):
    times = ref_times or [600.0 + index * 1200.0 for index in range(len(delays_ms))]
    return [
        {"start_sec": ref_time, "delay_ms": delay_ms, "score": 0.8}
        for ref_time, delay_ms in zip(times, delays_ms)
    ]


class MeasurementCoreTests(unittest.TestCase):
    def test_long_movie_uses_two_minute_guards(self):
        core = build_measurement_core(7200.0, "pelicula")
        self.assertEqual(core["start_sec"], 120.0)
        self.assertEqual(core["end_sec"], 7080.0)
        self.assertEqual(core["span_sec"], 6960.0)
        self.assertFalse(core["adaptive"])

    def test_short_movie_uses_adaptive_guards(self):
        core = build_measurement_core(3600.0, "pelicula")
        self.assertEqual(core["guard_start_sec"], 108.0)
        self.assertEqual(core["guard_end_sec"], 108.0)
        self.assertTrue(core["adaptive"])

    def test_very_short_movie_reduces_guards_and_keeps_useful_span(self):
        core = build_measurement_core(90.0, "pelicula")
        self.assertEqual(core["start_sec"], 15.0)
        self.assertEqual(core["end_sec"], 75.0)
        self.assertEqual(core["span_sec"], 60.0)
        self.assertEqual(core["reason"], "movie_short_reduced_guards")

    def test_trailer_guard_is_adaptive_and_bounded(self):
        long_core = build_measurement_core(120.0, "trailer")
        short_core = build_measurement_core(20.0, "trailer")
        self.assertEqual(long_core["guard_start_sec"], 4.0)
        self.assertEqual(short_core["guard_start_sec"], 1.6)
        self.assertEqual(long_core["profile"], "trailer")

    def test_every_zone_keeps_complete_segment_inside_core(self):
        core = build_measurement_core(7200.0, "pelicula")
        for pct in (0, 10, 50, 95, 100):
            with self.subTest(pct=pct):
                start = core_zone_start(core, pct, 40.0)
                self.assertGreaterEqual(start, core["start_sec"])
                self.assertLessEqual(start + 40.0, core["end_sec"] + 1e-6)


class TimelineModelTests(unittest.TestCase):
    def test_different_intro_and_identical_body_is_a_constant_intercept(self):
        model = fit_timeline_model(anchors([12000, 12000, 12000, 12000]), core_span_sec=5000.0)
        self.assertTrue(model["compatible"])
        self.assertAlmostEqual(model["intercept_ms"], 12000.0, places=3)

    def test_different_outro_does_not_change_interior_anchors(self):
        model = fit_timeline_model(anchors([0, 0, 0, 0]), core_span_sec=5000.0)
        self.assertTrue(model["compatible"])
        self.assertAlmostEqual(model["intercept_ms"], 0.0, places=3)

    def test_different_intro_and_outro_keep_stable_interior_model(self):
        model = fit_timeline_model(anchors([-7500, -7500, -7500, -7500]), core_span_sec=5000.0)
        self.assertTrue(model["compatible"])
        self.assertAlmostEqual(model["intercept_ms"], -7500.0, places=3)

    def test_stable_slope_and_nonzero_intercept(self):
        model = fit_timeline_model(anchors([800, 800, 800, 800]), core_span_sec=5000.0)
        self.assertTrue(model["compatible"])
        self.assertAlmostEqual(model["slope"], 1.0, places=9)
        self.assertAlmostEqual(model["intercept_ms"], 800.0, places=3)
        self.assertEqual(model["anchors_inliers"], 4)

    def test_large_total_duration_difference_does_not_affect_interior_model(self):
        model = fit_timeline_model(anchors([2588, 2588, 2588, 2588]), core_span_sec=5000.0)
        self.assertTrue(model["compatible"])
        self.assertAlmostEqual(model["intercept_ms"], 2588.0, places=3)

    def test_isolated_outlier_is_rejected(self):
        model = fit_timeline_model(
            anchors([800, 800, 5000, 800, 800], [600, 1600, 2600, 3600, 4600]),
            core_span_sec=5000.0,
        )
        self.assertTrue(model["compatible"])
        self.assertEqual(model["anchors_inliers"], 4)
        self.assertEqual(model["anchors_rejected"], 1)

    def test_wrong_tempo_keeps_progressive_drift_blocked(self):
        model = fit_timeline_model(
            anchors([800, 1200, 1600, 2000], [600, 1600, 2600, 3600]),
            core_span_sec=4000.0,
        )
        self.assertFalse(model["compatible"])
        self.assertEqual(model["reason"], "timeline_drift_too_high")
        self.assertGreater(abs(model["drift_ms_per_sec"]), 0.1)

    def test_internal_cut_creates_incompatible_residuals(self):
        model = fit_timeline_model(
            anchors([800, 800, 2800, 2800], [600, 1600, 2600, 3600]),
            core_span_sec=4000.0,
        )
        self.assertFalse(model["compatible"])
        self.assertIn(
            model["reason"],
            {"insufficient_inlier_anchors", "timeline_residuals_too_high", "too_many_rejected_anchors"},
        )

    def test_not_enough_anchors_never_exports_a_compatible_model(self):
        model = fit_timeline_model(anchors([800, 800]), core_span_sec=5000.0)
        self.assertFalse(model["compatible"])
        self.assertEqual(model["reason"], "insufficient_inlier_anchors")


if __name__ == "__main__":
    unittest.main()
