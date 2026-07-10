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


class StagedVisualVerifier:
    def __init__(self, motor):
        self.motor = motor

    def score_candidates(self, ref, esp, candidates, profile="pelicula", tempo=1.0, stage="visual_fast_path"):
        self.motor.visual_calls.append({"stage": stage, "candidates": list(candidates), "esp": esp})
        if stage == "visual_fast_path":
            winner = self.motor.fast_visual_winner
            strong = self.motor.fast_visual_strong
        else:
            winner = self.motor.final_visual_winner
            strong = self.motor.final_visual_strong
        required = 2 if profile == "trailer" else 3
        zones = []
        if stage == "visual_final" and self.motor.mixed_visual_winners and len(candidates) >= 2:
            for index in range(required):
                zones.append({
                    "state": "VALIDA",
                    "winner_delay_ms": int(candidates[index % 2]),
                })
        else:
            zones = [{"state": "FUERTE", "winner_delay_ms": winner} for _ in range(required)]
        return {
            "ok": True,
            "stage": stage,
            "profile": profile,
            "tempo": tempo,
            "candidate_delays_ms": list(candidates),
            "zones_attempted": required,
            "zones_valid": required,
            "zones_strong": required if strong else 0,
            "winner_delay_ms": winner,
            "unique_winner": strong,
            "strong_winner": strong,
            "candidates": [
                {"delay_ms": int(candidate), "wins": required if int(candidate) == int(winner or 0) else 0, "mean_ssim": 0.95}
                for candidate in candidates
            ],
            "zones": zones,
            "duration_sec": 0.1,
        }


class DeterministicDiscoveryMotor(DelayAudio):
    def __init__(
        self,
        job_dir,
        profile="pelicula",
        hint=0,
        fast_visual_winner=0,
        fast_visual_strong=False,
        final_visual_winner=3000,
        final_visual_strong=True,
        fast_audio_delays=(),
        discovery_delays=(3000, 3000, 3000, 3000),
        discovery_scores=None,
        mixed_visual_winners=False,
        technical_discovery_error=False,
    ):
        super().__init__(
            "ref.mkv",
            "esp-audio.mka",
            job_dir,
            ref_audio_index=0,
            esp_audio_index=0,
            profile=profile,
            delay_hint_ms=hint,
            esp_video_original="esp-video-original.mkv",
            hybrid_enabled=True,
        )
        self.fast_visual_winner = fast_visual_winner
        self.fast_visual_strong = fast_visual_strong
        self.final_visual_winner = final_visual_winner
        self.final_visual_strong = final_visual_strong
        self.fast_audio_delays = list(fast_audio_delays)
        self.discovery_delays = list(discovery_delays)
        self.discovery_scores = list(discovery_scores or [0.72] * len(self.discovery_delays))
        self.mixed_visual_winners = mixed_visual_winners
        self.technical_discovery_error = technical_discovery_error
        self.fast_audio_calls = 0
        self.discovery_audio_calls = 0
        self.visual_calls = []

    def create_visual_verifier(self):
        return StagedVisualVerifier(self)

    def analyze_zone(self, zone_number, start_sec, ref_index, esp_index, work_dir, **kwargs):
        discovery = kwargs.get("residual_min_ms") is not None
        if discovery:
            if self.technical_discovery_error:
                raise PermissionError("permiso denegado al leer el audio")
            index = self.discovery_audio_calls
            self.discovery_audio_calls += 1
            if index >= len(self.discovery_delays):
                raise RuntimeError("Audio casi plano o silencioso.")
            delay = int(self.discovery_delays[index])
            score = float(self.discovery_scores[index])
        else:
            index = self.fast_audio_calls
            self.fast_audio_calls += 1
            if index >= len(self.fast_audio_delays):
                raise RuntimeError("Audio casi plano o silencioso.")
            delay = int(self.fast_audio_delays[index])
            score = 0.72
        return {
            "zone": int(zone_number),
            "start_sec": float(start_sec),
            "start_text": "00:00:00",
            "esp_start_sec": float(kwargs.get("esp_start_sec") or 0.0),
            "delay_ms": delay,
            "residual_delay_ms": delay - int(kwargs.get("search_center_ms") or 0),
            "score": score,
            "score_gap": 0.02,
            "confidence": "ALTA" if score >= 0.48 else "MEDIA",
            "search_center_ms": int(kwargs.get("search_center_ms") or 0),
            "search_min_ms": -45000,
            "search_max_ms": 45000,
        }


class HybridDiscoveryTests(unittest.TestCase):
    def run_case(self, duration=300.0, **kwargs):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        job_dir = os.path.join(runtime_root, f"phase5-unit-{uuid.uuid4().hex}")
        motor = DeterministicDiscoveryMotor(job_dir, **kwargs)
        try:
            motor.reset_logs()
            motor.diag.init(inputs={"synthetic": True}, settings={"hybrid_enabled": True})
            returncode = motor.run_hybrid_fast_path(duration, duration, 0, 0)
            with open(motor.result_path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            return motor, returncode, result
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_unknown_delay_is_discovered_ranked_and_verified(self):
        motor, returncode, result = self.run_case()
        self.assertEqual(returncode, 0)
        self.assertEqual(result["state"], "OK_VERIFICADO")
        self.assertTrue(result["export_allowed"])
        self.assertEqual(result["delay_ms"], 3000)
        self.assertEqual(result["stage"], "adaptive_discovery")
        self.assertEqual(result["audio"]["supporting_zones"], 4)
        self.assertFalse(result["audio"]["expanded"])
        self.assertLessEqual(len(result["audio"]["candidate_delays_ms"]), 4)
        self.assertIn(3000, result["audio"]["candidate_delays_ms"])
        self.assertIn(0, result["audio"]["candidate_delays_ms"])
        self.assertTrue(contrato_resultado_hibrido_valido(result))
        self.assertEqual(motor.discovery_audio_calls, 4)

    def test_audio_and_image_with_different_delays_are_origin_doubtful(self):
        _, _, result = self.run_case(
            fast_visual_winner=0,
            fast_visual_strong=True,
            final_visual_winner=0,
            fast_audio_delays=(1000, 1000),
            discovery_delays=(1000, 1000, 1000, 1000),
        )
        self.assertEqual(result["state"], "AUDIO_VIDEO_ORIGEN_DUDOSO")
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["audio"]["delay_ms"], 1000)
        self.assertEqual(result["visual"]["winner_delay_ms"], 0)
        self.assertIn("audio_does_not_support_visual_winner", result["decision"]["contradictions"])

    def test_ambiguous_audio_expands_only_for_recorded_doubt(self):
        motor, _, result = self.run_case(
            final_visual_winner=1000,
            discovery_delays=(1000, 5000, -4000, 12000, 1000, 1000),
        )
        self.assertTrue(result["audio"]["expanded"])
        self.assertEqual(result["audio"]["expansion_reason"], "corroboracion_insuficiente")
        self.assertLessEqual(result["audio"]["zones_attempted"], 8)
        self.assertGreater(result["audio"]["zones_attempted"], 4)
        self.assertEqual(result["state"], "OK_VERIFICADO")
        self.assertEqual(result["audio"]["required_supporting_zones"], 3)
        self.assertEqual(result["audio"]["zones_attempted"], 6)
        self.assertEqual(motor.discovery_audio_calls, result["audio"]["zones_attempted"])

    def test_different_zone_delays_are_classified_as_different_edit(self):
        _, _, result = self.run_case(
            final_visual_winner=0,
            final_visual_strong=False,
            discovery_delays=(-12000, -4000, 5000, 14000, 22000, 30000),
            mixed_visual_winners=True,
        )
        self.assertEqual(result["state"], "MONTAJE_DISTINTO")
        self.assertFalse(result["export_allowed"])

    def test_strong_visual_does_not_hide_a_different_edit(self):
        _, _, result = self.run_case(
            final_visual_winner=0,
            final_visual_strong=True,
            discovery_delays=(-12000, -4000, 5000, 14000, 22000, 30000),
        )
        self.assertEqual(result["state"], "MONTAJE_DISTINTO")
        self.assertFalse(result["export_allowed"])

    def test_isolated_high_score_never_authorizes(self):
        _, _, result = self.run_case(
            final_visual_winner=7000,
            discovery_delays=(7000, -8000, 15000, -20000, 26000, -32000),
            discovery_scores=(0.95, 0.20, 0.20, 0.20, 0.20, 0.20),
        )
        self.assertNotEqual(result["state"], "OK_VERIFICADO")
        self.assertFalse(result["export_allowed"])

    def test_tied_repeated_audio_clusters_never_authorize(self):
        _, _, result = self.run_case(
            final_visual_winner=1000,
            discovery_delays=(1000, 5000, 1000, 5000),
        )
        self.assertEqual(result["state"], "MONTAJE_DISTINTO")
        self.assertFalse(result["export_allowed"])
        self.assertIn("audio_top_clusters_ambiguous", result["decision"]["contradictions"])
        self.assertIn("multiple_repeated_audio_delays", result["decision"]["contradictions"])

    def test_majority_does_not_hide_a_second_repeated_edit(self):
        _, _, result = self.run_case(
            final_visual_winner=1000,
            discovery_delays=(1000, 1500, 1000, 1500, 1000, 1000),
        )
        self.assertEqual(result["state"], "MONTAJE_DISTINTO")
        self.assertFalse(result["export_allowed"])
        self.assertIn("multiple_repeated_audio_delays", result["decision"]["contradictions"])

    def test_two_weak_repeated_clusters_do_not_claim_different_edit(self):
        _, _, result = self.run_case(
            final_visual_winner=0,
            discovery_delays=(1000, 5000, 1000, 5000),
            discovery_scores=(0.20, 0.20, 0.20, 0.20),
        )
        self.assertNotEqual(result["state"], "MONTAJE_DISTINTO")
        self.assertFalse(result["export_allowed"])

    def test_expansion_stops_as_soon_as_the_recorded_doubt_is_resolved(self):
        motor, _, result = self.run_case(
            final_visual_winner=1000,
            discovery_delays=(1000, 5000, -4000, 12000, 1000, 1000, 1000, 1000),
        )
        self.assertTrue(result["audio"]["expanded"])
        self.assertEqual(result["state"], "OK_VERIFICADO")
        self.assertEqual(result["audio"]["required_supporting_zones"], 3)
        self.assertEqual(result["audio"]["zones_attempted"], 6)
        self.assertEqual(motor.discovery_audio_calls, 6)

    def test_two_of_five_after_ambiguity_never_authorize(self):
        _, _, result = self.run_case(
            final_visual_winner=1000,
            discovery_delays=(1000, 5000, -4000, 12000, 1000),
        )
        self.assertEqual(result["audio"]["required_supporting_zones"], 3)
        self.assertEqual(result["audio"]["supporting_zones"], 2)
        self.assertNotEqual(result["state"], "OK_VERIFICADO")
        self.assertFalse(result["export_allowed"])

    def test_cluster_spread_cannot_chain_beyond_tolerance(self):
        rows = [
            {"delay_ms": delay, "score": 0.72}
            for delay in (0, 160, 240)
        ]
        clusters = DelayAudio.cluster_audio_rows(rows, 160, 0.18)
        self.assertEqual(clusters[0]["count"], 2)
        self.assertLessEqual(clusters[0]["spread_ms"], 160)

    def test_technical_discovery_error_is_not_disguised_as_semantic_state(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        job_dir = os.path.join(runtime_root, f"phase5-technical-{uuid.uuid4().hex}")
        motor = DeterministicDiscoveryMotor(job_dir, technical_discovery_error=True)
        try:
            motor.reset_logs()
            motor.diag.init(inputs={"synthetic": True}, settings={"hybrid_enabled": True})
            with self.assertRaisesRegex(RuntimeError, "Fallo técnico en zona de descubrimiento"):
                motor.run_hybrid_fast_path(300.0, 300.0, 0, 0)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_visual_always_receives_original_video_not_audio_mka(self):
        motor, _, _ = self.run_case()
        self.assertGreaterEqual(len(motor.visual_calls), 2)
        self.assertTrue(all(call["esp"].endswith("esp-video-original.mkv") for call in motor.visual_calls))
        self.assertTrue(motor.esp_file.endswith("esp-audio.mka"))


class DiscoveryConfigurationTests(unittest.TestCase):
    def test_movie_defaults_match_phase_five(self):
        motor = DelayAudio("ref", "esp", "job", profile="pelicula")
        settings = motor.discovery_audio_settings(300.0)
        self.assertEqual(settings["initial_zone_pcts"], [12.0, 37.0, 63.0, 88.0])
        self.assertEqual(settings["segment_sec"], 40.0)
        self.assertEqual(settings["radius_ms"], 45000)
        self.assertEqual(settings["tolerance_ms"], 160)
        self.assertEqual(settings["max_audio_zones"], 8)

    def test_trailer_defaults_match_phase_five(self):
        motor = DelayAudio("ref", "esp", "job", profile="trailer")
        settings = motor.discovery_audio_settings(100.0)
        self.assertEqual(settings["initial_zone_pcts"], [20.0, 50.0, 80.0])
        self.assertGreaterEqual(settings["segment_sec"], 8.0)
        self.assertLessEqual(settings["segment_sec"], 12.0)
        self.assertEqual(settings["radius_ms"], 12000)
        self.assertEqual(settings["tolerance_ms"], 120)
        self.assertEqual(settings["max_audio_zones"], 6)

    def test_discovery_window_maps_absolute_search_range(self):
        motor = DelayAudio("ref", "esp", "job", profile="pelicula")
        settings = motor.discovery_audio_settings(300.0)
        zones = motor.build_discovery_audio_zones(300.0, 300.0, settings, settings["initial_zone_pcts"])
        self.assertEqual(len(zones), 4)
        for zone in zones:
            center_ms = round((zone["ref_start_sec"] - zone["esp_start_sec"]) * 1000)
            self.assertEqual(center_ms, settings["radius_ms"])
            self.assertEqual(
                zone["esp_segment_sec"],
                settings["segment_sec"] + (2.0 * settings["radius_ms"] / 1000.0),
            )


class ProductiveDiscoverySignTests(unittest.TestCase):
    @staticmethod
    def write_wave(path, samples, sample_rate=8000):
        payload = array("h", samples)
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(payload.tobytes())

    @staticmethod
    def signal(seconds=30, sample_rate=8000):
        rng = random.Random(5005)
        samples = []
        for frame in range(int(seconds * sample_rate / 160)):
            amplitude = rng.randint(1500, 25000)
            frequency = 200 + (frame % 19) * 23
            for index in range(160):
                samples.append(int(amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate)))
        return samples

    def test_asymmetric_discovery_window_finds_both_signs(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        root = os.path.join(runtime_root, f"phase5-sign-{uuid.uuid4().hex}")
        os.makedirs(root, exist_ok=True)
        reference = self.signal()
        shift_samples = 3 * 8000
        variants = {
            "positive": (reference[shift_samples:] + [0] * shift_samples, 3000),
            "negative": ([0] * shift_samples + reference[:-shift_samples], -3000),
        }
        ref_path = os.path.join(root, "ref.wav")
        self.write_wave(ref_path, reference)
        try:
            for label, (samples, expected) in variants.items():
                with self.subTest(label=label):
                    esp_path = os.path.join(root, f"{label}.wav")
                    self.write_wave(esp_path, samples)
                    case_dir = os.path.join(root, label)
                    work_dir = os.path.join(case_dir, "tmp")
                    os.makedirs(work_dir, exist_ok=True)
                    motor = DelayAudio(ref_path, esp_path, case_dir, ref_audio_index=0, esp_audio_index=0)
                    motor.reset_logs()
                    motor.diag.command = lambda *args, **kwargs: None
                    row = motor.analyze_zone(
                        1,
                        10.0,
                        0,
                        0,
                        work_dir,
                        segment_sec=6.0,
                        esp_segment_sec=16.0,
                        search_center_ms=5000,
                        search_radius_ms=5000,
                        residual_min_ms=-10000,
                        residual_max_ms=0,
                        esp_start_sec=5.0,
                    )
                    self.assertLessEqual(abs(row["delay_ms"] - expected), 40)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
