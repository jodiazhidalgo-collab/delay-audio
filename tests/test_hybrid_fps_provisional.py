import json
import os
import shutil
import sys
import unittest
import uuid


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(PROJECT_ROOT, "app")
MOTOR_ROOT = os.path.join(APP_ROOT, "motor", "delay_audio")
for path in (APP_ROOT, MOTOR_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from api.modulos.delay_audio.routes import contrato_resultado_hibrido_valido  # noqa: E402
from medir_delay_audio import DelayAudio  # noqa: E402
from verificacion_visual import VideoMetadata, VisualVerifier  # noqa: E402


def fake_meta(path, duration, fps, vfr=False):
    real_fps = fps + 1.0 if vfr else fps
    return VideoMetadata(path, duration, fps, real_fps, 1920, 1080, "yuv420p", "bt709", vfr)


class RelativeVisualVerifier(VisualVerifier):
    def __init__(self, ref_meta, esp_meta, planned_score=0.55, nominal_score=0.40):
        super().__init__()
        self.ref_meta = ref_meta
        self.esp_meta = esp_meta
        self.planned_score = planned_score
        self.nominal_score = nominal_score
        self.calls = []

    def probe_video(self, path):
        return self.ref_meta if path == "ref-original.mkv" else self.esp_meta

    def score_candidate(self, ref, esp, ref_time, delay_ms, tempo=1.0, *args, **kwargs):
        self.calls.append({"ref": ref, "esp": esp, "delay_ms": delay_ms, "tempo": tempo})
        expected_tempo = self.ref_meta.avg_fps / self.esp_meta.avg_fps
        score = self.planned_score if abs(tempo - expected_tempo) < 1e-9 else self.nominal_score
        return {"ok": True, "mean_ssim": score, "frames": 4}


class FpsPlanningDecisionTests(unittest.TestCase):
    def confirm_pair(self, ref_fps, esp_fps, delay_ms):
        tempo = ref_fps / esp_fps
        verifier = RelativeVisualVerifier(
            fake_meta("ref", 100.0, ref_fps),
            fake_meta("esp", 100.0 * tempo, esp_fps),
        )
        result = verifier.confirm_fps_plan(
            "ref-original.mkv",
            "esp-original.mkv",
            ref_fps,
            esp_fps,
            "pelicula",
            delay_ms,
            {"stable": True},
        )
        self.assertTrue(result["confirmed"])
        self.assertTrue(result["applied"])
        self.assertEqual(result["visual"]["delay_ms"], delay_ms)
        self.assertTrue(all(call["delay_ms"] == delay_ms for call in verifier.calls))
        self.assertTrue(all(call["esp"] == "esp-original.mkv" for call in verifier.calls))
        return result

    def test_25_to_23976_uses_nonzero_800ms_delay(self):
        result = self.confirm_pair(24000 / 1001, 25.0, 800)
        self.assertAlmostEqual(result["tempo"], (24000 / 1001) / 25.0, places=9)

    def test_25_to_24_uses_nonzero_2588ms_delay(self):
        result = self.confirm_pair(24.0, 25.0, 2588)
        self.assertAlmostEqual(result["tempo"], 0.96, places=9)

    def test_duration_mismatch_is_warning_without_visual_work(self):
        verifier = RelativeVisualVerifier(fake_meta("ref", 100.0, 24.0), fake_meta("esp", 100.0, 25.0))
        result = verifier.confirm_fps_plan(
            "ref-original.mkv",
            "esp-original.mkv",
            24.0,
            25.0,
            "pelicula",
            provisional_only=True,
        )
        self.assertTrue(result["provisional"])
        self.assertFalse(result["duration"]["match"])
        self.assertEqual(result["reason"], "duration_ratio_warning")
        self.assertEqual(verifier.calls, [])

    def test_vfr_rejects_before_visual_work(self):
        tempo = 24.0 / 25.0
        verifier = RelativeVisualVerifier(
            fake_meta("ref", 100.0, 24.0, vfr=True),
            fake_meta("esp", 100.0 * tempo, 25.0),
        )
        result = verifier.confirm_fps_plan(
            "ref-original.mkv",
            "esp-original.mkv",
            24.0,
            25.0,
            "pelicula",
            provisional_only=True,
        )
        self.assertFalse(result["provisional"])
        self.assertEqual(result["reason"], "vfr_no_confirmado")
        self.assertEqual(verifier.calls, [])

    def test_audio_stability_is_mandatory_even_with_good_relative_ssim(self):
        tempo = 24.0 / 25.0
        verifier = RelativeVisualVerifier(
            fake_meta("ref", 100.0, 24.0),
            fake_meta("esp", 100.0 * tempo, 25.0),
        )
        result = verifier.confirm_fps_plan(
            "ref-original.mkv",
            "esp-original.mkv",
            24.0,
            25.0,
            "pelicula",
            2588,
            {"stable": False},
        )
        self.assertFalse(result["confirmed"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "audio_corregido_no_confirma_tempo")


class FakeFpsVisualVerifier:
    def __init__(self, motor, confirm=True):
        self.motor = motor
        self.confirm = confirm

    def confirm_fps_plan(self, ref, esp, ref_fps, esp_fps, profile, delay_ms, audio_evidence):
        self.motor.visual_calls.append({
            "ref": ref,
            "esp": esp,
            "delay_ms": delay_ms,
            "audio_stable": audio_evidence.get("stable"),
        })
        confirmed = bool(self.confirm and audio_evidence.get("stable"))
        return {
            "planned": True,
            "provisional": True,
            "enabled": confirmed,
            "confirmed": confirmed,
            "applied": confirmed,
            "reason": "duration_audio_drift_and_visual_match" if confirmed else "imagen_no_confirma_tempo",
            "ref_fps": ref_fps,
            "esp_fps": esp_fps,
            "tempo": ref_fps / esp_fps,
            "duration": {"match": True},
            "variable_frame_rate": False,
            "visual": {
                "verified": confirmed,
                "delay_ms": delay_ms,
                "zones_attempted": 3,
                "zones_valid": 3,
                "absolute_match": False,
                "relative_match": confirmed,
                "relative_wins": 3 if confirmed else 0,
                "mean_delta": 0.15 if confirmed else 0.0,
                "comparisons": [],
            },
        }


class ProvisionalFpsMotor(DelayAudio):
    def __init__(self, job_dir, delay_ms=800, slope=0.0, hint=0, visual_confirm=True):
        super().__init__(
            "ref-original.mkv",
            "audio-corrected.mka",
            job_dir,
            ref_audio_index=1,
            esp_audio_index=0,
            profile="pelicula",
            delay_hint_ms=hint,
            esp_video_original="esp-original.mkv",
            fps_ref=24000 / 1001,
            fps_esp=25.0,
            fps_tempo=(24000 / 1001) / 25.0,
            fps_plan_enabled=True,
            fps_plan_provisional=True,
            fps_plan_confirmed=False,
            fps_plan_context={
                "planned": True,
                "provisional": True,
                "confirmed": False,
                "applied": False,
                "duration": {"match": True},
                "variable_frame_rate": False,
            },
            hybrid_enabled=True,
        )
        self.base_delay = float(delay_ms)
        self.slope = float(slope)
        self.visual_confirm = visual_confirm
        self.audio_calls = []
        self.visual_calls = []

    def create_visual_verifier(self):
        return FakeFpsVisualVerifier(self, self.visual_confirm)

    def analyze_zone(self, zone_number, start_sec, ref_index, esp_index, work_dir, **kwargs):
        delay = int(round(self.base_delay + (self.slope * float(start_sec))))
        row = {
            "zone": zone_number,
            "start_sec": float(start_sec),
            "esp_start_sec": float(kwargs.get("esp_start_sec") or 0.0),
            "delay_ms": delay,
            "score": 0.72,
            "confidence": "ALTA",
        }
        self.audio_calls.append(row)
        return row


class ProvisionalFpsMotorTests(unittest.TestCase):
    def run_case(self, **kwargs):
        runtime_root = os.path.join(PROJECT_ROOT, "_codex_runtime", "tmp")
        os.makedirs(runtime_root, exist_ok=True)
        job_dir = os.path.join(runtime_root, f"fps-provisional-{uuid.uuid4().hex}")
        motor = ProvisionalFpsMotor(job_dir, **kwargs)
        try:
            motor.reset_logs()
            motor.diag.init(inputs={"synthetic": True}, settings={"hybrid_enabled": True})
            returncode = motor.run_hybrid_fast_path(1000.0, 1000.0, 1, 0)
            with open(motor.result_path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            return motor, returncode, result
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def test_stable_audio_confirms_fps_and_reuses_original_video_for_image(self):
        motor, returncode, result = self.run_case(delay_ms=800)
        self.assertEqual(returncode, 0)
        self.assertEqual(result["state"], "OK_VERIFICADO")
        self.assertTrue(result["export_allowed"])
        self.assertEqual(result["delay_ms"], 800)
        self.assertTrue(result["fps_correction"]["provisional"])
        self.assertTrue(result["fps_correction"]["confirmed"])
        self.assertTrue(result["fps_correction"]["applied"])
        self.assertGreaterEqual(result["audio"]["supporting_zones"], 3)
        self.assertEqual(result["audio"]["slope_ms_per_sec"], 0.0)
        self.assertTrue(all(call["esp"] == motor.esp_video_original for call in motor.visual_calls))
        self.assertTrue(motor.esp_file.endswith("audio-corrected.mka"))
        self.assertTrue(contrato_resultado_hibrido_valido(result))

    def test_audio_with_progressive_drift_rejects_before_visual(self):
        motor, _, result = self.run_case(delay_ms=800, slope=0.12)
        self.assertEqual(result["state"], "FPS_NO_CONFIRMADOS")
        self.assertFalse(result["export_allowed"])
        self.assertFalse(result["fps_correction"]["confirmed"])
        self.assertFalse(result["fps_correction"]["applied"])
        self.assertFalse(result["audio"]["stable"])
        self.assertGreater(abs(result["audio"]["slope_ms_per_sec"]), 0.1)
        self.assertEqual(motor.visual_calls, [])

    def test_correct_hint_does_not_replace_measurement(self):
        motor, _, result = self.run_case(delay_ms=2588, hint=2000)
        self.assertEqual(result["delay_ms"], 2588)
        self.assertEqual(result["audio"]["hint_ms"], 2000)
        self.assertFalse(result["audio"]["hint_is_measurement"])
        self.assertTrue(result["edit_hint"]["hint_helped_fast_path"])
        self.assertEqual(len(motor.audio_calls), 3)

    def test_wrong_hint_does_not_replace_measurement(self):
        _, _, result = self.run_case(delay_ms=2588, hint=-9000)
        self.assertEqual(result["delay_ms"], 2588)
        self.assertNotEqual(result["delay_ms"], -9000)
        self.assertTrue(result["edit_hint"]["hint_rejected"])

    def test_visual_rejection_keeps_provisional_state_fail_closed(self):
        _, _, result = self.run_case(delay_ms=800, visual_confirm=False)
        self.assertEqual(result["state"], "FPS_NO_CONFIRMADOS")
        self.assertFalse(result["export_allowed"])
        self.assertTrue(result["fps_correction"]["provisional"])
        self.assertFalse(result["fps_correction"]["confirmed"])
        self.assertFalse(result["fps_correction"]["applied"])


if __name__ == "__main__":
    unittest.main()
