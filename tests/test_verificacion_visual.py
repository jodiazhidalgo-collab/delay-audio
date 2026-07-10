import os
import sys
import unittest


MOTOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "motor", "delay_audio"))
if MOTOR_ROOT not in sys.path:
    sys.path.insert(0, MOTOR_ROOT)

from verificacion_visual import VisualVerifier, map_ref_to_esp_time, pick_zones  # noqa: E402


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
