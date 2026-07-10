import os
import sys
import unittest
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
            "confirmed": False,
            "applied": False,
            "reason": "fps_iguales",
            "ref_fps": 23.976,
            "esp_fps": 23.976,
        },
        "visual": {"verified": True},
        "audio": {"supporting_zones": 2},
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

    def test_unconfirmed_planned_fps_cannot_become_verified(self):
        result = verified_result(fps_correction={"planned": True, "confirmed": False, "applied": False})
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


class HybridExportGateTests(unittest.TestCase):
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
