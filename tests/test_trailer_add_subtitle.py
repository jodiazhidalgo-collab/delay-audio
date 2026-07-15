import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MOTOR_ROOT = PROJECT_ROOT / "app" / "motor" / "delay_audio"
if str(MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTOR_ROOT))

import eliminar_trailer_pistas as motor  # noqa: E402


class TrailerAddSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.runtime_root = PROJECT_ROOT / "_codex_runtime" / "test-data" / f"add-subtitle-{uuid.uuid4().hex}"
        self.runtime_root.mkdir(parents=True)
        self.video = self.runtime_root / "Pelicula.mkv"
        self.subtitle = self.runtime_root / "Pelicula.es.forced.srt"
        self.video.write_bytes(b"original-mkv")
        self.subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_language_comes_from_filename_but_forced_is_only_a_qualifier(self):
        self.assertEqual(motor.subtitle_language_from_filename("Pelicula.es.forced.srt"), "spa")
        self.assertEqual(motor.subtitle_language_from_filename("Pelicula.en.sdh.srt"), "eng")
        self.assertEqual(motor.subtitle_language_from_filename("Pelicula.Spanish.srt"), "spa")
        self.assertEqual(motor.subtitle_language_from_filename("Vivir en paz.srt"), "und")

    def test_add_subtitle_preserves_source_and_applies_requested_track_flags(self):
        captured = {}

        def fake_run(cmd, timeout=0):
            captured["cmd"] = cmd
            output = Path(cmd[cmd.index("-o") + 1])
            output.write_bytes(b"muxed-mkv" + b"x" * 5000)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        added_track = {
            "id": "1",
            "codec": "SubRip/SRT",
            "language": "spa",
            "name": "",
            "default": False,
            "forced": False,
            "count": 1,
        }
        source_before = self.subtitle.read_bytes()
        with (
            patch.object(motor, "run_cmd", side_effect=fake_run),
            patch.object(
                motor,
                "mkv_track_type_counts",
                side_effect=[
                    {"video": 1, "audio": 1, "subtitles": 0},
                    {"video": 1, "audio": 1, "subtitles": 1},
                ],
            ),
            patch.object(motor, "mkv_subtitle_tracks", side_effect=[[], [added_track]]),
            patch.object(motor, "validate_duration"),
            patch.object(motor, "copy_stat"),
            patch.object(motor, "media_info", return_value={"ok": True, "info": {"subtitles": [added_track]}}),
        ):
            result = motor.add_srt_to_mkv(self.video, self.subtitle)

        self.assertTrue(result["ok"])
        self.assertTrue(result["source_preserved"])
        self.assertEqual(result["language"], "spa")
        self.assertEqual(self.subtitle.read_bytes(), source_before)
        self.assertTrue(self.video.read_bytes().startswith(b"muxed-mkv"))
        command = captured["cmd"]
        self.assertIn("0:spa", command)
        self.assertIn("0:", command)
        self.assertIn("0:no", command)
        self.assertEqual(command.count("0:no"), 2)
        self.assertEqual(command[-1], str(self.subtitle))


if __name__ == "__main__":
    unittest.main()
