#!/usr/bin/env python3
"""Comparador visual ligero para Taller.

Usa ráfagas cortas normalizadas y el filtro SSIM de FFmpeg. No genera
fotogramas, clips ni ficheros de estadísticas: toda la evidencia se lee de
stdout/stderr y se devuelve como JSON serializable.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from measurement_core import build_measurement_core, core_zone_start, map_ref_to_esp_time


SSIM_RE = re.compile(r"\bAll:([-+]?[0-9]*\.?[0-9]+)")
FINAL_STATES = {"FUERTE", "VALIDA", "SOSPECHOSA", "INUTIL"}
RELATIVE_CLEAR_DELTA = 0.05
RELATIVE_MEAN_DELTA = 0.08

DEFAULT_VISUAL_CONFIG: dict[str, dict[str, Any]] = {
    "pelicula": {
        "visual_zone_pcts": [18, 50, 82],
        "visual_zone_fallback_pcts": [10, 30, 70, 90, 40, 60],
        "visual_burst_sec": 2.0,
        "visual_fps": 2.0,
        "visual_width": 192,
        "visual_height": 108,
        "visual_crop_safe_pct": 90,
        "visual_strong_min": 0.88,
        "visual_valid_min": 0.80,
        "visual_margin_strong": 0.08,
        "visual_margin_valid": 0.05,
        "visual_required_zones": 3,
        "visual_required_strong": 2,
        "visual_max_zones": 7,
        "visual_competitor_ms": 400,
    },
    "trailer": {
        "visual_zone_pcts": [22, 58, 82],
        "visual_zone_fallback_pcts": [35, 75, 15, 88],
        "visual_burst_sec": 1.5,
        "visual_fps": 2.0,
        "visual_width": 160,
        "visual_height": 90,
        "visual_crop_safe_pct": 90,
        "visual_strong_min": 0.88,
        "visual_valid_min": 0.80,
        "visual_margin_strong": 0.08,
        "visual_margin_valid": 0.05,
        "visual_required_zones": 2,
        "visual_required_strong": 1,
        "visual_max_zones": 4,
        "visual_competitor_ms": 400,
    },
}

FRIENDLY_VISUAL_KEYS = {
    "zone_pcts": "visual_zone_pcts",
    "fallback_zone_pcts": "visual_zone_fallback_pcts",
    "burst_sec": "visual_burst_sec",
    "fps": "visual_fps",
    "width": "visual_width",
    "height": "visual_height",
    "crop_safe_pct": "visual_crop_safe_pct",
    "strong_min": "visual_strong_min",
    "valid_min": "visual_valid_min",
    "margin_strong": "visual_margin_strong",
    "margin_valid": "visual_margin_valid",
    "required_zones": "visual_required_zones",
    "required_strong": "visual_required_strong",
    "max_zones": "visual_max_zones",
    "competitor_ms": "visual_competitor_ms",
}


def _finite_float(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _even(value: float, minimum: int = 2) -> int:
    number = max(minimum, int(round(value)))
    return number if number % 2 == 0 else number - 1


def parse_json_object(value: Any, label: str = "configuración") -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} no contiene JSON válido") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} debe ser un objeto JSON")
    return payload


def visual_overrides_from_profile_config(profile_config: Any) -> dict[str, Any]:
    """Traduce el esquema público del perfil a las claves internas visuales."""

    profile_data = parse_json_object(profile_config, "profile-config-json")
    visual = profile_data.get("visual") if isinstance(profile_data.get("visual"), dict) else profile_data
    result = {
        internal_key: visual[public_key]
        for public_key, internal_key in FRIENDLY_VISUAL_KEYS.items()
        if public_key in visual and visual[public_key] is not None
    }
    if isinstance(profile_data.get("measurement_core"), dict):
        result["measurement_core"] = dict(profile_data["measurement_core"])
    if isinstance(profile_data.get("preview"), dict):
        result["preview"] = dict(profile_data["preview"])
    return result


def _profile_config_json_arg(value: str) -> dict[str, Any]:
    try:
        return parse_json_object(value, "--profile-config-json")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def profile_config(profile: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    key = "trailer" if str(profile).lower() == "trailer" else "pelicula"
    defaults = DEFAULT_VISUAL_CONFIG[key]
    result = deepcopy(defaults)
    if isinstance(overrides, dict):
        result.update({name: value for name, value in overrides.items() if value is not None})
    max_zones = 4 if key == "trailer" else 7
    result["visual_max_zones"] = max(
        int(defaults["visual_required_zones"]),
        min(max_zones, int(_finite_float(result.get("visual_max_zones"), max_zones))),
    )
    result["visual_required_zones"] = max(
        int(defaults["visual_required_zones"]),
        min(result["visual_max_zones"], int(_finite_float(
            result.get("visual_required_zones"),
            defaults["visual_required_zones"],
        ))),
    )
    result["visual_required_strong"] = max(
        int(defaults["visual_required_strong"]),
        min(result["visual_required_zones"], int(_finite_float(
            result.get("visual_required_strong"),
            defaults["visual_required_strong"],
        ))),
    )
    max_burst = 2.25 if key == "trailer" else 3.0
    min_burst = float(defaults["visual_burst_sec"])
    max_width = 320 if key == "trailer" else 384
    max_height = 180 if key == "trailer" else 216
    min_width = int(defaults["visual_width"])
    min_height = int(defaults["visual_height"])
    result["visual_burst_sec"] = max(min_burst, min(max_burst, _finite_float(
        result.get("visual_burst_sec"),
        defaults["visual_burst_sec"],
    )))
    result["visual_fps"] = max(float(defaults["visual_fps"]), min(4.0, _finite_float(
        result.get("visual_fps"),
        defaults["visual_fps"],
    )))
    result["visual_width"] = _even(max(min_width, min(max_width, _finite_float(
        result.get("visual_width"),
        defaults["visual_width"],
    ))))
    result["visual_height"] = _even(max(min_height, min(max_height, _finite_float(
        result.get("visual_height"),
        defaults["visual_height"],
    ))))
    result["visual_crop_safe_pct"] = float(defaults["visual_crop_safe_pct"])
    for name in ("visual_strong_min", "visual_valid_min", "visual_margin_strong", "visual_margin_valid"):
        result[name] = max(float(defaults[name]), min(1.0, _finite_float(result.get(name), defaults[name])))
    result["visual_competitor_ms"] = int(defaults["visual_competitor_ms"])
    return result


def pick_zones(duration: float, profile: str = "pelicula", config: dict[str, Any] | None = None) -> list[dict[str, float]]:
    cfg = profile_config(profile, config)
    duration_value = _finite_float(duration)
    burst = _finite_float(cfg.get("visual_burst_sec"), 2.0)
    core = build_measurement_core(
        duration_value,
        profile,
        cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None,
    )
    if duration_value <= 0 or burst <= 0 or core["span_sec"] < burst:
        return []

    initial = list(cfg.get("visual_zone_pcts") or [])
    if str(profile).lower() == "trailer" and duration_value <= 45:
        initial = initial[:2]
    fallback = list(cfg.get("visual_zone_fallback_pcts") or [])
    zones: list[dict[str, float]] = []
    seen: set[int] = set()
    for origin, values in (("initial", initial), ("fallback", fallback)):
        for raw_pct in values:
            pct = max(0.0, min(100.0, _finite_float(raw_pct)))
            start = core_zone_start(core, pct, burst)
            if start is None:
                continue
            bucket = int(round(start * 1000))
            if bucket in seen:
                continue
            seen.add(bucket)
            zones.append({"pct": pct, "start_sec": round(start, 6), "origin": origin})
    return zones


@dataclass
class VideoMetadata:
    path: str
    duration: float
    avg_fps: float
    real_fps: float
    width: int
    height: int
    pix_fmt: str
    color_transfer: str
    variable_frame_rate: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration": self.duration,
            "avg_fps": self.avg_fps,
            "real_fps": self.real_fps,
            "width": self.width,
            "height": self.height,
            "pix_fmt": self.pix_fmt,
            "color_transfer": self.color_transfer,
            "variable_frame_rate": self.variable_frame_rate,
        }


class VisualVerifier:
    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout: int = 180,
        profile_overrides: dict[str, dict[str, Any]] | None = None,
        event_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.timeout = int(timeout)
        self.profile_overrides = profile_overrides or {}
        self.event_callback = event_callback

    def _event(self, phase: str, event: str, data: dict[str, Any]) -> None:
        if self.event_callback:
            self.event_callback(phase, event, data)

    def config(self, profile: str) -> dict[str, Any]:
        key = "trailer" if str(profile).lower() == "trailer" else "pelicula"
        return profile_config(key, self.profile_overrides.get(key))

    def probe_video(self, path: str) -> VideoMetadata:
        if not path or not os.path.isfile(path):
            raise RuntimeError(f"No existe el vídeo visual: {path}")
        cmd = [
            self.ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,avg_frame_rate,r_frame_rate,width,height,pix_fmt,color_transfer:stream_tags=DURATION",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffprobe visual falló").strip()[-800:])
        try:
            raw = json.loads(proc.stdout or "{}")
            stream = (raw.get("streams") or [])[0]
        except (ValueError, IndexError, TypeError) as exc:
            raise RuntimeError("ffprobe no devolvió vídeo válido") from exc

        duration = _parse_duration(stream.get("duration"))
        if duration <= 0:
            duration = _parse_duration((stream.get("tags") or {}).get("DURATION"))
        if duration <= 0:
            duration = _parse_duration((raw.get("format") or {}).get("duration"))
        avg_fps = _parse_rate(stream.get("avg_frame_rate"))
        real_fps = _parse_rate(stream.get("r_frame_rate"))
        if duration <= 0 or avg_fps <= 0:
            raise RuntimeError("Metadatos visuales incompletos")
        return VideoMetadata(
            path=os.path.abspath(path),
            duration=duration,
            avg_fps=avg_fps,
            real_fps=real_fps or avg_fps,
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
            pix_fmt=str(stream.get("pix_fmt") or ""),
            color_transfer=str(stream.get("color_transfer") or ""),
            variable_frame_rate=bool(real_fps and abs(real_fps - avg_fps) > 0.01),
        )

    def preview_plan(
        self,
        ref_video: str,
        esp_video_original: str,
        profile: str = "pelicula",
        delay_hint_ms: int | float = 0,
    ) -> dict[str, Any]:
        """Planifica dos clips centrales equivalentes para el botón Editar."""

        ref_meta = self.probe_video(ref_video)
        esp_meta = self.probe_video(esp_video_original)
        cfg = self.config(profile)
        core_cfg = cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None
        preview_cfg = cfg.get("preview") if isinstance(cfg.get("preview"), dict) else {}
        ref_core = build_measurement_core(ref_meta.duration, profile, core_cfg)
        esp_core = build_measurement_core(esp_meta.duration, profile, core_cfg)
        default_duration = 12.0 if str(profile).lower() == "trailer" else 30.0
        requested_duration = max(2.0, _finite_float(preview_cfg.get("duration_sec"), default_duration))
        preview_duration = min(requested_duration, ref_core["span_sec"], esp_core["span_sec"])
        if preview_duration < 2.0:
            raise RuntimeError("No hay core suficiente para crear el preview")
        default_center = 40.0 if str(profile).lower() == "trailer" else 45.0
        center_pct = max(0.0, min(100.0, _finite_float(preview_cfg.get("center_pct"), default_center)))
        center_time = ref_core["start_sec"] + ref_core["span_sec"] * center_pct / 100.0
        ref_start = min(
            ref_core["end_sec"] - preview_duration,
            max(ref_core["start_sec"], center_time - preview_duration / 2.0),
        )

        rates_differ = abs(round(ref_meta.avg_fps, 3) - round(esp_meta.avg_fps, 3)) > 0.0005
        vfr = ref_meta.variable_frame_rate or esp_meta.variable_frame_rate
        tempo = ref_meta.avg_fps / esp_meta.avg_fps if rates_differ and not vfr else 1.0
        delay_hint = max(-120000, min(120000, int(round(_finite_float(delay_hint_ms)))))
        window_sec = min(6.0, max(2.0, preview_duration / 3.0))
        window_sec = min(window_sec, esp_core["span_sec"] / tempo)
        if window_sec < 2.0:
            raise RuntimeError("No hay core español suficiente para reproducir el preview")

        relative_span_sec = max(0.0, preview_duration - window_sec)
        esp_window_source_duration = window_sec * tempo
        mapped_esp_base = map_ref_to_esp_time(ref_start, delay_hint / 1000.0, tempo)
        esp_base = min(
            esp_core["end_sec"] - esp_window_source_duration,
            max(esp_core["start_sec"], mapped_esp_base),
        )
        available_before_sec = max(0.0, (esp_base - esp_core["start_sec"]) / tempo)
        available_after_sec = max(
            0.0,
            (esp_core["end_sec"] - (esp_base + esp_window_source_duration)) / tempo,
        )
        spanish_before_sec = min(relative_span_sec, available_before_sec)
        spanish_after_sec = min(relative_span_sec, available_after_sec)
        spanish_preview_duration = spanish_before_sec + window_sec + spanish_after_sec
        esp_start = esp_base - spanish_before_sec * tempo
        esp_source_duration = spanish_preview_duration * tempo
        clamped = (
            abs(esp_base - mapped_esp_base) > 0.05
            or spanish_before_sec < relative_span_sec - 0.05
            or spanish_after_sec < relative_span_sec - 0.05
        )
        return {
            "ok": True,
            "profile": "trailer" if str(profile).lower() == "trailer" else "pelicula",
            "core_start_sec": round(ref_core["start_sec"], 6),
            "core_end_sec": round(ref_core["end_sec"], 6),
            "core_span_sec": round(ref_core["span_sec"], 6),
            "reference_clip_start_sec": round(ref_start, 6),
            "spanish_clip_start_sec": round(esp_start, 6),
            "spanish_source_duration_sec": round(esp_source_duration, 6),
            "spanish_preview_duration_sec": round(spanish_preview_duration, 6),
            "spanish_neutral_offset_sec": round(spanish_before_sec, 6),
            "preview_duration_sec": round(preview_duration, 6),
            "window_sec": round(window_sec, 6),
            "relative_min_offset_ms": -max(0, int(round(spanish_before_sec * 1000.0))),
            "relative_max_offset_ms": max(0, int(round(spanish_after_sec * 1000.0))),
            "delay_hint_ms": delay_hint,
            "tempo": round(tempo, 12),
            "fps_correction_planned": bool(rates_differ and not vfr),
            "variable_frame_rate": vfr,
            "clip_reason": "core_center_tempo_hint_clamped" if clamped else "core_center_tempo_and_hint",
            "measurement_core": ref_core,
            "spanish_measurement_core": esp_core,
        }

    def score_candidate(
        self,
        ref_video: str,
        esp_video_original: str,
        ref_time: float,
        delay_ms: int | float,
        tempo: float = 1.0,
        profile: str = "pelicula",
        ref_duration: float | None = None,
        esp_duration: float | None = None,
    ) -> dict[str, Any]:
        cfg = self.config(profile)
        burst = _finite_float(cfg.get("visual_burst_sec"), 2.0)
        delay_value = _finite_float(delay_ms) / 1000.0
        tempo_value = _finite_float(tempo, 1.0)
        started = time.monotonic()
        try:
            esp_time = map_ref_to_esp_time(ref_time, delay_value, tempo_value)
            if ref_time < 0 or esp_time < 0:
                raise ValueError("posición visual fuera de rango")
            esp_source_burst = burst * tempo_value
            if ref_duration:
                ref_core = build_measurement_core(
                    float(ref_duration),
                    profile,
                    cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None,
                )
                if ref_time < ref_core["start_sec"] - 0.05 or ref_time + burst > ref_core["end_sec"] + 0.05:
                    raise ValueError("ráfaga maestra fuera de rango del core")
            if esp_duration:
                esp_core = build_measurement_core(
                    float(esp_duration),
                    profile,
                    cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None,
                )
                if esp_time < esp_core["start_sec"] - 0.05 or esp_time + esp_source_burst > esp_core["end_sec"] + 0.05:
                    raise ValueError("ráfaga española fuera de rango del core")
            scores, command_seconds = self._run_ssim(
                ref_video,
                esp_video_original,
                ref_time,
                esp_time,
                tempo_value,
                cfg,
            )
            mean = sum(scores) / len(scores)
            return {
                "ok": True,
                "delay_ms": int(round(_finite_float(delay_ms))),
                "ref_time": round(float(ref_time), 6),
                "esp_time": round(float(esp_time), 6),
                "tempo": round(tempo_value, 9),
                "mean_ssim": round(mean, 6),
                "min_ssim": round(min(scores), 6),
                "max_ssim": round(max(scores), 6),
                "frames": len(scores),
                "duration_sec": round(time.monotonic() - started, 3),
                "command_sec": round(command_seconds, 3),
            }
        except Exception as exc:
            if isinstance(exc, ValueError) and "fuera de rango" in str(exc).lower():
                return {
                    "ok": False,
                    "delay_ms": int(round(_finite_float(delay_ms))),
                    "ref_time": round(float(ref_time), 6),
                    "tempo": round(tempo_value, 9),
                    "error_kind": "out_of_range",
                    "error": str(exc),
                    "duration_sec": round(time.monotonic() - started, 3),
                }
            raise RuntimeError(f"Fallo técnico visual SSIM: {exc}") from exc

    def _run_ssim(
        self,
        ref_video: str,
        esp_video_original: str,
        ref_time: float,
        esp_time: float,
        tempo: float,
        cfg: dict[str, Any],
    ) -> tuple[list[float], float]:
        burst = _finite_float(cfg.get("visual_burst_sec"), 2.0)
        sample_fps = _finite_float(cfg.get("visual_fps"), 2.0)
        width = _even(_finite_float(cfg.get("visual_width"), 192))
        height = _even(_finite_float(cfg.get("visual_height"), 108))
        crop_pct = max(50.0, min(100.0, _finite_float(cfg.get("visual_crop_safe_pct"), 90.0)))
        crop_width = _even(width * crop_pct / 100.0)
        crop_height = _even(height * crop_pct / 100.0)
        crop_x = max(0, (width - crop_width) // 2)
        crop_y = max(0, (height - crop_height) // 2)
        esp_source_burst = burst * tempo
        ref_read = burst + max(0.75, 1.0 / sample_fps)
        esp_read = esp_source_burst + max(0.75, tempo / sample_fps)

        common = (
            f"fps={sample_fps:.6f},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            "format=gbrp,normalize=smoothing=2:independence=0:strength=1,format=gray,"
            f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},settb=AVTB"
        )
        ref_filter = f"trim=duration={burst:.6f},setpts=PTS-STARTPTS,{common}"
        esp_filter = (
            f"trim=duration={esp_source_burst:.6f},"
            f"setpts=(PTS-STARTPTS)/{tempo:.12f},{common}"
        )
        filter_graph = (
            f"[0:v:0]{ref_filter}[ref];"
            f"[1:v:0]{esp_filter}[esp];"
            "[ref][esp]ssim=stats_file=-"
        )
        cmd = [
            self.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{ref_time:.6f}",
            "-t",
            f"{ref_read:.6f}",
            "-i",
            ref_video,
            "-ss",
            f"{esp_time:.6f}",
            "-t",
            f"{esp_read:.6f}",
            "-i",
            esp_video_original,
            "-filter_complex",
            filter_graph,
            "-an",
            "-sn",
            "-dn",
            "-f",
            "null",
            "-",
        ]
        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=self.timeout,
        )
        elapsed = time.monotonic() - started
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError((combined.strip() or "FFmpeg SSIM falló")[-1000:])
        scores = [float(value) for value in SSIM_RE.findall(combined)]
        expected_min = max(2, int(math.floor(burst * sample_fps)) - 1)
        if len(scores) < expected_min:
            raise RuntimeError(f"SSIM devolvió pocos frames: {len(scores)}")
        return scores, elapsed

    def score_candidates(
        self,
        ref_video: str,
        esp_video_original: str,
        candidate_delays_ms: Iterable[int | float],
        profile: str = "pelicula",
        tempo: float = 1.0,
        stage: str = "visual_gate",
    ) -> dict[str, Any]:
        started = time.monotonic()
        ref_meta = self.probe_video(ref_video)
        esp_meta = self.probe_video(esp_video_original)
        cfg = self.config(profile)
        input_candidates = _unique_ints(candidate_delays_ms)
        if not input_candidates:
            input_candidates = [0]
        candidate_equivalence = _visual_candidate_equivalence(
            input_candidates,
            ref_meta,
            esp_meta,
            tempo,
        )
        base_candidates = list(candidate_equivalence["effective_candidates_ms"])
        zero_reference = int(candidate_equivalence["zero_representative_ms"])
        competitor_ms = int(cfg.get("visual_competitor_ms") or 400)
        external_relative_controls = []
        zero_group = next(
            (
                item for item in candidate_equivalence["groups"]
                if 0 in item["members_ms"]
            ),
            None,
        )
        if (
            stage == "visual_final"
            and candidate_equivalence["applied"]
            and len(base_candidates) == 1
            and zero_group is not None
            and len(zero_group["members_ms"]) > 1
        ):
            representative = int(base_candidates[0])
            external_relative_controls = [
                representative - competitor_ms,
                representative + competitor_ms,
            ]
        candidate_equivalence["external_relative_controls_ms"] = external_relative_controls
        required = int(cfg.get("visual_required_zones") or 1)
        required_strong = int(cfg.get("visual_required_strong") or 1)
        max_zones = int(cfg.get("visual_max_zones") or required)
        zones = pick_zones(ref_meta.duration, profile, cfg)
        measurement_core = build_measurement_core(
            ref_meta.duration,
            profile,
            cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None,
        )
        zone_results: list[dict[str, Any]] = []
        valid_zones: list[dict[str, Any]] = []
        pending_replacements: list[dict[str, Any]] = []
        self._event(stage, "started", {
            "profile": profile,
            "candidates": base_candidates,
            "tempo": tempo,
            "measurement_core": measurement_core,
            "candidate_equivalence": candidate_equivalence,
        })
        if candidate_equivalence["applied"]:
            self._event(stage, "candidates_grouped", candidate_equivalence)

        for zone in zones:
            if len(zone_results) >= max_zones:
                break
            evaluated = set(base_candidates)
            for candidate in base_candidates:
                evaluated.add(candidate - competitor_ms)
                evaluated.add(candidate + competitor_ms)
                if candidate != zero_reference:
                    evaluated.add(zero_reference)
            raw_scores: dict[int, dict[str, Any]] = {}
            for delay in sorted(evaluated):
                raw_scores[delay] = self.score_candidate(
                    ref_video,
                    esp_video_original,
                    zone["start_sec"],
                    delay,
                    tempo,
                    profile,
                    ref_meta.duration,
                    esp_meta.duration,
                )

            evidence: list[dict[str, Any]] = []
            for candidate in base_candidates:
                own = raw_scores.get(candidate) or {}
                competitors = [candidate - competitor_ms, candidate + competitor_ms]
                if candidate != zero_reference:
                    competitors.append(zero_reference)
                if candidate_equivalence["applied"]:
                    competitors.extend(
                        item for item in base_candidates
                        if item != candidate
                    )
                competitors = _unique_ints(competitors)
                competitor_scores = [
                    raw_scores[item]["mean_ssim"]
                    for item in competitors
                    if raw_scores.get(item, {}).get("ok")
                ]
                own_score = own.get("mean_ssim") if own.get("ok") else None
                best_competitor = max(competitor_scores) if competitor_scores else None
                margin = None
                if own_score is not None and best_competitor is not None:
                    margin = float(own_score) - float(best_competitor)
                evidence.append({
                    "delay_ms": candidate,
                    "mean_ssim": own_score,
                    "margin": round(margin, 6) if margin is not None else None,
                    "frames": own.get("frames", 0),
                    "ok": bool(own.get("ok")),
                })

            available = [item for item in evidence if item["mean_ssim"] is not None]
            winner = max(available, key=lambda item: item["mean_ssim"]) if available else None
            classification = self._classify_zone(winner, cfg)
            zone_payload = {
                "pct": zone["pct"],
                "start_sec": zone["start_sec"],
                "origin": zone["origin"],
                "state": classification,
                "winner_delay_ms": winner.get("delay_ms") if winner else None,
                "winner_ssim": winner.get("mean_ssim") if winner else None,
                "winner_margin": winner.get("margin") if winner else None,
                "candidates": evidence,
                "raw": {str(key): value for key, value in raw_scores.items()},
            }
            zone_results.append(zone_payload)
            self._event(stage, "zone_scored", {
                "profile": profile,
                "pct": zone_payload["pct"],
                "start_sec": zone_payload["start_sec"],
                "candidate_ms": zone_payload["winner_delay_ms"],
                "score": zone_payload["winner_ssim"],
                "margin": zone_payload["winner_margin"],
                "decision": zone_payload["state"],
            })
            if classification in {"FUERTE", "VALIDA"}:
                if zone["origin"] == "fallback" and pending_replacements:
                    replaced = pending_replacements.pop(0)
                    self._event(stage, "zone_replaced", {
                        "profile": profile,
                        "from_pct": replaced["pct"],
                        "to_pct": zone["pct"],
                        "reason": replaced["state"],
                        "decision": classification,
                    })
                valid_zones.append(zone_payload)
            elif zone["origin"] == "initial":
                pending_replacements.append({"pct": zone["pct"], "state": classification})
            if len(valid_zones) >= required:
                break

        aggregate = self._aggregate_candidates(base_candidates, valid_zones)
        strong_count = sum(1 for zone in valid_zones if zone["state"] == "FUERTE")
        winner_delay = aggregate[0]["delay_ms"] if aggregate else None
        winner_wins = aggregate[0]["wins"] if aggregate else 0
        runner_wins = aggregate[1]["wins"] if len(aggregate) > 1 else -1
        unique_winner = bool(
            winner_delay is not None
            and len(valid_zones) >= required
            and winner_wins >= required
            and winner_wins > runner_wins
        )
        strong_winner = bool(unique_winner and strong_count >= required_strong)
        relative = self._relative_evidence(
            base_candidates,
            zone_results,
            cfg,
            external_reference_delays=external_relative_controls,
        )
        relative_match = bool(stage == "visual_final" and relative["relative_match"])
        candidate_equivalence["relative_reference_kind"] = relative["relative_reference_kind"]
        verification_mode = (
            "absolute"
            if strong_winner
            else "relative"
            if relative_match
            else "none"
        )
        result = {
            "ok": True,
            "method": "ffmpeg_ssim_burst_v1",
            "stage": stage,
            "profile": "trailer" if str(profile).lower() == "trailer" else "pelicula",
            "tempo": round(_finite_float(tempo, 1.0), 9),
            "measurement_core": measurement_core,
            "candidate_delays_ms": base_candidates,
            "candidate_equivalence": candidate_equivalence,
            "zones_attempted": len(zone_results),
            "zones_valid": len(valid_zones),
            "zones_strong": strong_count,
            "winner_delay_ms": winner_delay,
            "unique_winner": unique_winner,
            "strong_winner": strong_winner,
            "absolute_supported": strong_winner,
            "relative_supported": relative_match,
            "verification_mode": verification_mode,
            "verified": verification_mode != "none",
            "candidates": aggregate,
            "zones": zone_results,
            "ref": ref_meta.as_dict(),
            "esp_video_original": esp_meta.as_dict(),
            "duration_sec": round(time.monotonic() - started, 3),
        }
        result.update(relative)
        result["relative_match"] = relative_match
        if stage != "visual_final":
            self._event(stage, "finished", {
                "profile": profile,
                "zones_attempted": result["zones_attempted"],
                "zones_valid": result["zones_valid"],
                "zones_strong": result["zones_strong"],
                "winner_delay_ms": winner_delay,
                "unique_winner": unique_winner,
                "strong_winner": strong_winner,
                "verification_mode": verification_mode,
                "duration_sec": result["duration_sec"],
            })
        return result

    @staticmethod
    def _classify_zone(winner: dict[str, Any] | None, cfg: dict[str, Any]) -> str:
        if not winner or winner.get("mean_ssim") is None or winner.get("margin") is None:
            return "INUTIL"
        score = float(winner["mean_ssim"])
        margin = float(winner["margin"])
        if score >= float(cfg["visual_strong_min"]) and margin >= float(cfg["visual_margin_strong"]):
            return "FUERTE"
        if score >= float(cfg["visual_valid_min"]) and margin >= float(cfg["visual_margin_valid"]):
            return "VALIDA"
        if score >= float(cfg["visual_valid_min"]):
            return "SOSPECHOSA"
        return "INUTIL"

    @staticmethod
    def _relative_evidence(
        base_candidates: list[int],
        zones: list[dict[str, Any]],
        cfg: dict[str, Any],
        external_reference_delays: Iterable[int | float] | None = None,
    ) -> dict[str, Any]:
        external_references = _unique_ints(external_reference_delays or [])
        target = int(base_candidates[0]) if len(base_candidates) >= 2 or external_references else None
        required_zones = int(cfg.get("visual_required_zones") or 1)
        required_wins = max(2, int(cfg.get("visual_required_strong") or 1))
        comparisons = []
        reference_counts: dict[int, int] = {}
        reference_kind_counts: dict[str, int] = {}
        deltas = []
        wins = 0
        ties = 0
        losses = 0

        if target is not None:
            for zone in zones:
                candidates = [
                    item for item in zone.get("candidates") or []
                    if item.get("mean_ssim") is not None
                ]
                own = next(
                    (item for item in candidates if int(item.get("delay_ms") or 0) == target),
                    None,
                )
                alternatives = [
                    (item, "candidate") for item in candidates
                    if int(item.get("delay_ms") or 0) != target
                ]
                raw = zone.get("raw") if isinstance(zone.get("raw"), dict) else {}
                for delay in external_references:
                    item = raw.get(str(delay)) if isinstance(raw, dict) else None
                    if isinstance(item, dict) and item.get("mean_ssim") is not None:
                        alternatives.append(({
                            "delay_ms": delay,
                            "mean_ssim": item["mean_ssim"],
                        }, "external_control"))
                if own is None or not alternatives:
                    continue
                reference, reference_kind = max(
                    alternatives,
                    key=lambda item: float(item[0]["mean_ssim"]),
                )
                reference_delay = int(reference.get("delay_ms") or 0)
                delta = round(float(own["mean_ssim"]) - float(reference["mean_ssim"]), 6)
                if not math.isfinite(delta):
                    continue
                deltas.append(delta)
                reference_counts[reference_delay] = reference_counts.get(reference_delay, 0) + 1
                reference_kind_counts[reference_kind] = reference_kind_counts.get(reference_kind, 0) + 1
                if delta >= RELATIVE_CLEAR_DELTA:
                    outcome = "win"
                    wins += 1
                elif delta < -RELATIVE_CLEAR_DELTA:
                    outcome = "loss"
                    losses += 1
                else:
                    outcome = "tie"
                    ties += 1
                comparisons.append({
                    "pct": zone.get("pct"),
                    "target_delay_ms": target,
                    "reference_delay_ms": reference_delay,
                    "reference_kind": reference_kind,
                    "target_ssim": round(float(own["mean_ssim"]), 6),
                    "reference_ssim": round(float(reference["mean_ssim"]), 6),
                    "delta": delta,
                    "outcome": outcome,
                })

        mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
        reference_delay = None
        if reference_counts:
            candidate_order = {int(value): index for index, value in enumerate(base_candidates)}
            reference_delay = max(
                reference_counts,
                key=lambda value: (
                    reference_counts[value],
                    -candidate_order.get(value, len(candidate_order)),
                ),
            )
        reference_kind = None
        if reference_kind_counts:
            reference_kind = max(
                reference_kind_counts,
                key=lambda value: reference_kind_counts[value],
            )
        relative_match = bool(
            target is not None
            and len(deltas) >= required_zones
            and wins >= required_wins
            and losses == 0
            and mean_delta >= RELATIVE_MEAN_DELTA
        )
        return {
            "relative_target_delay_ms": target,
            "relative_reference_delay_ms": reference_delay,
            "relative_reference_kind": reference_kind,
            "relative_comparable_zones": len(deltas),
            "relative_required_zones": required_zones,
            "relative_required_wins": required_wins,
            "relative_wins": wins,
            "relative_ties": ties,
            "relative_losses": losses,
            "relative_mean_delta": round(mean_delta, 6),
            "relative_match": relative_match,
            "relative_comparisons": comparisons,
        }

    @staticmethod
    def _aggregate_candidates(base_candidates: list[int], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for candidate in base_candidates:
            wins = 0
            scores = []
            margins = []
            for zone in zones:
                item = next((row for row in zone["candidates"] if row["delay_ms"] == candidate), None)
                if not item or item.get("mean_ssim") is None:
                    continue
                scores.append(float(item["mean_ssim"]))
                if item.get("margin") is not None:
                    margins.append(float(item["margin"]))
                if zone.get("winner_delay_ms") == candidate:
                    wins += 1
            out.append({
                "delay_ms": candidate,
                "wins": wins,
                "mean_ssim": round(sum(scores) / len(scores), 6) if scores else None,
                "mean_margin": round(sum(margins) / len(margins), 6) if margins else None,
                "zones": len(scores),
            })
        return sorted(
            out,
            key=lambda item: (
                item["wins"],
                item["mean_ssim"] if item["mean_ssim"] is not None else -1.0,
            ),
            reverse=True,
        )

    def confirm_fps_plan(
        self,
        ref_video: str,
        esp_video_original: str,
        ref_fps: float | None = None,
        esp_fps: float | None = None,
        profile: str = "pelicula",
        delay_ms: int | float = 0,
        audio_evidence: dict[str, Any] | None = None,
        provisional_only: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        ref_meta = self.probe_video(ref_video)
        esp_meta = self.probe_video(esp_video_original)
        ref_rate = _finite_float(ref_fps, ref_meta.avg_fps)
        esp_rate = _finite_float(esp_fps, esp_meta.avg_fps)
        if ref_rate <= 0 or esp_rate <= 0:
            return _fps_result(False, False, False, "fps_no_detectado", ref_rate, esp_rate, 1.0, started)
        if abs(round(ref_rate, 3) - round(esp_rate, 3)) <= 0.0005:
            return _fps_result(False, False, False, "fps_iguales", ref_rate, esp_rate, 1.0, started)

        tempo = ref_rate / esp_rate
        expected_ref_duration = esp_meta.duration / tempo
        duration_delta = abs(expected_ref_duration - ref_meta.duration)
        if str(profile).lower() == "trailer":
            tolerance = max(0.35, ref_meta.duration * 0.005)
        else:
            tolerance = max(1.5, ref_meta.duration * 0.0015)
        duration_match = duration_delta <= tolerance
        vfr = ref_meta.variable_frame_rate or esp_meta.variable_frame_rate
        # La duración total es una señal preliminar: intros y créditos distintos
        # no invalidan por sí solos un cuerpo interior estable.
        provisional = bool(not vfr)
        duration_payload = {
            "ref": round(ref_meta.duration, 6),
            "esp": round(esp_meta.duration, 6),
            "expected_ref": round(expected_ref_duration, 6),
            "delta": round(duration_delta, 6),
            "tolerance": round(tolerance, 6),
            "match": duration_match,
        }
        if provisional_only:
            if vfr:
                reason = "vfr_no_confirmado"
            elif not duration_match:
                reason = "duration_ratio_warning"
            else:
                reason = "duration_ratio_provisional"
            return {
                "planned": True,
                "provisional": provisional,
                "enabled": provisional,
                "confirmed": False,
                "applied": False,
                "reason": reason,
                "ref_fps": round(ref_rate, 9),
                "esp_fps": round(esp_rate, 9),
                "tempo": round(tempo, 12),
                "duration": duration_payload,
                "visual": {},
                "variable_frame_rate": vfr,
                "duration_sec": round(time.monotonic() - started, 3),
            }

        cfg = self.config(profile)
        zones = pick_zones(ref_meta.duration, profile, cfg)[:3]
        measurement_core = build_measurement_core(
            ref_meta.duration,
            profile,
            cfg.get("measurement_core") if isinstance(cfg.get("measurement_core"), dict) else None,
        )
        comparisons = []
        absolute_wins = 0
        relative_wins = 0
        useful = 0
        deltas = []
        for zone in zones:
            planned = self.score_candidate(
                ref_video,
                esp_video_original,
                zone["start_sec"],
                delay_ms,
                tempo,
                profile,
                ref_meta.duration,
                esp_meta.duration,
            )
            nominal = self.score_candidate(
                ref_video,
                esp_video_original,
                zone["start_sec"],
                delay_ms,
                1.0,
                profile,
                ref_meta.duration,
                esp_meta.duration,
            )
            planned_score = planned.get("mean_ssim") if planned.get("ok") else None
            nominal_score = nominal.get("mean_ssim") if nominal.get("ok") else None
            delta = None
            if planned_score is not None and nominal_score is not None:
                useful += 1
                delta = float(planned_score) - float(nominal_score)
                deltas.append(delta)
                if planned_score >= float(cfg["visual_valid_min"]) and delta >= 0.02:
                    absolute_wins += 1
                if delta >= 0.05:
                    relative_wins += 1
            comparisons.append({
                "pct": zone["pct"],
                "start_sec": zone["start_sec"],
                "delay_ms": int(round(_finite_float(delay_ms))),
                "planned_ssim": planned_score,
                "nominal_ssim": nominal_score,
                "delta": round(delta, 6) if delta is not None else None,
            })

        mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
        contradictory_zones = sum(1 for delta in deltas if delta <= 0.0)
        absolute_match = useful >= 2 and absolute_wins >= 2
        relative_match = bool(
            useful >= 2
            and relative_wins >= 2
            and mean_delta >= 0.08
            and contradictory_zones == 0
        )
        visual_match = bool(absolute_match or relative_match)
        audio_stable = bool(isinstance(audio_evidence, dict) and audio_evidence.get("stable") is True)
        confirmed = bool(provisional and audio_stable and visual_match)
        if vfr:
            reason = "vfr_no_confirmado"
        elif not audio_stable:
            reason = "audio_corregido_no_confirma_tempo"
        elif not visual_match:
            reason = "imagen_no_confirma_tempo"
        else:
            reason = (
                "duration_audio_drift_and_visual_match"
                if duration_match
                else "interior_timeline_audio_and_visual_match"
            )
        return {
            "planned": True,
            "provisional": provisional,
            "enabled": confirmed,
            "confirmed": confirmed,
            "applied": confirmed,
            "reason": reason,
            "ref_fps": round(ref_rate, 9),
            "esp_fps": round(esp_rate, 9),
            "tempo": round(tempo, 12),
            "duration": duration_payload,
            "visual": {
                "verified": confirmed,
                "delay_ms": int(round(_finite_float(delay_ms))),
                "useful_zones": useful,
                "zones_attempted": len(comparisons),
                "zones_valid": useful,
                "planned_wins": max(absolute_wins, relative_wins),
                "absolute_wins": absolute_wins,
                "relative_wins": relative_wins,
                "absolute_match": absolute_match,
                "relative_match": relative_match,
                "mean_delta": round(mean_delta, 6),
                "contradictory_zones": contradictory_zones,
                "match": visual_match,
                "measurement_core": measurement_core,
                "comparisons": comparisons,
            },
            "audio": dict(audio_evidence or {}),
            "variable_frame_rate": vfr,
            "duration_sec": round(time.monotonic() - started, 3),
        }


def _parse_rate(value: Any) -> float:
    text = str(value or "").strip()
    if not text or text == "0/0":
        return 0.0
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            divisor = float(denominator)
            return float(numerator) / divisor if divisor else 0.0
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _parse_duration(value: Any) -> float:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    match = re.match(r"^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)$", text)
    if not match:
        return 0.0
    return int(match.group(1)) * 3600.0 + int(match.group(2)) * 60.0 + float(match.group(3))


def _visual_candidate_equivalence(
    values: Iterable[int | float],
    ref_meta: VideoMetadata,
    esp_meta: VideoMetadata,
    tempo: int | float,
) -> dict[str, Any]:
    candidates = _unique_ints(values)
    tempo_value = _finite_float(tempo, 0.0)
    ref_fps = _finite_float(ref_meta.avg_fps, 0.0)
    esp_fps = _finite_float(esp_meta.avg_fps, 0.0)
    effective_esp_fps = esp_fps * tempo_value
    variable_frame_rate = bool(ref_meta.variable_frame_rate or esp_meta.variable_frame_rate)

    if variable_frame_rate:
        threshold_ms = 0.0
        reason = "disabled_variable_frame_rate"
    elif ref_fps <= 0.0 or esp_fps <= 0.0 or effective_esp_fps <= 0.0:
        threshold_ms = 0.0
        reason = "disabled_invalid_fps_or_tempo"
    else:
        threshold_ms = min(500.0 / ref_fps, 500.0 / effective_esp_fps)
        reason = "no_equivalent_candidates"

    groups: list[dict[str, Any]] = []
    for candidate in candidates:
        group = next(
            (
                item for item in groups
                if threshold_ms > 0.0
                and (
                    max([int(candidate), *item["members_ms"]])
                    - min([int(candidate), *item["members_ms"]])
                ) < threshold_ms
            ),
            None,
        )
        if group is None:
            groups.append({
                "representative_ms": int(candidate),
                "members_ms": [int(candidate)],
            })
        else:
            group["members_ms"].append(int(candidate))

    implicit_zero_added = False
    if 0 not in candidates and threshold_ms > 0.0:
        zero_group = next(
            (
                item for item in groups
                if (
                    max([0, *item["members_ms"]])
                    - min([0, *item["members_ms"]])
                ) < threshold_ms
            ),
            None,
        )
        if zero_group is not None:
            zero_group["members_ms"].append(0)
            implicit_zero_added = True

    applied = any(len(item["members_ms"]) > 1 for item in groups)
    if applied:
        reason = "half_frame_equivalence_applied"
    effective = [int(item["representative_ms"]) for item in groups]
    zero_representative = 0
    zero_group = next((item for item in groups if 0 in item["members_ms"]), None)
    if zero_group is not None:
        zero_representative = int(zero_group["representative_ms"])

    return {
        "applied": applied,
        "reason": reason,
        "boundary": "strict",
        "threshold_ms": round(threshold_ms, 6),
        "ref_fps": round(ref_fps, 9),
        "esp_fps": round(esp_fps, 9),
        "effective_esp_fps": round(effective_esp_fps, 9),
        "tempo": round(tempo_value, 12),
        "ref_variable_frame_rate": bool(ref_meta.variable_frame_rate),
        "esp_variable_frame_rate": bool(esp_meta.variable_frame_rate),
        "input_candidates_ms": candidates,
        "effective_candidates_ms": effective,
        "groups": groups,
        "zero_representative_ms": zero_representative,
        "implicit_zero_added": implicit_zero_added,
    }


def _unique_ints(values: Iterable[int | float]) -> list[int]:
    out = []
    seen = set()
    for value in values:
        number = int(round(_finite_float(value)))
        if number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out


def _fps_result(
    planned: bool,
    enabled: bool,
    confirmed: bool,
    reason: str,
    ref_fps: float,
    esp_fps: float,
    tempo: float,
    started: float,
) -> dict[str, Any]:
    return {
        "planned": planned,
        "provisional": False,
        "enabled": enabled,
        "confirmed": confirmed,
        "applied": False,
        "reason": reason,
        "ref_fps": round(ref_fps, 9),
        "esp_fps": round(esp_fps, 9),
        "tempo": round(tempo, 12),
        "duration_sec": round(time.monotonic() - started, 3),
    }


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificación visual SSIM para Delay Audio")
    parser.add_argument("action", choices=("score", "confirm-fps", "preview-plan"))
    parser.add_argument("--ref", required=True)
    parser.add_argument("--esp-video-original", required=True)
    parser.add_argument("--profile", choices=("pelicula", "trailer"), default="pelicula")
    parser.add_argument("--candidate-ms", action="append", default=[])
    parser.add_argument("--tempo", type=float, default=1.0)
    parser.add_argument("--fps-ref", type=float)
    parser.add_argument("--fps-esp", type=float)
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--provisional-only", action="store_true")
    parser.add_argument("--profile-config-json", type=_profile_config_json_arg, default={})
    args = parser.parse_args()
    visual_overrides = visual_overrides_from_profile_config(args.profile_config_json)
    verifier = VisualVerifier(profile_overrides={args.profile: visual_overrides})
    try:
        if args.action == "preview-plan":
            payload = verifier.preview_plan(
                args.ref,
                args.esp_video_original,
                args.profile,
                args.delay_ms,
            )
        elif args.action == "confirm-fps":
            payload = verifier.confirm_fps_plan(
                args.ref,
                args.esp_video_original,
                args.fps_ref,
                args.fps_esp,
                args.profile,
                args.delay_ms,
                None,
                args.provisional_only,
            )
        else:
            candidates = [int(round(float(value))) for value in args.candidate_ms] or [0]
            payload = verifier.score_candidates(
                args.ref,
                args.esp_video_original,
                candidates,
                args.profile,
                args.tempo,
            )
        _json_print(payload)
        return 0 if payload.get("ok", True) else 1
    except Exception as exc:
        _json_print({"ok": False, "state": "ERROR_TECNICO", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
