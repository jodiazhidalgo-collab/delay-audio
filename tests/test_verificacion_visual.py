import os
import sys
import unittest


MOTOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "motor", "delay_audio"))
if MOTOR_ROOT not in sys.path:
    sys.path.insert(0, MOTOR_ROOT)

from verificacion_visual import VideoMetadata, VisualVerifier, map_ref_to_esp_time, pick_zones  # noqa: E402


class VisualMappingTests(unittest.TestCase):
    def test_map_equal_fps_and_zero_delay(self):
        self.assertAlmostEqual(map_ref_to_esp_time(100.0, 0.0, 1.0), 100.0)

    def test_map_positive_delay_moves_origin_earlier(self):
        self.assertAlmostEqual(map_ref_to_esp_time(100.0, 2.5, 1.0), 97.5)

    def test_map_negative_delay_moves_origin_later(self):
        self.assertAlmostEqual(map_ref_to_esp_time(100.0, -2.5, 1.0), 102.5)

    def test_map_24_to_23976(self):
        tempo = (24000 / 1001) / 24.0
        self.assertAlmostEqual(map_ref_to_esp_time(1000.0, 15.0, tempo), 984.015984, places=6)

    def test_map_24_to_23976_keeps_sign_at_start_middle_and_end(self):
        tempo = (24000 / 1001) / 24.0
        for ref_time in (18.0, 60.0, 102.0):
            with self.subTest(ref_time=ref_time):
                positive = map_ref_to_esp_time(ref_time, 1.5, tempo)
                negative = map_ref_to_esp_time(ref_time, -1.5, tempo)
                self.assertAlmostEqual(positive, (ref_time - 1.5) * tempo, places=9)
                self.assertAlmostEqual(negative, (ref_time + 1.5) * tempo, places=9)
                self.assertLess(positive, ref_time * tempo)
                self.assertGreater(negative, ref_time * tempo)

    def test_map_rejects_invalid_tempo(self):
        with self.assertRaises(ValueError):
            map_ref_to_esp_time(10.0, 0.0, 0.0)


class ZoneSelectionTests(unittest.TestCase):
    def test_movie_initial_zones(self):
        zones = pick_zones(1000.0, "pelicula")
        self.assertEqual([item["pct"] for item in zones[:3]], [18.0, 50.0, 82.0])

    def test_trailer_initial_zones(self):
        zones = pick_zones(120.0, "trailer")
        self.assertEqual([item["pct"] for item in zones[:3]], [22.0, 58.0, 82.0])

    def test_short_trailer_omits_third_initial_zone(self):
        zones = pick_zones(30.0, "trailer")
        self.assertEqual([item["pct"] for item in zones[:2]], [22.0, 58.0])
        self.assertNotIn(82.0, [item["pct"] for item in zones[:2]])

    def test_extremely_short_video_has_no_zone(self):
        self.assertEqual(pick_zones(1.0, "pelicula"), [])


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.movie_cfg = VisualVerifier().config("pelicula")

    def test_strong_zone(self):
        state = VisualVerifier._classify_zone({"mean_ssim": 0.93, "margin": 0.12}, self.movie_cfg)
        self.assertEqual(state, "FUERTE")

    def test_valid_zone(self):
        state = VisualVerifier._classify_zone({"mean_ssim": 0.84, "margin": 0.06}, self.movie_cfg)
        self.assertEqual(state, "VALIDA")

    def test_static_zone_is_suspicious_when_margin_is_small(self):
        state = VisualVerifier._classify_zone({"mean_ssim": 0.99, "margin": 0.001}, self.movie_cfg)
        self.assertEqual(state, "SOSPECHOSA")

    def test_low_score_zone_is_useless(self):
        state = VisualVerifier._classify_zone({"mean_ssim": 0.42, "margin": 0.20}, self.movie_cfg)
        self.assertEqual(state, "INUTIL")

    def test_candidate_ranking_requires_repeated_wins(self):
        zones = [
            {
                "winner_delay_ms": 0,
                "candidates": [
                    {"delay_ms": 0, "mean_ssim": 0.95, "margin": 0.20},
                    {"delay_ms": 96540, "mean_ssim": 0.40, "margin": -0.50},
                ],
            },
            {
                "winner_delay_ms": 0,
                "candidates": [
                    {"delay_ms": 0, "mean_ssim": 0.92, "margin": 0.17},
                    {"delay_ms": 96540, "mean_ssim": 0.44, "margin": -0.45},
                ],
            },
        ]
        ranked = VisualVerifier._aggregate_candidates([0, 96540], zones)
        self.assertEqual(ranked[0]["delay_ms"], 0)
        self.assertEqual(ranked[0]["wins"], 2)
        self.assertEqual(ranked[1]["wins"], 0)


class DeterministicFpsVerifier(VisualVerifier):
    def __init__(self, ref_meta, esp_meta, planned_score=0.95, nominal_score=0.40):
        super().__init__()
        self._metas = [ref_meta, esp_meta]
        self._planned_score = planned_score
        self._nominal_score = nominal_score

    def probe_video(self, path):
        return self._metas[0] if path == "ref" else self._metas[1]

    def score_candidate(self, ref_video, esp_video_original, ref_time, delay_ms, tempo=1.0, *args, **kwargs):
        expected_tempo = self._metas[0].avg_fps / self._metas[1].avg_fps
        score = self._planned_score if abs(tempo - expected_tempo) < 0.0000001 else self._nominal_score
        return {"ok": True, "mean_ssim": score, "frames": 4}


def fake_meta(path, duration, fps, real_fps=None, vfr=False):
    return VideoMetadata(path, duration, fps, real_fps or fps, 1920, 1080, "yuv420p", "bt709", vfr)


class FpsConfirmationTests(unittest.TestCase):
    def assert_confirmed_pair(self, ref_fps, esp_fps):
        tempo = ref_fps / esp_fps
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100.0, ref_fps),
            fake_meta("esp", 100.0 * tempo, esp_fps),
        )
        result = verifier.confirm_fps_plan("ref", "esp", ref_fps, esp_fps, "pelicula")
        self.assertTrue(result["planned"])
        self.assertTrue(result["confirmed"])
        self.assertAlmostEqual(result["tempo"], tempo, places=9)

    def test_24_to_23976_is_confirmable(self):
        self.assert_confirmed_pair(24000 / 1001, 24.0)

    def test_25_to_23976_is_confirmable(self):
        self.assert_confirmed_pair(24000 / 1001, 25.0)

    def test_23976_to_25_is_confirmable(self):
        self.assert_confirmed_pair(25.0, 24000 / 1001)

    def test_equal_fps_needs_no_plan(self):
        verifier = DeterministicFpsVerifier(fake_meta("ref", 100, 24), fake_meta("esp", 100, 24))
        result = verifier.confirm_fps_plan("ref", "esp", 24, 24, "pelicula")
        self.assertFalse(result["planned"])
        self.assertEqual(result["reason"], "fps_iguales")

    def test_metadata_only_difference_is_rejected_by_duration(self):
        verifier = DeterministicFpsVerifier(fake_meta("ref", 100, 24), fake_meta("esp", 100, 25))
        result = verifier.confirm_fps_plan("ref", "esp", 24, 25, "pelicula")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["reason"], "duracion_no_confirma_tempo")

    def test_vfr_is_not_automatically_confirmed(self):
        tempo = (24000 / 1001) / 24
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100, 24000 / 1001, vfr=True),
            fake_meta("esp", 100 * tempo, 24),
        )
        result = verifier.confirm_fps_plan("ref", "esp", 24000 / 1001, 24, "pelicula")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["reason"], "vfr_no_confirmado")


@unittest.skipUnless(
    os.environ.get("DELAY_AUDIO_TEST_MR_BEAN_REF") and os.environ.get("DELAY_AUDIO_TEST_MR_BEAN_ESP"),
    "material real Mr. Bean no configurado",
)
class RealMrBeanVisualTests(unittest.TestCase):
    def test_zero_wins_and_96540_is_rejected_in_multiple_zones(self):
        verifier = VisualVerifier(timeout=240)
        result = verifier.score_candidates(
            os.environ["DELAY_AUDIO_TEST_MR_BEAN_REF"],
            os.environ["DELAY_AUDIO_TEST_MR_BEAN_ESP"],
            [0, 96540],
            "pelicula",
        )
        self.assertTrue(result["strong_winner"])
        self.assertEqual(result["winner_delay_ms"], 0)
        self.assertGreaterEqual(result["zones_valid"], 3)
        by_delay = {item["delay_ms"]: item for item in result["candidates"]}
        self.assertEqual(by_delay[0]["wins"], result["zones_valid"])
        self.assertEqual(by_delay[96540]["wins"], 0)
        self.assertLess(by_delay[96540]["mean_ssim"], 0.60)


if __name__ == "__main__":
    unittest.main()
