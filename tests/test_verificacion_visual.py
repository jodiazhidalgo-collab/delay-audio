import os
import sys
import unittest
from itertools import permutations
from types import SimpleNamespace
from unittest.mock import patch


MOTOR_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "motor", "delay_audio"))
if MOTOR_ROOT not in sys.path:
    sys.path.insert(0, MOTOR_ROOT)

import verificacion_visual as visual_module  # noqa: E402
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

    def test_all_required_fps_pairs_keep_formula_and_delay_sign(self):
        pairs = (
            (24.0, 24.0),
            (24000 / 1001, 24.0),
            (24000 / 1001, 25.0),
            (25.0, 24000 / 1001),
        )
        for ref_fps, esp_fps in pairs:
            tempo = ref_fps / esp_fps
            for ref_time in (18.0, 60.0, 102.0):
                for delay_sec in (-1.5, 0.0, 1.5):
                    with self.subTest(
                        ref_fps=ref_fps,
                        esp_fps=esp_fps,
                        ref_time=ref_time,
                        delay_sec=delay_sec,
                    ):
                        mapped = map_ref_to_esp_time(ref_time, delay_sec, tempo)
                        zero = map_ref_to_esp_time(ref_time, 0.0, tempo)
                        self.assertAlmostEqual(mapped, (ref_time - delay_sec) * tempo, places=9)
                        if delay_sec > 0:
                            self.assertLess(mapped, zero)
                        elif delay_sec < 0:
                            self.assertGreater(mapped, zero)
                        else:
                            self.assertEqual(mapped, zero)

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

    def test_relative_evidence_uses_comparable_low_ssim_zones(self):
        zones = []
        deltas = [0.258832, -0.012151, 0.327195, 0.273071, 0.145336, 0.292567, 0.083159]
        for index, delta in enumerate(deltas):
            zones.append({
                "pct": index,
                "state": "INUTIL",
                "candidates": [
                    {"delay_ms": -1000, "mean_ssim": 0.50 + delta},
                    {"delay_ms": 0, "mean_ssim": 0.50},
                ],
            })
        evidence = VisualVerifier._relative_evidence([-1000, 0], zones, self.movie_cfg)
        self.assertTrue(evidence["relative_match"])
        self.assertEqual(evidence["relative_wins"], 6)
        self.assertEqual(evidence["relative_ties"], 1)
        self.assertEqual(evidence["relative_losses"], 0)
        self.assertAlmostEqual(evidence["relative_mean_delta"], 0.19543, places=6)

    def test_one_clear_relative_loss_blocks_verification(self):
        zones = [
            {
                "pct": index,
                "candidates": [
                    {"delay_ms": 1000, "mean_ssim": target},
                    {"delay_ms": 0, "mean_ssim": 0.50},
                ],
            }
            for index, target in enumerate((0.70, 0.68, 0.40))
        ]
        evidence = VisualVerifier._relative_evidence([1000, 0], zones, self.movie_cfg)
        self.assertFalse(evidence["relative_match"])
        self.assertEqual(evidence["relative_losses"], 1)

    def test_relative_delta_boundaries_are_classified_after_stable_rounding(self):
        zones = [
            {
                "pct": 10,
                "candidates": [
                    {"delay_ms": 1000, "mean_ssim": 0.50},
                    {"delay_ms": 0, "mean_ssim": 0.45},
                ],
            },
            {
                "pct": 20,
                "candidates": [
                    {"delay_ms": 1000, "mean_ssim": 0.45},
                    {"delay_ms": 0, "mean_ssim": 0.50},
                ],
            },
        ]
        evidence = VisualVerifier._relative_evidence([1000, 0], zones, self.movie_cfg)
        self.assertEqual(evidence["relative_wins"], 1)
        self.assertEqual(evidence["relative_ties"], 1)
        self.assertEqual(evidence["relative_losses"], 0)
        self.assertEqual(
            [item["outcome"] for item in evidence["relative_comparisons"]],
            ["win", "tie"],
        )


class RelativeVisualVerifier(VisualVerifier):
    def probe_video(self, path):
        return fake_meta(path, 100.0, 24.0)

    def score_candidate(self, ref_video, esp_video_original, ref_time, delay_ms, *args, **kwargs):
        score = 0.65 if int(delay_ms) == -1000 else 0.45 if int(delay_ms) == 0 else 0.40
        return {"ok": True, "mean_ssim": score, "frames": 4}


class RelativeVisualIntegrationTests(unittest.TestCase):
    def test_visual_final_can_verify_relative_with_zero_absolute_valid_zones(self):
        result = RelativeVisualVerifier().score_candidates(
            "ref",
            "esp",
            [-1000, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["zones_valid"], 0)
        self.assertEqual(result["winner_delay_ms"], -1000)
        self.assertTrue(result["relative_match"])
        self.assertEqual(result["relative_target_delay_ms"], -1000)
        self.assertEqual(result["verification_mode"], "relative")
        self.assertTrue(result["verified"])

    def test_fast_path_remains_absolute_only(self):
        result = RelativeVisualVerifier().score_candidates(
            "ref",
            "esp",
            [-1000, 0],
            "pelicula",
            stage="visual_fast_path",
        )
        self.assertTrue(result["relative_match"] is False)
        self.assertEqual(result["verification_mode"], "none")
        self.assertFalse(result["verified"])


class FailingVisualVerifier(VisualVerifier):
    def _run_ssim(self, *args, **kwargs):
        raise RuntimeError("ffmpeg visual simulado falló")


class PassingVisualVerifier(VisualVerifier):
    def _run_ssim(self, *args, **kwargs):
        return [0.91, 0.92, 0.93, 0.94], 0.001


class VisualTechnicalErrorTests(unittest.TestCase):
    def test_master_and_spanish_duration_boundaries_are_fail_closed(self):
        verifier = PassingVisualVerifier()
        master_core = visual_module.build_measurement_core(99.95, "pelicula")
        master_exact = verifier.score_candidate(
            "ref.mkv",
            "esp.mkv",
            master_core["end_sec"] - 2.0,
            0,
            ref_duration=99.95,
            esp_duration=100.0,
        )
        master_outside = verifier.score_candidate(
            "ref.mkv",
            "esp.mkv",
            master_core["end_sec"] - 2.0,
            0,
            ref_duration=99.7,
            esp_duration=100.0,
        )
        spanish_exact = verifier.score_candidate(
            "ref.mkv",
            "esp.mkv",
            10.0,
            0,
            tempo=2.0,
            ref_duration=20.0,
            esp_duration=23.95,
        )
        spanish_outside = verifier.score_candidate(
            "ref.mkv",
            "esp.mkv",
            10.0,
            0,
            tempo=2.0,
            ref_duration=20.0,
            esp_duration=23.949,
        )
        self.assertTrue(master_exact["ok"])
        self.assertEqual(master_outside["error_kind"], "out_of_range")
        self.assertTrue(spanish_exact["ok"])
        self.assertEqual(spanish_outside["error_kind"], "out_of_range")

    def test_out_of_range_candidate_is_expected_rejection(self):
        verifier = FailingVisualVerifier()
        result = verifier.score_candidate(
            "ref.mkv",
            "esp.mkv",
            0.0,
            1000,
            ref_duration=100.0,
            esp_duration=100.0,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_kind"], "out_of_range")

    def test_internal_ssim_failure_is_technical_error(self):
        verifier = FailingVisualVerifier()
        with self.assertRaisesRegex(RuntimeError, "Fallo técnico visual SSIM"):
            verifier.score_candidate(
                "ref.mkv",
                "esp.mkv",
                50.0,
                0,
                ref_duration=100.0,
                esp_duration=100.0,
            )


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


class CandidateEquivalenceTests(unittest.TestCase):
    @staticmethod
    def equivalence(candidates, ref_fps, esp_fps=None, tempo=1.0, ref_vfr=False, esp_vfr=False):
        return visual_module._visual_candidate_equivalence(
            candidates,
            fake_meta("ref", 100.0, ref_fps, vfr=ref_vfr),
            fake_meta("esp", 100.0, esp_fps or ref_fps, vfr=esp_vfr),
            tempo,
        )

    def test_integer_offsets_strictly_inside_half_frame_are_grouped(self):
        cases = (
            (24000 / 1001, 20, 21),
            (24.0, 20, 21),
            (25.0, 19, 20),
            (30.0, 16, 17),
            (60.0, 8, 9),
        )
        for fps, inside, outside in cases:
            for sign in (-1, 1):
                with self.subTest(fps=fps, sign=sign, position="inside"):
                    grouped = self.equivalence([sign * inside, 0], fps)
                    self.assertTrue(grouped["applied"])
                    self.assertEqual(grouped["effective_candidates_ms"], [sign * inside])
                with self.subTest(fps=fps, sign=sign, position="outside"):
                    separate = self.equivalence([sign * outside, 0], fps)
                    self.assertFalse(separate["applied"])
                    self.assertEqual(separate["effective_candidates_ms"], [sign * outside, 0])

    def test_cross_fps_uses_reference_timeline_after_tempo(self):
        for ref_fps, esp_fps in ((24000 / 1001, 25.0), (25.0, 24000 / 1001)):
            tempo = ref_fps / esp_fps
            with self.subTest(ref_fps=ref_fps, esp_fps=esp_fps):
                inside = 19 if ref_fps == 25.0 else 20
                grouped = self.equivalence([inside, 0], ref_fps, esp_fps, tempo)
                self.assertTrue(grouped["applied"])
                self.assertAlmostEqual(grouped["effective_esp_fps"], ref_fps, places=6)

    def test_first_candidate_is_preserved_as_exact_representative(self):
        measured_first = self.equivalence([-20, 0], 24.0)
        zero_first = self.equivalence([0, -20], 24.0)
        self.assertEqual(measured_first["effective_candidates_ms"], [-20])
        self.assertEqual(measured_first["zero_representative_ms"], -20)
        self.assertEqual(zero_first["effective_candidates_ms"], [0])
        self.assertEqual(zero_first["zero_representative_ms"], 0)

    def test_exact_half_frame_boundary_is_not_grouped(self):
        for sign in (-1, 1):
            with self.subTest(sign=sign):
                result = self.equivalence([sign * 20, 0], 25.0)
                self.assertFalse(result["applied"])
                self.assertEqual(result["boundary"], "strict")

    def test_grouping_never_chains_across_more_than_half_frame(self):
        for ordered in permutations((0, 20, 40)):
            with self.subTest(ordered=ordered):
                result = self.equivalence(ordered, 24.0)
                self.assertEqual(len(result["effective_candidates_ms"]), 2)
                for group in result["groups"]:
                    self.assertLess(max(group["members_ms"]) - min(group["members_ms"]), result["threshold_ms"])

    def test_large_and_full_frame_delays_remain_separate(self):
        for delay in (42, 160, 400, 1000, 5000, 15000):
            with self.subTest(delay=delay):
                result = self.equivalence([delay, 0], 24000 / 1001)
                self.assertFalse(result["applied"])
                self.assertEqual(result["effective_candidates_ms"], [delay, 0])

    def test_vfr_disables_equivalence_fail_closed(self):
        for ref_vfr, esp_vfr in ((True, False), (False, True)):
            with self.subTest(ref_vfr=ref_vfr, esp_vfr=esp_vfr):
                result = self.equivalence([-20, 0], 24.0, ref_vfr=ref_vfr, esp_vfr=esp_vfr)
                self.assertFalse(result["applied"])
                self.assertEqual(result["reason"], "disabled_variable_frame_rate")
                self.assertEqual(result["effective_candidates_ms"], [-20, 0])

    def test_implicit_zero_is_grouped_without_becoming_a_base_candidate(self):
        result = self.equivalence([-20], 24.0)
        self.assertTrue(result["applied"])
        self.assertTrue(result["implicit_zero_added"])
        self.assertEqual(result["input_candidates_ms"], [-20])
        self.assertEqual(result["effective_candidates_ms"], [-20])
        self.assertEqual(result["groups"][0]["members_ms"], [-20, 0])

    def test_implicit_zero_stays_separate_outside_half_frame(self):
        result = self.equivalence([-21], 24.0)
        self.assertFalse(result["applied"])
        self.assertFalse(result["implicit_zero_added"])
        self.assertEqual(result["effective_candidates_ms"], [-21])


class FrameAwareVisualVerifier(VisualVerifier):
    def __init__(
        self,
        primary=-20,
        secondary=None,
        fps=24.0,
        vfr=False,
        lose_first_zone=False,
        primary_score=0.70,
        secondary_score=0.50,
        zero_score=0.70,
        control_score=0.40,
    ):
        super().__init__()
        self.primary = int(primary)
        self.secondary = int(secondary) if secondary is not None else None
        self.fps = float(fps)
        self.vfr = bool(vfr)
        self.lose_first_zone = bool(lose_first_zone)
        self.primary_score = float(primary_score)
        self.secondary_score = float(secondary_score)
        self.zero_score = float(zero_score)
        self.control_score = float(control_score)

    def probe_video(self, path):
        return fake_meta(path, 100.0, self.fps, vfr=self.vfr)

    def score_candidate(self, ref_video, esp_video_original, ref_time, delay_ms, *args, **kwargs):
        delay = int(delay_ms)
        if delay == self.primary:
            score = 0.30 if self.lose_first_zone and ref_time < 40.0 else self.primary_score
        elif delay == 0:
            score = self.zero_score
        elif self.secondary is not None and delay == self.secondary:
            score = self.secondary_score
        else:
            score = self.control_score
        return {"ok": True, "mean_ssim": score, "frames": 4}


class FrameAwareVisualIntegrationTests(unittest.TestCase):
    def test_current_subframe_case_groups_zero_and_verifies_against_real_rival(self):
        result = FrameAwareVisualVerifier(secondary=-280).score_candidates(
            "ref",
            "esp",
            [-20, -280, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [-20, -280])
        self.assertEqual(result["candidate_equivalence"]["groups"][0]["members_ms"], [-20, 0])
        self.assertTrue(result["verified"])
        self.assertEqual(result["verification_mode"], "relative")
        self.assertEqual(result["relative_target_delay_ms"], -20)
        self.assertEqual(result["relative_reference_delay_ms"], -280)
        self.assertEqual(result["relative_reference_kind"], "candidate")
        self.assertGreaterEqual(result["relative_wins"], 2)
        self.assertEqual(result["relative_losses"], 0)
        self.assertTrue(all("0" not in zone["raw"] for zone in result["zones"]))

    def test_all_collapsed_rivals_must_beat_external_controls(self):
        result = FrameAwareVisualVerifier().score_candidates(
            "ref",
            "esp",
            [-20, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [-20])
        self.assertEqual(result["candidate_equivalence"]["external_relative_controls_ms"], [-420, 380])
        self.assertEqual(result["relative_reference_kind"], "external_control")
        self.assertTrue(result["relative_match"])
        self.assertEqual(result["verification_mode"], "relative")
        self.assertTrue(all("0" not in zone["raw"] for zone in result["zones"]))

    def test_external_control_loss_still_blocks(self):
        result = FrameAwareVisualVerifier(lose_first_zone=True).score_candidates(
            "ref",
            "esp",
            [-20, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertGreaterEqual(result["relative_losses"], 1)
        self.assertFalse(result["relative_match"])
        self.assertFalse(result["verified"])

    def test_nearly_tied_real_rival_blocks_absolute_and_relative_paths(self):
        result = FrameAwareVisualVerifier(
            secondary=-280,
            primary_score=0.95,
            secondary_score=0.94,
            zero_score=0.95,
        ).score_candidates(
            "ref",
            "esp",
            [-20, -280, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [-20, -280])
        self.assertFalse(result["strong_winner"])
        self.assertFalse(result["relative_match"])
        self.assertFalse(result["verified"])

    def test_nearby_nonzero_candidates_do_not_receive_external_controls(self):
        result = FrameAwareVisualVerifier(primary=1000, secondary=1010).score_candidates(
            "ref",
            "esp",
            [1000, 1010],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [1000])
        self.assertEqual(result["candidate_equivalence"]["external_relative_controls_ms"], [])
        self.assertNotEqual(result["relative_reference_kind"], "external_control")
        self.assertFalse(result["verified"])

    def test_single_subframe_candidate_groups_implicit_zero_and_uses_controls(self):
        result = FrameAwareVisualVerifier().score_candidates(
            "ref",
            "esp",
            [-20],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [-20])
        self.assertTrue(result["candidate_equivalence"]["implicit_zero_added"])
        self.assertEqual(result["relative_reference_kind"], "external_control")
        self.assertTrue(result["relative_match"])
        self.assertTrue(result["verified"])

    def test_just_outside_half_frame_remains_a_real_rival(self):
        result = FrameAwareVisualVerifier(primary=-21).score_candidates(
            "ref",
            "esp",
            [-21, 0],
            "pelicula",
            stage="visual_final",
        )
        self.assertEqual(result["candidate_delays_ms"], [-21, 0])
        self.assertFalse(result["candidate_equivalence"]["applied"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["relative_ties"], result["relative_comparable_zones"])

    def test_single_zero_candidate_gets_no_new_relative_authorization(self):
        result = FrameAwareVisualVerifier(primary=0).score_candidates(
            "ref",
            "esp",
            [0],
            "pelicula",
            stage="visual_final",
        )
        self.assertFalse(result["candidate_equivalence"]["applied"])
        self.assertEqual(result["candidate_equivalence"]["external_relative_controls_ms"], [])
        self.assertFalse(result["relative_match"])
        self.assertFalse(result["verified"])


class FpsConfirmationTests(unittest.TestCase):
    def assert_confirmed_pair(self, ref_fps, esp_fps):
        tempo = ref_fps / esp_fps
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100.0, ref_fps),
            fake_meta("esp", 100.0 * tempo, esp_fps),
        )
        result = verifier.confirm_fps_plan(
            "ref",
            "esp",
            ref_fps,
            esp_fps,
            "pelicula",
            audio_evidence={"stable": True},
        )
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

    def test_duration_difference_is_only_preliminary_and_audio_still_blocks(self):
        verifier = DeterministicFpsVerifier(fake_meta("ref", 100, 24), fake_meta("esp", 100, 25))
        result = verifier.confirm_fps_plan("ref", "esp", 24, 25, "pelicula")
        self.assertFalse(result["confirmed"])
        self.assertTrue(result["provisional"])
        self.assertFalse(result["duration"]["match"])
        self.assertEqual(result["reason"], "audio_corregido_no_confirma_tempo")

    def test_duration_difference_can_confirm_when_interior_evidence_converges(self):
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100.0, 24.0),
            fake_meta("esp", 100.0, 25.0),
        )
        result = verifier.confirm_fps_plan(
            "ref",
            "esp",
            24.0,
            25.0,
            "pelicula",
            800,
            {"stable": True},
        )
        self.assertFalse(result["duration"]["match"])
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["reason"], "interior_timeline_audio_and_visual_match")

    def test_compatible_duration_is_still_rejected_without_absolute_or_relative_visual_support(self):
        ref_fps = 24000 / 1001
        esp_fps = 25.0
        tempo = ref_fps / esp_fps
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100.0, ref_fps),
            fake_meta("esp", 100.0 * tempo, esp_fps),
            planned_score=0.44,
            nominal_score=0.40,
        )
        result = verifier.confirm_fps_plan(
            "ref",
            "esp",
            ref_fps,
            esp_fps,
            "pelicula",
            audio_evidence={"stable": True},
        )
        self.assertTrue(result["duration"]["match"])
        self.assertFalse(result["visual"]["match"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["reason"], "imagen_no_confirma_tempo")

    def test_low_absolute_ssim_can_confirm_with_clear_consistent_relative_gain(self):
        ref_fps = 24000 / 1001
        esp_fps = 25.0
        tempo = ref_fps / esp_fps
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100.0, ref_fps),
            fake_meta("esp", 100.0 * tempo, esp_fps),
            planned_score=0.55,
            nominal_score=0.40,
        )
        result = verifier.confirm_fps_plan(
            "ref",
            "esp",
            ref_fps,
            esp_fps,
            "pelicula",
            800,
            {"stable": True},
        )
        self.assertTrue(result["confirmed"])
        self.assertFalse(result["visual"]["absolute_match"])
        self.assertTrue(result["visual"]["relative_match"])
        self.assertEqual(result["reason"], "duration_audio_drift_and_visual_match")

    def test_vfr_is_not_automatically_confirmed(self):
        tempo = (24000 / 1001) / 24
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100, 24000 / 1001, vfr=True),
            fake_meta("esp", 100 * tempo, 24),
        )
        result = verifier.confirm_fps_plan("ref", "esp", 24000 / 1001, 24, "pelicula")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["reason"], "vfr_no_confirmado")

    def test_vfr_in_spanish_video_is_not_automatically_confirmed(self):
        tempo = (24000 / 1001) / 24
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 100, 24000 / 1001),
            fake_meta("esp", 100 * tempo, 24, vfr=True),
        )
        result = verifier.confirm_fps_plan("ref", "esp", 24000 / 1001, 24, "pelicula")
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["reason"], "vfr_no_confirmado")

    def test_probe_video_detects_vfr_from_average_and_real_rates(self):
        payload = (
            '{"streams":[{"duration":"100.0","avg_frame_rate":"24000/1001",'
            '"r_frame_rate":"24/1","width":1920,"height":1080,'
            '"pix_fmt":"yuv420p","color_transfer":"bt709"}],'
            '"format":{"duration":"100.0"}}'
        )
        proc = SimpleNamespace(returncode=0, stdout=payload, stderr="")
        with (
            patch.object(visual_module.os.path, "isfile", return_value=True),
            patch.object(visual_module.subprocess, "run", return_value=proc),
        ):
            metadata = VisualVerifier().probe_video("video.mkv")
        self.assertAlmostEqual(metadata.avg_fps, 24000 / 1001, places=9)
        self.assertEqual(metadata.real_fps, 24.0)
        self.assertTrue(metadata.variable_frame_rate)


class PreviewPlanTests(unittest.TestCase):
    def test_movie_preview_is_central_and_maps_tempo_and_hint(self):
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 7200.0, 24.0),
            fake_meta("esp", 7500.0, 25.0),
        )
        plan = verifier.preview_plan("ref", "esp", "pelicula", 2000)
        self.assertEqual(plan["profile"], "pelicula")
        self.assertEqual(plan["preview_duration_sec"], 30.0)
        self.assertGreater(plan["reference_clip_start_sec"], 3000.0)
        self.assertNotEqual(plan["reference_clip_start_sec"], 0.0)
        self.assertAlmostEqual(plan["tempo"], 0.96, places=9)
        mapped_base = (plan["reference_clip_start_sec"] - 2.0) * 0.96
        expected_start = mapped_base - 24.0 * 0.96
        self.assertAlmostEqual(plan["spanish_clip_start_sec"], expected_start, places=6)
        self.assertEqual(plan["spanish_preview_duration_sec"], 54.0)
        self.assertEqual(plan["spanish_neutral_offset_sec"], 24.0)
        self.assertEqual(plan["relative_min_offset_ms"], -24000)
        self.assertEqual(plan["relative_max_offset_ms"], 24000)
        self.assertEqual(plan["delay_hint_ms"], 2000)

    def test_trailer_preview_uses_short_profile_and_core(self):
        verifier = DeterministicFpsVerifier(
            fake_meta("ref", 90.0, 24.0),
            fake_meta("esp", 90.0, 24.0),
        )
        plan = verifier.preview_plan("ref", "esp", "trailer", 0)
        self.assertEqual(plan["preview_duration_sec"], 12.0)
        self.assertEqual(plan["core_start_sec"], 4.0)
        self.assertEqual(plan["core_end_sec"], 86.0)
        self.assertGreater(plan["reference_clip_start_sec"], 0.0)
        self.assertLess(plan["window_sec"], plan["preview_duration_sec"])
        self.assertEqual(plan["spanish_preview_duration_sec"], 20.0)
        self.assertEqual(plan["spanish_neutral_offset_sec"], 8.0)
        self.assertEqual(plan["relative_min_offset_ms"], -8000)
        self.assertEqual(plan["relative_max_offset_ms"], 8000)


class ReplacementVisualVerifier(VisualVerifier):
    def __init__(self, event_callback=None):
        super().__init__(event_callback=event_callback)

    def probe_video(self, path):
        return fake_meta(path, 100.0, 24.0)

    def score_candidate(self, ref_video, esp_video_original, ref_time, delay_ms, *args, **kwargs):
        initial = any(abs(ref_time - value) < 0.001 for value in (30.8, 50.0, 69.2))
        score = 0.30 if initial else (0.95 if int(delay_ms) == 0 else 0.40)
        return {"ok": True, "mean_ssim": score, "frames": 4}


class VisualReplacementTests(unittest.TestCase):
    def test_useless_initial_zones_do_not_count_and_are_replaced(self):
        events = []
        verifier = ReplacementVisualVerifier(
            event_callback=lambda phase, event, data: events.append((phase, event, data))
        )
        result = verifier.score_candidates("ref", "esp", [0], "pelicula")
        initial = [zone for zone in result["zones"] if zone["origin"] == "initial"]
        replacements = [event for event in events if event[1] == "zone_replaced"]
        self.assertEqual([zone["state"] for zone in initial], ["INUTIL", "INUTIL", "INUTIL"])
        self.assertEqual(result["zones_valid"], 3)
        self.assertEqual(result["winner_delay_ms"], 0)
        self.assertTrue(result["strong_winner"])
        self.assertEqual(result["candidates"][0]["wins"], 3)
        self.assertEqual(len(replacements), 3)


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
