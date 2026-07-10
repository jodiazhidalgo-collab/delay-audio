import json
import math
import os
import random
import shutil
import sys
import unittest
import uuid
import wave
from array import array


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
MOTOR_ROOT = os.path.join(APP_ROOT, "motor", "delay_audio")
for path in (APP_ROOT, MOTOR_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from api.modulos.delay_audio.routes import contrato_resultado_hibrido_valido  # noqa: E402
from medir_delay_audio import DelayAudio  # noqa: E402


class FakeVisualVerifier:
    def __init__(self, winner, strong=True, zones_valid=3):
        self.winner = winner
        self.strong = strong
        self.zones_valid = zones_valid

    def score_candidates(self, ref, esp, candidates, profile="pelicula", tempo=1.0, stage="visual_fast_path"):
        return {
            "ok": True,
            "stage": stage,
            "profile": profile,
            "tempo": tempo,
            "candidate_delays_ms": list(candidates),
            "zones_attempted": self.zones_valid,
            "zones_valid": self.zones_valid,
            "zones_strong": self.zones_valid if self.strong else 0,
            "winner_delay_ms": self.winner,
            "unique_winner": self.strong,
            "strong_winner": self.strong,
            "candidates": [{"delay_ms": self.winner, "wins": self.zones_valid}],
            "zones": [],
            "duration_sec": 0.125,
        }


class DeterministicFastMotor(DelayAudio):
    def __init__(self, job_dir, profile, hint, winner, audio_delays, scores=None, strong=True, fps_planned=False, fps_confirmed=False):
        super().__init__(
            "ref.mkv",
            "esp.mkv",
            job_dir,
            ref_audio_index=0,
            esp_audio_index=0,
            profile=profile,
            delay_hint_ms=hint,
            esp_video_original="esp-original.mkv",
            fps_ref=24000 / 1001 if fps_planned else 24.0,
            fps_esp=24.0,
            fps_tempo=(24000 / 1001) / 24.0 if fps_planned else 1.0,
            fps_plan_enabled=fps_planned,
            fps_plan_confirmed=fps_confirmed,
            hybrid_enabled=True,
        )
        self.fake_winner = winner
        self.fake_strong = strong
        self.audio_delays = list(audio_delays)
        self.audio_scores = list(scores or [0.72] * len(self.audio_delays))
        self.audio_calls = []

    def create_visual_verifier(self):
        return FakeVisualVerifier(self.fake_winner, self.fake_strong, 3 if self.profile == "pelicula" else 2)

    def analyze_zone(self, zone_number, start_sec, ref_index, esp_index, work_dir, **kwargs):
        self.audio_calls.append({"zone": zone_number, "start_sec": start_sec, **kwargs})
        index = zone_number - 1
        if index >= len(self.audio_delays):
            raise RuntimeError("Audio casi plano o silencioso.")
        delay = int(self.audio_delays[index])
        score = float(self.audio_scores[index])
        return {
            "zone": zone_number,
            "start_sec": float(start_sec),
            "start_text": "00:00:00",
            "esp_start_sec": float(kwargs.get("esp_start_sec") or 0.0),
            "delay_ms": delay,
            "residual_delay_ms": delay - int(kwargs.get("search_center_ms") or 0),
            "score": score,
            "score_gap": 0.02,
            "confidence": "ALTA" if score >= 0.48 else "MEDIA",
            "search_center_ms": int(kwargs.get("search_center_ms") or 0),
            "search_min_ms": int(kwargs.get("search_center_ms") or 0) - int(kwargs.get("search_radius_ms") or 0),
            "search_max_ms": int(kwargs.get("search_center_ms") or 0) + int(kwargs.get("search_radius_ms") or 0),
        }


class HybridFastPathTests(unittest.TestCase):
    def run_case(
        self,
        profile="pelicula",
        hint=0,
        winner=0,
        audio_delays=(0, 0),
        scores=None,
        strong=True,
        fps_planned=False,
        fps_confirmed=False,
        duration=120.0,
    ):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        job_dir = os.path.join(runtime_root, f"phase4-unit-{uuid.uuid4().hex}")
        motor = DeterministicFastMotor(
            job_dir,
            profile,
            hint,
            winner,
            audio_delays,
            scores=scores,
            strong=strong,
            fps_planned=fps_planned,
            fps_confirmed=fps_confirmed,
        )
        try:
            motor.reset_logs()
            motor.diag.init(inputs={"synthetic": True}, settings={"hybrid_enabled": True})
            returncode = motor.run_hybrid_fast_path(duration, duration, 0, 0)
            with open(motor.result_path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            return motor, returncode, result
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def assert_verified(self, result, expected_delay):
        self.assertEqual(result["state"], "OK_VERIFICADO")
        self.assertTrue(result["export_allowed"])
        self.assertEqual(result["confidence"], "ALTA")
        self.assertEqual(result["delay_ms"], expected_delay)
        self.assertGreaterEqual(result["audio"]["supporting_zones"], 2)
        self.assertTrue(result["visual"]["verified"])
        self.assertTrue(contrato_resultado_hibrido_valido(result))

    def test_aligned_movie_finishes_after_two_audio_zones(self):
        motor, returncode, result = self.run_case()
        self.assertEqual(returncode, 0)
        self.assert_verified(result, 0)
        self.assertEqual(len(motor.audio_calls), 2)
        self.assertEqual(result["audio"]["segment_sec"], 25.0)
        self.assertEqual(result["audio"]["radius_ms"], 2000)

    def test_correct_hint_uses_wider_narrow_radius(self):
        motor, _, result = self.run_case(hint=3000, winner=3000, audio_delays=(3000, 3000))
        self.assert_verified(result, 3000)
        self.assertEqual(result["audio"]["radius_ms"], 6000)
        self.assertEqual({call["search_center_ms"] for call in motor.audio_calls}, {3000})

    def test_wrong_hint_loses_to_zero_and_uses_normal_radius(self):
        motor, _, result = self.run_case(hint=3000, winner=0, audio_delays=(0, 0))
        self.assert_verified(result, 0)
        self.assertEqual(result["audio"]["radius_ms"], 2000)
        self.assertEqual(result["visual"]["candidate_delays_ms"], [0, 3000])
        self.assertEqual({call["search_center_ms"] for call in motor.audio_calls}, {0})

    def test_positive_delay_keeps_sign(self):
        _, _, result = self.run_case(hint=1000, winner=1000, audio_delays=(1000, 1000))
        self.assert_verified(result, 1000)

    def test_negative_delay_keeps_sign(self):
        _, _, result = self.run_case(hint=-1000, winner=-1000, audio_delays=(-1000, -1000))
        self.assert_verified(result, -1000)

    def test_aligned_trailer_uses_short_segments(self):
        _, _, result = self.run_case(profile="trailer", duration=60.0)
        self.assert_verified(result, 0)
        self.assertGreaterEqual(result["audio"]["segment_sec"], 6.0)
        self.assertLessEqual(result["audio"]["segment_sec"], 8.0)
        self.assertEqual(result["audio"]["radius_ms"], 1500)

    def test_trailer_with_known_delay(self):
        _, _, result = self.run_case(profile="trailer", hint=1200, winner=1200, audio_delays=(1200, 1200), duration=60.0)
        self.assert_verified(result, 1200)
        self.assertEqual(result["audio"]["radius_ms"], 4000)

    def test_one_audio_zone_never_verifies(self):
        _, _, result = self.run_case(audio_delays=(0,))
        self.assertNotEqual(result["state"], "OK_VERIFICADO")
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["audio"]["supporting_zones"], 1)

    def test_without_strong_visual_winner_runs_discovery_but_never_fast_accepts(self):
        motor, _, result = self.run_case(strong=False)
        self.assertIn(result["state"], {"NO_FIABLE", "SIN_ZONAS_VALIDAS"})
        self.assertFalse(result["export_allowed"])
        self.assertGreaterEqual(len(motor.audio_calls), 2)
        self.assertEqual(result["stage"], "adaptive_discovery")

    def test_unconfirmed_fps_plan_cannot_verify(self):
        _, _, result = self.run_case(fps_planned=True, fps_confirmed=False)
        self.assertNotEqual(result["state"], "OK_VERIFICADO")
        self.assertFalse(result["export_allowed"])
        self.assertIn("fps_plan_not_confirmed", result["decision"]["contradictions"])

    def test_audio_that_agrees_with_itself_but_not_image_is_blocked_as_mismatch(self):
        _, _, result = self.run_case(winner=0, audio_delays=(1000, 1000))
        self.assertEqual(result["state"], "AUDIO_VIDEO_ORIGEN_DUDOSO")
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["audio"]["supporting_zones"], 2)
        self.assertIn("audio_does_not_support_visual_winner", result["decision"]["contradictions"])

    def test_two_low_audio_scores_cannot_authorize(self):
        _, _, result = self.run_case(scores=(0.35, 0.35))
        self.assertNotEqual(result["state"], "OK_VERIFICADO")
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["audio"]["supporting_zones"], 2)
        self.assertIn("audio_does_not_support_visual_winner", result["decision"]["contradictions"])

    def test_short_trailer_does_not_count_overlapping_windows_twice(self):
        _, _, result = self.run_case(profile="trailer", duration=10.0)
        self.assertEqual(result["state"], "SIN_ZONAS_VALIDAS")
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["audio"]["supporting_zones"], 0)


class FastAudioZoneTests(unittest.TestCase):
    def test_zone_mapping_preserves_positive_and_negative_centers(self):
        for center in (-6000, 6000):
            with self.subTest(center=center):
                zones = DelayAudio.build_fast_audio_zones(120.0, 120.0, 25.0, center, [30.0, 70.0])
                self.assertEqual(len(zones), 2)
                for zone in zones:
                    mapped = round((zone["ref_start_sec"] - zone["esp_start_sec"]) * 1000)
                    self.assertEqual(mapped, center)

    def test_audio_clusters_prefer_repeated_candidate(self):
        rows = [
            {"delay_ms": 1000, "score": 0.70},
            {"delay_ms": 1080, "score": 0.65},
            {"delay_ms": -500, "score": 0.95},
        ]
        clusters = DelayAudio.cluster_audio_rows(rows, 180, 0.18)
        self.assertEqual(clusters[0]["count"], 2)
        self.assertGreaterEqual(clusters[0]["delay_ms"], 1000)
        self.assertLessEqual(clusters[0]["delay_ms"], 1080)

    def test_short_windows_must_be_independent(self):
        zones = DelayAudio.build_fast_audio_zones(10.0, 10.0, 6.0, 0, [35.0, 70.0])
        self.assertLess(len(zones), 2)

    def test_cleanup_refuses_to_report_success_when_path_remains(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        fake_dir = os.path.join(runtime_root, f"phase4-cleanup-{uuid.uuid4().hex}")
        with open(fake_dir, "w", encoding="utf-8") as handle:
            handle.write("not-a-directory")
        try:
            with self.assertRaises(RuntimeError):
                DelayAudio.remove_work_dir_checked(fake_dir)
        finally:
            if os.path.exists(fake_dir):
                os.remove(fake_dir)


class ProductiveAudioSignTests(unittest.TestCase):
    @staticmethod
    def write_wave(path, samples, sample_rate=8000):
        payload = array("h", samples)
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(payload.tobytes())

    @staticmethod
    def reference_signal(seconds=18, sample_rate=8000):
        rng = random.Random(20260710)
        frame_samples = 160
        frames = int(seconds * sample_rate / frame_samples)
        samples = []
        for frame in range(frames):
            amplitude = rng.randint(1200, 26000)
            frequency = 180 + (frame % 23) * 17
            for index in range(frame_samples):
                value = amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate)
                samples.append(int(max(-32767, min(32767, value))))
        return samples

    def test_real_ffmpeg_correlation_adds_positive_and_negative_residual(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        job_dir = os.path.join(runtime_root, f"phase4-sign-{uuid.uuid4().hex}")
        os.makedirs(job_dir, exist_ok=True)
        ref_path = os.path.join(job_dir, "ref.wav")
        shift_samples = int(1.2 * 8000)
        reference = self.reference_signal()
        plus = reference[shift_samples:] + [0] * shift_samples
        minus = [0] * shift_samples + reference[:-shift_samples]
        plus_path = os.path.join(job_dir, "plus.wav")
        minus_path = os.path.join(job_dir, "minus.wav")
        self.write_wave(ref_path, reference)
        self.write_wave(plus_path, plus)
        self.write_wave(minus_path, minus)
        try:
            observed = {}
            for label, esp_path, center_ms, esp_start, expected in (
                ("positive", plus_path, 1000, 5.0, 1200),
                ("negative", minus_path, -1000, 7.0, -1200),
            ):
                case_dir = os.path.join(job_dir, label)
                work_dir = os.path.join(case_dir, "tmp")
                os.makedirs(work_dir, exist_ok=True)
                motor = DelayAudio(ref_path, esp_path, case_dir, ref_audio_index=0, esp_audio_index=0)
                motor.reset_logs()
                motor.diag.command = lambda *args, **kwargs: None
                row = motor.analyze_zone(
                    1,
                    6.0,
                    0,
                    0,
                    work_dir,
                    segment_sec=6.0,
                    search_center_ms=center_ms,
                    search_radius_ms=500,
                    esp_start_sec=esp_start,
                )
                observed[label] = row["delay_ms"]
                self.assertLessEqual(abs(row["delay_ms"] - expected), 40)
            self.assertGreater(observed["positive"], 0)
            self.assertLess(observed["negative"], 0)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
