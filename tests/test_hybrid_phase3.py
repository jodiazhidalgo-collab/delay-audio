import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from api.modulos.delay_audio import routes  # noqa: E402


def verified_result(**overrides):
    values = {
        "state": "OK_VERIFICADO",
        "delay_ms": 120,
        "confidence": "ALTA",
        "fps_correction": {
            "planned": False,
            "provisional": False,
            "confirmed": False,
            "applied": False,
            "reason": "fps_iguales",
            "ref_fps": 23.976,
            "esp_fps": 23.976,
        },
        "measurement_core": {"start_sec": 120.0, "end_sec": 5880.0, "span_sec": 5760.0},
        "timeline_model": {
            "compatible": True,
            "anchors_total": 3,
            "anchors_inliers": 3,
            "anchors_rejected": 0,
        },
        "edit_hint": {"hint_used": False, "hint_is_measurement": False},
        "visual": {"verified": True},
        "audio": {"supporting_zones": 3},
        "reason": "audio_and_visual_agree",
        "contradictions": [],
    }
    values.update(overrides)
    return routes.construir_resultado_hibrido(**values)


def complete_legacy_result():
    return {
        "ok": True,
        "delay_ms": 96540,
        "confidence": "MEDIA",
        "zones_count": 1,
        "avg_score": 0.4883274785,
        "results": [{"zone": 6, "delay_ms": 96540, "score": 0.4883274785}],
        "profile": "pelicula",
    }


class HybridResultContractTests(unittest.TestCase):
    def test_cleanup_reason_only_matches_real_removal_failures(self):
        self.assertTrue(routes.es_error_limpieza_temporal("No he podido eliminar el temporal propio"))
        self.assertTrue(routes.es_error_limpieza_temporal("El temporal sigue existiendo"))
        self.assertFalse(routes.es_error_limpieza_temporal("No he podido crear un temporal libre"))
        self.assertFalse(routes.es_error_limpieza_temporal("El audio temporal normalizado está vacío"))

    def test_all_required_final_states_exist(self):
        self.assertEqual(
            routes.HYBRID_FINAL_STATES,
            {
                "OK_VERIFICADO",
                "NO_FIABLE",
                "MONTAJE_DISTINTO",
                "FPS_NO_CONFIRMADOS",
                "SIN_ZONAS_VALIDAS",
                "AUDIO_VIDEO_ORIGEN_DUDOSO",
                "ERROR_TECNICO",
            },
        )

    def test_verified_result_is_the_only_authorized_state(self):
        result = verified_result()
        self.assertTrue(routes.contrato_resultado_hibrido_valido(result))
        self.assertTrue(routes.exportacion_hibrida_autorizada(result))
        self.assertIs(result["export_allowed"], True)

    def test_media_cannot_become_verified(self):
        result = verified_result(confidence="MEDIA")
        self.assertEqual(result["state"], "NO_FIABLE")
        self.assertIs(result["export_allowed"], False)
        self.assertFalse(routes.exportacion_hibrida_autorizada(result))

    def test_one_audio_zone_cannot_become_verified(self):
        result = verified_result(audio={"supporting_zones": 1})
        self.assertEqual(result["state"], "NO_FIABLE")
        self.assertIs(result["export_allowed"], False)

    def test_hint_alone_never_authorizes_export(self):
        result = routes.construir_resultado_hibrido(
            "OK_VERIFICADO",
            confidence="ALTA",
            fps_correction={
                "planned": False,
                "provisional": False,
                "confirmed": False,
                "applied": False,
                "reason": "fps_iguales",
                "ref_fps": 24.0,
                "esp_fps": 24.0,
            },
            visual={"verified": False},
            audio={"supporting_zones": 0},
            edit_hint={"hint_used": True, "hint_is_measurement": False},
        )
        self.assertEqual(result["state"], "NO_FIABLE")
        self.assertFalse(routes.exportacion_hibrida_autorizada(result))

    def test_unconfirmed_planned_fps_cannot_become_verified(self):
        result = verified_result(fps_correction={"planned": True, "provisional": True, "confirmed": False, "applied": False})
        self.assertEqual(result["state"], "NO_FIABLE")
        self.assertIs(result["export_allowed"], False)

    def test_planned_fps_requires_finite_coherent_ratio(self):
        invalid_plans = (
            {"planned": True, "confirmed": True, "applied": True},
            {"planned": True, "confirmed": True, "applied": True, "ref_fps": 0, "esp_fps": 0, "tempo": -9},
            {"planned": True, "confirmed": True, "applied": True, "ref_fps": 23.976, "esp_fps": 24, "tempo": 1.25},
        )
        for fps in invalid_plans:
            with self.subTest(fps=fps):
                result = verified_result(fps_correction=fps)
                self.assertEqual(result["state"], "NO_FIABLE")
                self.assertFalse(routes.exportacion_hibrida_autorizada(result))

        valid = verified_result(fps_correction={
            "planned": True,
            "provisional": True,
            "confirmed": True,
            "applied": True,
            "ref_fps": 24000 / 1001,
            "esp_fps": 24.0,
            "tempo": (24000 / 1001) / 24.0,
        })
        self.assertEqual(valid["state"], "OK_VERIFICADO")
        self.assertTrue(routes.exportacion_hibrida_autorizada(valid))

    def test_unknown_or_missing_fps_cannot_become_verified(self):
        for fps in (
            {},
            {"planned": False, "confirmed": False, "applied": False, "reason": "fps_no_detectado"},
            {"planned": False, "confirmed": False, "applied": False, "reason": "tempo_no_valido"},
        ):
            with self.subTest(fps=fps):
                result = verified_result(fps_correction=fps)
                self.assertEqual(result["state"], "NO_FIABLE")
                self.assertIs(result["export_allowed"], False)

    def test_text_fps_flags_cannot_become_verified(self):
        result = verified_result(fps_correction={"planned": "false", "confirmed": "true", "applied": "true"})
        self.assertEqual(result["state"], "NO_FIABLE")
        self.assertIs(result["export_allowed"], False)

    def test_unknown_state_is_technical_error_and_blocked(self):
        result = routes.construir_resultado_hibrido("ESTADO_INVENTADO")
        self.assertEqual(result["state"], "ERROR_TECNICO")
        self.assertFalse(routes.exportacion_hibrida_autorizada(result))

    def test_incomplete_json_is_blocked(self):
        self.assertFalse(routes.exportacion_hibrida_autorizada({"state": "OK_VERIFICADO", "export_allowed": True}))

    def test_integer_one_is_not_accepted_as_boolean_authorization(self):
        result = verified_result()
        result["export_allowed"] = 1
        self.assertFalse(routes.exportacion_hibrida_autorizada(result))

    def test_old_media_result_is_not_new_authorization(self):
        old_result = complete_legacy_result()
        self.assertFalse(routes.exportacion_hibrida_autorizada(old_result))
        normalized = routes.resultado_hibrido_desde_legacy(old_result, {"fps_correction": {}}, "pelicula")
        self.assertEqual(normalized["state"], "NO_FIABLE")
        self.assertFalse(normalized["export_allowed"])

    def test_complete_legacy_bridge_is_blocked_but_not_a_technical_error(self):
        job = {"result_path": "result.json", "fps_correction": {}}
        with (
            patch.object(routes, "leer_json", return_value=complete_legacy_result()),
            patch.object(routes, "escribir_json") as write_json,
        ):
            normalized = routes.normalizar_resultado_hibrido(job, "pelicula")
        self.assertEqual(normalized["state"], "NO_FIABLE")
        self.assertFalse(normalized["export_allowed"])
        write_json.assert_called_once()

    def test_truncated_hybrid_json_is_a_technical_error(self):
        job = {"result_path": "result.json", "fps_correction": {}, "log_path": "log", "csv_path": "csv"}
        with (
            patch.object(routes, "leer_json", return_value={"ok": True, "delay_ms": 120}),
            patch.object(routes, "escribir_json") as write_json,
        ):
            normalized = routes.normalizar_resultado_hibrido(job, "pelicula")
        self.assertEqual(normalized["state"], "ERROR_TECNICO")
        self.assertFalse(normalized["export_allowed"])
        write_json.assert_called_once()

    def test_legacy_policy_remains_available_only_outside_hybrid(self):
        old_result = {"ok": True, "confidence": "MEDIA"}
        self.assertTrue(routes.exportacion_legacy_autorizada(old_result, {"confianza_minima": "MEDIA"}))
        self.assertFalse(routes.exportacion_legacy_autorizada(old_result, {"confianza_minima": "ALTA"}))

    def test_nontechnical_hybrid_state_finishes_without_fake_error(self):
        result = routes.construir_resultado_hibrido("FPS_NO_CONFIRMADOS", reason="duration_mismatch")
        self.assertEqual(routes.status_para_resultado(result, "done"), "done")
        error = routes.construir_resultado_hibrido("ERROR_TECNICO", reason="ffmpeg_failed")
        self.assertEqual(routes.status_para_resultado(error, "done"), "error")
        self.assertEqual(routes.status_para_resultado(result, "running"), "running")

    def test_old_jobs_keep_their_status_semantics(self):
        self.assertEqual(routes.status_para_resultado({"ok": True}, "done"), "done")
        self.assertEqual(routes.status_para_resultado({"ok": False}, "done"), "error")

    def test_real_legacy_job_directory_is_reconstructed_and_returned_by_status(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="phase7-legacy-", dir=runtime_root) as log_root:
            job_id = "legacy_job_2024"
            job_dir = os.path.join(log_root, job_id)
            os.makedirs(job_dir, exist_ok=True)
            with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "status": "done",
                    "inputs": {"video_bueno": "ref.mkv", "video_espanol": "esp.mkv"},
                    "settings": {"modo": "medir", "perfil": "pelicula"},
                }, handle)
            with open(os.path.join(job_dir, "resultado.json"), "w", encoding="utf-8") as handle:
                json.dump(complete_legacy_result(), handle)
            with open(os.path.join(job_dir, "MEDIR_DELAY_AUDIO_LOG.txt"), "w", encoding="utf-8") as handle:
                handle.write("resultado legacy listo\n")
            with open(os.path.join(job_dir, "MEDIR_DELAY_AUDIO_RESULTADOS.csv"), "w", encoding="utf-8") as handle:
                handle.write("zona;delay_ms\n6;96540\n")
            with (
                patch.object(routes, "LOG_ROOT", log_root),
                patch.object(routes, "_JOBS", {}),
            ):
                response = routes.estado(job_id)
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "done")
        self.assertEqual(response["requested_mode"], "medir")
        self.assertEqual(response["profile"], "pelicula")
        self.assertEqual(response["result"]["delay_ms"], 96540)
        self.assertEqual(response["result"]["confidence"], "MEDIA")
        self.assertNotIn("state", response["result"])


class HybridExportGateTests(unittest.TestCase):
    def test_cleanup_removes_only_empty_owned_temp_directories(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cleanup-owned-", dir=runtime_root) as job_dir:
            owned = os.path.join(job_dir, "tmp")
            other = os.path.join(job_dir, "other")
            os.makedirs(owned)
            os.makedirs(other)
            owned_file = os.path.join(owned, "audio.mka")
            other_file = os.path.join(other, "keep-parent.mka")
            with open(owned_file, "w", encoding="utf-8") as handle:
                handle.write("owned")
            with open(other_file, "w", encoding="utf-8") as handle:
                handle.write("other")
            with (
                patch.object(routes, "diagnostico_event"),
                patch.object(routes, "diagnostico_error"),
            ):
                owned_outcome = routes.limpiar_temporal_diagnosticado(
                    {"job_dir": job_dir}, owned_file, "export_audio"
                )
                other_outcome = routes.limpiar_temporal_diagnosticado(
                    {"job_dir": job_dir}, other_file, "export_audio"
                )
            self.assertFalse(os.path.exists(owned_file))
            self.assertFalse(os.path.exists(owned))
            self.assertTrue(owned_outcome["directory_removed"])
            self.assertFalse(owned_outcome["remaining"])
            self.assertFalse(os.path.exists(other_file))
            self.assertTrue(os.path.isdir(other))
            self.assertFalse(other_outcome["directory_removed"])

    def test_cleanup_waits_for_last_owned_temp_before_removing_directory(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cleanup-multiple-", dir=runtime_root) as job_dir:
            owned = os.path.join(job_dir, "fps")
            os.makedirs(owned)
            first = os.path.join(owned, "first.mka")
            second = os.path.join(owned, "second.mka")
            for path in (first, second):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("temp")
            with (
                patch.object(routes, "diagnostico_event"),
                patch.object(routes, "diagnostico_error"),
            ):
                first_outcome = routes.limpiar_temporal_diagnosticado(
                    {"job_dir": job_dir}, first, "fps_audio"
                )
                second_outcome = routes.limpiar_temporal_diagnosticado(
                    {"job_dir": job_dir}, second, "fps_audio"
                )
            self.assertFalse(os.path.isdir(owned))
            self.assertFalse(first_outcome["directory_removed"])
            self.assertTrue(second_outcome["directory_removed"])
            self.assertFalse(second_outcome["remaining"])

    def test_api_job_converts_real_motor_failure_to_one_blocked_technical_closure(self):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="phase7-api-error-", dir=runtime_root) as job_dir:
            job = {
                "id": "phase7-api-error",
                "status": "running",
                "job_dir": job_dir,
                "ref": "ref.mkv",
                "esp": "esp.mkv",
                "esp_video_original": "esp.mkv",
                "ref_audio": "",
                "esp_audio": "",
                "delay_hint_ms": 0,
                "requested_mode": "exportar",
                "profile": "pelicula",
                "hybrid_enabled": True,
                "fps_correction": {
                    "planned": False,
                    "provisional": False,
                    "enabled": False,
                    "confirmed": False,
                    "applied": False,
                    "reason": "fps_iguales",
                    "ref_fps": 24.0,
                    "esp_fps": 24.0,
                },
                "log_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_LOG.txt"),
                "csv_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_RESULTADOS.csv"),
                "result_path": os.path.join(job_dir, "resultado.json"),
                "progress_path": os.path.join(job_dir, "progress.json"),
            }
            trace = []

            def record_event(_job, phase, event_name, message="", data=None, level="info"):
                trace.append(("event", phase, event_name, data or {}))

            def record_error(_job, error_code, phase, message, data=None, exc=None):
                trace.append(("error", phase, error_code, data or {}))

            def record_finish(_job, status, result=None):
                trace.append(("finish", status, (result or {}).get("state"), result or {}))

            with (
                patch.object(routes, "diagnostico_attach"),
                patch.object(routes, "diagnostico_update"),
                patch.object(routes, "diagnostico_command"),
                patch.object(routes, "diagnostico_event", side_effect=record_event),
                patch.object(routes, "diagnostico_error", side_effect=record_error),
                patch.object(routes, "diagnostico_finish", side_effect=record_finish),
                patch.object(routes, "leer_config", return_value={"modo": "exportar"}),
                patch.object(routes, "log_job"),
                patch.object(routes, "limpiar_temporales_diagnosticados", return_value=[]),
                patch.object(routes.subprocess, "Popen", return_value=SimpleNamespace(wait=lambda: 1)),
            ):
                routes._ejecutar_job(job)

            with open(job["result_path"], "r", encoding="utf-8") as handle:
                result = json.load(handle)

        self.assertEqual(job["status"], "error")
        self.assertEqual(result["state"], "ERROR_TECNICO")
        self.assertIs(result["export_allowed"], False)
        self.assertEqual(result["decision"]["reason"], "motor_medicion_fallido")
        self.assertEqual(result["export"]["status"], "skipped")
        decisions = [item for item in trace if item[0:2] == ("event", "decision")]
        gates = [item for item in trace if item[0:3] == ("event", "export_gate", "blocked")]
        finishes = [item for item in trace if item[0] == "finish"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0][2], "error_tecnico")
        self.assertEqual(len(gates), 1)
        self.assertEqual(len(finishes), 1)
        self.assertEqual(finishes[0][1:3], ("error", "ERROR_TECNICO"))
        self.assertLess(trace.index(gates[0]), trace.index(decisions[0]))
        self.assertLess(trace.index(decisions[0]), trace.index(finishes[0]))

    def test_failed_cleanup_paths_are_kept_for_retry(self):
        paths = ["removed.tmp", "remaining.tmp"]
        outcomes = {
            "removed.tmp": {"remaining": False},
            "remaining.tmp": {"remaining": True},
        }
        with patch.object(routes, "limpiar_temporal_diagnosticado", side_effect=lambda job, path, scope: outcomes[path]):
            failures = routes.limpiar_temporales_diagnosticados({}, paths, "test")
        self.assertEqual(failures, ["remaining.tmp"])
        self.assertEqual(paths, ["remaining.tmp"])

    def test_duplicate_guard_does_not_reuse_a_job_with_different_mode(self):
        running = {
            "id": "existing",
            "status": "running",
            "created": 1,
            "ref": "ref.mkv",
            "esp": "esp.mkv",
            "ref_audio": 0,
            "esp_audio": 1,
            "output_dir": "out",
            "delay_hint_ms": 0,
            "requested_mode": "exportar",
        }
        with patch.object(routes, "_JOBS", {"existing": running}):
            found = routes.job_activo_misma_salida(
                "ref.mkv", "esp.mkv", 0, 1, "out", 0, requested_mode="medir"
            )
        self.assertIsNone(found)

    def test_mr_bean_legacy_result_is_blocked_before_export_code(self):
        job = {"hybrid_enabled": True, "result_path": "result.json"}
        old_result = {"ok": True, "delay_ms": 96540, "confidence": "MEDIA", "zones_count": 1}
        with (
            patch.object(routes, "diagnostico_attach"),
            patch.object(routes, "leer_config", return_value={"modo": "exportar", "confianza_minima": "MEDIA"}),
            patch.object(routes, "leer_json", return_value=old_result),
            patch.object(routes, "log_job"),
            patch.object(routes, "diagnostico_event") as event,
            patch.object(routes, "escribir_json") as write_json,
            patch.object(routes, "escribir_progreso"),
            patch.object(routes, "duracion_video_principal") as duration_probe,
        ):
            routes.exportar_si_corresponde(job)
        duration_probe.assert_not_called()
        write_json.assert_called_once()
        self.assertEqual(write_json.call_args.args[1]["export"]["reason"], "hybrid_export_gate_blocked")
        self.assertTrue(any(call.args[2] == "blocked" for call in event.call_args_list))

    def test_technical_error_closes_result_and_blocks_before_export_code(self):
        job = {"hybrid_enabled": True, "requested_mode": "exportar", "result_path": "result.json"}
        technical = routes.construir_resultado_hibrido(
            "ERROR_TECNICO",
            reason="ffmpeg_failed",
            contradictions=["technical_failure"],
        )
        with (
            patch.object(routes, "diagnostico_attach"),
            patch.object(routes, "leer_config", return_value={"modo": "exportar"}),
            patch.object(routes, "leer_json", return_value=technical),
            patch.object(routes, "log_job"),
            patch.object(routes, "diagnostico_event") as event,
            patch.object(routes, "escribir_json") as write_json,
            patch.object(routes, "escribir_progreso"),
            patch.object(routes, "duracion_video_principal") as duration_probe,
        ):
            routes.exportar_si_corresponde(job)
        self.assertEqual(technical["state"], "ERROR_TECNICO")
        self.assertIs(technical["export_allowed"], False)
        self.assertEqual(job["_export_gate_event"], "blocked")
        duration_probe.assert_not_called()
        self.assertEqual(write_json.call_args.args[1]["export"]["status"], "skipped")
        self.assertTrue(any(call.args[1:3] == ("export_gate", "blocked") for call in event.call_args_list))

    def test_measure_and_export_enters_exporter_only_for_verified_result(self):
        job = {
            "hybrid_enabled": True,
            "requested_mode": "exportar",
            "result_path": "result.json",
            "ref": "ref.mkv",
            "esp": "esp.mkv",
            "output_dir": "out",
        }
        with (
            patch.object(routes, "diagnostico_attach"),
            patch.object(routes, "leer_config", return_value={"modo": "exportar", "carpeta_salida": "out"}),
            patch.object(routes, "leer_json", return_value=verified_result()),
            patch.object(routes, "log_job"),
            patch.object(routes, "diagnostico_event") as event,
            patch.object(routes, "ruta_permitida", return_value=True),
            patch.object(routes.os, "makedirs"),
            patch.object(routes, "ruta_salida_unica", return_value="out/final.mkv"),
            patch.object(routes, "ruta_temporal_exportacion", return_value="out/final.tmp.mkv"),
            patch.object(routes, "duracion_video_principal", side_effect=RuntimeError("EXPORTER_REACHED")) as duration_probe,
        ):
            with self.assertRaisesRegex(RuntimeError, "EXPORTER_REACHED"):
                routes.exportar_si_corresponde(job)
        self.assertEqual(job["_export_gate_event"], "allowed")
        duration_probe.assert_called_once_with("ref.mkv")
        self.assertTrue(any(call.args[1:3] == ("export_gate", "allowed") for call in event.call_args_list))

    def test_measure_only_never_reads_or_exports_result(self):
        with (
            patch.object(routes, "diagnostico_attach"),
            patch.object(routes, "leer_config", return_value={"modo": "medir"}),
            patch.object(routes, "leer_json") as read_json,
            patch.object(routes, "diagnostico_event"),
        ):
            routes.exportar_si_corresponde({"hybrid_enabled": True, "result_path": "result.json"})
        read_json.assert_not_called()

    def test_mode_is_frozen_when_job_started_as_measure_only(self):
        job = {"hybrid_enabled": True, "requested_mode": "medir", "result_path": "result.json"}
        with (
            patch.object(routes, "diagnostico_attach"),
            patch.object(routes, "leer_config", return_value={"modo": "exportar"}),
            patch.object(routes, "leer_json") as read_json,
            patch.object(routes, "diagnostico_event"),
        ):
            routes.exportar_si_corresponde(job)
        read_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
