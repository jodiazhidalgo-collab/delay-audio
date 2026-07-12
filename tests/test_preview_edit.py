import json
import os
import shutil
import sys
import unittest
import uuid
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from api.modulos.delay_audio import routes  # noqa: E402


class PreviewEditTests(unittest.TestCase):
    def test_preview_manifest_keeps_core_mapping_profile_tempo_and_hint(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp", f"preview-{uuid.uuid4().hex}")
        os.makedirs(runtime_root, exist_ok=True)
        plan = {
            "ok": True,
            "profile": "pelicula",
            "core_start_sec": 120.0,
            "core_end_sec": 7080.0,
            "core_span_sec": 6960.0,
            "reference_clip_start_sec": 3237.0,
            "spanish_clip_start_sec": 3082.56,
            "spanish_source_duration_sec": 51.84,
            "spanish_preview_duration_sec": 54.0,
            "spanish_neutral_offset_sec": 24.0,
            "preview_duration_sec": 30.0,
            "window_sec": 6.0,
            "relative_min_offset_ms": -24000,
            "relative_max_offset_ms": 24000,
            "delay_hint_ms": 2000,
            "tempo": 0.96,
            "fps_correction_planned": True,
            "variable_frame_rate": False,
            "clip_reason": "core_center_tempo_and_hint",
            "measurement_core": {"start_sec": 120.0, "end_sec": 7080.0, "span_sec": 6960.0},
            "spanish_measurement_core": {"start_sec": 120.0, "end_sec": 7380.0, "span_sec": 7260.0},
        }
        q = {
            "ref": ["ref.mkv"],
            "esp": ["esp.mkv"],
            "profile": ["pelicula"],
            "delay_hint_ms": ["2000"],
        }
        try:
            with (
                patch.object(routes, "PREVIEW_ROOT", runtime_root),
                patch.object(routes, "normalizar_ruta", side_effect=lambda value: value),
                patch.object(routes, "validar_video", return_value=None),
                patch.object(routes, "limpiar_previews_antiguos"),
                patch.object(routes, "leer_config", return_value={"hybrid": routes.DEFAULT_HYBRID_CONFIG}),
                patch.object(routes, "generar_plan_preview", return_value=plan),
                patch.object(routes, "generar_preview_clip") as generate,
            ):
                result = routes.preview_visual(q)
            self.assertTrue(result["ok"])
            self.assertEqual(result["profile"], "pelicula")
            self.assertEqual(result["delay_hint_ms"], 2000)
            self.assertEqual(result["preview_duration_sec"], 30.0)
            self.assertEqual(result["reference_clip_start_sec"], 3237.0)
            self.assertEqual(result["spanish_clip_start_sec"], 3082.56)
            self.assertEqual(result["spanish_preview_duration_sec"], 54.0)
            self.assertEqual(result["spanish_neutral_offset_sec"], 24.0)
            self.assertEqual(generate.call_count, 2)
            self.assertEqual(generate.call_args_list[0].args[3:6], (3237.0, 30.0, 1.0))
            self.assertEqual(generate.call_args_list[1].args[3:6], (3082.56, 54.0, 0.96))
            preview_id = result["id"]
            with open(os.path.join(runtime_root, preview_id, "preview.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            for key in (
                "profile",
                "core_start_sec",
                "core_end_sec",
                "core_span_sec",
                "reference_clip_start_sec",
                "spanish_clip_start_sec",
                "spanish_preview_duration_sec",
                "spanish_neutral_offset_sec",
                "preview_duration_sec",
                "delay_hint_ms",
                "clip_reason",
            ):
                self.assertIn(key, manifest)
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)

    def test_preview_clip_applies_nonzero_seek_and_provisional_tempo(self):
        captured = {}

        class Process:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            return Process()

        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp", f"preview-cmd-{uuid.uuid4().hex}")
        os.makedirs(runtime_root, exist_ok=True)
        target = os.path.join(runtime_root, "preview.mp4")
        try:
            with (
                patch.object(routes.subprocess, "run", side_effect=fake_run),
                patch.object(routes.os.path, "isfile", return_value=True),
                patch.object(routes.os.path, "getsize", return_value=50000),
            ):
                routes.generar_preview_clip("esp.mkv", target, "Audio Español", 3082.56, 54.0, 0.96)
            command = captured["command"]
            self.assertEqual(command[command.index("-ss") + 1], "3082.560000")
            self.assertIn("setpts=(PTS-STARTPTS)/0.960000000000", command[command.index("-vf") + 1])
            self.assertIn("51.840000", command)
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)

    def test_successful_preview_log_omits_ffmpeg_noise(self):
        class Process:
            returncode = 0
            stdout = ""
            stderr = "PPS changed between slices.\nLast message repeated 6 times"

        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp", f"preview-log-{uuid.uuid4().hex}")
        os.makedirs(runtime_root, exist_ok=True)
        target = os.path.join(runtime_root, "preview.mp4")
        try:
            with (
                patch.object(routes.subprocess, "run", return_value=Process()),
                patch.object(routes.os.path, "isfile", return_value=True),
                patch.object(routes.os.path, "getsize", return_value=50000),
            ):
                routes.generar_preview_clip("esp.mkv", target, "Audio Español", 10.0, 20.0, 1.0)
            with open(os.path.join(runtime_root, "preview.log"), encoding="utf-8") as handle:
                log_text = handle.read()
            self.assertIn("Audio Español rc=0", log_text)
            self.assertNotIn("PPS changed", log_text)
            self.assertNotIn("Last message repeated", log_text)
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
