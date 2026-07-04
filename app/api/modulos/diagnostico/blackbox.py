import json
import os
import time
import traceback
from datetime import datetime, timezone


EVENTS_FILE = "eventos.jsonl"
TIMELINE_FILE = "timeline.json"
ERRORS_FILE = "errores.json"
COMMANDS_FILE = "comandos.json"
JOB_FILE = "job.json"
README_FILE = "LEEME_CODEX.txt"
FILTERED_LOG_FILE = "logs_filtrados.txt"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def tail_text(text, limit=4000):
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[-limit:]


def safe_json_read(path, default):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return json.load(handle)
    except Exception:
        return default


def safe_json_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def append_jsonl(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def diagnostic_paths(job_dir):
    return {
        "job_json_path": os.path.join(job_dir, JOB_FILE),
        "events_path": os.path.join(job_dir, EVENTS_FILE),
        "timeline_path": os.path.join(job_dir, TIMELINE_FILE),
        "errors_path": os.path.join(job_dir, ERRORS_FILE),
        "commands_path": os.path.join(job_dir, COMMANDS_FILE),
        "readme_path": os.path.join(job_dir, README_FILE),
        "filtered_log_path": os.path.join(job_dir, FILTERED_LOG_FILE),
    }


def attach(job):
    paths = diagnostic_paths(job["job_dir"])
    job.update(paths)
    return job


def init_job(job, kind, inputs=None, settings=None):
    attach(job)
    data = {
        "job_id": job.get("id"),
        "kind": kind,
        "status": job.get("status", "running"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "inputs": inputs or {},
        "settings": settings or {},
        "paths": {
            "job_dir": job.get("job_dir"),
            "result": job.get("result_path"),
            "progress": job.get("progress_path"),
            "human_log": job.get("log_path"),
        },
    }
    safe_json_write(job["job_json_path"], data)
    safe_json_write(job["errors_path"], [])
    safe_json_write(job["commands_path"], [])
    with open(job["filtered_log_path"], "w", encoding="utf-8") as handle:
        handle.write("")
    event(job, "job", "created", f"Job {kind} creado", {"inputs": inputs or {}, "settings": settings or {}})
    write_readme(job)


def update_job(job, **fields):
    attach(job)
    data = safe_json_read(job["job_json_path"], {})
    data.update(fields)
    data["updated_at"] = now_iso()
    safe_json_write(job["job_json_path"], data)
    write_readme(job)


def event(job, phase, event_name, message="", data=None, level="info"):
    attach(job)
    payload = {
        "ts": now_iso(),
        "job_id": job.get("id"),
        "phase": phase,
        "event": event_name,
        "level": level,
        "message": str(message or ""),
        "data": data or {},
    }
    append_jsonl(job["events_path"], payload)
    append_filtered(job, payload)
    rebuild_timeline(job)
    return payload


def record_error(job, error_code, phase, message, data=None, exc=None):
    attach(job)
    payload = {
        "ts": now_iso(),
        "job_id": job.get("id"),
        "phase": phase,
        "error_code": error_code,
        "message": str(message or ""),
        "data": data or {},
    }
    if exc is not None:
        payload["exception_type"] = type(exc).__name__
        payload["traceback_tail"] = tail_text(traceback.format_exc(), 3000)
    errors = safe_json_read(job["errors_path"], [])
    errors.append(payload)
    safe_json_write(job["errors_path"], errors)
    event(job, phase, "error", message, {"error_code": error_code, **(data or {})}, level="error")
    update_job(job, status="error", last_error=payload)
    return payload


def record_command(job, phase, name, cmd, returncode=None, started_at=None, stdout="", stderr="", ok=None):
    attach(job)
    finished = time.time()
    duration = None
    if started_at is not None:
        duration = round(max(0.0, finished - float(started_at)), 3)
    command = {
        "ts": now_iso(),
        "job_id": job.get("id"),
        "phase": phase,
        "name": name,
        "cmd": [str(part) for part in (cmd or [])],
        "returncode": returncode,
        "duration_sec": duration,
        "ok": ok if ok is not None else (returncode in (0, None)),
        "stdout_tail": tail_text(stdout),
        "stderr_tail": tail_text(stderr),
    }
    commands = safe_json_read(job["commands_path"], [])
    commands.append(command)
    safe_json_write(job["commands_path"], commands)
    event(job, phase, "command_finished", f"Comando {name} terminado", {
        "returncode": returncode,
        "duration_sec": duration,
        "ok": command["ok"],
    }, level="info" if command["ok"] else "error")
    return command


def finish_job(job, status, result=None):
    attach(job)
    update_job(job, status=status, finished_at=now_iso(), result=result or {})
    event(job, "finished", status, f"Job finalizado: {status}", result or {}, level="info" if status == "done" else "error")
    write_readme(job)


def rebuild_timeline(job):
    attach(job)
    phases = {}
    events = []
    try:
        with open(job["events_path"], "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                item = json.loads(raw)
                events.append(item)
    except Exception:
        events = []
    for item in events:
        phase = item.get("phase") or "unknown"
        entry = phases.setdefault(phase, {
            "phase": phase,
            "first_ts": item.get("ts"),
            "last_ts": item.get("ts"),
            "events": 0,
            "errors": 0,
            "last_message": "",
        })
        entry["last_ts"] = item.get("ts")
        entry["events"] += 1
        entry["last_message"] = item.get("message", "")
        if item.get("level") == "error" or item.get("event") == "error":
            entry["errors"] += 1
    safe_json_write(job["timeline_path"], {
        "job_id": job.get("id"),
        "generated_at": now_iso(),
        "source": EVENTS_FILE,
        "phases": list(phases.values()),
    })


def append_filtered(job, payload):
    if payload.get("event") == "command_finished" and payload.get("level") != "error":
        return
    line = "[{ts}] {level} {phase}.{event}: {message}".format(
        ts=payload.get("ts", ""),
        level=payload.get("level", "info").upper(),
        phase=payload.get("phase", ""),
        event=payload.get("event", ""),
        message=payload.get("message", ""),
    )
    with open(job["filtered_log_path"], "a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def write_readme(job):
    attach(job)
    job_data = safe_json_read(job["job_json_path"], {})
    errors = safe_json_read(job["errors_path"], [])
    commands = safe_json_read(job["commands_path"], [])
    timeline = safe_json_read(job["timeline_path"], {})
    result = safe_json_read(job.get("result_path", ""), None) if job.get("result_path") else None
    lines = [
        "LEEME_CODEX - diagnostico rapido",
        f"job_id: {job.get('id', '')}",
        f"tipo: {job_data.get('kind', '')}",
        f"estado: {job_data.get('status', job.get('status', ''))}",
        f"carpeta: {job.get('job_dir', '')}",
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
        export = result.get("export") or {}
        lines.extend([
            "",
            "Resultado:",
            f"- ok: {result.get('ok')}",
            f"- delay_ms: {result.get('delay_ms', '')}",
            f"- confianza: {result.get('confidence', '')}",
            f"- export_ok: {export.get('ok', '')}",
            f"- export_status: {export.get('status', '')}",
            f"- export_path: {export.get('path', '')}",
        ])
    with open(job["readme_path"], "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")


def classify_error(message):
    text = str(message or "").lower()
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
    if "docker" in text or "http" in text or "qbit" in text or "arr" in text:
        return "EXTERNAL_SERVICE_UNAVAILABLE"
    return "UNEXPECTED_ERROR"
