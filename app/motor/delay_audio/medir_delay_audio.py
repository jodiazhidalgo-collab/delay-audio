#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from array import array
from datetime import datetime

from diagnostico_job import JobDiagnostics, _write_json, classify_error
from measurement_core import build_measurement_core, core_zone_start, fit_timeline_model
from verificacion_visual import VisualVerifier, parse_json_object, visual_overrides_from_profile_config


MAX_DELAY_SEC = 120
SEGMENT_SEC = 240
MAX_ZONES = 10
SAMPLE_RATE = 8000
FINE_FRAME_MS = 20
COARSE_FACTOR = 5
CLUSTER_TOLERANCE_MS = 700
HINT_SEARCH_RADIUS_MS = 12000

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv"}
AUDIO_EXTENSIONS = {".mka", ".m4a", ".aac", ".ac3", ".eac3", ".dts", ".flac", ".mp3", ".wav", ".ogg", ".opus"}


class DelayAudio:
    def __init__(
        self,
        ref_file,
        esp_file,
        job_dir,
        ref_audio_index=None,
        esp_audio_index=None,
        profile="pelicula",
        delay_hint_ms=0,
        esp_video_original=None,
        fps_ref=0.0,
        fps_esp=0.0,
        fps_tempo=1.0,
        fps_plan_enabled=False,
        fps_plan_provisional=False,
        fps_plan_confirmed=False,
        fps_plan_context=None,
        hybrid_enabled=False,
        hybrid_config=None,
    ):
        self.ref_file = os.path.abspath(ref_file)
        self.esp_file = os.path.abspath(esp_file)
        self.esp_video_original = os.path.abspath(esp_video_original or esp_file)
        self.job_dir = os.path.abspath(job_dir)
        self.ref_audio_index = ref_audio_index
        self.esp_audio_index = esp_audio_index
        self.profile = profile if profile in ("pelicula", "trailer") else "pelicula"
        self.delay_hint_ms = max(-120000, min(120000, int(delay_hint_ms or 0)))
        self.fps_ref = float(fps_ref or 0.0)
        self.fps_esp = float(fps_esp or 0.0)
        self.fps_tempo = float(fps_tempo or 1.0)
        self.fps_plan_enabled = bool(fps_plan_enabled)
        self.fps_plan_provisional = bool(fps_plan_provisional or fps_plan_confirmed)
        self.fps_plan_confirmed = bool(fps_plan_confirmed)
        self.fps_confirmation = dict(fps_plan_context) if isinstance(fps_plan_context, dict) else {}
        self.hybrid_enabled = bool(hybrid_enabled)
        self.hybrid_config = dict(hybrid_config) if isinstance(hybrid_config, dict) else {}
        self.measurement_core = {}
        self.esp_measurement_core = {}
        self.timeline_model = {}
        self.core_timing_sec = 0.0
        self.metadata_timing_sec = 0.0
        self.timeline_timing_sec = 0.0
        self.hint_evidence = {
            "hint_used": self.delay_hint_ms != 0,
            "hint_is_measurement": False,
            "hint_helped_fast_path": False,
            "hint_rejected": False,
            "hint_error_ms": None,
        }
        self.segment_sec = SEGMENT_SEC
        self.max_delay_sec = MAX_DELAY_SEC
        self.max_zones = MAX_ZONES
        self.cluster_tolerance_ms = CLUSTER_TOLERANCE_MS
        self.log_path = os.path.join(self.job_dir, "MEDIR_DELAY_AUDIO_LOG.txt")
        self.csv_path = os.path.join(self.job_dir, "MEDIR_DELAY_AUDIO_RESULTADOS.csv")
        self.result_path = os.path.join(self.job_dir, "resultado.json")
        self.progress_path = os.path.join(self.job_dir, "progress.json")
        self.diag = JobDiagnostics(self.job_dir, os.path.basename(self.job_dir), "delay_audio")

    def reset_logs(self):
        os.makedirs(self.job_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(f"MEDIR_DELAY_AUDIO NAS v1 - LOG - {stamp}\n")
        with open(self.csv_path, "w", encoding="utf-8") as f:
            f.write("zona;inicio_segundos;inicio_hora;delay_ms;puntuacion;confianza;pista_video;pista_espanol\n")

    def log(self, text):
        line = str(text).rstrip()
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    def write_result(self, data):
        with open(self.result_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def write_progress(self, phase, percent, label="", total=None, done=None):
        data = {
            "phase": phase,
            "percent": max(0, min(100, int(round(float(percent))))),
            "label": label,
        }
        if total is not None:
            data["total"] = int(total)
        if done is not None:
            data["done"] = int(done)
        _write_json(self.progress_path, data)

    @staticmethod
    def is_expected_zone_rejection(exc):
        """Distingue contenido no útil de un fallo técnico de medición."""
        text = str(exc or "").lower()
        return any(phrase in text for phrase in (
            "audio temporal demasiado pequeno",
            "audio temporal demasiado pequeño",
            "muy poco audio para analizar",
            "audio demasiado corto para busqueda gruesa",
            "audio demasiado corto para búsqueda gruesa",
            "audio casi plano o silencioso",
        ))

    def run_cmd(self, cmd, timeout=None):
        phase = self.command_phase(cmd)
        started_at = time.time()
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        self.diag.command(phase, cmd[0] if cmd else "command", cmd, p.returncode, started_at, p.stdout, p.stderr, p.returncode == 0)
        return p.returncode, p.stdout or "", p.stderr or ""

    def command_phase(self, cmd):
        text = " ".join(map(str, cmd or [])).lower()
        if "ffprobe" in text and "format=duration" in text:
            return "probe_duration"
        if "ffprobe" in text and "-select_streams a" in text:
            return "probe_audio_tracks"
        if "ffmpeg" in text and "-f s16le" in text:
            return "measure_zone"
        return "tool"

    def get_duration_sec(self, input_file):
        self.log(f"FFPROBE duration: {input_file}")
        code, out, err = self.run_cmd([
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            input_file,
        ])
        raw = (out + "\n" + err).strip()
        self.log(raw)
        if code != 0:
            raise RuntimeError("ffprobe fallo leyendo duracion. Revisa el LOG.")
        for line in raw.splitlines():
            text = line.strip().replace(",", ".")
            if re.match(r"^[0-9]+(\.[0-9]+)?$", text):
                return float(text)
        raise RuntimeError("ffprobe no devolvio duracion valida. Revisa el LOG.")

    def get_audio_streams(self, input_file):
        self.log(f"FFPROBE audios JSON: {input_file}")
        code, out, err = self.run_cmd([
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index:stream_tags=language,title",
            "-of",
            "json",
            input_file,
        ])
        text = (out + err).strip()
        self.log(text)
        if code != 0:
            raise RuntimeError("ffprobe fallo leyendo pistas de audio. Revisa el LOG.")
        data = json.loads(text or "{}")
        streams = data.get("streams") or []
        if not streams:
            raise RuntimeError("No encuentro pistas de audio en el archivo.")
        return streams

    def get_audio_stream_index(self, input_file, prefer_spanish, selected_index=None):
        streams = self.get_audio_streams(input_file)
        if selected_index is not None:
            selected = int(selected_index)
            for st in streams:
                if int(st["index"]) == selected:
                    self.log(f"Pista elegida manualmente: 0:{selected}")
                    return selected
            raise RuntimeError(f"La pista elegida no existe en el archivo: 0:{selected}")

        if prefer_spanish:
            for st in streams:
                tags = st.get("tags") or {}
                lang = str(tags.get("language") or "").lower()
                title = str(tags.get("title") or "").lower()
                haystack = f"{lang} {title}"
                spanish = False
                if re.search(r"(^|[^a-z])(spa|es|esp|esl)([^a-z]|$)", haystack):
                    spanish = True
                if any(x in haystack for x in ("spanish", "espanol", "español", "castellano")):
                    spanish = True
                if spanish:
                    idx = int(st["index"])
                    self.log(f"Pista espanola detectada: 0:{idx} ({haystack})")
                    return idx
        idx = int(streams[0]["index"])
        self.log(f"Pista por defecto: 0:{idx}")
        return idx

    def configure_profile(self, duration_sec):
        if self.profile == "trailer":
            duration = max(1.0, float(duration_sec))
            segment = min(20.0, max(8.0, duration / 8.0))
            if duration <= segment + 1.0:
                segment = max(4.0, duration - 1.0)
            self.segment_sec = max(4.0, min(segment, duration))
            self.max_delay_sec = min(30.0, max(5.0, duration * 0.30))
            self.max_zones = MAX_ZONES
            self.cluster_tolerance_ms = 500
            self.apply_delay_hint_profile(duration)
            return
        self.segment_sec = SEGMENT_SEC
        self.max_delay_sec = MAX_DELAY_SEC
        self.max_zones = MAX_ZONES
        self.cluster_tolerance_ms = CLUSTER_TOLERANCE_MS
        self.apply_delay_hint_profile(duration_sec)

    def apply_delay_hint_profile(self, duration_sec):
        if self.delay_hint_ms == 0:
            return
        duration = max(1.0, float(duration_sec))
        abs_hint_sec = abs(self.delay_hint_ms) / 1000.0
        hint_radius_sec = HINT_SEARCH_RADIUS_MS / 1000.0
        self.max_delay_sec = max(self.max_delay_sec, min(MAX_DELAY_SEC, abs_hint_sec + hint_radius_sec))
        if self.profile == "trailer":
            self.segment_sec = min(duration, max(self.segment_sec, abs_hint_sec + 24.0))
            self.cluster_tolerance_ms = max(self.cluster_tolerance_ms, 900)

    def build_zones(self, duration_sec):
        duration = float(duration_sec)
        usable = max(0.0, duration - self.segment_sec - 1.0)
        if self.profile == "trailer":
            if usable <= 0.0:
                return [0.0]
            min_gap = max(4.0, self.segment_sec / 2.0)
            desired = int(math.floor(duration / min_gap))
            count = max(1, min(self.max_zones, desired))
            if count <= 1:
                return [0.0]
            step = usable / float(count - 1)
            return [round(step * idx, 2) for idx in range(count)]
        ratios = (0.02, 0.08, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.93)
        zones = []
        for ratio in ratios:
            start = round(usable * ratio)
            if not any(abs(z - start) < 90 for z in zones):
                zones.append(float(start))
            if len(zones) >= self.max_zones:
                break
        return zones or [0.0]

    def extract_raw(self, input_file, output_raw, audio_stream_index, start_sec, label, duration_sec=None):
        start_text = inv(start_sec)
        duration_text = inv(self.segment_sec if duration_sec is None else duration_sec)
        self.log(f"EXTRACT {label} start={start_text} duration={duration_text} stream=0:{audio_stream_index}")
        code, out, err = self.run_cmd([
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            start_text,
            "-i",
            input_file,
            "-t",
            duration_text,
            "-map",
            f"0:{audio_stream_index}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            output_raw,
        ])
        if out.strip():
            self.log(out.strip())
        if err.strip():
            self.log(err.strip())
        if code != 0:
            raise RuntimeError(f"FFmpeg fallo extrayendo audio de {label}. Revisa el LOG.")
        if not os.path.isfile(output_raw):
            raise RuntimeError(f"No se genero el audio temporal de {label}.")
        if os.path.getsize(output_raw) < 10000:
            raise RuntimeError(f"Audio temporal demasiado pequeno en {label}.")

    def get_envelope_20ms(self, raw_path):
        with open(raw_path, "rb") as f:
            samples = array("h")
            samples.frombytes(f.read())
        if sys.byteorder != "little":
            samples.byteswap()
        frame_samples = int(SAMPLE_RATE * FINE_FRAME_MS / 1000)
        frame_count = len(samples) // frame_samples
        if frame_count < 200:
            raise RuntimeError("Muy poco audio para analizar.")
        env = []
        for frame in range(frame_count):
            base = frame * frame_samples
            total = 0.0
            for value in samples[base:base + frame_samples]:
                total += float(value) * float(value)
            rms = math.sqrt(total / frame_samples)
            env.append(math.log(1.0 + rms))
        return env

    def analyze_zone(
        self,
        zone_number,
        start_sec,
        ref_index,
        esp_index,
        work_dir,
        segment_sec=None,
        esp_segment_sec=None,
        search_center_ms=None,
        search_radius_ms=None,
        residual_min_ms=None,
        residual_max_ms=None,
        esp_start_sec=None,
    ):
        segment_sec = float(self.segment_sec if segment_sec is None else segment_sec)
        esp_segment_sec = float(segment_sec if esp_segment_sec is None else esp_segment_sec)
        ref_start_sec = max(0.0, float(start_sec))
        if esp_start_sec is None:
            esp_start_sec = ref_start_sec
        esp_start_sec = max(0.0, float(esp_start_sec))
        effective_center_ms = int(round((ref_start_sec - esp_start_sec) * 1000.0))
        ref_raw = os.path.join(work_dir, f"ref_{zone_number}.raw")
        esp_raw = os.path.join(work_dir, f"esp_{zone_number}.raw")
        self.extract_raw(
            self.ref_file,
            ref_raw,
            ref_index,
            ref_start_sec,
            f"VIDEO BUENO zona {zone_number}",
            duration_sec=segment_sec,
        )
        self.extract_raw(
            self.esp_file,
            esp_raw,
            esp_index,
            esp_start_sec,
            f"AUDIO ESPANOL zona {zone_number}",
            duration_sec=esp_segment_sec,
        )

        ref_env = self.get_envelope_20ms(ref_raw)
        esp_env = self.get_envelope_20ms(esp_raw)
        ref_smooth = smooth(ref_env, 4)
        esp_smooth = smooth(esp_env, 4)
        ref_der = derivative(ref_smooth)
        esp_der = derivative(esp_smooth)

        ref_fine_1 = normalize(ref_smooth)
        esp_fine_1 = normalize(esp_smooth)
        ref_fine_2 = normalize(ref_der)
        esp_fine_2 = normalize(esp_der)

        ref_coarse_1 = normalize(downsample(ref_smooth, COARSE_FACTOR))
        esp_coarse_1 = normalize(downsample(esp_smooth, COARSE_FACTOR))
        ref_coarse_2 = normalize(downsample(ref_der, COARSE_FACTOR))
        esp_coarse_2 = normalize(downsample(esp_der, COARSE_FACTOR))

        coarse_frame_ms = FINE_FRAME_MS * COARSE_FACTOR
        explicit_residual_min_ms = int(residual_min_ms) if residual_min_ms is not None else None
        explicit_residual_max_ms = int(residual_max_ms) if residual_max_ms is not None else None
        if explicit_residual_min_ms is not None and explicit_residual_max_ms is not None:
            if explicit_residual_min_ms > explicit_residual_max_ms:
                raise RuntimeError("Rango residual de audio inválido")
            explicit_radius_ms = max(
                FINE_FRAME_MS,
                abs(explicit_residual_min_ms),
                abs(explicit_residual_max_ms),
            )
        else:
            explicit_radius_ms = max(FINE_FRAME_MS, int(abs(search_radius_ms or 0)))
        if search_center_ms is not None:
            max_coarse_lag = max(1, round(explicit_radius_ms / coarse_frame_ms))
            if explicit_residual_min_ms is not None and explicit_residual_max_ms is not None:
                coarse_min = math.floor(explicit_residual_min_ms / coarse_frame_ms)
                coarse_max = math.ceil(explicit_residual_max_ms / coarse_frame_ms)
            else:
                coarse_min = -max_coarse_lag
                coarse_max = max_coarse_lag
        else:
            max_coarse_lag = round((self.max_delay_sec * 1000.0) / coarse_frame_ms)
        if search_center_ms is None and self.delay_hint_ms != 0:
            center_coarse_lag = round(self.delay_hint_ms / coarse_frame_ms)
            radius_coarse_lag = round(HINT_SEARCH_RADIUS_MS / coarse_frame_ms)
            coarse_min = max(-max_coarse_lag, center_coarse_lag - radius_coarse_lag)
            coarse_max = min(max_coarse_lag, center_coarse_lag + radius_coarse_lag)
        elif search_center_ms is None:
            coarse_min = -max_coarse_lag
            coarse_max = max_coarse_lag
        coarse = find_best_lag_range(
            ref_coarse_1,
            esp_coarse_1,
            ref_coarse_2,
            esp_coarse_2,
            coarse_min,
            coarse_max,
        )

        center_fine_lag = int(coarse["lag"] * COARSE_FACTOR)
        fine_radius_ms = min(2500.0, float(explicit_radius_ms)) if search_center_ms is not None else 2500.0
        fine_radius = max(1, round(fine_radius_ms / FINE_FRAME_MS))
        if search_center_ms is not None and explicit_residual_min_ms is not None and explicit_residual_max_ms is not None:
            fine_bound_min = math.floor(explicit_residual_min_ms / FINE_FRAME_MS)
            fine_bound_max = math.ceil(explicit_residual_max_ms / FINE_FRAME_MS)
        else:
            max_fine_lag = (
                max(1, round(float(explicit_radius_ms) / FINE_FRAME_MS))
                if search_center_ms is not None
                else round((self.max_delay_sec * 1000.0) / FINE_FRAME_MS)
            )
            fine_bound_min = -max_fine_lag
            fine_bound_max = max_fine_lag
        fine_min = max(fine_bound_min, center_fine_lag - fine_radius)
        fine_max = min(fine_bound_max, center_fine_lag + fine_radius)
        fine = find_best_lag_range(ref_fine_1, esp_fine_1, ref_fine_2, esp_fine_2, fine_min, fine_max)

        residual_delay_ms = round(fine["lag"] * FINE_FRAME_MS)
        delay_ms = effective_center_ms + residual_delay_ms if search_center_ms is not None else residual_delay_ms
        score = float(fine["score"])
        if score >= 0.48:
            confidence = "ALTA"
        elif score >= 0.30:
            confidence = "MEDIA"
        elif score >= 0.18:
            confidence = "BAJA"
        else:
            confidence = "MUY BAJA"

        row = {
            "zone": int(zone_number),
            "start_sec": ref_start_sec,
            "start_text": format_time_simple(ref_start_sec),
            "esp_start_sec": esp_start_sec,
            "delay_ms": int(delay_ms),
            "residual_delay_ms": int(residual_delay_ms),
            "score": score,
            "score_gap": float(fine.get("gap") or 0.0),
            "confidence": confidence,
            "delay_hint_ms": int(self.delay_hint_ms),
            "search_center_ms": effective_center_ms if search_center_ms is not None else 0,
            "search_min_ms": int(effective_center_ms + (explicit_residual_min_ms if explicit_residual_min_ms is not None else coarse_min * coarse_frame_ms)) if search_center_ms is not None else int(coarse_min * coarse_frame_ms),
            "search_max_ms": int(effective_center_ms + (explicit_residual_max_ms if explicit_residual_max_ms is not None else coarse_max * coarse_frame_ms)) if search_center_ms is not None else int(coarse_max * coarse_frame_ms),
        }
        with open(self.csv_path, "a", encoding="utf-8") as f:
            f.write(
                f"{row['zone']};{inv(row['start_sec'])};{row['start_text']};{row['delay_ms']};"
                f"{score:.3f};{confidence};0:{ref_index};0:{esp_index}\n"
            )
        return row

    def hybrid_section(self, name):
        section = self.hybrid_config.get(name)
        return section if isinstance(section, dict) else {}

    def build_measurement_cores(self, duration_ref, duration_esp):
        configured = self.hybrid_section("measurement_core")
        started = time.monotonic()
        self.measurement_core = build_measurement_core(duration_ref, self.profile, configured)
        self.esp_measurement_core = build_measurement_core(duration_esp, self.profile, configured)
        elapsed = time.monotonic() - started
        self.diag.event("measurement_core", "measurement_core.built", "Zona útil construida", {
            **self.measurement_core,
            "spanish_audio_core": self.esp_measurement_core,
            "duration_sec": round(elapsed, 6),
        })
        return elapsed

    def fit_audio_timeline(self, rows, score_min=0.0):
        started = time.monotonic()
        usable = [
            row for row in rows
            if float(row.get("score") or 0.0) >= float(score_min)
        ]
        model = fit_timeline_model(
            usable,
            self.profile,
            self.hybrid_section("timeline_model"),
            self.measurement_core.get("span_sec"),
        )
        inlier_indexes = set(model.get("inlier_indexes") or [])
        for index, row in enumerate(usable):
            payload = {
                "anchor": index + 1,
                "ref_time_sec": row.get("start_sec"),
                "esp_time_sec": round(float(row.get("start_sec") or 0.0) - float(row.get("delay_ms") or 0.0) / 1000.0, 6),
                "delay_ms": row.get("delay_ms"),
                "score": row.get("score"),
            }
            if index in inlier_indexes:
                self.diag.event("timeline_model", "timeline_anchor.matched", "Ancla temporal compatible", payload)
            else:
                payload["reason"] = "robust_residual_outlier"
                self.diag.event(
                    "timeline_model",
                    "timeline_anchor.rejected",
                    "Ancla temporal rechazada",
                    payload,
                    level="warning",
                )
        event_name = "timeline_model.fitted" if model.get("compatible") else "timeline_model.incompatible"
        self.diag.event(
            "timeline_model",
            event_name,
            "Modelo temporal ajustado" if model.get("compatible") else "Modelo temporal incompatible",
            model,
            level="info" if model.get("compatible") else "warning",
        )
        self.timeline_model = model
        self.timeline_timing_sec += time.monotonic() - started
        return model

    @staticmethod
    def config_number(section, key, default, minimum=None, maximum=None, integer=False):
        value = section.get(key, default)
        if isinstance(value, bool):
            value = default
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(default)
        if not math.isfinite(number):
            number = float(default)
        if minimum is not None:
            number = max(float(minimum), number)
        if maximum is not None:
            number = min(float(maximum), number)
        return int(round(number)) if integer else number

    @staticmethod
    def config_pcts(section, key, default):
        if key not in section:
            return list(default)
        values = section.get(key)
        if not isinstance(values, list):
            return list(default)
        result = []
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            result.append(max(0.0, min(100.0, number)))
        return result

    def fast_audio_settings(self, duration_sec, around_hint=False):
        duration = max(1.0, float(duration_sec))
        configured = self.hybrid_section("audio_narrow")
        if self.profile == "trailer":
            segment_cap = self.config_number(configured, "segment_cap_sec", 8.0, minimum=6.0, maximum=8.0)
            segment = min(segment_cap, max(6.0, duration * 0.12))
            if duration <= segment + 0.5:
                segment = max(2.0, duration - 0.5)
            return {
                "zone_pcts": self.config_pcts(configured, "zone_pcts", [35.0, 70.0]),
                "segment_sec": segment,
                "radius_ms": self.config_number(
                    configured,
                    "hint_radius_ms" if around_hint else "radius_ms",
                    4000 if around_hint else 1500,
                    minimum=FINE_FRAME_MS,
                    maximum=4000 if around_hint else 1500,
                    integer=True,
                ),
                "tolerance_ms": self.config_number(configured, "tolerance_ms", 140, minimum=20, maximum=140, integer=True),
                "score_min": self.config_number(configured, "score_min", 0.30, minimum=0.30, maximum=1.0),
                "avg_score_min": self.config_number(configured, "avg_score_min", 0.38, minimum=0.38, maximum=1.0),
                "strong_score_min": self.config_number(configured, "strong_score_min", 0.48, minimum=0.48, maximum=1.0),
            }
        segment_cap = self.config_number(configured, "segment_cap_sec", 25.0, minimum=8.0, maximum=25.0)
        return {
            "zone_pcts": self.config_pcts(configured, "zone_pcts", [30.0, 70.0]),
            "segment_sec": min(segment_cap, max(8.0, duration - 0.5)),
            "radius_ms": self.config_number(
                configured,
                "hint_radius_ms" if around_hint else "radius_ms",
                6000 if around_hint else 2000,
                minimum=FINE_FRAME_MS,
                maximum=6000 if around_hint else 2000,
                integer=True,
            ),
            "tolerance_ms": self.config_number(configured, "tolerance_ms", 180, minimum=20, maximum=180, integer=True),
            "score_min": self.config_number(configured, "score_min", 0.30, minimum=0.30, maximum=1.0),
            "avg_score_min": self.config_number(configured, "avg_score_min", 0.38, minimum=0.38, maximum=1.0),
            "strong_score_min": self.config_number(configured, "strong_score_min", 0.48, minimum=0.48, maximum=1.0),
        }

    def discovery_audio_settings(self, duration_sec):
        duration = max(1.0, float(duration_sec))
        configured = self.hybrid_section("audio_discovery")
        if self.profile == "trailer":
            segment_cap = self.config_number(configured, "segment_cap_sec", 12.0, minimum=8.0, maximum=12.0)
            max_delay_sec = self.config_number(configured, "max_delay_ms", 12000, minimum=500, maximum=12000, integer=True) / 1000.0
            segment = min(segment_cap, max(8.0, duration * 0.12))
            if duration <= segment + 0.5:
                segment = max(2.0, duration - 0.5)
            required_span = segment * 0.45 * 2.0
            radius = min(
                max_delay_sec,
                duration * 0.20,
                max(0.0, (duration - segment - required_span - 0.1) / 2.0),
            )
            return {
                "initial_zone_pcts": self.config_pcts(configured, "initial_zone_pcts", [20.0, 50.0, 80.0]),
                "extra_zone_pcts": self.config_pcts(configured, "extra_zone_pcts", [35.0, 65.0, 90.0]),
                "segment_sec": segment,
                "radius_ms": max(500, int(round(radius * 1000.0))),
                "tolerance_ms": self.config_number(configured, "tolerance_ms", 120, minimum=20, maximum=120, integer=True),
                "score_min": self.config_number(configured, "score_min", 0.18, minimum=0.18, maximum=1.0),
                "support_avg_min": self.config_number(configured, "support_avg_min", 0.38, minimum=0.38, maximum=1.0),
                "support_strong_min": self.config_number(configured, "support_strong_min", 0.48, minimum=0.48, maximum=1.0),
                "max_audio_zones": self.config_number(configured, "max_audio_zones", 6, minimum=2, maximum=6, integer=True),
                "max_visual_candidates": self.config_number(configured, "max_visual_candidates", 4, minimum=1, maximum=4, integer=True),
            }
        segment_cap = self.config_number(configured, "segment_cap_sec", 40.0, minimum=12.0, maximum=40.0)
        max_delay_sec = self.config_number(configured, "max_delay_ms", 45000, minimum=1000, maximum=45000, integer=True) / 1000.0
        segment = min(segment_cap, max(12.0, duration - 0.5))
        required_span = segment * 0.45 * 3.0
        radius = min(max_delay_sec, max(0.0, (duration - segment - required_span - 0.1) / 2.0))
        return {
            "initial_zone_pcts": self.config_pcts(configured, "initial_zone_pcts", [12.0, 37.0, 63.0, 88.0]),
            "extra_zone_pcts": self.config_pcts(configured, "extra_zone_pcts", [22.0, 50.0, 78.0, 95.0]),
            "segment_sec": segment,
            "radius_ms": max(1000, int(round(radius * 1000.0))),
            "tolerance_ms": self.config_number(configured, "tolerance_ms", 160, minimum=20, maximum=160, integer=True),
            "score_min": self.config_number(configured, "score_min", 0.18, minimum=0.18, maximum=1.0),
            "support_avg_min": self.config_number(configured, "support_avg_min", 0.38, minimum=0.38, maximum=1.0),
            "support_strong_min": self.config_number(configured, "support_strong_min", 0.48, minimum=0.48, maximum=1.0),
            "max_audio_zones": self.config_number(configured, "max_audio_zones", 8, minimum=2, maximum=8, integer=True),
            "max_visual_candidates": self.config_number(configured, "max_visual_candidates", 4, minimum=1, maximum=4, integer=True),
        }

    @staticmethod
    def build_discovery_audio_zones(
        duration_ref,
        duration_esp,
        settings,
        zone_pcts,
        existing=None,
        ref_core=None,
        esp_core=None,
    ):
        segment = float(settings["segment_sec"])
        radius_sec = float(settings["radius_ms"]) / 1000.0
        ref_core = ref_core or {
            "start_sec": 0.0,
            "end_sec": float(duration_ref),
            "span_sec": float(duration_ref),
        }
        esp_core = esp_core or {
            "start_sec": 0.0,
            "end_sec": float(duration_esp),
            "span_sec": float(duration_esp),
        }
        min_start = max(float(ref_core["start_sec"]), float(esp_core["start_sec"]) + radius_sec)
        max_start = min(
            max(0.0, float(ref_core["end_sec"]) - segment - 0.05),
            max(0.0, float(esp_core["end_sec"]) - segment - radius_sec - 0.05),
        )
        if max_start < min_start:
            return []
        zones = []
        known = list(existing or [])
        minimum_gap = segment * 0.45
        for pct in zone_pcts:
            core_start = core_zone_start(ref_core, pct, segment)
            if core_start is None:
                continue
            ref_start = max(min_start, min(max_start, core_start))
            esp_start = ref_start - radius_sec
            if any(
                abs(ref_start - item["ref_start_sec"]) < minimum_gap
                or abs(esp_start - item["esp_start_sec"]) < minimum_gap
                for item in known + zones
            ):
                continue
            zones.append({
                "pct": float(pct),
                "ref_start_sec": round(ref_start, 6),
                "esp_start_sec": round(esp_start, 6),
                "esp_segment_sec": round(segment + (radius_sec * 2.0), 6),
            })
        return zones

    @staticmethod
    def rank_visual_candidates(clusters, limit=4):
        candidates = []
        for cluster in clusters[:2]:
            delay = int(cluster.get("delay_ms") or 0)
            if delay not in candidates:
                candidates.append(delay)
        if 0 not in candidates:
            candidates.append(0)
        return candidates[:max(1, int(limit))]

    @staticmethod
    def visual_decision_evidence(visual):
        visual = visual if isinstance(visual, dict) else {}
        mode = str(visual.get("verification_mode") or "").strip().lower()
        if mode not in {"absolute", "relative", "none"}:
            mode = "absolute" if visual.get("strong_winner") is True else "none"

        decision_delay = None
        verified = False
        if mode == "absolute":
            candidate = visual.get("winner_delay_ms")
            if visual.get("strong_winner") is True and isinstance(candidate, (int, float)):
                if not isinstance(candidate, bool) and math.isfinite(float(candidate)):
                    decision_delay = int(round(float(candidate)))
                    verified = True
        elif mode == "relative":
            candidate = visual.get("relative_target_delay_ms")
            if visual.get("relative_match") is True and isinstance(candidate, (int, float)):
                if not isinstance(candidate, bool) and math.isfinite(float(candidate)):
                    decision_delay = int(round(float(candidate)))
                    verified = True

        if not verified:
            mode = "none"
        visual["verification_mode"] = mode
        visual["verified"] = verified
        return mode, verified, decision_delay

    @staticmethod
    def build_fast_audio_zones(
        duration_ref,
        duration_esp,
        segment_sec,
        center_ms,
        zone_pcts,
        ref_core=None,
        esp_core=None,
    ):
        segment = max(1.0, float(segment_sec))
        ref_core = ref_core or {
            "start_sec": 0.0,
            "end_sec": float(duration_ref),
            "span_sec": float(duration_ref),
        }
        esp_core = esp_core or {
            "start_sec": 0.0,
            "end_sec": float(duration_esp),
            "span_sec": float(duration_esp),
        }
        min_ref_start = float(ref_core["start_sec"])
        max_ref_start = max(min_ref_start, float(ref_core["end_sec"]) - segment - 0.05)
        min_esp_start = float(esp_core["start_sec"])
        max_esp_start = max(min_esp_start, float(esp_core["end_sec"]) - segment - 0.05)
        center_sec = float(center_ms) / 1000.0
        zones = []
        seen = set()
        for pct in zone_pcts:
            ref_start = core_zone_start(ref_core, pct, segment)
            if ref_start is None:
                continue
            ref_start = min(max_ref_start, max(min_ref_start, ref_start))
            esp_start = ref_start - center_sec
            if (
                ref_start < min_ref_start
                or ref_start > max_ref_start
                or esp_start < min_esp_start
                or esp_start > max_esp_start
            ):
                continue
            effective_center_ms = int(round((ref_start - esp_start) * 1000.0))
            if abs(effective_center_ms - int(center_ms)) > FINE_FRAME_MS:
                continue
            bucket = (round(ref_start, 2), round(esp_start, 2))
            if bucket in seen:
                continue
            minimum_gap = segment * 0.75
            if any(
                abs(ref_start - existing["ref_start_sec"]) < minimum_gap
                or abs(esp_start - existing["esp_start_sec"]) < minimum_gap
                for existing in zones
            ):
                continue
            seen.add(bucket)
            zones.append({
                "pct": float(pct),
                "ref_start_sec": round(ref_start, 6),
                "esp_start_sec": round(esp_start, 6),
            })
        return zones

    @staticmethod
    def cluster_audio_rows(rows, tolerance_ms, score_min):
        usable = [row for row in rows if float(row.get("score") or 0.0) >= float(score_min)]
        clusters = []
        for row in sorted(usable, key=lambda item: int(item.get("delay_ms") or 0)):
            target = None
            for cluster in clusters:
                candidate_delay = int(row.get("delay_ms") or 0)
                cluster_delays = [int(item.get("delay_ms") or 0) for item in cluster["items"]]
                if (
                    abs(candidate_delay - float(cluster["center"])) <= int(tolerance_ms)
                    and max(cluster_delays + [candidate_delay]) - min(cluster_delays + [candidate_delay])
                    <= int(tolerance_ms)
                ):
                    target = cluster
                    break
            if target is None:
                target = {"center": float(int(row.get("delay_ms") or 0)), "items": []}
                clusters.append(target)
            target["items"].append(row)
            weights = [max(0.05, float(item.get("score") or 0.0)) ** 2 for item in target["items"]]
            target["center"] = sum(
                int(item.get("delay_ms") or 0) * weight for item, weight in zip(target["items"], weights)
            ) / sum(weights)
        ranked = []
        for cluster in clusters:
            items = cluster["items"]
            delays = [int(item.get("delay_ms") or 0) for item in items]
            ranked.append({
                "delay_ms": int(round(cluster["center"])),
                "count": len(items),
                "avg_score": sum(float(item.get("score") or 0.0) for item in items) / len(items),
                "spread_ms": max(delays) - min(delays),
                "items": items,
            })
        return sorted(ranked, key=lambda item: (item["count"], item["avg_score"]), reverse=True)

    def remove_work_dir_checked(self, work_dir):
        if os.path.isdir(work_dir):
            try:
                shutil.rmtree(work_dir)
            except OSError as exc:
                self.diag.event("cleanup", "failed", "No se pudo eliminar el temporal de medición", {
                    "scope": "measurement_tmp",
                    "path": work_dir,
                    "error": str(exc),
                    "decision": "remaining",
                }, level="error")
                raise RuntimeError(f"No he podido eliminar el temporal propio: {work_dir}") from exc
        if os.path.exists(work_dir):
            self.diag.event("cleanup", "failed", "El temporal de medición sigue existiendo", {
                "scope": "measurement_tmp",
                "path": work_dir,
                "error": "path_still_exists",
                "decision": "remaining",
            }, level="error")
            raise RuntimeError(f"El temporal propio sigue existiendo: {work_dir}")

    def hybrid_fps_summary(self):
        summary = dict(self.fps_confirmation) if isinstance(self.fps_confirmation, dict) else {}
        summary.update({
            "planned": self.fps_plan_enabled,
            "provisional": self.fps_plan_provisional,
            "confirmed": self.fps_plan_confirmed,
            "applied": bool(
                self.fps_plan_enabled
                and self.fps_plan_provisional
                and self.fps_plan_confirmed
            ),
            "ref_fps": self.fps_ref,
            "esp_fps": self.fps_esp,
            "tempo": self.fps_tempo,
        })
        if not self.fps_plan_enabled:
            if self.fps_ref > 0 and self.fps_esp > 0 and round(self.fps_ref, 3) == round(self.fps_esp, 3):
                summary["reason"] = "fps_iguales"
            elif self.fps_ref <= 0 or self.fps_esp <= 0:
                summary["reason"] = "fps_no_detectado"
            else:
                summary["reason"] = "fps_no_confirmado"
        return summary

    def finish_hybrid_result(
        self,
        state,
        delay_ms,
        visual,
        audio,
        reason,
        contradictions,
        timing,
        ref_index,
        esp_index,
        stage="fast_path",
    ):
        verified = state == "OK_VERIFICADO"
        timing.setdefault("metadata_sec", round(self.metadata_timing_sec, 3))
        timing.setdefault("core_sec", round(self.core_timing_sec, 6))
        timing["anchors_sec"] = round(self.timeline_timing_sec, 6)
        if self.fps_plan_enabled:
            timing["fps_sec"] = round(
                float(timing.get("audio_hint_sec") or 0.0)
                + float(timing.get("audio_discovery_sec") or 0.0)
                + float(timing.get("visual_final_sec") or 0.0),
                3,
            )
        if self.delay_hint_ms != 0:
            hint_error_ms = int(round(float(delay_ms or 0))) - int(self.delay_hint_ms)
            hint_tolerance = int(self.hybrid_section("audio_narrow").get("tolerance_ms") or 180)
            hint_rejection_tolerance = max(1000, hint_tolerance * 5)
            self.hint_evidence.update({
                "hint_used": True,
                "hint_error_ms": hint_error_ms,
                "hint_helped_fast_path": bool(
                    self.hint_evidence.get("hint_helped_fast_path")
                    or (
                        verified
                        and stage == "fast_path"
                        and abs(hint_error_ms) <= hint_tolerance
                    )
                ),
                "hint_rejected": abs(hint_error_ms) > hint_rejection_tolerance,
            })
            self.diag.event("edit_hint", "edit_hint.used", "Ayuda Editar utilizada como semilla", {
                "delay_hint_ms": self.delay_hint_ms,
                "hint_is_measurement": False,
                "final_delay_ms": int(round(float(delay_ms or 0))),
                "hint_error_ms": hint_error_ms,
            })
            if self.hint_evidence["hint_helped_fast_path"]:
                self.diag.event("edit_hint", "edit_hint.helped", "La ayuda aceleró el fast path", self.hint_evidence)
            elif self.hint_evidence["hint_rejected"]:
                self.diag.event(
                    "edit_hint",
                    "edit_hint.rejected",
                    "La medición descartó la ayuda",
                    self.hint_evidence,
                    level="warning",
                )
        rows = list(audio.get("results") or [])
        scores = [float(row.get("score") or 0.0) for row in rows]
        data = {
            "ok": True,
            "state": state,
            "export_allowed": verified,
            "delay_ms": int(round(float(delay_ms or 0))),
            "confidence": "ALTA" if verified else "BAJA",
            "fps_correction": self.hybrid_fps_summary(),
            "measurement_core": dict(self.measurement_core),
            "timeline_model": dict(self.timeline_model),
            "visual": visual,
            "audio": audio,
            "edit_hint": dict(self.hint_evidence),
            "decision": {
                "reason": str(reason or ""),
                "contradictions": list(contradictions or []),
            },
            "profile": self.profile,
            "stage": stage,
            "zones_count": int(audio.get("supporting_zones") or 0),
            "avg_score": (sum(scores) / len(scores)) if scores else 0.0,
            "results": rows,
            "timing": timing,
            "delay_hint_ms": self.delay_hint_ms,
            "ref_stream": f"0:{ref_index}",
            "esp_stream": f"0:{esp_index}",
            "csv_path": self.csv_path,
            "log_path": self.log_path,
        }
        self.write_result(data)
        self.write_progress("done", 100, "Verificado" if verified else "Bloqueado")
        self.diag.event("measurement", "result_candidate", "Resultado candidato del motor", {
            "profile": self.profile,
            "state": state,
            "export_allowed": verified,
            "delay_ms": data["delay_ms"],
            "reason": reason,
            "contradictions": list(contradictions or []),
            "duration_sec": timing.get("measurement_sec"),
        })
        self.diag.event("decision", "decision.final", "Decisión final del motor híbrido", {
            "state": state,
            "export_allowed": verified,
            "delay_ms": data["delay_ms"],
            "reason": reason,
            "timeline_compatible": bool(self.timeline_model.get("compatible")),
        }, level="info" if verified else "warning")
        self.diag.finish("done", data)
        return 0

    def create_visual_verifier(self):
        visual_overrides = visual_overrides_from_profile_config(self.hybrid_config)
        return VisualVerifier(
            profile_overrides={self.profile: visual_overrides},
            event_callback=lambda phase, event, data: self.diag.event(
                "visual_gate" if phase == "visual_fast_path" else phase,
                event,
                "Verificación visual",
                data,
            ),
        )

    def try_provisional_fps_hint_seed(
        self,
        duration_ref,
        duration_esp,
        ref_index,
        esp_index,
        timing,
        total_started,
    ):
        """Prueba el hint como semilla rápida; nunca lo convierte en medida."""

        if self.delay_hint_ms == 0:
            return None
        narrow = self.fast_audio_settings(min(duration_ref, duration_esp), around_hint=True)
        timeline_settings = self.hybrid_section("timeline_model")
        anchor_pcts = self.config_pcts(
            timeline_settings,
            "anchor_pcts",
            [35.0, 52.0, 70.0] if self.profile == "trailer" else [30.0, 50.0, 70.0],
        )
        initial_zones = self.build_fast_audio_zones(
            duration_ref,
            duration_esp,
            narrow["segment_sec"],
            self.delay_hint_ms,
            anchor_pcts,
            ref_core=self.measurement_core,
            esp_core=self.esp_measurement_core,
        )
        if len(initial_zones) < 3:
            return None
        initial_zones = initial_zones[:3]
        discovery = self.discovery_audio_settings(min(duration_ref, duration_esp))
        extra_zones = self.build_fast_audio_zones(
            duration_ref,
            duration_esp,
            narrow["segment_sec"],
            self.delay_hint_ms,
            discovery["extra_zone_pcts"],
            ref_core=self.measurement_core,
            esp_core=self.esp_measurement_core,
        )
        minimum_gap = float(narrow["segment_sec"]) * 0.75
        extra_zones = [
            zone for zone in extra_zones
            if all(
                abs(float(zone["ref_start_sec"]) - float(existing["ref_start_sec"])) >= minimum_gap
                and abs(float(zone["esp_start_sec"]) - float(existing["esp_start_sec"])) >= minimum_gap
                for existing in initial_zones
            )
        ][:1]
        zones = initial_zones + extra_zones

        work_dir = os.path.join(self.job_dir, "tmp")
        self.remove_work_dir_checked(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        started = time.monotonic()
        rows = []
        zones_run = []
        clusters = []
        top = None
        stable = False
        self.diag.event("fps_audio_seed", "started", "Semilla Editar para FPS iniciada", {
            "delay_hint_ms": self.delay_hint_ms,
            "hint_is_measurement": False,
            "zones": len(initial_zones),
            "radius_ms": narrow["radius_ms"],
        })
        try:
            for index, zone in enumerate(zones, 1):
                if index > len(initial_zones):
                    self.diag.event("fps_audio_seed", "expanded", "Semilla ampliada por una duda concreta", {
                        "reason": "hint_seed_inconsistent",
                        "zones_attempted_before": len(zones_run),
                        "extra_pct": zone["pct"],
                    })
                zones_run.append(zone)
                try:
                    row = self.analyze_zone(
                        index,
                        zone["ref_start_sec"],
                        ref_index,
                        esp_index,
                        work_dir,
                        segment_sec=narrow["segment_sec"],
                        search_center_ms=self.delay_hint_ms,
                        search_radius_ms=narrow["radius_ms"],
                        esp_start_sec=zone["esp_start_sec"],
                    )
                    if abs(int(row.get("delay_ms") or 0) - self.delay_hint_ms) > int(narrow["radius_ms"]):
                        self.diag.event("fps_audio_seed", "zone_rejected", "Ancla fuera del radio de la semilla", {
                            "zone": index,
                            "delay_ms": row.get("delay_ms"),
                            "delay_hint_ms": self.delay_hint_ms,
                            "radius_ms": narrow["radius_ms"],
                        }, level="warning")
                        continue
                    rows.append(row)
                except Exception as exc:
                    if not self.is_expected_zone_rejection(exc):
                        raise
                    self.diag.event("fps_audio_seed", "zone_rejected", "Ancla de semilla no útil", {
                        "zone": index,
                        "reason": str(exc),
                    }, level="warning")
                if len(rows) >= 3:
                    clusters = self.cluster_audio_rows(rows, narrow["tolerance_ms"], narrow["score_min"])
                    top = clusters[0] if clusters else None
                    model = fit_timeline_model(
                        [row for row in rows if float(row.get("score") or 0.0) >= float(narrow["score_min"])],
                        self.profile,
                        timeline_settings,
                        self.measurement_core.get("span_sec"),
                    )
                    unique = bool(
                        top
                        and (len(clusters) < 2 or int(top["count"]) > int(clusters[1]["count"]))
                    )
                    stable = bool(
                        top
                        and int(top["count"]) >= 3
                        and float(top["avg_score"]) >= float(narrow["avg_score_min"])
                        and any(
                            float(row.get("score") or 0.0) >= float(narrow["strong_score_min"])
                            for row in top.get("items") or []
                        )
                        and int(top["spread_ms"]) <= int(narrow["tolerance_ms"])
                        and unique
                        and model.get("compatible") is True
                    )
                    if stable:
                        break
        finally:
            self.remove_work_dir_checked(work_dir)

        elapsed = time.monotonic() - started
        self.diag.event("fps_audio_seed", "finished", "Semilla Editar para FPS terminada", {
            "delay_hint_ms": self.delay_hint_ms,
            "zones_attempted": len(zones_run),
            "zones_measured": len(rows),
            "candidate_delay_ms": (top or {}).get("delay_ms"),
            "stable": stable,
            "duration_sec": round(elapsed, 3),
            "decision": "visual_confirmation" if stable else "audio_discovery",
        })
        timing["audio_hint_sec"] = round(elapsed, 3)
        if not stable:
            return None

        self.hint_evidence["hint_helped_fast_path"] = True
        public_clusters = [
            {key: value for key, value in cluster.items() if key != "items"}
            for cluster in clusters
        ]
        settings = {
            "score_min": narrow["score_min"],
            "support_avg_min": narrow["avg_score_min"],
            "support_strong_min": narrow["strong_score_min"],
            "tolerance_ms": narrow["tolerance_ms"],
        }
        return self.finish_provisional_fps_discovery(
            duration_ref,
            ref_index,
            esp_index,
            settings,
            clusters,
            public_clusters,
            rows,
            zones_run,
            len(zones_run) > len(initial_zones),
            "hint_seed_inconsistent" if len(zones_run) > len(initial_zones) else "",
            timing,
            total_started,
            0.0,
        )

    def finish_provisional_fps_discovery(
        self,
        duration_ref,
        ref_index,
        esp_index,
        settings,
        clusters,
        ranked_public,
        rows,
        zones_run,
        expanded,
        expansion_reason,
        timing,
        total_started,
        discovery_sec,
    ):
        top_cluster = clusters[0] if clusters else None
        supporting_rows = list((top_cluster or {}).get("items") or [])
        support_count = int((top_cluster or {}).get("count") or 0)
        support_avg = float((top_cluster or {}).get("avg_score") or 0.0)
        support_spread = int((top_cluster or {}).get("spread_ms") or 0)
        support_strong = sum(
            1 for row in supporting_rows
            if float(row.get("score") or 0.0) >= float(settings["support_strong_min"])
        )
        unique_audio_top = bool(
            top_cluster is not None
            and (
                len(clusters) < 2
                or int(clusters[0]["count"]) > int(clusters[1]["count"])
            )
        )
        required_support = 3
        timeline_model = self.fit_audio_timeline(rows, settings["score_min"])
        audio_stable = bool(
            support_count >= required_support
            and support_avg >= float(settings["support_avg_min"])
            and support_strong >= 1
            and support_spread <= int(settings["tolerance_ms"])
            and unique_audio_top
            and timeline_model.get("compatible") is True
        )
        provisional_delay = int((top_cluster or {}).get("delay_ms") or 0)
        audio = {
            "method": "fps_provisional_audio_cluster_v1",
            "delay_ms": provisional_delay,
            "supporting_zones": support_count,
            "required_supporting_zones": required_support,
            "strong_zones": support_strong,
            "avg_score": support_avg,
            "spread_ms": support_spread,
            "tolerance_ms": int(settings["tolerance_ms"]),
            "zones_attempted": len(zones_run),
            "zones_measured": len(rows),
            "zones_separated": bool(
                float(timeline_model.get("span_sec") or 0.0)
                >= float(timeline_model.get("minimum_span_sec") or 0.0)
            ),
            "slope_ms_per_sec": timeline_model.get("drift_ms_per_sec"),
            "slope_limit_ms_per_sec": self.hybrid_section("timeline_model").get("max_drift_ms_per_sec"),
            "span_sec": timeline_model.get("span_sec"),
            "timeline_model": timeline_model,
            "stable": audio_stable,
            "expanded": expanded,
            "expansion_reason": expansion_reason,
            "hint_ms": self.delay_hint_ms,
            "hint_is_measurement": False,
            "clusters": ranked_public,
            "results": rows,
        }
        self.diag.event("fps_audio_evidence", "finished", "Corroboración provisional de audio terminada", {
            "delay_ms": provisional_delay,
            "supporting_zones": support_count,
            "required_supporting_zones": required_support,
            "spread_ms": support_spread,
            "slope_ms_per_sec": timeline_model.get("drift_ms_per_sec"),
            "slope_limit_ms_per_sec": self.hybrid_section("timeline_model").get("max_drift_ms_per_sec"),
            "zones_separated": bool(
                float(timeline_model.get("span_sec") or 0.0)
                >= float(timeline_model.get("minimum_span_sec") or 0.0)
            ),
            "stable": audio_stable,
            "decision": "visual_confirmation" if audio_stable else "blocked",
        }, level="info" if audio_stable else "error")
        timing["audio_discovery_sec"] = round(discovery_sec, 3)

        if not audio_stable:
            self.fps_plan_confirmed = False
            self.fps_confirmation.update({
                "planned": True,
                "provisional": True,
                "confirmed": False,
                "applied": False,
                "enabled": False,
                "reason": "audio_corregido_no_confirma_tempo",
                "audio": audio,
            })
            visual = {
                "verified": False,
                "stage": "fps_visual_skipped",
                "reason": "audio_corregido_no_confirma_tempo",
                "zones_attempted": 0,
                "zones_valid": 0,
            }
            timing["visual_final_sec"] = 0.0
            timing["measurement_sec"] = round(time.monotonic() - total_started, 3)
            return self.finish_hybrid_result(
                "FPS_NO_CONFIRMADOS",
                provisional_delay,
                visual,
                audio,
                "audio_corregido_no_confirma_tempo",
                ["fps_audio_timeline_not_confirmed"],
                timing,
                ref_index,
                esp_index,
                stage="fps_provisional",
            )

        verifier = self.create_visual_verifier()
        visual_started = time.monotonic()
        self.diag.event("fps_visual_confirmation", "started", "Confirmación visual FPS iniciada", {
            "delay_ms": provisional_delay,
            "tempo": self.fps_tempo,
            "video_espanol_original": self.esp_video_original,
        })
        confirmation = verifier.confirm_fps_plan(
            self.ref_file,
            self.esp_video_original,
            self.fps_ref,
            self.fps_esp,
            self.profile,
            provisional_delay,
            audio,
        )
        visual_sec = time.monotonic() - visual_started
        self.fps_confirmation = dict(confirmation)
        self.fps_plan_provisional = confirmation.get("provisional") is True
        self.fps_plan_confirmed = confirmation.get("confirmed") is True
        visual = dict(confirmation.get("visual") or {})
        visual["stage"] = "fps_visual_confirmation"
        visual["tempo"] = self.fps_tempo
        visual["used_original_spanish_video"] = True
        for comparison in visual.get("comparisons") or []:
            self.diag.event("fps_visual_confirmation", "zone_scored", "Zona visual FPS comparada", comparison)
        self.diag.event("fps_visual_confirmation", "finished", "Confirmación visual FPS terminada", {
            "delay_ms": provisional_delay,
            "confirmed": self.fps_plan_confirmed,
            "absolute_match": bool(visual.get("absolute_match")),
            "relative_match": bool(visual.get("relative_match")),
            "relative_wins": int(visual.get("relative_wins") or 0),
            "mean_delta": visual.get("mean_delta"),
            "reason": confirmation.get("reason"),
            "duration_sec": round(visual_sec, 3),
            "decision": "confirmed" if self.fps_plan_confirmed else "blocked",
        }, level="info" if self.fps_plan_confirmed else "error")
        timing["visual_final_sec"] = round(visual_sec, 3)
        timing["measurement_sec"] = round(time.monotonic() - total_started, 3)
        if self.fps_plan_confirmed:
            state = "OK_VERIFICADO"
            reason = confirmation.get("reason") or "interior_timeline_audio_and_visual_match"
            contradictions = []
        else:
            state = "FPS_NO_CONFIRMADOS"
            reason = confirmation.get("reason") or "fps_no_confirmados"
            contradictions = ["fps_plan_not_confirmed"]
        return self.finish_hybrid_result(
            state,
            provisional_delay,
            visual,
            audio,
            reason,
            contradictions,
            timing,
            ref_index,
            esp_index,
            stage="fps_provisional",
        )

    def run_hybrid_discovery(
        self,
        duration_ref,
        duration_esp,
        ref_index,
        esp_index,
        fast_visual,
        fast_audio,
        timing,
        total_started,
        initial_reason,
    ):
        settings = self.discovery_audio_settings(min(duration_ref, duration_esp))
        initial_zones = self.build_discovery_audio_zones(
            duration_ref,
            duration_esp,
            settings,
            settings["initial_zone_pcts"],
            ref_core=self.measurement_core,
            esp_core=self.esp_measurement_core,
        )
        if len(initial_zones) < 2:
            self.diag.event("audio_discovery", "started", "Descubrimiento de candidatos iniciado", {
                "profile": self.profile,
                "initial_reason": initial_reason,
                "zone_pcts": settings["initial_zone_pcts"],
                "segment_sec": settings["segment_sec"],
                "radius_ms": settings["radius_ms"],
            })
            self.diag.event("audio_discovery", "finished", "Descubrimiento sin dos zonas independientes", {
                "zones_attempted": 0,
                "zones_measured": 0,
                "expanded": False,
                "expansion_reason": "insufficient_discovery_zones",
                "candidate_delays_ms": [],
                "duration_sec": 0.0,
            })
            visual = dict(fast_visual or {})
            visual["verified"] = False
            audio = {
                "method": "legacy_correlation_discovery_v1",
                "supporting_zones": 0,
                "zones_attempted": 0,
                "results": [],
                "fast_path": {
                    "supporting_zones": int((fast_audio or {}).get("supporting_zones") or 0),
                    "reason": initial_reason,
                },
            }
            timing["audio_discovery_sec"] = 0.0
            timing["visual_final_sec"] = 0.0
            timing["measurement_sec"] = round(time.monotonic() - total_started, 3)
            return self.finish_hybrid_result(
                "SIN_ZONAS_VALIDAS",
                0,
                visual,
                audio,
                "descubrimiento_sin_dos_zonas_independientes",
                ["insufficient_discovery_zones"],
                timing,
                ref_index,
                esp_index,
                stage="adaptive_discovery",
            )

        work_dir = os.path.join(self.job_dir, "tmp")
        self.remove_work_dir_checked(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        discovery_started = time.monotonic()
        rows = []
        zones_run = []
        expanded = False
        expansion_reason = ""
        self.diag.event("audio_discovery", "started", "Descubrimiento de candidatos iniciado", {
            "profile": self.profile,
            "initial_reason": initial_reason,
            "zone_pcts": settings["initial_zone_pcts"],
            "segment_sec": settings["segment_sec"],
            "radius_ms": settings["radius_ms"],
            "tolerance_ms": settings["tolerance_ms"],
        })

        def measure_zones(zones):
            start_index = len(zones_run)
            for offset, zone in enumerate(zones, 1):
                index = start_index + offset
                if index > int(settings["max_audio_zones"]):
                    break
                zones_run.append(zone)
                radius_ms = int(settings["radius_ms"])
                center_ms = int(round((zone["ref_start_sec"] - zone["esp_start_sec"]) * 1000.0))
                residual_min_ms = -radius_ms - center_ms
                residual_max_ms = radius_ms - center_ms
                self.write_progress(
                    "audio_discovery",
                    min(95, (index / int(settings["max_audio_zones"])) * 100),
                    "Buscando",
                    int(settings["max_audio_zones"]),
                    index - 1,
                )
                self.diag.event("audio_discovery", "zone_started", "Midiendo zona de descubrimiento", {
                    "zone": index,
                    "pct": zone["pct"],
                    "ref_start_sec": zone["ref_start_sec"],
                    "esp_start_sec": zone["esp_start_sec"],
                    "search_min_ms": -radius_ms,
                    "search_max_ms": radius_ms,
                })
                try:
                    row = self.analyze_zone(
                        index,
                        zone["ref_start_sec"],
                        ref_index,
                        esp_index,
                        work_dir,
                        segment_sec=settings["segment_sec"],
                        esp_segment_sec=zone["esp_segment_sec"],
                        search_center_ms=center_ms,
                        search_radius_ms=radius_ms,
                        residual_min_ms=residual_min_ms,
                        residual_max_ms=residual_max_ms,
                        esp_start_sec=zone["esp_start_sec"],
                    )
                    row["discovery_pct"] = zone["pct"]
                    rows.append(row)
                    self.diag.event("audio_discovery", "zone_finished", "Zona de descubrimiento medida", row)
                except Exception as exc:
                    self.log(f"ERROR DESCUBRIMIENTO ZONA {index}: {exc}")
                    if self.is_expected_zone_rejection(exc):
                        self.diag.event("audio_discovery", "zone_rejected", "Zona de descubrimiento no útil", {
                            "zone": index,
                            "reason": str(exc),
                            "decision": "skipped",
                        })
                    else:
                        self.diag.error(classify_error(str(exc)), "audio_discovery", "Zona de descubrimiento fallida", {
                            "zone": index,
                            "error": str(exc),
                        }, exc)
                        raise RuntimeError(
                            f"Fallo técnico en zona de descubrimiento {index}: {exc}"
                        ) from exc

        try:
            measure_zones(initial_zones)
            clusters = self.cluster_audio_rows(rows, settings["tolerance_ms"], settings["score_min"])
            top_count = int(clusters[0]["count"]) if clusters else 0
            tied_top = bool(len(clusters) > 1 and int(clusters[1]["count"]) == top_count)
            if top_count < 2 or tied_top:
                expansion_reason = "sin_cluster_repetido" if top_count < 2 else "clusters_empatados"
                extra_zones = self.build_discovery_audio_zones(
                    duration_ref,
                    duration_esp,
                    settings,
                    settings["extra_zone_pcts"],
                    existing=zones_run,
                    ref_core=self.measurement_core,
                    esp_core=self.esp_measurement_core,
                )
                remaining = max(0, int(settings["max_audio_zones"]) - len(zones_run))
                extra_zones = extra_zones[:remaining]
                for extra_index, extra_zone in enumerate(extra_zones, 1):
                    current_clusters = self.cluster_audio_rows(
                        rows,
                        settings["tolerance_ms"],
                        settings["score_min"],
                    )
                    current_top_count = int(current_clusters[0]["count"]) if current_clusters else 0
                    current_tied_top = bool(
                        len(current_clusters) > 1
                        and int(current_clusters[1]["count"]) == current_top_count
                    )
                    if current_top_count >= 3 and not current_tied_top:
                        break
                    if current_top_count < 2:
                        expansion_reason = "sin_cluster_repetido"
                    elif current_tied_top:
                        expansion_reason = "clusters_empatados"
                    else:
                        expansion_reason = "corroboracion_insuficiente"
                    expanded = True
                    self.diag.event("audio_discovery", "expanded", "Se amplía por una duda concreta", {
                        "reason": expansion_reason,
                        "extra_zone": extra_index,
                        "zones_attempted_before": len(zones_run),
                        "max_audio_zones": settings["max_audio_zones"],
                    })
                    measure_zones([extra_zone])
            clusters = self.cluster_audio_rows(rows, settings["tolerance_ms"], settings["score_min"])
        finally:
            self.remove_work_dir_checked(work_dir)
            self.diag.event("cleanup", "remove_discovery_tmp", "Temporales de descubrimiento eliminados", {
                "work_dir": work_dir,
            })

        discovery_sec = time.monotonic() - discovery_started
        ranked_public = []
        for rank, cluster in enumerate(clusters, 1):
            public = {key: value for key, value in cluster.items() if key != "items"}
            public["rank"] = rank
            ranked_public.append(public)
            self.diag.event("audio_discovery", "candidate_ranked", "Candidato de audio ordenado", public)
        candidates = self.rank_visual_candidates(
            clusters,
            settings["max_visual_candidates"],
        )
        self.diag.event("audio_discovery", "finished", "Descubrimiento de candidatos terminado", {
            "zones_attempted": len(zones_run),
            "zones_measured": len(rows),
            "expanded": expanded,
            "expansion_reason": expansion_reason,
            "candidate_delays_ms": candidates,
            "duration_sec": round(discovery_sec, 3),
        })

        if self.fps_plan_enabled and self.fps_plan_provisional and not self.fps_plan_confirmed:
            return self.finish_provisional_fps_discovery(
                duration_ref,
                ref_index,
                esp_index,
                settings,
                clusters,
                ranked_public,
                rows,
                zones_run,
                expanded,
                expansion_reason,
                timing,
                total_started,
                discovery_sec,
            )

        if not candidates:
            candidates = [0]
        timeline_model = self.fit_audio_timeline(rows, settings["score_min"])
        verifier = self.create_visual_verifier()
        visual_started = time.monotonic()
        tempo = self.fps_tempo if self.fps_plan_enabled else 1.0
        visual = verifier.score_candidates(
            self.ref_file,
            self.esp_video_original,
            candidates,
            profile=self.profile,
            tempo=tempo,
            stage="visual_final",
        )
        visual = dict(visual)
        visual_mode, visual_verified, visual_winner = self.visual_decision_evidence(visual)
        visual["fast_path"] = {
            "winner_delay_ms": (fast_visual or {}).get("winner_delay_ms"),
            "strong_winner": bool((fast_visual or {}).get("strong_winner")),
            "zones_valid": int((fast_visual or {}).get("zones_valid") or 0),
            "verification_mode": str((fast_visual or {}).get("verification_mode") or "none"),
            "reason": initial_reason,
        }
        for candidate in visual.get("candidates") or []:
            self.diag.event("visual_final", "candidate_scored", "Candidato visual final puntuado", candidate)
        visual_final_sec = time.monotonic() - visual_started
        self.diag.event("visual_final", "finished", "Validación visual final terminada", {
            "profile": self.profile,
            "zones_attempted": int(visual.get("zones_attempted") or 0),
            "zones_valid": int(visual.get("zones_valid") or 0),
            "zones_strong": int(visual.get("zones_strong") or 0),
            "winner_delay_ms": visual.get("winner_delay_ms"),
            "unique_winner": bool(visual.get("unique_winner")),
            "strong_winner": bool(visual.get("strong_winner")),
            "verified": visual_verified,
            "verification_mode": visual_mode,
            "decision_delay_ms": visual_winner,
            "duration_sec": round(visual_final_sec, 3),
        })

        tolerance_ms = int(settings["tolerance_ms"])
        matching_clusters = []
        if visual_winner is not None:
            matching_clusters = [
                cluster for cluster in clusters
                if abs(int(cluster["delay_ms"]) - int(visual_winner)) <= tolerance_ms
            ]
        support_cluster = matching_clusters[0] if matching_clusters else None
        top_cluster = clusters[0] if clusters else None
        supporting_rows = list((support_cluster or {}).get("items") or [])
        support_count = int((support_cluster or {}).get("count") or 0)
        support_avg = float((support_cluster or {}).get("avg_score") or 0.0)
        support_spread = int((support_cluster or {}).get("spread_ms") or 0)
        support_strong = sum(
            1 for row in supporting_rows
            if float(row.get("score") or 0.0) >= float(settings["support_strong_min"])
        )
        unique_audio_top = bool(
            support_cluster is not None
            and top_cluster is support_cluster
            and (
                len(clusters) < 2
                or int(clusters[0]["count"]) > int(clusters[1]["count"])
            )
        )
        required_support = 3
        audio_support_ok = bool(
            support_count >= required_support
            and support_avg >= float(settings["support_avg_min"])
            and support_strong >= 1
            and support_spread <= tolerance_ms
            and unique_audio_top
            and timeline_model.get("compatible") is True
        )
        contradictions = []
        if not visual_verified:
            contradictions.append("visual_final_not_verified")
        if not audio_support_ok:
            contradictions.append("audio_does_not_support_visual_winner")
        if timeline_model.get("compatible") is not True:
            contradictions.append("timeline_model_incompatible")
        if support_cluster is not None and top_cluster is not support_cluster:
            contradictions.append("stronger_audio_candidate_disagrees")
        if support_cluster is not None and top_cluster is support_cluster and not unique_audio_top:
            contradictions.append("audio_top_clusters_ambiguous")
        if self.fps_plan_enabled and not self.fps_plan_confirmed:
            contradictions.append("fps_plan_not_confirmed")

        usable_delays = [
            int(row["delay_ms"])
            for row in rows
            if float(row.get("score") or 0.0) >= float(settings["score_min"])
        ]
        audio_spread = max(usable_delays) - min(usable_delays) if len(usable_delays) >= 2 else 0
        valid_visual_winners = {
            int(zone["winner_delay_ms"])
            for zone in visual.get("zones") or []
            if zone.get("state") in {"FUERTE", "VALIDA"} and zone.get("winner_delay_ms") is not None
        }
        repeated_audio_clusters = [
            cluster for cluster in clusters
            if int(cluster.get("count") or 0) >= 2
            and float(cluster.get("avg_score") or 0.0) >= float(settings["support_avg_min"])
            and any(
                float(item.get("score") or 0.0) >= float(settings["support_strong_min"])
                for item in cluster.get("items") or []
            )
        ]
        multiple_repeated_audio_delays = any(
            abs(int(left["delay_ms"]) - int(right["delay_ms"])) > tolerance_ms
            for index, left in enumerate(repeated_audio_clusters)
            for right in repeated_audio_clusters[index + 1:]
        )
        mounting_different = bool(
            len(valid_visual_winners) >= 2
            or multiple_repeated_audio_delays
            or (
                int(timeline_model.get("anchors_total") or 0) >= 3
                and timeline_model.get("reason") in {
                    "timeline_residuals_too_high",
                    "timeline_drift_too_high",
                    "too_many_rejected_anchors",
                }
            )
            or (
                len(usable_delays) >= 3
                and int((top_cluster or {}).get("count") or 0) < 2
                and audio_spread > max(1000, tolerance_ms * 5)
            )
        )
        if multiple_repeated_audio_delays:
            contradictions.append("multiple_repeated_audio_delays")
        if len(valid_visual_winners) >= 2:
            contradictions.append("multiple_visual_delays")
        if visual_verified and audio_support_ok and not contradictions:
            state = "OK_VERIFICADO"
            reason = (
                "descubrimiento_audio_timeline_y_visual_relativo_coinciden"
                if visual_mode == "relative"
                else "descubrimiento_audio_y_visual_coinciden"
            )
            final_delay = int(support_cluster["delay_ms"])
            contradictions = []
        elif mounting_different:
            state = "MONTAJE_DISTINTO"
            reason = "ningun_delay_fijo_explica_las_zonas"
            final_delay = int((top_cluster or {}).get("delay_ms") or 0)
        elif visual_verified:
            state = "AUDIO_VIDEO_ORIGEN_DUDOSO"
            reason = "imagen_alinea_pero_audio_no_sostiene_el_mismo_origen"
            final_delay = int(visual_winner or 0)
        elif not rows and int(visual.get("zones_valid") or 0) == 0:
            state = "SIN_ZONAS_VALIDAS"
            reason = "sin_zonas_utiles_en_audio_o_imagen"
            final_delay = 0
        else:
            state = "NO_FIABLE"
            reason = "descubrimiento_sin_evidencia_suficiente"
            final_delay = int(visual_winner if visual_winner is not None else (top_cluster or {}).get("delay_ms") or 0)

        coherent_cluster = top_cluster or {"delay_ms": 0, "count": 0, "avg_score": 0.0, "items": []}
        audio = {
            "method": "legacy_correlation_discovery_v1",
            "delay_ms": int(coherent_cluster["delay_ms"]),
            "supporting_zones": int(coherent_cluster["count"]),
            "visual_supporting_zones": support_count,
            "strong_zones": support_strong,
            "avg_score": float(coherent_cluster["avg_score"]),
            "zones_attempted": len(zones_run),
            "zones_measured": len(rows),
            "segment_sec": settings["segment_sec"],
            "radius_ms": settings["radius_ms"],
            "tolerance_ms": tolerance_ms,
            "required_supporting_zones": required_support,
            "expanded": expanded,
            "expansion_reason": expansion_reason,
            "candidate_delays_ms": candidates,
            "clusters": ranked_public,
            "timeline_model": timeline_model,
            "results": rows,
            "fast_path": {
                "candidate_delay_ms": (fast_audio or {}).get("candidate_delay_ms"),
                "supporting_zones": int((fast_audio or {}).get("supporting_zones") or 0),
                "reason": initial_reason,
            },
        }
        timing["audio_discovery_sec"] = round(discovery_sec, 3)
        timing["visual_final_sec"] = round(visual_final_sec, 3)
        timing["measurement_sec"] = round(time.monotonic() - total_started, 3)
        return self.finish_hybrid_result(
            state,
            final_delay,
            visual,
            audio,
            reason,
            contradictions,
            timing,
            ref_index,
            esp_index,
            stage="adaptive_discovery",
        )

    def run_hybrid_fast_path(self, duration_ref, duration_esp, ref_index, esp_index):
        total_started = time.monotonic()
        if not self.measurement_core or not self.esp_measurement_core:
            self.core_timing_sec = self.build_measurement_cores(duration_ref, duration_esp)
        if self.fps_plan_enabled and self.fps_plan_provisional and not self.fps_plan_confirmed:
            timing = {
                "metadata_sec": round(self.metadata_timing_sec, 3),
                "core_sec": round(self.core_timing_sec, 6),
                "visual_fast_path_sec": 0.0,
                "audio_narrow_sec": 0.0,
                "measurement_sec": 0.0,
            }
            seeded = self.try_provisional_fps_hint_seed(
                duration_ref,
                duration_esp,
                ref_index,
                esp_index,
                timing,
                total_started,
            )
            if seeded is not None:
                return seeded
            return self.run_hybrid_discovery(
                duration_ref,
                duration_esp,
                ref_index,
                esp_index,
                {"verified": False, "reason": "fps_audio_must_precede_visual"},
                {"supporting_zones": 0, "results": []},
                timing,
                total_started,
                "fps_provisional_audio_first",
            )
        candidates = [0]
        if self.delay_hint_ms != 0:
            candidates.append(self.delay_hint_ms)
        tempo = self.fps_tempo if self.fps_plan_enabled else 1.0
        self.write_progress("visual", 0, "Imagen")
        verifier = self.create_visual_verifier()
        visual = verifier.score_candidates(
            self.ref_file,
            self.esp_video_original,
            candidates,
            profile=self.profile,
            tempo=tempo,
            stage="visual_fast_path",
        )
        visual = dict(visual)
        visual["verified"] = bool(visual.get("strong_winner"))
        visual_time = float(visual.get("duration_sec") or 0.0)
        timing = {
            "metadata_sec": round(self.metadata_timing_sec, 3),
            "core_sec": round(self.core_timing_sec, 6),
            "visual_fast_path_sec": round(visual_time, 3),
            "audio_narrow_sec": 0.0,
            "measurement_sec": round(time.monotonic() - total_started, 3),
        }
        empty_audio = {
            "method": "legacy_correlation_narrow_v1",
            "supporting_zones": 0,
            "zones_attempted": 0,
            "results": [],
        }
        winner_delay = visual.get("winner_delay_ms")
        if winner_delay is None or not visual.get("strong_winner"):
            return self.run_hybrid_discovery(
                duration_ref,
                duration_esp,
                ref_index,
                esp_index,
                visual,
                empty_audio,
                timing,
                total_started,
                "visual_fast_path_sin_ganador_fuerte",
            )

        winner_delay = int(winner_delay)
        around_hint = self.delay_hint_ms != 0 and winner_delay == self.delay_hint_ms
        settings = self.fast_audio_settings(min(duration_ref, duration_esp), around_hint=around_hint)
        timeline_settings = self.hybrid_section("timeline_model")
        anchor_pcts = self.config_pcts(
            timeline_settings,
            "anchor_pcts",
            [35.0, 52.0, 70.0] if self.profile == "trailer" else [30.0, 50.0, 70.0],
        )
        zones = self.build_fast_audio_zones(
            duration_ref,
            duration_esp,
            settings["segment_sec"],
            winner_delay,
            anchor_pcts,
            ref_core=self.measurement_core,
            esp_core=self.esp_measurement_core,
        )
        if len(zones) < 3:
            return self.run_hybrid_discovery(
                duration_ref,
                duration_esp,
                ref_index,
                esp_index,
                visual,
                empty_audio,
                timing,
                total_started,
                "audio_estrecho_sin_tres_anclas",
            )

        work_dir = os.path.join(self.job_dir, "tmp")
        self.remove_work_dir_checked(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        audio_started = time.monotonic()
        rows = []
        self.diag.event("audio_narrow", "started", "Corroboración de audio estrecho iniciada", {
            "profile": self.profile,
            "candidate_ms": winner_delay,
            "zones": len(zones),
            "segment_sec": settings["segment_sec"],
            "radius_ms": settings["radius_ms"],
            "tolerance_ms": settings["tolerance_ms"],
        })
        self.write_progress("audio_narrow", 0, "Audio", len(zones), 0)
        try:
            for index, zone in enumerate(zones, 1):
                self.diag.event("audio_narrow", "zone_started", "Corroborando audio estrecho", {
                    "zone": index,
                    "pct": zone["pct"],
                    "ref_start_sec": zone["ref_start_sec"],
                    "esp_start_sec": zone["esp_start_sec"],
                    "center_ms": winner_delay,
                    "radius_ms": settings["radius_ms"],
                })
                try:
                    row = self.analyze_zone(
                        index,
                        zone["ref_start_sec"],
                        ref_index,
                        esp_index,
                        work_dir,
                        segment_sec=settings["segment_sec"],
                        search_center_ms=winner_delay,
                        search_radius_ms=settings["radius_ms"],
                        esp_start_sec=zone["esp_start_sec"],
                    )
                    rows.append(row)
                    self.diag.event("audio_narrow", "zone_finished", "Audio estrecho medido", row)
                except Exception as exc:
                    self.log(f"ERROR AUDIO ESTRECHO ZONA {index}: {exc}")
                    if self.is_expected_zone_rejection(exc):
                        self.diag.event("audio_narrow", "zone_rejected", "Zona de audio estrecho no útil", {
                            "zone": index,
                            "reason": str(exc),
                            "decision": "skipped",
                        })
                    else:
                        self.diag.error(classify_error(str(exc)), "audio_narrow", "Zona de audio estrecho fallida", {
                            "zone": index,
                            "error": str(exc),
                        }, exc)
                        raise RuntimeError(
                            f"Fallo técnico en zona de audio estrecho {index}: {exc}"
                        ) from exc
                self.write_progress("audio_narrow", (index / len(zones)) * 100, "Audio", len(zones), index)
        finally:
            self.remove_work_dir_checked(work_dir)
            self.diag.event("cleanup", "remove_measure_tmp", "Temporales de audio estrecho eliminados", {
                "work_dir": work_dir,
            })

        audio_time = time.monotonic() - audio_started
        tolerance_ms = int(settings["tolerance_ms"])
        clusters = self.cluster_audio_rows(rows, tolerance_ms, settings["score_min"])
        best_cluster = clusters[0] if clusters else {"delay_ms": winner_delay, "count": 0, "avg_score": 0.0, "items": []}
        supporting_rows = list(best_cluster["items"])
        supporting_zones = int(best_cluster["count"])
        audio_avg_score = float(best_cluster["avg_score"])
        strong_audio_zones = sum(
            1 for row in supporting_rows if float(row.get("score") or 0.0) >= float(settings["strong_score_min"])
        )
        audio_delay = int(best_cluster["delay_ms"])
        spread_ms = max((int(row["delay_ms"]) for row in supporting_rows), default=audio_delay) - min(
            (int(row["delay_ms"]) for row in supporting_rows), default=audio_delay
        )
        timeline_model = self.fit_audio_timeline(rows, settings["score_min"])
        contradictions = []
        if supporting_zones < 3:
            contradictions.append("audio_supports_fewer_than_three_anchors")
        if supporting_zones >= 3 and audio_avg_score < float(settings["avg_score_min"]):
            contradictions.append("audio_cluster_score_too_low")
        if supporting_zones >= 3 and strong_audio_zones < 1:
            contradictions.append("audio_has_no_strong_zone")
        if supporting_zones >= 3 and spread_ms > tolerance_ms:
            contradictions.append("audio_zones_disagree")
        if timeline_model.get("compatible") is not True:
            contradictions.append("timeline_model_incompatible")
        if abs(audio_delay - winner_delay) > tolerance_ms:
            contradictions.append("audio_visual_delay_mismatch")
        if self.fps_plan_enabled and not self.fps_plan_confirmed:
            contradictions.append("fps_plan_not_confirmed")
        audio = {
            "method": "legacy_correlation_narrow_v1",
            "candidate_delay_ms": winner_delay,
            "delay_ms": audio_delay,
            "supporting_zones": supporting_zones,
            "zones_attempted": len(zones),
            "segment_sec": settings["segment_sec"],
            "radius_ms": settings["radius_ms"],
            "tolerance_ms": tolerance_ms,
            "spread_ms": spread_ms,
            "score_min": settings["score_min"],
            "avg_score": audio_avg_score,
            "avg_score_min": settings["avg_score_min"],
            "strong_score_min": settings["strong_score_min"],
            "strong_zones": strong_audio_zones,
            "clusters": [
                {key: value for key, value in cluster.items() if key != "items"}
                for cluster in clusters
            ],
            "timeline_model": timeline_model,
            "results": rows,
        }
        timing["audio_narrow_sec"] = round(audio_time, 3)
        timing["measurement_sec"] = round(time.monotonic() - total_started, 3)
        narrow_accepted = not contradictions and supporting_zones >= 3
        self.diag.event("audio_narrow", "finished", "Corroboración de audio estrecho terminada", {
            "profile": self.profile,
            "duration_sec": round(audio_time, 3),
            "candidate_ms": winner_delay,
            "delay_ms": audio_delay,
            "zones_attempted": len(zones),
            "supporting_zones": supporting_zones,
            "avg_score": audio_avg_score,
            "spread_ms": spread_ms,
            "reason": "fast_path_visual_y_audio_coinciden" if narrow_accepted else "fast_path_audio_inconcluso",
            "decision": "accepted" if narrow_accepted else "audio_discovery",
        })
        if narrow_accepted:
            return self.finish_hybrid_result(
                "OK_VERIFICADO",
                audio_delay,
                visual,
                audio,
                "fast_path_visual_y_audio_coinciden",
                [],
                timing,
                ref_index,
                esp_index,
            )
        return self.run_hybrid_discovery(
            duration_ref,
            duration_esp,
            ref_index,
            esp_index,
            visual,
            audio,
            timing,
            total_started,
            "fast_path_audio_inconcluso",
        )

    def recommended_delay(self, results):
        usable = [r for r in results if r["score"] >= 0.18]
        if not usable:
            usable = sorted(results, key=lambda r: r["score"], reverse=True)[:3]

        clusters = []
        for result in sorted(usable, key=lambda r: r["delay_ms"]):
            placed = False
            for cluster in clusters:
                if abs(result["delay_ms"] - cluster["center"]) <= self.cluster_tolerance_ms:
                    cluster["items"].append(result)
                    sum_w = 0.0
                    sum_d = 0.0
                    for item in cluster["items"]:
                        weight = max(0.05, float(item["score"]))
                        weight = weight * weight
                        sum_w += weight
                        sum_d += item["delay_ms"] * weight
                    cluster["center"] = sum_d / sum_w
                    placed = True
                    break
            if not placed:
                clusters.append({"center": float(result["delay_ms"]), "items": [result]})

        ranked = []
        for cluster in clusters:
            count = len(cluster["items"])
            avg_score = sum(float(item["score"]) for item in cluster["items"]) / count
            strength = (avg_score * 100.0) + (count * 18.0)
            ranked.append({
                "center": round(cluster["center"]),
                "count": count,
                "avg_score": avg_score,
                "strength": strength,
                "items": cluster["items"],
            })
        if not ranked:
            raise RuntimeError("No he podido agrupar resultados.")
        best = sorted(ranked, key=lambda r: r["strength"], reverse=True)[0]
        if best["count"] >= 3 and best["avg_score"] >= 0.30:
            final_confidence = "ALTA"
        elif best["count"] >= 2 and best["avg_score"] >= 0.22:
            final_confidence = "MEDIA"
        elif best["avg_score"] >= 0.30:
            final_confidence = "MEDIA"
        else:
            final_confidence = "BAJA"
        return {
            "delay_ms": int(best["center"]),
            "confidence": final_confidence,
            "count": int(best["count"]),
            "avg_score": float(best["avg_score"]),
            "clusters": ranked,
        }

    def run(self):
        run_started = time.monotonic()
        self.reset_logs()
        self.diag.init(inputs={
            "video_bueno": self.ref_file,
            "video_espanol": self.esp_video_original,
            "video_espanol_original": self.esp_video_original,
            "audio_espanol_medicion": self.esp_file,
            "ref_audio": self.ref_audio_index,
            "esp_audio": self.esp_audio_index,
        }, settings={
            "profile": self.profile,
            "segment_sec": self.segment_sec,
            "max_delay_sec": self.max_delay_sec,
            "max_zones": self.max_zones,
            "delay_hint_ms": self.delay_hint_ms,
            "hybrid_enabled": self.hybrid_enabled,
            "fps_plan": {
                "planned": self.fps_plan_enabled,
                "provisional": self.fps_plan_provisional,
                "confirmed": self.fps_plan_confirmed,
                "ref_fps": self.fps_ref,
                "esp_fps": self.fps_esp,
                "tempo": self.fps_tempo,
            },
        })
        self.write_progress("starting", 0, "Arrancando")
        try:
            self.diag.event("validate_inputs", "started", "Validando entradas")
            self.log("ARGUMENTOS RECIBIDOS: 2")
            self.log(f"VIDEO BUENO: {self.ref_file}")
            self.log(f"VIDEO ESPANOL: {self.esp_file}")
            if self.esp_video_original != self.esp_file:
                self.log(f"VIDEO ESPANOL ORIGINAL: {self.esp_video_original}")
                self.log(f"AUDIO ESPANOL MEDICION: {self.esp_file}")
            validate_video(self.ref_file)
            validate_video(self.esp_file, allow_audio=True)
            self.diag.event("validate_inputs", "finished", "Entradas validas")

            metadata_started = time.monotonic()
            self.diag.event("probe_ref", "started", "Leyendo duracion del video bueno", {"path": self.ref_file})
            duration_ref = self.get_duration_sec(self.ref_file)
            self.diag.event("probe_ref", "finished", "Duracion video bueno leida", {"duration_sec": duration_ref})
            self.diag.event("probe_esp", "started", "Leyendo duracion del video espanol", {"path": self.esp_file})
            duration_esp = self.get_duration_sec(self.esp_file)
            self.diag.event("probe_esp", "finished", "Duracion video espanol leida", {"duration_sec": duration_esp})
            duration = min(duration_ref, duration_esp)
            self.configure_profile(duration)
            if self.hybrid_enabled:
                self.core_timing_sec = self.build_measurement_cores(duration_ref, duration_esp)
            self.diag.event("measure_setup", "profile_configured", "Perfil de medicion configurado", {
                "profile": self.profile,
                "segment_sec": self.segment_sec,
                "max_delay_sec": self.max_delay_sec,
                "max_zones": self.max_zones,
                "delay_hint_ms": self.delay_hint_ms,
            })
            self.diag.event("select_audio_tracks", "started", "Seleccionando pistas de audio")
            ref_index = self.get_audio_stream_index(self.ref_file, False, self.ref_audio_index)
            esp_index = self.get_audio_stream_index(self.esp_file, True, self.esp_audio_index)
            self.diag.event("select_audio_tracks", "finished", "Pistas de audio seleccionadas", {
                "ref_stream": f"0:{ref_index}",
                "esp_stream": f"0:{esp_index}",
            })
            self.metadata_timing_sec = time.monotonic() - metadata_started

            self.log(f"Duracion video bueno: {format_time_simple(duration_ref)}")
            self.log(f"Duracion audio espanol: {format_time_simple(duration_esp)}")
            self.log(f"Pista usada en VIDEO BUENO: 0:{ref_index}")
            self.log(f"Pista usada en AUDIO ESPANOL: 0:{esp_index}")
            self.log(f"Perfil de medicion: {self.profile}")
            if self.delay_hint_ms != 0:
                self.log(f"Ayuda visual de busqueda: {self.delay_hint_ms} ms")

            if self.hybrid_enabled:
                return self.run_hybrid_fast_path(duration_ref, duration_esp, ref_index, esp_index)

            zones = self.build_zones(duration)
            self.log(f"Zonas que voy a analizar: {len(zones)}")
            self.log(f"Duracion por zona: {inv(self.segment_sec)} segundos")
            self.log(f"Busqueda maxima: +/-{inv(self.max_delay_sec)} segundos")
            self.diag.event("measure_setup", "finished", "Zonas de medicion preparadas", {
                "zones": len(zones),
                "duration_sec": duration,
                "segment_sec": self.segment_sec,
                "delay_hint_ms": self.delay_hint_ms,
            })
            self.write_progress("measure", 0, "Midiendo", len(zones), 0)

            work_dir = os.path.join(self.job_dir, "tmp")
            if os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
            os.makedirs(work_dir, exist_ok=True)
            self.log(f"WORKDIR: {work_dir}")

            results = []
            for index, start in enumerate(zones, 1):
                self.log(f"Analizando zona {index}/{len(zones)} desde {format_time_simple(start)}...")
                self.diag.event("measure_zone", "started", f"Analizando zona {index}", {
                    "zone": index,
                    "start_sec": start,
                    "start_text": format_time_simple(start),
                })
                self.write_progress("measure", ((index - 1) / len(zones)) * 100, "Midiendo", len(zones), index - 1)
                try:
                    row = self.analyze_zone(index, start, ref_index, esp_index, work_dir)
                    results.append(row)
                    self.log(
                        "  Delay: {delay_ms} ms | Confianza zona: {confidence} | Puntuacion: {score:.3f}".format(**row)
                    )
                    self.diag.event("measure_zone", "finished", f"Zona {index} medida", row)
                except Exception as exc:
                    self.log(f"ERROR ZONA {index} : {exc}")
                    self.log(f"  Zona saltada: {exc}")
                    self.diag.error(classify_error(str(exc)), "measure_zone", f"Zona {index} fallida", {
                        "zone": index,
                        "start_sec": start,
                        "error": str(exc),
                    }, exc)
                self.write_progress("measure", (index / len(zones)) * 100, "Midiendo", len(zones), index)

            shutil.rmtree(work_dir, ignore_errors=True)
            self.diag.event("cleanup", "remove_measure_tmp", "Temporales de medicion eliminados", {"work_dir": work_dir})
            if not results:
                raise RuntimeError("No he podido analizar ninguna zona. Mira el LOG.")

            self.diag.event("calculate_final_delay", "started", "Calculando delay final", {"valid_zones": len(results)})
            rec = self.recommended_delay(results)
            self.diag.event("calculate_final_delay", "finished", "Delay final calculado", rec)
            self.log("==================================================")
            self.log("RESULTADO")
            self.log("==================================================")
            self.log("VALOR PARA MKVToolNix:")
            self.log(f"Delay audio espanol: {rec['delay_ms']} ms")
            self.log(f"Confianza final: {rec['confidence']}")
            self.log(f"Zonas que coinciden: {rec['count']}")
            self.log(f"Puntuacion media: {rec['avg_score']:.3f}")
            self.log(
                "RESULTADO FINAL: {delay_ms} ms | Confianza {confidence} | Zonas {count} | Score {avg_score}".format(
                    **rec
                )
            )
            data = {
                "ok": True,
                "delay_ms": rec["delay_ms"],
                "confidence": rec["confidence"],
                "zones_count": rec["count"],
                "avg_score": rec["avg_score"],
                "profile": self.profile,
                "segment_sec": self.segment_sec,
                "max_delay_sec": self.max_delay_sec,
                "delay_hint_ms": self.delay_hint_ms,
                "ref_stream": f"0:{ref_index}",
                "esp_stream": f"0:{esp_index}",
                "results": results,
                "csv_path": self.csv_path,
                "log_path": self.log_path,
            }
            self.write_result(data)
            self.write_progress("done", 100, "Listo", len(zones), len(zones))
            self.diag.finish("measure_done", data)
            return 0
        except Exception as exc:
            self.log(f"ERROR: {exc}")
            data = {"ok": False, "error": str(exc), "log_path": self.log_path, "csv_path": self.csv_path}
            self.write_result(data)
            self.write_progress("error", 100, "Aviso")
            if self.hybrid_enabled:
                self.diag.event("measurement", "failed", "El motor híbrido terminó con error", {
                    "profile": self.profile,
                    "state": "ERROR_TECNICO",
                    "export_allowed": False,
                    "reason": str(exc),
                    "duration_sec": round(time.monotonic() - run_started, 3),
                }, level="error")
            self.diag.error(classify_error(str(exc)), "measure", str(exc), {}, exc)
            self.diag.finish("error", data)
            return 1


def inv(number):
    return str(float(number)).rstrip("0").rstrip(".") if "." in str(float(number)) else str(int(number))


def format_time_simple(seconds):
    total = round(max(0.0, float(seconds)))
    hour = total // 3600
    minute = (total % 3600) // 60
    sec = total % 60
    return f"{hour:02d}:{minute:02d}:{sec:02d}"


def validate_video(path, allow_audio=False):
    if not os.path.isfile(path):
        raise RuntimeError(f"No existe el archivo: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTENSIONS and not (allow_audio and ext in AUDIO_EXTENSIONS):
        raise RuntimeError(f"Extension no soportada: {ext}")


def smooth(values, radius):
    size = len(values)
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    out = []
    for idx in range(size):
        start = max(0, idx - radius)
        end = min(size - 1, idx + radius)
        out.append((prefix[end + 1] - prefix[start]) / (end - start + 1))
    return out


def downsample(values, factor):
    count = len(values) // factor
    if count < 20:
        raise RuntimeError("Audio demasiado corto para busqueda gruesa.")
    return [sum(values[i * factor:(i + 1) * factor]) / factor for i in range(count)]


def derivative(values):
    if not values:
        return []
    out = [0.0]
    for idx in range(1, len(values)):
        out.append(values[idx] - values[idx - 1])
    return out


def normalize(values):
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) * (value - mean) for value in values)
    std = math.sqrt(variance / max(1.0, count - 1))
    if std < 0.000001:
        raise RuntimeError("Audio casi plano o silencioso.")
    return [(value - mean) / std for value in values]


def corr_at_lag(a_values, b_values, lag):
    n_a = len(a_values)
    n_b = len(b_values)
    start = max(0, lag)
    end = min(n_a - 1, n_b - 1 + lag)
    count = end - start + 1
    if count < 50:
        return float("-inf")
    score = 0.0
    a_local = a_values
    b_local = b_values
    for idx in range(start, end + 1):
        score += a_local[idx] * b_local[idx - lag]
    return score / count


def find_best_lag_range(a1, b1, a2, b2, lag_min, lag_max):
    best_lag = 0
    best_score = float("-inf")
    second_score = float("-inf")
    for lag in range(int(lag_min), int(lag_max) + 1):
        s1 = corr_at_lag(a1, b1, lag)
        s2 = corr_at_lag(a2, b2, lag)
        score = (s1 * 0.45) + (s2 * 0.55)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_lag = lag
        elif score > second_score:
            second_score = score
    return {"lag": best_lag, "score": best_score, "gap": best_score - second_score}


def hybrid_config_json_arg(value):
    try:
        return parse_json_object(value, "--hybrid-config-json")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, help="Video bueno de imagen")
    parser.add_argument("--esp", required=True, help="Video con audio espanol")
    parser.add_argument("--job-dir", required=True, help="Carpeta de trabajo/logs")
    parser.add_argument("--ref-audio-index", type=int, help="Pista de audio del video bueno")
    parser.add_argument("--esp-audio-index", type=int, help="Pista de audio del video espanol")
    parser.add_argument("--profile", choices=("pelicula", "trailer"), default="pelicula", help="Perfil de medicion")
    parser.add_argument("--delay-hint-ms", type=int, default=0, help="Ayuda visual opcional para centrar la busqueda")
    parser.add_argument("--esp-video-original", default="", help="Video español original para validación visual")
    parser.add_argument("--fps-ref", type=float, default=0.0)
    parser.add_argument("--fps-esp", type=float, default=0.0)
    parser.add_argument("--fps-tempo", type=float, default=1.0)
    parser.add_argument("--fps-plan-enabled", action="store_true")
    parser.add_argument("--fps-plan-provisional", action="store_true")
    parser.add_argument("--fps-plan-confirmed", action="store_true")
    parser.add_argument("--fps-plan-context-json", type=hybrid_config_json_arg, default={})
    parser.add_argument("--hybrid-enabled", action="store_true")
    parser.add_argument("--hybrid-config-json", type=hybrid_config_json_arg, default={})
    args = parser.parse_args()
    return DelayAudio(
        args.ref,
        args.esp,
        args.job_dir,
        args.ref_audio_index,
        args.esp_audio_index,
        args.profile,
        args.delay_hint_ms,
        args.esp_video_original or args.esp,
        args.fps_ref,
        args.fps_esp,
        args.fps_tempo,
        args.fps_plan_enabled,
        args.fps_plan_provisional,
        args.fps_plan_confirmed,
        args.fps_plan_context_json,
        args.hybrid_enabled,
        args.hybrid_config_json,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
