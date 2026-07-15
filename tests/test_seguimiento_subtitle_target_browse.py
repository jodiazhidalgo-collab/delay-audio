import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from api.modulos.seguimiento import routes  # noqa: E402


class SeguimientoSubtitleTargetBrowseTests(unittest.TestCase):
    def setUp(self):
        self.runtime_root = Path(PROJECT_ROOT) / "_codex_runtime" / "test-data" / f"subtitle-target-{uuid.uuid4().hex}"
        self.runtime_root.mkdir(parents=True)
        (self.runtime_root / "Hospital").mkdir()
        (self.runtime_root / "movies").mkdir()
        (self.runtime_root / "source").mkdir()
        (self.runtime_root / "trailer-raiz.mkv").write_bytes(b"mkv")
        (self.runtime_root / "ignorar-raiz.mp4").write_bytes(b"mp4")
        (self.runtime_root / "movies" / "Pelicula.mkv").write_bytes(b"mkv")
        (self.runtime_root / "movies" / "Pelicula.mp4").write_bytes(b"mp4")
        (self.runtime_root / "movies" / "Pelicula.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n", encoding="utf-8")
        (self.runtime_root / "source" / "Pelicula.es.forced.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHola\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_selector_lists_folders_and_only_mkv_videos(self):
        with patch.object(routes, "MEDIA_MOVE_ROOT", self.runtime_root.resolve()):
            root_result = routes.seguimiento_subtitle_target_browse({"part": []})
            movies_result = routes.seguimiento_subtitle_target_browse({"part": ["movies"]})
            move_result = routes.seguimiento_move_browse({"part": []})

        self.assertTrue(root_result["ok"])
        self.assertEqual(
            [(item["name"], item["kind"]) for item in root_result["items"]],
            [("Hospital", "folder"), ("movies", "folder"), ("source", "folder"), ("trailer-raiz.mkv", "video")],
        )
        self.assertEqual(
            [(item["name"], item["kind"]) for item in movies_result["items"]],
            [("Pelicula.mkv", "video")],
        )
        self.assertEqual([item["name"] for item in move_result["items"]], ["Hospital", "movies", "source"])

    def test_selector_rejects_paths_outside_media_root(self):
        with patch.object(routes, "MEDIA_MOVE_ROOT", self.runtime_root.resolve()):
            result = routes.seguimiento_subtitle_target_browse({"part": [".."]})

        self.assertFalse(result["ok"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["error"], "Ruta no valida")

    def test_add_subtitle_job_keeps_srt_as_source_and_targets_only_mkv(self):
        fake_job = {"id": "job-test", "action": "add_subtitle"}
        source_root = self.runtime_root / "source"
        with (
            patch.object(routes, "MEDIA_MOVE_ROOT", self.runtime_root.resolve()),
            patch.object(routes, "child_sources", return_value={"test": {"path": str(source_root)}}),
            patch.object(routes, "create_trailer_job", return_value=(fake_job, None)) as create_job,
            patch.object(routes, "trailer_job_status_payload", return_value={"ok": True, "job": "job-test"}),
        ):
            result = routes.seguimiento_trailer_job_start({
                "action": ["add_subtitle"],
                "source": ["test"],
                "part": ["Pelicula.es.forced.srt"],
                "video_part": ["trailer-raiz.mkv"],
            })

        self.assertTrue(result["ok"])
        args = create_job.call_args.args
        self.assertEqual(args[0], "add_subtitle")
        self.assertEqual(args[1], (self.runtime_root / "trailer-raiz.mkv").resolve())
        self.assertEqual(create_job.call_args.kwargs["subtitle_path"], (source_root / "Pelicula.es.forced.srt").resolve())
        self.assertTrue((source_root / "Pelicula.es.forced.srt").exists())

    def test_add_subtitle_job_rejects_non_mkv_target(self):
        source_root = self.runtime_root / "source"
        with (
            patch.object(routes, "MEDIA_MOVE_ROOT", self.runtime_root.resolve()),
            patch.object(routes, "child_sources", return_value={"test": {"path": str(source_root)}}),
        ):
            result = routes.seguimiento_trailer_job_start({
                "action": ["add_subtitle"],
                "source": ["test"],
                "part": ["Pelicula.es.forced.srt"],
                "video_part": ["ignorar-raiz.mp4"],
            })

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "El destino debe ser un MKV")


if __name__ == "__main__":
    unittest.main()
