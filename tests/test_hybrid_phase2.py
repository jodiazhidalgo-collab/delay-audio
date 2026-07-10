import os
import sys
import unittest
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


class HybridConfigTests(unittest.TestCase):
    def test_missing_hybrid_block_is_disabled(self):
        self.assertFalse(hybrid_enabled({"modo": "exportar"}))

    def test_partial_hybrid_block_is_disabled(self):
        self.assertFalse(hybrid_enabled({"hybrid": {}}))

    def test_only_literal_true_enables_hybrid(self):
        self.assertTrue(hybrid_enabled({"hybrid": {"enabled": True}}))
        self.assertFalse(hybrid_enabled({"hybrid": {"enabled": "true"}}))


class RouteSeparationTests(unittest.TestCase):
    def test_fps_rejection_is_fail_closed(self):
        job = {"log_path": "/logs/job/log.txt", "csv_path": "/logs/job/result.csv"}
        fps = {"planned": True, "confirmed": False, "reason": "imagen_no_confirma_tempo"}
        result = resultado_fps_no_confirmados(job, fps, "pelicula")
        self.assertFalse(result["ok"])
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


if __name__ == "__main__":
    unittest.main()
