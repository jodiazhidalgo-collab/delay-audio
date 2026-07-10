#!/usr/bin/env python3
"""Zona útil común y modelo temporal robusto para Delay Audio.

Este módulo no conoce FFmpeg ni el flujo web. Solo concentra las dos reglas
temporales que deben ser idénticas en imagen, audio y preview:

* construir el cuerpo interior de la pieza;
* separar tempo, offset fijo y residuos a partir de anclas interiores.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable


DEFAULT_MEASUREMENT_CORE = {
    "pelicula": {
        "long_duration_sec": 5400.0,
        "guard_start_sec": 120.0,
        "guard_end_sec": 120.0,
        "adaptive_guard_min_sec": 45.0,
        "adaptive_guard_max_sec": 120.0,
        "adaptive_guard_ratio": 0.03,
        "min_span_sec": 600.0,
    },
    "trailer": {
        "guard_min_sec": 1.5,
        "guard_max_sec": 4.0,
        "guard_ratio": 0.08,
        "min_span_sec": 8.0,
    },
}

DEFAULT_TIMELINE_MODEL = {
    "pelicula": {
        "anchor_pcts": [30.0, 50.0, 70.0],
        "min_anchors": 3,
        "min_span_ratio": 0.25,
        "residual_median_max_ms": 100.0,
        "residual_max_ms": 180.0,
        "max_drift_ms_per_sec": 0.1,
        "max_rejected_anchors": 1,
    },
    "trailer": {
        "anchor_pcts": [35.0, 52.0, 70.0],
        "min_anchors": 3,
        "min_span_ratio": 0.25,
        "residual_median_max_ms": 80.0,
        "residual_max_ms": 140.0,
        "max_drift_ms_per_sec": 0.1,
        "max_rejected_anchors": 1,
    },
}


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _profile(profile: str) -> str:
    return "trailer" if str(profile).lower() == "trailer" else "pelicula"


def _merged(defaults: dict[str, Any], config: Any) -> dict[str, Any]:
    result = dict(defaults)
    if isinstance(config, dict):
        result.update({key: value for key, value in config.items() if value is not None})
    return result


def build_measurement_core(
    duration: float,
    profile: str = "pelicula",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye el intervalo interior donde se eligen las mediciones.

    Los márgenes solo eliminan zonas poco fiables de los extremos. No intentan
    afirmar que dos intros o dos créditos tengan la misma duración.
    """

    key = _profile(profile)
    duration_sec = max(0.0, _finite(duration))
    cfg = _merged(DEFAULT_MEASUREMENT_CORE[key], config)

    if key == "trailer":
        min_span = min(duration_sec, max(0.0, _finite(cfg.get("min_span_sec"), 8.0)))
        requested = min(
            max(0.0, _finite(cfg.get("guard_max_sec"), 4.0)),
            max(
                max(0.0, _finite(cfg.get("guard_min_sec"), 1.5)),
                duration_sec * max(0.0, _finite(cfg.get("guard_ratio"), 0.08)),
            ),
        )
        available_each = max(0.0, (duration_sec - min_span) / 2.0)
        guard_start = min(requested, available_each)
        guard_end = min(requested, available_each)
        reduced = guard_start + 1e-9 < requested
        adaptive = True
        reason = "trailer_reduced_guards" if reduced else "trailer_adaptive_guards"
    else:
        configured_min_span = max(0.0, _finite(cfg.get("min_span_sec"), 600.0))
        # Una película corta no puede heredar una exigencia física de 10 min.
        # Conserva como mínimo el 60 % de su duración y nunca inventa tiempo.
        short_min_span = min(duration_sec, max(60.0, duration_sec * 0.60)) if duration_sec else 0.0
        min_span = min(configured_min_span, short_min_span) if duration_sec < configured_min_span else configured_min_span
        long_threshold = max(configured_min_span, _finite(cfg.get("long_duration_sec"), 5400.0))
        if duration_sec >= long_threshold:
            requested_start = max(0.0, _finite(cfg.get("guard_start_sec"), 120.0))
            requested_end = max(0.0, _finite(cfg.get("guard_end_sec"), 120.0))
            adaptive = False
            reason = "movie_long_fixed_guards"
        else:
            adaptive_guard = min(
                max(0.0, _finite(cfg.get("adaptive_guard_max_sec"), 120.0)),
                max(
                    max(0.0, _finite(cfg.get("adaptive_guard_min_sec"), 45.0)),
                    duration_sec * max(0.0, _finite(cfg.get("adaptive_guard_ratio"), 0.03)),
                ),
            )
            requested_start = adaptive_guard
            requested_end = adaptive_guard
            adaptive = True
            reason = "movie_short_adaptive_guards"

        requested_total = requested_start + requested_end
        available_total = max(0.0, duration_sec - min_span)
        if requested_total > available_total and requested_total > 0:
            scale = available_total / requested_total
            guard_start = requested_start * scale
            guard_end = requested_end * scale
            adaptive = True
            reason = "movie_short_reduced_guards"
        else:
            guard_start = requested_start
            guard_end = requested_end

    start = min(duration_sec, max(0.0, guard_start))
    end = max(start, duration_sec - max(0.0, guard_end))
    span = max(0.0, end - start)
    return {
        "start_sec": round(start, 6),
        "end_sec": round(end, 6),
        "span_sec": round(span, 6),
        "guard_start_sec": round(start, 6),
        "guard_end_sec": round(max(0.0, duration_sec - end), 6),
        "profile": key,
        "adaptive": bool(adaptive),
        "reason": reason,
    }


def core_zone_start(core: dict[str, Any], percentage: float, segment_sec: float = 0.0) -> float | None:
    """Devuelve un inicio dentro del core, incluyendo el segmento completo."""

    start = max(0.0, _finite(core.get("start_sec")))
    end = max(start, _finite(core.get("end_sec"), start))
    span = max(0.0, _finite(core.get("span_sec"), end - start))
    segment = max(0.0, _finite(segment_sec))
    if span <= 0 or segment > span + 1e-6:
        return None
    pct = max(0.0, min(100.0, _finite(percentage)))
    raw = start + span * pct / 100.0
    latest = max(start, end - segment)
    return round(min(latest, max(start, raw)), 6)


def map_ref_to_esp_time(ref_time: float, delay_sec: float = 0.0, tempo: float = 1.0) -> float:
    """Mapea tiempo maestro al vídeo español original con la convención real."""

    ref_value = _finite(ref_time, -1.0)
    delay_value = _finite(delay_sec)
    tempo_value = _finite(tempo, -1.0)
    if ref_value < 0:
        raise ValueError("ref_time debe ser positivo")
    if tempo_value <= 0:
        raise ValueError("tempo debe ser mayor que cero")
    return (ref_value - delay_value) * tempo_value


def _anchor_pair(anchor: Any) -> tuple[float, float] | None:
    if not isinstance(anchor, dict):
        return None
    ref_time = _finite(anchor.get("ref_time_sec", anchor.get("start_sec")), math.nan)
    esp_time = _finite(anchor.get("esp_time_sec"), math.nan)
    if not math.isfinite(esp_time):
        delay_ms = _finite(anchor.get("delay_ms"), math.nan)
        if math.isfinite(delay_ms):
            esp_time = ref_time - (delay_ms / 1000.0)
    if not math.isfinite(ref_time) or not math.isfinite(esp_time) or ref_time < 0 or esp_time < 0:
        return None
    return ref_time, esp_time


def _robust_line(points: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    slopes = []
    for index, (ref_left, esp_left) in enumerate(points):
        for ref_right, esp_right in points[index + 1:]:
            delta_esp = esp_right - esp_left
            if abs(delta_esp) < 0.5:
                continue
            slopes.append((ref_right - ref_left) / delta_esp)
    if not slopes:
        return None, None
    slope = median(slopes)
    intercept = median(ref_time - slope * esp_time for ref_time, esp_time in points)
    return float(slope), float(intercept)


def fit_timeline_model(
    anchors: Iterable[dict[str, Any]],
    profile: str = "pelicula",
    config: dict[str, Any] | None = None,
    core_span_sec: float | None = None,
) -> dict[str, Any]:
    """Ajusta ``ref_time = slope * esp_time + intercept`` sin dependencias.

    La mediana de pendientes entre pares y la mediana de intercepts hacen que
    un ancla aislada no fuerce el resultado. Después se rechazan residuos fuera
    del límite y se reajusta una vez solo con los inliers.
    """

    key = _profile(profile)
    cfg = _merged(DEFAULT_TIMELINE_MODEL[key], config)
    rows = list(anchors or [])
    indexed_points = [
        (index, pair)
        for index, row in enumerate(rows)
        for pair in [_anchor_pair(row)]
        if pair is not None
    ]
    points = [pair for _, pair in indexed_points]
    min_anchors = max(2, int(round(_finite(cfg.get("min_anchors"), 3))))
    max_residual = max(1.0, _finite(cfg.get("residual_max_ms"), 180.0))
    median_limit = max(1.0, min(max_residual, _finite(cfg.get("residual_median_max_ms"), 100.0)))
    drift_limit = max(0.0, _finite(cfg.get("max_drift_ms_per_sec"), 0.1))
    max_rejected = max(0, int(round(_finite(cfg.get("max_rejected_anchors"), 1))))
    min_span_ratio = max(0.0, min(1.0, _finite(cfg.get("min_span_ratio"), 0.25)))

    slope, intercept = _robust_line(points)
    if slope is None or intercept is None:
        return {
            "slope": None,
            "intercept_ms": None,
            "residual_median_ms": None,
            "residual_max_ms": None,
            "anchors_total": len(points),
            "anchors_inliers": 0,
            "anchors_rejected": len(points),
            "drift_ms_per_sec": None,
            "compatible": False,
            "span_sec": 0.0,
            "minimum_span_sec": round(max(0.0, _finite(core_span_sec)) * min_span_ratio, 6),
            "reason": "insufficient_anchors",
            "inlier_indexes": [],
            "rejected_indexes": [index for index, _ in indexed_points],
        }

    def residual_ms(point: tuple[float, float], line_slope: float, line_intercept: float) -> float:
        ref_time, esp_time = point
        return (ref_time - (line_slope * esp_time + line_intercept)) * 1000.0

    initial_inliers = [
        item for item in indexed_points
        if abs(residual_ms(item[1], slope, intercept)) <= max_residual
    ]
    if len(initial_inliers) >= 2:
        refined_slope, refined_intercept = _robust_line([point for _, point in initial_inliers])
        if refined_slope is not None and refined_intercept is not None:
            slope, intercept = refined_slope, refined_intercept

    final_residuals = [
        (index, point, residual_ms(point, slope, intercept))
        for index, point in indexed_points
    ]
    inliers = [item for item in final_residuals if abs(item[2]) <= max_residual]
    rejected = [item for item in final_residuals if abs(item[2]) > max_residual]
    absolute_residuals = [abs(item[2]) for item in inliers]
    ref_times = sorted(item[1][0] for item in inliers)
    span = ref_times[-1] - ref_times[0] if len(ref_times) >= 2 else 0.0
    minimum_span = max(1.0, max(0.0, _finite(core_span_sec)) * min_span_ratio)
    residual_median = median(absolute_residuals) if absolute_residuals else None
    residual_maximum = max(absolute_residuals) if absolute_residuals else None
    drift = (slope - 1.0) * 1000.0

    if len(inliers) < min_anchors:
        reason = "insufficient_inlier_anchors"
    elif len(rejected) > max_rejected:
        reason = "too_many_rejected_anchors"
    elif span < minimum_span:
        reason = "anchors_not_distributed"
    elif residual_median is None or residual_median > median_limit or residual_maximum > max_residual:
        reason = "timeline_residuals_too_high"
    elif abs(drift) > drift_limit:
        reason = "timeline_drift_too_high"
    else:
        reason = "stable_slope_intercept_and_residuals"
    compatible = reason == "stable_slope_intercept_and_residuals"

    return {
        "slope": round(slope, 12),
        "intercept_ms": round(intercept * 1000.0, 3),
        "residual_median_ms": round(residual_median, 3) if residual_median is not None else None,
        "residual_max_ms": round(residual_maximum, 3) if residual_maximum is not None else None,
        "anchors_total": len(points),
        "anchors_inliers": len(inliers),
        "anchors_rejected": len(rejected),
        "drift_ms_per_sec": round(drift, 9),
        "compatible": compatible,
        "span_sec": round(span, 6),
        "minimum_span_sec": round(minimum_span, 6),
        "reason": reason,
        "inlier_indexes": [item[0] for item in inliers],
        "rejected_indexes": [item[0] for item in rejected],
    }
