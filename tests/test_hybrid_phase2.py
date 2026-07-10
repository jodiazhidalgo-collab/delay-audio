import os
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
MOTOR_ROOT = os.path.join(APP_ROOT, "motor", "delay_audio")
for path in (APP_ROOT, MOTOR_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from api.modulos.delay_audio import routes as routes_module  # noqa: E402
from api.modulos.delay_audio.routes import confirmar_plan_fps, hybrid_enabled, resultado_fps_no_confirmados  # noqa: E402
from medir_delay_audio import DelayAudio  # noqa: E402
from verificacion_visual import profile_config as visual_profile_config  # noqa: E402


class HybridConfigTests(unittest.TestCase):
    def test_missing_hybrid_block_is_disabled(self):
        self.assertFalse(hybrid_enabled({"modo": "exportar"}))

    def test_partial_hybrid_block_is_disabled(self):
        self.assertFalse(hybrid_enabled({"hybrid": {}}))

    def test_partial_true_block_is_still_disabled(self):
        self.assertFalse(hybrid_enabled({"hybrid": {"enabled": True}}))
        self.assertTrue(routes_module.activacion_hibrida_invalida({"enabled": True}))

    def test_explicit_false_partial_block_is_safe_legacy(self):
        self.assertFalse(routes_module.activacion_hibrida_invalida({"enabled": False}))

    def test_only_complete_config_with_literal_true_enables_hybrid(self):
        hybrid = deepcopy(routes_module.DEFAULT_HYBRID_CONFIG)
        hybrid["enabled"] = True
        self.assertTrue(hybrid_enabled({"hybrid": hybrid}))
        hybrid["enabled"] = "true"
        self.assertFalse(hybrid_enabled({"hybrid": hybrid}))

    def test_profile_limits_cannot_be_expanded_by_config(self):
        hybrid = deepcopy(routes_module.DEFAULT_HYBRID_CONFIG)
        hybrid["enabled"] = True
        hybrid["trailer"]["audio_narrow"]["segment_cap_sec"] = 36.0
        self.assertFalse(hybrid_enabled({"hybrid": hybrid}))
        hybrid = deepcopy(routes_module.DEFAULT_HYBRID_CONFIG)
        hybrid["enabled"] = True
        hybrid["movie"]["visual"]["max_zones"] = 8
        self.assertFalse(hybrid_enabled({"hybrid": hybrid}))

    def test_safety_thresholds_and_visual_load_cannot_be_weakened(self):
        unsafe_changes = (
            ("movie", "visual", "strong_min", 0.0),
            ("movie", "visual", "required_zones", 1),
            ("trailer", "audio_narrow", "avg_score_min", 0.0),
            ("movie", "audio_discovery", "support_avg_min", 0.0),
            ("movie", "visual", "burst_sec", 30.0),
            ("movie", "visual", "burst_sec", 1.0),
            ("movie", "visual", "fps", 30.0),
            ("movie", "visual", "fps", 1.0),
            ("movie", "visual", "width", 4096),
            ("movie", "visual", "width", 128),
            ("movie", "visual", "crop_safe_pct", 70),
            ("movie", "visual", "competitor_ms", 2000),
        )
        for profile, section, key, value in unsafe_changes:
            with self.subTest(profile=profile, section=section, key=key):
                hybrid = deepcopy(routes_module.DEFAULT_HYBRID_CONFIG)
                hybrid["enabled"] = True
                hybrid[profile][section][key] = value
                self.assertFalse(hybrid_enabled({"hybrid": hybrid}))

    def test_invalid_activation_cannot_be_silently_persisted_as_legacy(self):
        config = deepcopy(routes_module.DEFAULT_CONFIG)
        config["_config_error"] = "hybrid inválido"
        with (
            patch.object(routes_module, "leer_config", return_value=config),
            patch.object(routes_module, "open", create=True) as open_file,
        ):
            result = routes_module.guardar_config_desde_query({})
        self.assertFalse(result["ok"])
        self.assertIn("hybrid", result["error"])
        open_file.assert_not_called()

    def test_visual_runtime_clamps_direct_unsafe_overrides(self):
        config = visual_profile_config("pelicula", {
            "visual_burst_sec": 0.1,
            "visual_fps": 0.1,
            "visual_width": 16,
            "visual_height": 16,
            "visual_crop_safe_pct": 70,
            "visual_competitor_ms": 2000,
            "visual_strong_min": 0,
            "visual_valid_min": 0,
            "visual_margin_strong": 0,
            "visual_margin_valid": 0,
            "visual_required_zones": 1,
            "visual_required_strong": 1,
            "visual_max_zones": 12,
        })
        self.assertGreaterEqual(config["visual_burst_sec"], 2.0)
        self.assertGreaterEqual(config["visual_fps"], 2.0)
        self.assertGreaterEqual(config["visual_width"], 192)
        self.assertGreaterEqual(config["visual_height"], 108)
        self.assertEqual(config["visual_crop_safe_pct"], 90)
        self.assertEqual(config["visual_competitor_ms"], 400)
        self.assertGreaterEqual(config["visual_strong_min"], 0.88)
        self.assertGreaterEqual(config["visual_required_zones"], 3)


class RouteSeparationTests(unittest.TestCase):
    def test_fps_rejection_is_fail_closed(self):
        job = {"log_path": "/logs/job/log.txt", "csv_path": "/logs/job/result.csv"}
        fps = {"planned": True, "confirmed": False, "reason": "imagen_no_confirma_tempo"}
        result = resultado_fps_no_confirmados(job, fps, "pelicula")
        self.assertTrue(result["ok"])
        self.assertFalse(result["export_allowed"])
        self.assertEqual(result["state"], "FPS_NO_CONFIRMADOS")

    def test_motor_keeps_visual_and_audio_paths_separate(self):
        motor = DelayAudio(
            "ref.mkv",
            "audio-medicion.mka",
            "job",
            esp_video_original="video-original.mkv",
            fps_ref=24000 / 1001,
            fps_esp=24,
            fps_tempo=(24000 / 1001) / 24,
            fps_plan_enabled=True,
            fps_plan_confirmed=True,
            hybrid_enabled=True,
        )
        self.assertTrue(motor.esp_file.endswith("audio-medicion.mka"))
        self.assertTrue(motor.esp_video_original.endswith("video-original.mkv"))
        self.assertNotEqual(motor.esp_file, motor.esp_video_original)
        self.assertTrue(motor.fps_plan_confirmed)

    def test_fps_confirmation_only_accepts_literal_boolean_true(self):
        job = {"ref": "ref.mkv", "esp": "esp.mkv", "esp_video_original": "esp.mkv"}
        proc = SimpleNamespace(
            returncode=0,
            stdout='{"confirmed": "true", "reason": "invalid_contract"}',
            stderr="",
        )
        with (
            patch.object(routes_module.subprocess, "run", return_value=proc),
            patch.object(routes_module, "diagnostico_event"),
            patch.object(routes_module, "diagnostico_command"),
        ):
            result = confirmar_plan_fps(
                job,
                {"planned": True, "enabled": True, "ref_fps": 23.976, "esp_fps": 24.0, "tempo": 0.999},
                "pelicula",
            )
        self.assertIs(result["confirmed"], False)
        self.assertIs(result["enabled"], False)

    def test_invalid_fps_confirmation_always_emits_rejected_terminal_event(self):
        job = {"ref": "ref.mkv", "esp": "esp.mkv", "esp_video_original": "esp.mkv"}
        proc = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
        with (
            patch.object(routes_module.subprocess, "run", return_value=proc),
            patch.object(routes_module, "diagnostico_event") as event,
            patch.object(routes_module, "diagnostico_command"),
        ):
            with self.assertRaises(RuntimeError):
                confirmar_plan_fps(
                    job,
                    {"planned": True, "enabled": True, "ref_fps": 23.976, "esp_fps": 24.0, "tempo": 0.999},
                    "pelicula",
                )
        self.assertEqual([call.args[2] for call in event.call_args_list], ["started", "rejected"])


if __name__ == "__main__":
    unittest.main()
