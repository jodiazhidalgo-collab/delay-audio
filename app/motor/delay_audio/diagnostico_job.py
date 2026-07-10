import json
import os
import time
import traceback
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _tail_text(text, limit=4000):
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[-limit:]


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (2 ** attempt))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _result_summary(result):
    if not isinstance(result, dict):
        return {}
    export = result.get("export") if isinstance(result.get("export"), dict) else {}
    return {
        "ok": result.get("ok"),
        "state": result.get("state"),
        "delay_ms": result.get("delay_ms"),
        "confidence": result.get("confidence"),
        "export_allowed": result.get("export_allowed"),
        "export_status": export.get("status"),
        "profile": result.get("profile"),
    }


class JobDiagnostics:
    def __init__(self, job_dir, job_id=None, kind="delay_audio"):
        self.job_dir = os.path.abspath(job_dir)
        self.job_id = job_id or os.path.basename(self.job_dir)
        self.kind = kind
        self.job_path = os.path.join(self.job_dir, "job.json")
        self.events_path = os.path.join(self.job_dir, "eventos.jsonl")
        self.timeline_path = os.path.join(self.job_dir, "timeline.json")
        self.errors_path = os.path.join(self.job_dir, "errores.json")
        self.commands_path = os.path.join(self.job_dir, "comandos.json")
        self.filtered_log_path = os.path.join(self.job_dir, "logs_filtrados.txt")
        self.readme_path = os.path.join(self.job_dir, "LEEME_CODEX.txt")

    def init(self, inputs=None, settings=None):
        os.makedirs(self.job_dir, exist_ok=True)
        job = _read_json(self.job_path, {})
        if not job:
            job = {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": "running",
                "created_at": _now_iso(),
                "inputs": inputs or {},
                "settings": settings or {},
                "paths": {"job_dir": self.job_dir},
            }
        else:
            job.setdefault("inputs", {}).update(inputs or {})
            job.setdefault("settings", {}).update(settings or {})
        job["updated_at"] = _now_iso()
        _write_json(self.job_path, job)
        if not os.path.exists(self.errors_path):
            _write_json(self.errors_path, [])
        if not os.path.exists(self.commands_path):
            _write_json(self.commands_path, [])
        if not os.path.exists(self.filtered_log_path):
            with open(self.filtered_log_path, "w", encoding="utf-8") as handle:
                handle.write("")
        self.event("job", "attached", "Motor de medicion conectado al diagnostico", {"inputs": inputs or {}})
        self.write_readme()

    def update_job(self, **fields):
        job = _read_json(self.job_path, {})
        job.update(fields)
        job["updated_at"] = _now_iso()
        _write_json(self.job_path, job)
        self.write_readme()

    def event(self, phase, event_name, message="", data=None, level="info"):
        payload = {
            "ts": _now_iso(),
            "job_id": self.job_id,
            "phase": phase,
            "event": event_name,
            "level": level,
            "message": str(message or ""),
            "data": data or {},
        }
        os.makedirs(self.job_dir, exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._append_filtered(payload)
        self.rebuild_timeline()
        return payload

    def error(self, error_code, phase, message, data=None, exc=None):
        payload = {
            "ts": _now_iso(),
            "job_id": self.job_id,
            "phase": phase,
            "error_code": error_code,
            "message": str(message or ""),
            "data": data or {},
        }
        if exc is not None:
            payload["exception_type"] = type(exc).__name__
            payload["traceback_tail"] = _tail_text(traceback.format_exc(), 3000)
        errors = _read_json(self.errors_path, [])
        errors.append(payload)
        _write_json(self.errors_path, errors)
        self.event(phase, "error", message, {"error_code": error_code, **(data or {})}, "error")
        self.update_job(status="error", last_error=payload)
        return payload

    def command(self, phase, name, cmd, returncode=None, started_at=None, stdout="", stderr="", ok=None):
        duration = None
        if started_at is not None:
            duration = round(max(0.0, time.time() - float(started_at)), 3)
        payload = {
            "ts": _now_iso(),
            "job_id": self.job_id,
            "phase": phase,
            "name": name,
            "cmd": [str(part) for part in (cmd or [])],
            "returncode": returncode,
            "duration_sec": duration,
            "ok": ok if ok is not None else (returncode in (0, None)),
            "stdout_tail": _tail_text(stdout),
            "stderr_tail": _tail_text(stderr),
        }
        commands = _read_json(self.commands_path, [])
        commands.append(payload)
        _write_json(self.commands_path, commands)
        self.event(phase, "command_finished", f"Comando {name} terminado", {
            "returncode": returncode,
            "duration_sec": duration,
            "ok": payload["ok"],
        }, "info" if payload["ok"] else "error")
        return payload

    def finish(self, status, result=None):
        measurement_status = "error" if status == "error" else "measurement_done"
        self.update_job(status=measurement_status, measurement_finished_at=_now_iso(), result=result or {})
        self.event(
            "measurement",
            "finished",
            f"Motor finalizado: {status}",
            _result_summary(result),
            "info" if status in {"done", "measure_done", "measurement_done"} else "error",
        )
        self.write_readme()

    def rebuild_timeline(self):
        events = []
        try:
            with open(self.events_path, "r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if raw:
                        events.append(json.loads(raw))
        except Exception:
            events = []
        phases = {}
        for item in events:
            phase = item.get("phase") or "unknown"
            current = phases.setdefault(phase, {
                "phase": phase,
                "first_ts": item.get("ts"),
                "last_ts": item.get("ts"),
                "events": 0,
                "errors": 0,
                "last_message": "",
            })
            current["last_ts"] = item.get("ts")
            current["events"] += 1
            current["last_message"] = item.get("message", "")
            if item.get("level") == "error" or item.get("event") == "error":
                current["errors"] += 1
        _write_json(self.timeline_path, {
            "job_id": self.job_id,
            "generated_at": _now_iso(),
            "source": "eventos.jsonl",
            "phases": list(phases.values()),
        })

    def _append_filtered(self, payload):
        if payload.get("event") == "command_finished" and payload.get("level") != "error":
            return
        line = "[{ts}] {level} {phase}.{event}: {message}".format(
            ts=payload.get("ts", ""),
            level=payload.get("level", "info").upper(),
            phase=payload.get("phase", ""),
            event=payload.get("event", ""),
            message=payload.get("message", ""),
        )
        with open(self.filtered_log_path, "a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")

    def write_readme(self):
        job = _read_json(self.job_path, {})
        errors = _read_json(self.errors_path, [])
        commands = _read_json(self.commands_path, [])
        timeline = _read_json(self.timeline_path, {})
        result = _read_json(os.path.join(self.job_dir, "resultado.json"), None)
        lines = [
            "LEEME_CODEX - diagnostico rapido",
            f"job_id: {self.job_id}",
            f"tipo: {job.get('kind', self.kind)}",
            f"estado: {job.get('status', '')}",
            f"carpeta: {self.job_dir}",
            "",
            "Orden recomendado de lectura:",
            "1. LEEME_CODEX.txt",
            "2. errores.json",
            "3. timeline.json",
            "4. eventos.jsonl",
            "5. comandos.json",
            "6. resultado.json",
            "7. logs_filtrados.txt",
            "",
            f"errores: {len(errors)}",
            f"comandos: {len(commands)}",
            f"fases: {len(timeline.get('phases') or [])}",
        ]
        if errors:
            last = errors[-1]
            lines.extend([
                "",
                "Ultimo error:",
                f"- codigo: {last.get('error_code', '')}",
                f"- fase: {last.get('phase', '')}",
                f"- mensaje: {last.get('message', '')}",
            ])
        if isinstance(result, dict):
            lines.extend([
                "",
                "Resultado:",
                f"- ok: {result.get('ok')}",
                f"- delay_ms: {result.get('delay_ms', '')}",
                f"- confianza: {result.get('confidence', '')}",
            ])
        with open(self.readme_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")


def classify_error(message):
    text = str(message or "").lower()
    if "temporal" in text and any(word in text for word in ("eliminar", "limpiar", "sigue existiendo")):
        return "CLEANUP_FAILED"
    if "no encuentro" in text or "not found" in text or "no existe" in text:
        return "INPUT_NOT_FOUND"
    if "ffprobe" in text:
        return "FFPROBE_FAILED"
    if "ffmpeg" in text:
        return "FFMPEG_FAILED"
    if "pista" in text and "audio" in text:
        return "AUDIO_TRACK_NOT_FOUND"
    if "zona" in text:
        return "ZONE_FAILED"
    if "confianza" in text:
        return "LOW_CONFIDENCE"
    if "mkvmerge" in text:
        return "MKVMERGE_FAILED"
    if "salida final ya existe" in text or "already exists" in text:
        return "OUTPUT_ALREADY_EXISTS"
    if "valid" in text or "verificar" in text:
        return "VALIDATION_FAILED"
    return "UNEXPECTED_ERROR"
