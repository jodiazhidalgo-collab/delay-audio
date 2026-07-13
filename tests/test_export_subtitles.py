import os
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from api.modulos.delay_audio import routes  # noqa: E402
from api.modulos.diagnostico import blackbox  # noqa: E402


def identified_tracks(subtitle_titles):
    tracks = [
        {"id": 0, "type": "video", "properties": {}},
        {"id": 1, "type": "audio", "properties": {}},
    ]
    for index, title in enumerate(subtitle_titles, start=2):
        tracks.append({
            "id": index,
            "type": "subtitles",
            "properties": {"track_name": title},
        })
    return {"tracks": tracks}


class SubtitleExportTests(unittest.TestCase):
    def test_blackbox_marks_missing_fps_scale_without_changing_the_motor(self):
        job = {
            "fps_audio_path": "audio-fps.mka",
            "fps_correction": {
                "tempo": 0.96,
                "ref_fps": 24.0,
                "esp_fps": 25.0,
            },
        }
        evidence = routes.evidencia_sincronizacion_subtitulos(
            job,
            2619,
            [4, 5, 6],
            structure_verified=True,
        )
        self.assertEqual(evidence["status"], "falta_escala_fps")
        self.assertAlmostEqual(evidence["required_scale"], 25 / 24, places=8)
        self.assertEqual(evidence["applied_scale"], 1.0)
        self.assertFalse(evidence["scale_matches"])

    def test_blackbox_marks_equal_fps_as_correct_after_structure_check(self):
        evidence = routes.evidencia_sincronizacion_subtitulos(
            {"fps_correction": {"ref_fps": 23.976024, "esp_fps": 23.976024}},
            -1000,
            [2],
            structure_verified=True,
        )
        self.assertEqual(evidence["status"], "correcto")
        self.assertEqual(evidence["required_scale"], 1.0)
        self.assertTrue(evidence["scale_matches"])

    def test_blackbox_marks_source_without_subtitles_without_false_warning(self):
        evidence = routes.evidencia_sincronizacion_subtitulos(
            {
                "fps_audio_path": "audio-fps.mka",
                "fps_correction": {"tempo": 0.96, "ref_fps": 24.0, "esp_fps": 25.0},
            },
            2619,
            [],
            structure_verified=True,
        )
        self.assertEqual(evidence["status"], "sin_subtitulos_origen")

    def test_diagnostic_summary_keeps_compact_subtitle_state(self):
        sync = {"status": "falta_escala_fps", "tracks": 3}
        summary = routes.resumen_resultado_diagnostico({
            "ok": True,
            "export": {"status": "done", "subtitle_sync": sync},
        })
        self.assertEqual(summary["subtitle_sync"], sync)

    def test_blackbox_readme_is_compact(self):
        result = {
            "export": {
                "subtitle_sync": {
                    "status": "falta_escala_fps",
                    "tracks": 3,
                    "delay_ms": 2619,
                    "esp_fps": 25.0,
                    "ref_fps": 24.0,
                    "required_scale": 1.041666667,
                    "applied_scale": 1.0,
                    "structure_verified": True,
                }
            }
        }
        lines = blackbox.subtitle_sync_readme_lines(result)
        self.assertEqual(lines.count("Subtitulos:"), 1)
        self.assertIn("- estado: falta_escala_fps", lines)
        self.assertIn("- pistas_origen: 3", lines)
        self.assertLessEqual(len(lines), 9)

    def test_subtitle_plan_uses_clean_separator_and_one_identify(self):
        source = identified_tracks(["Forzados", ""])
        with patch.object(routes, "mkvmerge_identify", return_value=source) as identify:
            plan = routes.mkvmerge_subtitle_plan("source.mkv", "ESPAÑOL delay audio")

        self.assertEqual(identify.call_count, 1)
        self.assertEqual(plan["track_ids"], [2, 3])
        self.assertEqual(
            plan["titles"],
            ["Forzados - ESPAÑOL delay audio", "ESPAÑOL delay audio"],
        )
        self.assertNotIn(" ? ", " ".join(plan["titles"]))

    def test_legacy_metadata_helper_uses_the_same_clean_separator(self):
        streams = [{"tags": {"title": "Forzados"}}]
        with patch.object(routes, "ffprobe_streams", return_value=streams):
            args = routes.metadata_subtitulos("source.mkv", 0, "ESPAÑOL delay audio")
        self.assertEqual(
            args,
            ["-metadata:s:s:0", "title=Forzados - ESPAÑOL delay audio"],
        )

    def validate(self, actual_titles, expected_titles):
        with (
            patch.object(routes.os.path, "isfile", return_value=True),
            patch.object(routes.os.path, "getsize", return_value=8192),
            patch.object(
                routes,
                "mkvmerge_identify",
                return_value=identified_tracks(actual_titles),
            ) as identify,
            patch.object(routes, "duracion_formato", return_value=100.0),
            patch.object(routes, "primer_packet_audio_ms", return_value=0.0),
            patch.object(routes, "validar_mkv_demux"),
        ):
            result = routes.validar_mkv_exportado("output.mkv", 100.0, expected_titles)
        return result, identify.call_count

    def test_valid_output_checks_count_and_names_without_extra_identify(self):
        expected = ["English - INGLES", "Forzados - ESPAÑOL delay audio"]
        result, identify_calls = self.validate(expected, expected)
        self.assertTrue(result)
        self.assertEqual(identify_calls, 1)

    def test_missing_subtitle_blocks_output(self):
        expected = ["English - INGLES", "Forzados - ESPAÑOL delay audio"]
        with self.assertRaisesRegex(RuntimeError, "esperados 2, encontrados 1"):
            self.validate([expected[0]], expected)

    def test_wrong_subtitle_name_blocks_output(self):
        expected = ["English - INGLES", "Forzados - ESPAÑOL delay audio"]
        with self.assertRaisesRegex(RuntimeError, "nombres de subtitulos esperados"):
            self.validate([expected[0], "Forzados"], expected)

    def test_zero_expected_subtitles_accepts_zero_subtitles(self):
        result, identify_calls = self.validate([], [])
        self.assertTrue(result)
        self.assertEqual(identify_calls, 1)


if __name__ == "__main__":
    unittest.main()
