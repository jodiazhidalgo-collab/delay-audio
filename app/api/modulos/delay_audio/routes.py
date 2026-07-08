import json
import os
import re
import select
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime

from api.modulos.delay_audio.memoria import guardar_memoria, leer_memoria
from api.modulos.diagnostico.blackbox import (
    attach as diag_attach,
    classify_error as diag_classify_error,
    event as diag_event_raw,
    finish_job as diag_finish_job,
    init_job as diag_init_job_raw,
    record_command as diag_record_command_raw,
    record_error as diag_record_error_raw,
    update_job as diag_update_job_raw,
    write_readme as diag_write_readme_raw,
)
from api._core.utils import esc


LOG_ROOT = "/logs/delay_audio"
PREVIEW_ROOT = "/logs/delay_audio_preview"
MOTOR = "/motor/delay_audio/medir_delay_audio.py"
CONFIG_PATH = "/config/delay_audio.json"
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv"}
DATA_ROOT = os.environ.get("DELAY_AUDIO_DATA_ROOT", "/data")
MEDIA_ROOT = os.environ.get("DELAY_AUDIO_MEDIA_ROOT", "/media")
QUEUE_MOVIES_PATH = os.environ.get(
    "DELAY_AUDIO_QUEUE_MOVIES_PATH",
    f"{DATA_ROOT}/downloads/torrents/queue/movies",
)
COMPLETE_MOVIES_PATH = os.environ.get(
    "DELAY_AUDIO_COMPLETE_MOVIES_PATH",
    f"{DATA_ROOT}/downloads/torrents/complete/movies",
)
AUDIO_NORMALIZE_THRESHOLD_MS = 500
AUDIO_FINAL_MAX_FIRST_PACKET_MS = 1000
AUDIO_DURATION_TOLERANCE_SEC = 1.0
FPS_CORRECTION_THRESHOLD = 0.0005
PREVIEW_WINDOW_SEC = 20
PREVIEW_CLIP_SEC = 85
PREVIEW_MAX_OFFSET_MS = 60000
PREVIEW_MAX_AGE_SEC = 6 * 3600
DEFAULT_CONFIG = {
    "modo": "medir",
    "perfil": "pelicula",
    "confianza_minima": "MEDIA",
    "carpeta_salida": COMPLETE_MOVIES_PATH,
    "sub_video_bueno": "INGLES",
    "sub_fuente_espanol": "ESPAÑOL delay audio",
}
ROOTS = [
    {"key": "data", "label": "Data", "path": DATA_ROOT},
    {"key": "media", "label": "Media", "path": MEDIA_ROOT},
]
ROOT_BUTTON_ORDER = ("media", "data")

_JOBS = {}
_LOCK = threading.Lock()
DUPLICATE_JOB_GRACE_SEC = 30


def job_activo_misma_salida(ref, esp, ref_audio, esp_audio, output_dir, delay_hint_ms=0):
    now = time.time()
    delay_hint_ms = int(delay_hint_ms or 0)
    for job in _JOBS.values():
        is_running = job.get("status") == "running"
        is_recent = now - float(job.get("created") or 0) <= DUPLICATE_JOB_GRACE_SEC
        if not is_running and not is_recent:
            continue
        same_hint = int(job.get("delay_hint_ms") or 0) == delay_hint_ms
        if job.get("esp") == esp and job.get("output_dir") == output_dir and (is_running or same_hint):
            return job
        if (
            job.get("ref") == ref
            and job.get("esp") == esp
            and str(job.get("ref_audio", "")) == str(ref_audio)
            and str(job.get("esp_audio", "")) == str(esp_audio)
            and (is_running or same_hint)
        ):
            return job
    return None


def fase_error_exportacion(message):
    text = str(message or "").lower()
    if "salida final ya existe" in text or "publish" in text:
        return "publish_output"
    if "mkvmerge" in text:
        return "mkvmerge"
    if "ffmpeg" in text or "audio temporal" in text:
        return "normalize_audio"
    if "valid" in text or "verificar" in text:
        return "verify_final"
    return "export"


def diagnostico_attach(job):
    try:
        diag_attach(job)
    except Exception:
        pass


def diagnostico_init(job, kind, inputs=None, settings=None):
    try:
        diag_init_job_raw(job, kind, inputs=inputs, settings=settings)
    except Exception:
        pass


def diagnostico_event(job, phase, event_name, message="", data=None, level="info"):
    try:
        diag_event_raw(job, phase, event_name, message, data or {}, level)
    except Exception:
        pass


def diagnostico_error(job, error_code, phase, message, data=None, exc=None):
    try:
        diag_record_error_raw(job, error_code, phase, message, data or {}, exc)
    except Exception:
        pass


def diagnostico_command(job, phase, name, cmd, returncode=None, started_at=None, stdout="", stderr="", ok=None):
    try:
        diag_record_command_raw(job, phase, name, cmd, returncode, started_at, stdout, stderr, ok)
    except Exception:
        pass


def diagnostico_update(job, **fields):
    try:
        diag_update_job_raw(job, **fields)
    except Exception:
        pass


def diagnostico_finish(job, status, result=None):
    try:
        diag_finish_job(job, status, result or {})
    except Exception:
        pass


def diagnostico_readme(job):
    try:
        diag_write_readme_raw(job)
    except Exception:
        pass


def vista_delay_audio():
    root_lookup = {r["key"]: r for r in ROOTS}
    visual_roots = [root_lookup[key] for key in ROOT_BUTTON_ORDER if key in root_lookup]
    root_buttons = "".join(
        f'<button class="btn" onclick="delayAudioAbrir(\'{esc(r["path"])}\')">{esc(r["label"])}</button>'
        for r in visual_roots
    )
    return f'''
    <div class="box delay-audio-panel" data-delay-audio="1">
      <section id="delay-view-medir" class="delay-section delay-section-videos">
        <div class="delay-section-head">
          <h2>Videos</h2>
        </div>
        <div class="delay-form">
        <input id="delay-ref" type="hidden">
        <input id="delay-esp" type="hidden">
        <div class="delay-pick-card">
          <div class="delay-card-head">
            <span>Video bueno / imagen buena</span>
            <button class="delay-mini-btn" onclick="delayAudioAbrirSelector('ref')">Elegir</button>
          </div>
          <input id="delay-ref-audio" type="hidden">
          <button class="delay-pick" onclick="delayAudioAbrirSelector('ref')">
            <b id="delay-ref-name">Tocar para elegir</b>
            <small id="delay-ref-path">Sin seleccionar</small>
            <span id="delay-ref-meta" class="delay-pick-meta"></span>
          </button>
          <div id="delay-ref-audio-list" class="delay-audio-list"></div>
        </div>
        <div class="delay-pick-card">
          <div class="delay-card-head">
            <span>Video con audio espanol</span>
            <button class="delay-mini-btn" onclick="delayAudioAbrirSelector('esp')">Elegir</button>
          </div>
          <input id="delay-esp-audio" type="hidden">
          <button class="delay-pick" onclick="delayAudioAbrirSelector('esp')">
            <b id="delay-esp-name">Tocar para elegir</b>
            <small id="delay-esp-path">Sin seleccionar</small>
            <span id="delay-esp-meta" class="delay-pick-meta"></span>
          </button>
          <div id="delay-esp-audio-list" class="delay-audio-list"></div>
        </div>
        </div>
        <div class="actions delay-actions">
          <button class="btn green" id="delay-main-action" onclick="delayAudioMedir(this)">Ejecutar</button>
          <button class="btn delay-clear-btn" onclick="delayAudioLimpiar()">Limpiar</button>
        </div>
        <div id="delay-result" class="box delay-result">
          <h2>Resultado</h2>
          <p>Esperando medicion.</p>
        </div>
      </section>
      <section id="delay-view-ajustes" class="delay-section delay-settings">
        <div class="delay-section-head">
          <h2>Ajustes</h2>
        </div>
        <div class="delay-setting">
          <label>Modo</label>
          <div class="delay-segment">
            <button id="delay-mode-exportar" onclick="delayAudioSetConfig('modo','exportar')">Medir y exportar</button>
            <button id="delay-mode-medir" onclick="delayAudioSetConfig('modo','medir')">Solo medir</button>
          </div>
        </div>
        <div class="delay-setting">
          <label>Tipo</label>
          <div class="delay-segment">
            <button id="delay-profile-pelicula" onclick="delayAudioSetConfig('perfil','pelicula')">Pelicula</button>
            <button id="delay-profile-trailer" onclick="delayAudioSetConfig('perfil','trailer')">Trailer</button>
          </div>
        </div>
        <div class="delay-setting">
          <label>Confianza minima</label>
          <div class="delay-segment three">
            <button id="delay-conf-ALTA" onclick="delayAudioSetConfig('confianza_minima','ALTA')">ALTA</button>
            <button id="delay-conf-MEDIA" onclick="delayAudioSetConfig('confianza_minima','MEDIA')">MEDIA+</button>
            <button id="delay-conf-CUALQUIERA" onclick="delayAudioSetConfig('confianza_minima','CUALQUIERA')">Todas</button>
          </div>
        </div>
        <div class="delay-subtitle-grid">
          <div class="delay-setting">
            <label>Sub video bueno</label>
            <span class="delay-help">Nombre que añade al subtitulo</span>
            <input id="delay-sub-ref" class="delay-text-input" oninput="delayAudioConfigInput('sub_video_bueno', this.value)">
          </div>
          <div class="delay-setting">
            <label>Sub fuente espanol</label>
            <span class="delay-help">Nombre que añade ( docker Media Automatizacion poner: ESPAÑOL delay audio )</span>
            <input id="delay-sub-esp" class="delay-text-input" oninput="delayAudioConfigInput('sub_fuente_espanol', this.value)">
          </div>
        </div>
        <div class="delay-setting">
          <label>Carpeta salida</label>
          <div class="delay-output-line">
            <input id="delay-output-path" readonly>
            <button class="btn" onclick="delayAudioAbrirCarpetaSalida()">Elegir</button>
          </div>
        </div>
        <div class="actions delay-save-actions">
          <button id="delay-save-action" class="btn green" onclick="delayAudioGuardarAjustes(this)">Guardar</button>
        </div>
        <div id="delay-follow" class="delay-setting delay-follow">
          <div class="delay-log-head">
            <div>
              <label>Seguimiento</label>
              <p id="delay-log-summary" class="delay-log-summary">Sin medicion todavia.</p>
            </div>
            <button id="delay-log-toggle" class="btn" onclick="delayAudioToggleLog()">Ocultar</button>
          </div>
          <div id="delay-log-human" class="delay-human-log">
            <div class="delay-human-empty">Cuando ejecutes una medicion veras aqui los pasos importantes.</div>
          </div>
          <pre id="delay-log-clean" class="delay-log-pre">Sin log todavia.</pre>
        </div>
      </section>
    </div>
    <div id="delay-sheet" class="delay-sheet" aria-hidden="true">
      <button class="delay-sheet-backdrop" onclick="delayAudioCerrarSelector()" aria-label="Cerrar"></button>
      <div class="delay-sheet-card">
        <div class="delay-sheet-grip"></div>
        <div class="delay-browser-head">
          <b id="delay-modo">Selecciona video bueno</b>
          <button class="delay-close" onclick="delayAudioCerrarSelector()">Cerrar</button>
        </div>
        <span id="delay-path" class="delay-path">{esc(DATA_ROOT)}</span>
        <div class="delay-root-actions">
          {root_buttons}
        </div>
        <button id="delay-use-folder" class="btn green delay-use-folder is-hidden" onclick="delayAudioUsarCarpetaActual()">Usar esta carpeta</button>
        <div id="delay-files" class="delay-files empty">Cargando archivos...</div>
      </div>
    </div>'''


def delay_audio_api(q):
    action = q.get("da", [""])[0]
    if action == "files":
        return listar_archivos(q.get("path", [ROOTS[0]["path"]])[0])
    if action == "dirs":
        return listar_carpetas(q.get("path", [ROOTS[0]["path"]])[0])
    if action == "streams":
        return pistas_audio(q.get("path", [""])[0])
    if action == "file_info":
        return info_archivo(q.get("path", [""])[0])
    if action == "preview":
        return preview_visual(q)
    if action == "memory_get":
        return memoria_compartida()
    if action == "memory_set":
        return guardar_memoria_compartida(q)
    if action == "settings":
        return {"ok": True, "settings": leer_config()}
    if action == "save_settings":
        return guardar_config_desde_query(q)
    if action == "start":
        return iniciar(
            q.get("ref", [""])[0],
            q.get("esp", [""])[0],
            q.get("ref_audio", [""])[0],
            q.get("esp_audio", [""])[0],
            q.get("delay_hint_ms", ["0"])[0],
        )
    if action == "status":
        return estado(q.get("job", [""])[0])
    if action == "last":
        return ultimo_estado()
    return {"ok": False, "error": "Accion delay_audio no reconocida."}


def preview_visual(q):
    ref = normalizar_ruta(q.get("ref", [""])[0])
    esp = normalizar_ruta(q.get("esp", [""])[0])
    error = validar_video(ref) or validar_video(esp)
    if error:
        return {"ok": False, "error": error}

    limpiar_previews_antiguos()
    preview_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    preview_dir = os.path.join(PREVIEW_ROOT, preview_id)
    os.makedirs(preview_dir, exist_ok=True)

    try:
        ref_out = os.path.join(preview_dir, "ref.mp4")
        esp_out = os.path.join(preview_dir, "esp.mp4")
        generar_preview_clip(ref, ref_out, "Video Bueno")
        generar_preview_clip(esp, esp_out, "Audio Espanol")
        manifest = {
            "id": preview_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "ref": ref,
            "esp": esp,
            "window_sec": PREVIEW_WINDOW_SEC,
            "clip_sec": PREVIEW_CLIP_SEC,
            "max_offset_ms": PREVIEW_MAX_OFFSET_MS,
        }
        with open(os.path.join(preview_dir, "preview.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return {
            "ok": True,
            "id": preview_id,
            "ref_url": f"/preview/{preview_id}/ref.mp4",
            "esp_url": f"/preview/{preview_id}/esp.mp4",
            "window_sec": PREVIEW_WINDOW_SEC,
            "clip_sec": PREVIEW_CLIP_SEC,
            "max_offset_ms": PREVIEW_MAX_OFFSET_MS,
        }
    except Exception as exc:
        shutil.rmtree(preview_dir, ignore_errors=True)
        return {"ok": False, "error": str(exc)}


def generar_preview_clip(source, target, label):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-t",
        str(PREVIEW_CLIP_SEC),
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "scale=640:-2,fps=24,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "31",
        "-movflags",
        "+faststart",
        target,
    ]
    started_at = time.time()
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=300,
    )
    log_path = os.path.join(os.path.dirname(target), "preview.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {label} rc={p.returncode} elapsed={time.time() - started_at:.2f}s\n")
        if p.stdout:
            f.write(p.stdout[-4000:] + "\n")
        if p.stderr:
            f.write(p.stderr[-4000:] + "\n")
    if p.returncode != 0:
        raise RuntimeError(f"No pude crear preview de {label}: {(p.stderr or p.stdout or '').strip()[-500:]}")
    if not os.path.isfile(target) or os.path.getsize(target) < 20000:
        raise RuntimeError(f"Preview de {label} no valido.")


def limpiar_previews_antiguos():
    os.makedirs(PREVIEW_ROOT, exist_ok=True)
    cutoff = time.time() - PREVIEW_MAX_AGE_SEC
    try:
        for name in os.listdir(PREVIEW_ROOT):
            path = os.path.join(PREVIEW_ROOT, name)
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def iniciar(ref, esp, ref_audio="", esp_audio="", delay_hint_ms=0):
    ref = normalizar_ruta(ref)
    esp = normalizar_ruta(esp)
    delay_hint_ms = normalizar_delay_hint_ms(delay_hint_ms)
    error = validar_video(ref) or validar_video(esp)
    if error:
        return {"ok": False, "error": error}
    error = validar_indice_audio(ref_audio, "video bueno") or validar_indice_audio(esp_audio, "audio espanol")
    if error:
        return {"ok": False, "error": error}

    cfg = leer_config()
    output_dir = normalizar_ruta(cfg.get("carpeta_salida") or DEFAULT_CONFIG["carpeta_salida"])
    fps_correction = planificar_correccion_fps(ref, esp)
    with _LOCK:
        existing = job_activo_misma_salida(ref, esp, ref_audio, esp_audio, output_dir, delay_hint_ms)
        if existing:
            diagnostico_event(existing, "duplicate_guard", "reused", "Peticion duplicada: se reutiliza el job activo", {
                "existing_job": existing.get("id"),
                "video_bueno": ref,
                "video_espanol": esp,
                "output_dir": output_dir,
                "delay_hint_ms": delay_hint_ms,
            })
            return {
                "ok": True,
                "job": existing.get("id"),
                "status": existing.get("status", "running"),
                "duplicate": True,
                "message": "Ya hay un proceso igual en marcha.",
            }
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        job_dir = os.path.join(LOG_ROOT, job_id)
        os.makedirs(job_dir, exist_ok=True)
        job = {
            "id": job_id,
            "status": "running",
            "created": time.time(),
            "ref": ref,
            "esp": esp,
            "ref_audio": ref_audio,
            "esp_audio": esp_audio,
            "delay_hint_ms": delay_hint_ms,
            "output_dir": output_dir,
            "job_dir": job_dir,
            "log_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_LOG.txt"),
            "csv_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_RESULTADOS.csv"),
            "result_path": os.path.join(job_dir, "resultado.json"),
            "progress_path": os.path.join(job_dir, "progress.json"),
            "returncode": None,
            "error": "",
            "fps_correction": fps_correction,
        }
        _JOBS[job_id] = job
    diagnostico_init(job, "delay_audio", inputs={
        "video_bueno": ref,
        "video_espanol": esp,
        "ref_audio": ref_audio,
        "esp_audio": esp_audio,
    }, settings={
        "modo": cfg.get("modo"),
        "perfil": cfg.get("perfil"),
        "confianza_minima": cfg.get("confianza_minima"),
        "carpeta_salida": output_dir,
        "delay_hint_ms": delay_hint_ms,
        "fps_correction": fps_correction,
    })
    diagnostico_event(job, "validate_inputs", "finished", "Entradas validadas", {
        "video_bueno": ref,
        "video_espanol": esp,
        "delay_hint_ms": delay_hint_ms,
    })
    thread = threading.Thread(target=_ejecutar_job, args=(job,), daemon=True)
    thread.start()
    return {"ok": True, "job": job_id, "status": "running"}


def _ejecutar_job(job):
    diagnostico_attach(job)
    stdout_path = os.path.join(job["job_dir"], "stdout.log")
    cfg = leer_config()
    profile = limpiar_opcion(cfg.get("perfil", DEFAULT_CONFIG["perfil"]), {"pelicula", "trailer"}, DEFAULT_CONFIG["perfil"])
    job["profile"] = profile
    temp_cleanup_paths = []
    try:
        fps_correction = job.get("fps_correction") or {}
        if fps_correction.get("enabled"):
            preparar_audio_fps_medicion(job, fps_correction, temp_cleanup_paths)

        esp_measure_path = job.get("esp_measure_path") or job["esp"]
        esp_measure_audio = job.get("esp_measure_audio", job.get("esp_audio"))
        cmd = ["python", MOTOR, "--ref", job["ref"], "--esp", esp_measure_path, "--job-dir", job["job_dir"], "--profile", profile]
        if job.get("ref_audio") != "":
            cmd += ["--ref-audio-index", str(job["ref_audio"])]
        if esp_measure_audio != "":
            cmd += ["--esp-audio-index", str(esp_measure_audio)]
        if int(job.get("delay_hint_ms") or 0) != 0:
            cmd += ["--delay-hint-ms", str(int(job.get("delay_hint_ms") or 0))]
        diagnostico_update(job, status="running", profile=profile, delay_hint_ms=int(job.get("delay_hint_ms") or 0))
        diagnostico_event(job, "measure_setup", "started", "Arranca motor de medicion", {
            "profile": profile,
            "stdout_log": stdout_path,
            "delay_hint_ms": int(job.get("delay_hint_ms") or 0),
            "fps_correction": fps_correction,
        })
        started_at = time.time()
        with open(stdout_path, "w", encoding="utf-8") as out:
            p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, text=True)
            rc = p.wait()
        job["returncode"] = rc
        diagnostico_command(job, "measure_setup", "medir_delay_audio.py", cmd, rc, started_at, leer_tail(stdout_path, 12000), "", rc == 0)
        if rc == 0:
            diagnostico_event(job, "measure_setup", "finished", "Motor de medicion terminado OK", {"returncode": rc})
            anexar_correccion_fps_resultado(job)
            exportar_si_corresponde(job)
            job["status"] = "done"
            diagnostico_finish(job, "done", leer_json(job["result_path"]) or {})
        else:
            job["status"] = "error"
            message = "El motor de medicion termino con error."
            diagnostico_error(job, "MEASURE_FAILED", "measure_setup", message, {"returncode": rc, "stdout_log": stdout_path})
            diagnostico_finish(job, "error", leer_json(job["result_path"]) or {})
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        diagnostico_error(job, diag_classify_error(str(exc)), "api_job", str(exc), {"returncode": job.get("returncode")}, exc)
        diagnostico_finish(job, "error", leer_json(job["result_path"]) or {})
        try:
            with open(job["log_path"], "a", encoding="utf-8") as f:
                f.write(f"ERROR API: {exc}\n")
        except Exception:
            pass
    finally:
        for path in temp_cleanup_paths:
            diagnostico_event(job, "cleanup", "remove_temp", "Eliminando temporal propio", {"path": path})
            limpiar_archivo_silencioso(path)


def exportar_si_corresponde(job):
    diagnostico_attach(job)
    cfg = leer_config()
    if cfg.get("modo") != "exportar":
        diagnostico_event(job, "export_prepare", "skipped", "Modo exportar desactivado", {"modo": cfg.get("modo")})
        return

    result = leer_json(job["result_path"]) or {}
    log_job(job, "MODO EXPORTAR: activo")
    diagnostico_event(job, "export_prepare", "started", "Modo exportar activo", {
        "confidence": result.get("confidence"),
        "delay_ms": result.get("delay_ms"),
    })
    if not result.get("ok"):
        log_job(job, "EXPORTACION: no se exporta porque la medicion no termino OK.")
        diagnostico_event(job, "export_prepare", "skipped", "No se exporta porque la medicion no termino OK")
        escribir_progreso(job, "done", 100, "Listo")
        return

    confidence = result.get("confidence", "BAJA")
    if not confianza_valida(confidence, cfg.get("confianza_minima", "MEDIA")):
        log_job(job, f"EXPORTACION: no se exporta. Confianza {confidence}, minimo {cfg.get('confianza_minima')}.")
        diagnostico_error(job, "LOW_CONFIDENCE", "export_prepare", "Confianza insuficiente para exportar", {
            "confidence": confidence,
            "confianza_minima": cfg.get("confianza_minima"),
        })
        result["export"] = {"ok": False, "status": "skipped", "reason": "confianza_baja"}
        escribir_json(job["result_path"], result)
        escribir_progreso(job, "done", 100, "Listo")
        return

    output_dir = job.get("output_dir") or cfg.get("carpeta_salida") or DEFAULT_CONFIG["carpeta_salida"]
    output_dir = normalizar_ruta(output_dir)
    if not ruta_permitida(output_dir):
        raise RuntimeError("Carpeta de salida no permitida.")
    os.makedirs(output_dir, exist_ok=True)

    output_path = ruta_salida_unica(job["esp"], output_dir)
    temp_output_path = ruta_temporal_exportacion(output_path)
    delay_ms = int(round(float(result.get("delay_ms", 0))))
    video_duration = duracion_video_principal(job["ref"])
    log_job(job, f"EXPORTACION: creando {output_path}")
    log_job(job, f"EXPORTACION: temporal seguro {temp_output_path}")
    log_job(job, f"EXPORTACION: delay audio espanol {result.get('delay_ms', 0)} ms")
    log_job(job, f"EXPORTACION: duracion maestra video bueno {video_duration:.3f} s")
    diagnostico_event(job, "export_prepare", "finished", "Exportacion preparada", {
        "output_path": output_path,
        "temp_output_path": temp_output_path,
        "delay_ms": delay_ms,
        "video_duration": video_duration,
    })
    result["export"] = {"ok": None, "status": "running", "path": output_path}
    escribir_json(job["result_path"], result)
    escribir_progreso(job, "export", 0, "Exportando")

    temp_cleanup_paths = []
    published_output = False
    try:
        diagnostico_event(job, "normalize_audio", "started", "Preparando audio espanol", {"delay_ms": delay_ms})
        audio_source_path = job.get("fps_audio_path") or job["esp"]
        audio_source_index = job.get("fps_audio_index", job.get("esp_audio"))
        audio_track_id = mkvmerge_track_id_for_ffprobe_index(audio_source_path, audio_source_index, "audio")
        audio_input = preparar_audio_espanol_exportacion(
            job,
            audio_track_id,
            delay_ms,
            video_duration,
            temp_cleanup_paths,
            source_path=audio_source_path,
            source_audio=audio_source_index,
        )
        diagnostico_event(job, "normalize_audio", "finished", "Audio espanol preparado", {
            "normalized": audio_input.get("normalized"),
            "track_id": audio_input.get("track_id"),
            "sync_ms": audio_input.get("sync_ms"),
            "path": audio_input.get("path"),
            "fps_corrected": bool(job.get("fps_audio_path")),
        })
        cmd = [
            "mkvmerge",
            "--gui-mode",
            "--output",
            temp_output_path,
            "--stop-after-video-ends",
            "--no-audio",
            "--no-buttons",
            "--no-attachments",
        ]
        cmd.extend(mkvmerge_metadata_subtitulos(job["ref"], cfg.get("sub_video_bueno", DEFAULT_CONFIG["sub_video_bueno"])))
        cmd.extend([
            job["ref"],
            "--no-video",
            "--no-subtitles",
            "--audio-tracks",
            str(audio_input["track_id"]),
            "--sync",
            f"{audio_input['track_id']}:{audio_input['sync_ms']}",
            "--default-track-flag",
            f"{audio_input['track_id']}:1",
            "--no-buttons",
            "--no-attachments",
            "--no-chapters",
            audio_input["path"],
        ])
        esp_subtitle_track_ids = mkvmerge_track_ids(job["esp"], "subtitles")
        if esp_subtitle_track_ids:
            cmd.extend(mkvmerge_sync_tracks(esp_subtitle_track_ids, delay_ms))
            cmd.extend(mkvmerge_metadata_subtitulos(job["esp"], cfg.get("sub_fuente_espanol", DEFAULT_CONFIG["sub_fuente_espanol"])))
            cmd.extend([
                "--no-video",
                "--no-audio",
                "--subtitle-tracks",
                ",".join(map(str, esp_subtitle_track_ids)),
                "--no-buttons",
                "--no-attachments",
                "--no-chapters",
                job["esp"],
            ])

        log_job(job, audio_input["log"])
        log_job(job, f"EXPORTACION: pista audio espanol mkvmerge ID {audio_input['track_id']}")
        if audio_input.get("normalized"):
            log_job(job, f"EXPORTACION: audio espanol normalizado {audio_input['normalized_reason']}")
        if esp_subtitle_track_ids:
            log_job(job, f"EXPORTACION: subtitulos del video espanol con delay {delay_ms} ms: {', '.join(map(str, esp_subtitle_track_ids))}")
        log_job(job, "EXPORTACION: video bueno manda y se corta al terminar su video")

        diagnostico_event(job, "mkvmerge", "started", "Arranca mkvmerge", {
            "temp_output_path": temp_output_path,
            "output_path": output_path,
        })
        returncode = ejecutar_mkvmerge_con_progreso(cmd, job)
        if returncode not in (0, 1):
            raise RuntimeError("mkvmerge fallo exportando el MKV final.")
        if returncode == 1:
            log_job(job, "EXPORTACION: mkvmerge termino con avisos; valido el temporal antes de publicarlo.")

        diagnostico_event(job, "verify_temp", "started", "Validando temporal", {"temp_output_path": temp_output_path})
        validar_mkv_exportado(temp_output_path, video_duration)
        diagnostico_event(job, "verify_temp", "finished", "Temporal validado", {"temp_output_path": temp_output_path})
        diagnostico_event(job, "publish_output", "started", "Publicando salida final", {
            "temp_output_path": temp_output_path,
            "output_path": output_path,
        })
        publicar_exportacion_temporal(temp_output_path, output_path)
        published_output = True
        diagnostico_event(job, "publish_output", "finished", "Salida final publicada", {"output_path": output_path})
        diagnostico_event(job, "verify_final", "started", "Validando salida final", {"output_path": output_path})
        validar_mkv_exportado(output_path, video_duration)
        diagnostico_event(job, "verify_final", "finished", "Salida final validada", {"output_path": output_path})
    except Exception as exc:
        error_phase = fase_error_exportacion(str(exc))
        diagnostico_error(job, diag_classify_error(str(exc)), error_phase, str(exc), {
            "output_path": output_path,
            "temp_output_path": temp_output_path,
            "published_output": published_output,
        }, exc)
        diagnostico_event(job, "cleanup", "started", "Limpieza tras error de exportacion", {
            "temp_output_exists": os.path.isfile(temp_output_path),
            "output_exists": os.path.isfile(output_path),
            "published_output": published_output,
        }, level="error")
        limpiar_archivo_silencioso(temp_output_path)
        if os.path.isfile(output_path):
            diagnostico_event(job, "cleanup", "preserve_output_path", "Se conserva output_path; la limpieza solo borra temporales propios", {
                "output_path": output_path,
                "published_output": published_output,
            })
        result["export"] = {"ok": False, "status": "error", "path": output_path}
        escribir_json(job["result_path"], result)
        escribir_progreso(job, "error", 100, "Aviso")
        raise
    finally:
        for path in temp_cleanup_paths:
            diagnostico_event(job, "cleanup", "remove_temp", "Eliminando temporal propio", {"path": path})
            limpiar_archivo_silencioso(path)

    result["export"] = {"ok": True, "status": "done", "path": output_path}
    escribir_json(job["result_path"], result)
    escribir_progreso(job, "done", 100, "Listo")
    log_job(job, f"EXPORTACION OK: {output_path}")
    diagnostico_event(job, "finished", "export_done", "Exportacion terminada OK", {"output_path": output_path})
    diagnostico_readme(job)


def estado(job_id):
    job = obtener_job(job_id)
    if not job:
        return {"ok": False, "error": "No encuentro ese trabajo."}
    result = leer_json(job["result_path"])
    rows = leer_csv(job["csv_path"])
    status = job.get("status", "done" if result else "running")
    if result and not result.get("ok", False):
        status = "error"
    progress = leer_progreso(job, status, rows, result)
    return {
        "ok": True,
        "job": job["id"],
        "status": status,
        "ref": job.get("ref", ""),
        "esp": job.get("esp", ""),
        "log": leer_tail(job["log_path"]),
        "rows": rows,
        "result": result,
        "progress": progress,
        "csv_path": job["csv_path"],
        "log_path": job["log_path"],
        "error": job.get("error", ""),
    }


def ultimo_estado():
    jobs = []
    try:
        for name in os.listdir(LOG_ROOT):
            path = os.path.join(LOG_ROOT, name)
            if os.path.isdir(path):
                jobs.append((os.path.getmtime(path), name))
    except Exception:
        pass
    if not jobs:
        return {"ok": True, "status": "empty", "log": "", "rows": [], "result": None}
    _, job_id = sorted(jobs, reverse=True)[0]
    return estado(job_id)


def obtener_job(job_id):
    with _LOCK:
        if job_id in _JOBS:
            return _JOBS[job_id]
    if not job_id:
        return None
    job_dir = os.path.join(LOG_ROOT, os.path.basename(job_id))
    if not os.path.isdir(job_dir):
        return None
    return {
        "id": os.path.basename(job_id),
        "status": "done",
        "ref": "",
        "esp": "",
        "job_dir": job_dir,
        "log_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_LOG.txt"),
        "csv_path": os.path.join(job_dir, "MEDIR_DELAY_AUDIO_RESULTADOS.csv"),
        "result_path": os.path.join(job_dir, "resultado.json"),
        "progress_path": os.path.join(job_dir, "progress.json"),
    }


def listar_archivos(path):
    path = normalizar_ruta(path or ROOTS[0]["path"])
    if not ruta_permitida(path):
        path = ROOTS[0]["path"]
    items = []
    parent = os.path.dirname(path.rstrip(os.sep)) or path
    if parent != path and ruta_permitida(parent):
        items.append({"name": "..", "path": parent, "type": "dir", "size": "", "date": ""})
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries[:500]:
            try:
                if entry.is_dir():
                    tipo = "dir"
                else:
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext not in VIDEO_EXTENSIONS:
                        continue
                    tipo = "file"
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": tipo,
                    "size": formato_size(stat.st_size) if tipo == "file" else "",
                    "date": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                })
            except Exception:
                pass
        return {"ok": True, "path": path, "items": items}
    except Exception as exc:
        return {"ok": False, "path": path, "error": str(exc), "items": items}


def listar_carpetas(path):
    path = normalizar_ruta(path or ROOTS[0]["path"])
    if not ruta_permitida(path):
        path = ROOTS[0]["path"]
    items = []
    parent = os.path.dirname(path.rstrip(os.sep)) or path
    if parent != path and ruta_permitida(parent):
        items.append({"name": "..", "path": parent, "type": "dir", "size": "", "date": ""})
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        for entry in entries[:500]:
            if not entry.is_dir():
                continue
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "dir",
                    "size": "",
                    "date": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
                })
            except Exception:
                pass
        return {"ok": True, "path": path, "items": items}
    except Exception as exc:
        return {"ok": False, "path": path, "error": str(exc), "items": items}


def pistas_audio(path):
    path = normalizar_ruta(path)
    error = validar_video(path)
    if error:
        return {"ok": False, "error": error, "streams": []}
    try:
        p = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index,codec_name,channels,channel_layout:stream_tags=language,title",
                "-of",
                "json",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=60,
        )
        if p.returncode != 0:
            return {"ok": False, "error": "No pude leer las pistas de audio.", "streams": []}
        data = json.loads(p.stdout or "{}")
        streams = []
        for st in data.get("streams") or []:
            tags = st.get("tags") or {}
            index = int(st.get("index"))
            language = str(tags.get("language") or "").strip()
            title = str(tags.get("title") or "").strip()
            codec = str(st.get("codec_name") or "").upper()
            channels = st.get("channels") or ""
            layout = str(st.get("channel_layout") or "").strip()
            spanish = es_espanol(language, title)
            parts = [f"0:{index}"]
            if language:
                parts.append(language)
            if codec:
                parts.append(codec)
            if channels:
                parts.append(f"{channels}ch")
            if title:
                parts.append(title)
            label = " - ".join(parts)
            streams.append({
                "index": index,
                "label": label,
                "language": language,
                "title": title,
                "codec": codec,
                "channels": channels,
                "layout": layout,
                "spanish": spanish,
            })
        if not streams:
            return {"ok": False, "error": "No encuentro pistas de audio en el archivo.", "streams": []}
        return {"ok": True, "streams": streams}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "streams": []}


def info_archivo(path):
    path = normalizar_ruta(path)
    error = validar_video(path)
    if error:
        return {"ok": False, "error": error}
    try:
        stat = os.stat(path)
        metadata = video_principal_metadata(path)
        duration = formato_duracion_segundos(metadata.get("duration"))
        if not duration:
            duration = duracion_archivo_legible(path)
        return {
            "ok": True,
            "path": path,
            "name": os.path.basename(path),
            "size": formato_size(stat.st_size),
            "duration": duration,
            "fps": metadata.get("fps", ""),
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def validar_video(path):
    if not ruta_permitida(path):
        return "Ruta no permitida. Usa Data o Media."
    if not os.path.isfile(path):
        return f"No existe el archivo: {path}"
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return f"Extension no soportada: {ext}"
    return ""


def validar_indice_audio(value, label):
    if value == "":
        return ""
    try:
        if int(value) < 0:
            return f"Pista no valida en {label}."
    except Exception:
        return f"Pista no valida en {label}."
    return ""


def es_espanol(language, title):
    haystack = f"{language} {title}".lower()
    if any(x in haystack for x in ("spanish", "espanol", "espa?ol", "castellano")):
        return True
    return bool(re.search(r"(^|[^a-z])(spa|es|esp|esl)([^a-z]|$)", haystack))


def memoria_compartida():
    data = leer_memoria()
    clean = {}
    salida = leer_config().get("carpeta_salida", ROOTS[0]["path"])
    for key, fallback in (
        ("ref_path", ROOTS[0]["path"]),
        ("esp_path", ROOTS[0]["path"]),
        ("output_path", salida),
    ):
        path = normalizar_ruta(data.get(key) or fallback)
        if not ruta_permitida(path) or not os.path.isdir(path):
            path = fallback if ruta_permitida(fallback) and os.path.isdir(fallback) else ROOTS[0]["path"]
        clean[key] = path
    return {"ok": True, "memory": clean}


def guardar_memoria_compartida(q):
    key_map = {"ref": "ref_path", "esp": "esp_path", "output": "output_path"}
    key = key_map.get(q.get("key", [""])[0])
    if not key:
        return {"ok": False, "error": "Memoria no valida."}
    path = normalizar_ruta(q.get("path", [""])[0])
    if not ruta_permitida(path) or not os.path.isdir(path):
        return {"ok": False, "error": "Carpeta no valida."}
    return {"ok": True, "memory": guardar_memoria(key, path)}


def leer_config():
    data = dict(DEFAULT_CONFIG)
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update({k: saved.get(k, v) for k, v in DEFAULT_CONFIG.items()})
    except Exception:
        pass
    if data.get("carpeta_salida") == QUEUE_MOVIES_PATH:
        data["carpeta_salida"] = COMPLETE_MOVIES_PATH
    return data


def guardar_config_desde_query(q):
    data = leer_config()
    data["modo"] = limpiar_opcion(q.get("modo", [data["modo"]])[0], {"medir", "exportar"}, data["modo"])
    data["perfil"] = limpiar_opcion(
        q.get("perfil", [data.get("perfil", DEFAULT_CONFIG["perfil"])])[0],
        {"pelicula", "trailer"},
        data.get("perfil", DEFAULT_CONFIG["perfil"]),
    )
    data["confianza_minima"] = "MEDIA"
    salida = normalizar_ruta(q.get("carpeta_salida", [data["carpeta_salida"]])[0])
    if not ruta_permitida(salida) or not os.path.isdir(salida):
        return {"ok": False, "error": "Carpeta de salida no valida.", "settings": data}
    data["carpeta_salida"] = salida
    data["sub_video_bueno"] = limpiar_texto(q.get("sub_video_bueno", [data["sub_video_bueno"]])[0], DEFAULT_CONFIG["sub_video_bueno"])
    data["sub_fuente_espanol"] = limpiar_texto(q.get("sub_fuente_espanol", [data["sub_fuente_espanol"]])[0], DEFAULT_CONFIG["sub_fuente_espanol"])
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "settings": data}


def limpiar_opcion(value, validos, fallback):
    return value if value in validos else fallback


def normalizar_delay_hint_ms(value):
    try:
        delay_ms = int(round(float(value or 0)))
    except Exception:
        delay_ms = 0
    return max(-120000, min(120000, delay_ms))


def limpiar_texto(value, fallback):
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    return text[:60] or fallback


def ruta_permitida(path):
    real = os.path.realpath(path)
    for root in ROOTS:
        base = os.path.realpath(root["path"])
        if real == base or real.startswith(base + os.sep):
            return True
    return False


def normalizar_ruta(path):
    return os.path.realpath(os.path.abspath(path or ""))


def leer_json(path):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def escribir_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ejecutar_mkvmerge_con_progreso(cmd, job):
    started_at = time.time()
    output_tail = []
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    deadline = time.time() + 21600
    last_percent = -1

    while True:
        if process.stdout is None:
            break
        if time.time() > deadline:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, 21600)
        if process.poll() is not None:
            tail = process.stdout.read()
            if tail:
                for line in tail.splitlines():
                    output_tail.append(line)
                    last_percent = procesar_linea_mkvmerge(line, job, last_percent)
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.5)
        if not readable:
            continue
        line = process.stdout.readline()
        if line:
            output_tail.append(line)
            last_percent = procesar_linea_mkvmerge(line, job, last_percent)

    returncode = process.wait()
    diagnostico_command(
        job,
        "mkvmerge",
        "mkvmerge",
        cmd,
        returncode,
        started_at,
        "\n".join(output_tail[-80:]),
        "",
        returncode in (0, 1),
    )
    return returncode


def procesar_linea_mkvmerge(line, job, last_percent):
    text = str(line or "").strip()
    if not text:
        return last_percent
    percent = extraer_porcentaje_mkvmerge(text)
    if percent is not None:
        if percent != last_percent:
            escribir_progreso(job, "export", percent, "Exportando")
        return percent
    log_job(job, text)
    return last_percent


def extraer_porcentaje_mkvmerge(text):
    for pattern in (r"#GUI#progress\s+([0-9]{1,3})\s*%?", r"Progress:\s*([0-9]{1,3})\s*%"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return max(0, min(100, int(match.group(1))))
    return None


def escribir_progreso(job, phase, percent, label=""):
    path = job.get("progress_path") or os.path.join(job["job_dir"], "progress.json")
    data = {
        "phase": phase,
        "percent": max(0, min(100, int(round(float(percent))))),
        "label": label,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, path)


def leer_progreso(job, status, rows, result):
    path = job.get("progress_path") or os.path.join(job["job_dir"], "progress.json")
    progress = leer_json(path)
    if isinstance(progress, dict) and "percent" in progress:
        return progress
    if status == "running":
        if (job.get("fps_correction") or {}).get("enabled") and not rows and not result:
            return {"phase": "fps", "percent": 0, "label": "FPS"}
        export_status = (result or {}).get("export", {}).get("status")
        if export_status == "running":
            return {"phase": "export", "percent": 0, "label": "Exportando"}
        return {"phase": "measure", "percent": min(95, len(rows) * 10), "label": "Midiendo"}
    if result and result.get("ok"):
        return {"phase": "done", "percent": 100, "label": "Listo"}
    if result and not result.get("ok"):
        return {"phase": "error", "percent": 100, "label": "Aviso"}
    return None


def log_job(job, text):
    with open(job["log_path"], "a", encoding="utf-8") as f:
        f.write(str(text).rstrip() + "\n")


def confianza_valida(confidence, minimum):
    order = {"BAJA": 1, "MEDIA": 2, "ALTA": 3}
    if minimum == "CUALQUIERA":
        return True
    return order.get(confidence, 0) >= order.get(minimum, 2)


def ruta_salida_unica(ref_file, output_dir):
    base = os.path.splitext(os.path.basename(ref_file))[0]
    candidate = os.path.join(output_dir, base + ".mkv")
    if not os.path.exists(candidate):
        return candidate
    for index in range(1, 1000):
        candidate = os.path.join(output_dir, f"{base} ({index}).mkv")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("No he podido crear un nombre de salida libre.")


def ruta_temporal_exportacion(output_path):
    directory = os.path.dirname(output_path)
    base = os.path.basename(output_path)
    for _ in range(20):
        candidate = os.path.join(directory, f".{base}.{uuid.uuid4().hex[:8]}.delay-audio-part")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("No he podido crear un temporal de exportacion libre.")


def publicar_exportacion_temporal(temp_output_path, output_path):
    if os.path.exists(output_path):
        raise RuntimeError("La salida final ya existe antes de publicar el temporal.")
    os.replace(temp_output_path, output_path)


def limpiar_archivo_silencioso(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def planificar_correccion_fps(ref, esp):
    ref_meta = video_principal_metadata(ref)
    esp_meta = video_principal_metadata(esp)
    ref_fps = float(ref_meta.get("fps_value") or 0.0)
    esp_fps = float(esp_meta.get("fps_value") or 0.0)
    if not ref_fps or not esp_fps:
        return {"enabled": False, "reason": "fps_no_detectado"}
    if abs(round(ref_fps, 3) - round(esp_fps, 3)) <= FPS_CORRECTION_THRESHOLD:
        return {
            "enabled": False,
            "reason": "fps_iguales",
            "ref_fps": round(ref_fps, 6),
            "esp_fps": round(esp_fps, 6),
        }
    tempo = ref_fps / esp_fps
    if not tempo or tempo <= 0:
        return {"enabled": False, "reason": "tempo_no_valido"}
    return {
        "enabled": True,
        "ref_fps": round(ref_fps, 6),
        "esp_fps": round(esp_fps, 6),
        "tempo": round(tempo, 9),
        "ref_label": formato_fps(ref_fps),
        "esp_label": formato_fps(esp_fps),
    }


def preparar_audio_fps_medicion(job, fps_correction, temp_cleanup_paths):
    tempo = float(fps_correction.get("tempo") or 0.0)
    if not tempo or tempo <= 0:
        raise RuntimeError("Correccion FPS no valida.")
    temp_audio_path = ruta_temporal_audio_fps(job)
    temp_cleanup_paths.append(temp_audio_path)
    source_duration = duracion_audio_stream(job["esp"], job["esp_audio"])
    if not source_duration or source_duration <= 0:
        source_duration = duracion_formato(job["esp"])
    target_duration = float(source_duration or 0.0) / tempo if tempo else 0.0

    log_job(job, f"FPS: corrigiendo audio espanol {fps_correction.get('esp_label')} -> {fps_correction.get('ref_label')}")
    log_job(job, f"FPS: factor atempo {tempo:.9f}")
    escribir_progreso(job, "fps", 0, "FPS")
    diagnostico_event(job, "fps_correction", "started", "Corrigiendo FPS del audio espanol", {
        "ref_fps": fps_correction.get("ref_fps"),
        "esp_fps": fps_correction.get("esp_fps"),
        "tempo": tempo,
        "source_duration": source_duration,
        "target_duration": target_duration,
    })

    filter_parts = atempo_filter_chain(tempo)
    filter_parts.append("aresample=async=1:first_pts=0")
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-i",
        job["esp"],
        "-map",
        f"0:{int(job['esp_audio'])}",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        ",".join(filter_parts),
        "-c:a",
        "ac3",
        "-b:a",
        "640k",
        "-progress",
        "pipe:1",
        "-nostats",
        temp_audio_path,
    ]
    started_at = time.time()
    returncode, output_tail = ejecutar_ffmpeg_fps_con_progreso(cmd, job, target_duration)
    diagnostico_command(job, "fps_correction", "ffmpeg_fps_audio", cmd, returncode, started_at, output_tail, "", returncode == 0)
    if returncode != 0:
        raise RuntimeError((output_tail or "ffmpeg fallo corrigiendo FPS del audio").strip()[-500:])
    if not os.path.isfile(temp_audio_path) or os.path.getsize(temp_audio_path) <= 4096:
        raise RuntimeError("El audio corregido por FPS esta vacio.")
    first_packet_ms = primer_packet_audio_ms(temp_audio_path, "a:0")
    if first_packet_ms is None:
        raise RuntimeError("No he podido validar el audio corregido por FPS.")
    if first_packet_ms > AUDIO_FINAL_MAX_FIRST_PACKET_MS:
        raise RuntimeError(f"Audio FPS no valido: empieza en {first_packet_ms:.0f} ms.")
    validar_duracion_audio_fps(temp_audio_path, target_duration)
    escribir_progreso(job, "fps", 100, "FPS")
    job["fps_audio_path"] = temp_audio_path
    job["fps_audio_index"] = 0
    job["esp_measure_path"] = temp_audio_path
    job["esp_measure_audio"] = 0
    diagnostico_event(job, "fps_correction", "finished", "Audio FPS preparado", {
        "path": temp_audio_path,
        "tempo": tempo,
    })


def ruta_temporal_audio_fps(job):
    directory = os.path.join(job["job_dir"], "fps")
    os.makedirs(directory, exist_ok=True)
    for _ in range(20):
        candidate = os.path.join(directory, f"audio_espanol_fps_{uuid.uuid4().hex[:8]}.mka")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("No he podido crear un temporal de FPS libre.")


def atempo_filter_chain(tempo):
    value = float(tempo)
    parts = []
    while value < 0.5:
        parts.append("atempo=0.5")
        value /= 0.5
    while value > 2.0:
        parts.append("atempo=2.0")
        value /= 2.0
    parts.append(f"atempo={value:.9f}")
    return parts


def ejecutar_ffmpeg_fps_con_progreso(cmd, job, target_duration):
    output_tail = []
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    deadline = time.time() + 21600
    last_percent = -1
    while True:
        if process.stdout is None:
            break
        if time.time() > deadline:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, 21600)
        if process.poll() is not None:
            tail = process.stdout.read()
            if tail:
                for line in tail.splitlines():
                    output_tail.append(line)
                    last_percent = procesar_linea_ffmpeg_fps(line, job, last_percent, target_duration)
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.5)
        if not readable:
            continue
        line = process.stdout.readline()
        if line:
            output_tail.append(line)
            last_percent = procesar_linea_ffmpeg_fps(line, job, last_percent, target_duration)
    returncode = process.wait()
    if returncode == 0:
        escribir_progreso(job, "fps", 100, "FPS")
    return returncode, "\n".join(output_tail[-80:])


def procesar_linea_ffmpeg_fps(line, job, last_percent, target_duration):
    text = str(line or "").strip()
    if not text:
        return last_percent
    if "=" not in text:
        log_job(job, text)
        return last_percent
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    seconds = None
    if key in {"out_time_ms", "out_time_us"}:
        try:
            seconds = float(value) / 1000000.0
        except Exception:
            seconds = None
    elif key == "out_time":
        seconds = parse_duration_value(value)
    elif key == "progress" and value == "end":
        escribir_progreso(job, "fps", 100, "FPS")
        return 100
    if seconds is None or not target_duration or target_duration <= 0:
        return last_percent
    percent = max(0, min(100, int(round((seconds / float(target_duration)) * 100))))
    if percent != last_percent:
        escribir_progreso(job, "fps", percent, "FPS")
    return percent


def validar_duracion_audio_fps(temp_audio_path, target_duration):
    if not target_duration or target_duration <= 0:
        return
    audio_duration = duracion_audio_stream(temp_audio_path, "a:0")
    if not audio_duration or audio_duration <= 0:
        raise RuntimeError("No he podido validar la duracion del audio FPS.")
    tolerance = max(2.0, min(15.0, float(target_duration) * 0.01))
    if abs(float(audio_duration) - float(target_duration)) > tolerance:
        raise RuntimeError(
            f"Audio FPS no valido: esperado {target_duration:.3f}s, generado {audio_duration:.3f}s."
        )


def anexar_correccion_fps_resultado(job):
    fps_correction = job.get("fps_correction") or {}
    if not fps_correction.get("enabled"):
        return
    result = leer_json(job["result_path"]) or {}
    if not isinstance(result, dict) or not result.get("ok"):
        return
    result["fps_correction"] = {
        "enabled": True,
        "ref_fps": fps_correction.get("ref_fps"),
        "esp_fps": fps_correction.get("esp_fps"),
        "tempo": fps_correction.get("tempo"),
    }
    escribir_json(job["result_path"], result)


def preparar_audio_espanol_exportacion(job, audio_track_id, delay_ms, video_duration, temp_cleanup_paths, source_path=None, source_audio=None):
    source_path = source_path or job["esp"]
    source_audio = job.get("esp_audio") if source_audio is None else source_audio
    first_packet_ms = primer_packet_audio_ms(source_path, source_audio)
    if first_packet_ms is None:
        raise RuntimeError("No he podido leer el primer paquete de audio espanol.")

    log_job(job, f"EXPORTACION: primer paquete audio espanol {first_packet_ms:.0f} ms")
    duration_master = bool(video_duration and video_duration > 0)
    needs_normalize = (
        first_packet_ms > AUDIO_NORMALIZE_THRESHOLD_MS
        or delay_ms > AUDIO_NORMALIZE_THRESHOLD_MS
        or delay_ms < -AUDIO_NORMALIZE_THRESHOLD_MS
        or duration_master
    )
    if not needs_normalize:
        return {
            "path": source_path,
            "track_id": audio_track_id,
            "sync_ms": delay_ms,
            "normalized": False,
            "normalized_reason": "",
            "log": "EXPORTACION: usando mkvmerge sin reconvertir audio",
        }

    reason = []
    if first_packet_ms > AUDIO_NORMALIZE_THRESHOLD_MS:
        reason.append(f"timestamp inicial {first_packet_ms:.0f} ms")
    if delay_ms > AUDIO_NORMALIZE_THRESHOLD_MS:
        reason.append(f"delay positivo {delay_ms} ms")
    elif delay_ms < -AUDIO_NORMALIZE_THRESHOLD_MS:
        reason.append(f"delay negativo {delay_ms} ms")
    if duration_master:
        reason.append("ajuste a duracion del video")
    reason_text = ", ".join(reason)

    escribir_progreso(job, "export", 1, "Preparando audio")
    temp_audio_path = ruta_temporal_audio(job)
    temp_cleanup_paths.append(temp_audio_path)
    crear_audio_espanol_normalizado(job, temp_audio_path, delay_ms, video_duration, source_path=source_path, source_audio=source_audio)
    first_normalized_ms = primer_packet_audio_ms(temp_audio_path, "a:0")
    if first_normalized_ms is None:
        raise RuntimeError("No he podido validar el audio normalizado.")
    if first_normalized_ms > AUDIO_FINAL_MAX_FIRST_PACKET_MS:
        raise RuntimeError(f"Audio normalizado no valido: empieza en {first_normalized_ms:.0f} ms.")
    validar_duracion_audio_normalizado(temp_audio_path, video_duration)

    return {
        "path": temp_audio_path,
        "track_id": mkvmerge_track_id_for_ffprobe_index(temp_audio_path, 0, "audio"),
        "sync_ms": 0,
        "normalized": True,
        "normalized_reason": reason_text,
        "log": "EXPORTACION: usando audio temporal normalizado",
    }


def ruta_temporal_audio(job):
    directory = os.path.join(job["job_dir"], "tmp")
    os.makedirs(directory, exist_ok=True)
    for _ in range(20):
        candidate = os.path.join(directory, f"audio_espanol_normalizado_{uuid.uuid4().hex[:8]}.mka")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("No he podido crear un temporal de audio libre.")


def crear_audio_espanol_normalizado(job, temp_audio_path, delay_ms, video_duration, source_path=None, source_audio=None):
    source_path = source_path or job["esp"]
    source_audio = job.get("esp_audio") if source_audio is None else source_audio
    filter_parts = ["aresample=async=1:first_pts=0"]
    if delay_ms > AUDIO_NORMALIZE_THRESHOLD_MS:
        filter_parts.append(f"adelay={delay_ms}:all=1")
    elif delay_ms < -AUDIO_NORMALIZE_THRESHOLD_MS:
        filter_parts.extend([f"atrim=start={abs(delay_ms) / 1000.0:.3f}", "asetpts=PTS-STARTPTS"])
    if video_duration and video_duration > 0:
        filter_parts.extend(["apad", f"atrim=0:{float(video_duration):.3f}", "asetpts=PTS-STARTPTS"])

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-i",
        source_path,
        "-map",
        f"0:{int(source_audio)}",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        ",".join(filter_parts),
        "-c:a",
        "ac3",
        "-b:a",
        "640k",
        temp_audio_path,
    ]
    log_job(job, "EXPORTACION: creando audio temporal con silencio real desde 0 hasta el final")
    started_at = time.time()
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=21600,
    )
    diagnostico_command(job, "normalize_audio", "ffmpeg_normalize_audio", cmd, p.returncode, started_at, p.stdout, p.stderr, p.returncode == 0)
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "ffmpeg no pudo normalizar el audio").strip()
        raise RuntimeError(detail[:500])
    if not os.path.isfile(temp_audio_path) or os.path.getsize(temp_audio_path) <= 4096:
        raise RuntimeError("El audio temporal normalizado esta vacio.")


def validar_duracion_audio_normalizado(temp_audio_path, video_duration):
    if not video_duration or video_duration <= 0:
        return
    audio_duration = duracion_audio_stream(temp_audio_path, "a:0")
    if not audio_duration or audio_duration <= 0:
        raise RuntimeError("No he podido validar la duracion del audio normalizado.")
    diff = abs(float(audio_duration) - float(video_duration))
    if diff > AUDIO_DURATION_TOLERANCE_SEC:
        raise RuntimeError(
            f"Audio normalizado no valido: video {video_duration:.3f}s, audio {audio_duration:.3f}s."
        )


def primer_packet_audio_ms(path, selector):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            str(selector),
            "-show_packets",
            "-read_intervals",
            "%+10",
            "-show_entries",
            "packet=pts_time,dts_time",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=120,
    )
    if p.returncode != 0:
        return None
    try:
        packets = json.loads(p.stdout or "{}").get("packets") or []
    except Exception:
        return None
    values = []
    for packet in packets:
        for key in ("pts_time", "dts_time"):
            try:
                values.append(float(packet.get(key)))
            except Exception:
                pass
    if not values:
        return None
    return max(0.0, min(values) * 1000.0)


def ffprobe_streams(path, selector):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            selector,
            "-show_entries",
            "stream=index:stream_tags=language,title",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        return []
    try:
        return (json.loads(p.stdout or "{}").get("streams") or [])
    except Exception:
        return []


def ffprobe_streams_todos(path):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type:stream_tags=language,title",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        return []
    try:
        return (json.loads(p.stdout or "{}").get("streams") or [])
    except Exception:
        return []


def mkvmerge_identify(path):
    p = subprocess.run(
        ["mkvmerge", "-J", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError("mkvmerge no pudo leer las pistas del archivo.")
    try:
        return json.loads(p.stdout or "{}")
    except Exception as exc:
        raise RuntimeError("mkvmerge no devolvio informacion valida de pistas.") from exc


def mkvmerge_track_id_for_ffprobe_index(path, ffprobe_index, codec_type):
    try:
        ffprobe_index = int(ffprobe_index)
    except Exception as exc:
        raise RuntimeError("Pista de audio espanol no valida para exportar.") from exc

    type_map = {"audio": "audio", "video": "video", "subtitle": "subtitles"}
    mkv_type = type_map.get(codec_type, codec_type)
    data = mkvmerge_identify(path)
    tracks = [t for t in data.get("tracks") or [] if t.get("type") == mkv_type]

    for track in tracks:
        try:
            if int(track.get("id")) == ffprobe_index:
                return int(track.get("id"))
        except Exception:
            pass

    streams = [s for s in ffprobe_streams_todos(path) if s.get("codec_type") == codec_type]
    position = None
    for idx, stream in enumerate(streams):
        try:
            if int(stream.get("index")) == ffprobe_index:
                position = idx
                break
        except Exception:
            pass
    if position is not None and position < len(tracks):
        return int(tracks[position].get("id"))

    raise RuntimeError("No he podido relacionar la pista elegida con mkvmerge.")


def mkvmerge_metadata_subtitulos(path, origen):
    out = []
    data = mkvmerge_identify(path)
    origen = limpiar_texto_mkv(origen)
    for track in data.get("tracks") or []:
        if track.get("type") != "subtitles":
            continue
        track_id = track.get("id")
        if track_id is None:
            continue
        properties = track.get("properties") or {}
        original = limpiar_texto_mkv(properties.get("track_name") or "")
        title = f"{original} ? {origen}" if original else origen
        out.extend(["--track-name", f"{track_id}:{title}"])
    return out


def mkvmerge_track_ids(path, track_type):
    data = mkvmerge_identify(path)
    ids = []
    for track in data.get("tracks") or []:
        if track.get("type") != track_type:
            continue
        track_id = track.get("id")
        if track_id is None:
            continue
        ids.append(int(track_id))
    return ids


def mkvmerge_sync_tracks(track_ids, delay_ms):
    out = []
    for track_id in track_ids:
        out.extend(["--sync", f"{track_id}:{delay_ms}"])
    return out


def limpiar_texto_mkv(value):
    text = str(value or "").strip()
    return re.sub(r"[\r\n\t]+", " ", text)[:120]


def validar_mkv_exportado(path, video_duration):
    if not os.path.isfile(path):
        raise RuntimeError("No se genero el MKV final.")
    if os.path.getsize(path) <= 4096:
        raise RuntimeError("El MKV final esta vacio o incompleto.")

    data = mkvmerge_identify(path)
    tracks = data.get("tracks") or []
    if not any(track.get("type") == "video" for track in tracks):
        raise RuntimeError("El MKV final no tiene pista de video.")
    if not any(track.get("type") == "audio" for track in tracks):
        raise RuntimeError("El MKV final no tiene pista de audio.")

    final_duration = duracion_formato(path)
    if not final_duration or final_duration <= 0:
        raise RuntimeError("No he podido leer la duracion del MKV final.")
    tolerance = max(5.0, min(20.0, float(video_duration or 0) * 0.002))
    if video_duration and abs(final_duration - float(video_duration)) > tolerance:
        raise RuntimeError(
            f"Duracion final no valida: video {video_duration:.3f}s, final {final_duration:.3f}s."
        )
    first_audio_ms = primer_packet_audio_ms(path, "a:0")
    if first_audio_ms is None:
        raise RuntimeError("No he podido validar el primer paquete de audio final.")
    if first_audio_ms > AUDIO_FINAL_MAX_FIRST_PACKET_MS:
        raise RuntimeError(f"Audio final no compatible: empieza en {first_audio_ms:.0f} ms.")

    validar_mkv_demux(path, final_duration)
    return True


def validar_mkv_demux(path, duration):
    starts = [0.0]
    if duration and duration > 45:
        starts.append(max(0.0, float(duration) - 20.0))
    for start in starts:
        cmd = ["ffmpeg", "-v", "error"]
        if start > 0:
            cmd.extend(["-ss", f"{start:.3f}"])
        cmd.extend([
            "-t",
            "8",
            "-i",
            path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-f",
            "null",
            "-",
        ])
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=120,
        )
        if p.returncode != 0:
            detail = (p.stderr or p.stdout or "ffmpeg no pudo verificar el MKV final").strip()
            raise RuntimeError(detail[:500])


def duracion_archivo_legible(path):
    duration = 0.0
    try:
        duration = duracion_video_principal(path)
    except Exception:
        duration = duracion_formato(path)
    return formato_duracion_segundos(duration)


def formato_duracion_segundos(duration):
    if not duration or duration <= 0:
        return ""
    total = int(round(duration))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def video_principal_metadata(path):
    result = {"duration": 0.0, "fps": "", "fps_value": 0.0}
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,avg_frame_rate,r_frame_rate:stream_tags=DURATION",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        return result
    try:
        streams = json.loads(p.stdout or "{}").get("streams") or []
    except Exception:
        return result
    if not streams:
        return result
    stream = streams[0]
    duration = parse_duration_value(stream.get("duration"))
    if not duration:
        duration = parse_duration_value((stream.get("tags") or {}).get("DURATION"))
    fps = parse_frame_rate_value(stream.get("avg_frame_rate"))
    if not fps:
        fps = parse_frame_rate_value(stream.get("r_frame_rate"))
    result["duration"] = float(duration or 0.0)
    result["fps_value"] = float(fps or 0.0)
    result["fps"] = formato_fps(fps)
    return result


def parse_frame_rate_value(value):
    text = str(value or "").strip()
    if not text or text == "0/0":
        return 0.0
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator = float(denominator)
            if denominator == 0:
                return 0.0
            return float(numerator) / denominator
        return float(text)
    except Exception:
        return 0.0


def formato_fps(value):
    if not value or value <= 0:
        return ""
    return f"{float(value):.3f} fps"


def duracion_video_principal(path):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration:stream_tags=DURATION",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError("No he podido leer la duracion del video bueno.")
    try:
        streams = json.loads(p.stdout or "{}").get("streams") or []
    except Exception as exc:
        raise RuntimeError("ffprobe no devolvio duracion valida del video bueno.") from exc
    if not streams:
        raise RuntimeError("El video bueno no tiene pista de video.")
    stream = streams[0]
    duration = parse_duration_value(stream.get("duration"))
    if not duration:
        duration = parse_duration_value((stream.get("tags") or {}).get("DURATION"))
    if not duration or duration <= 0:
        duration = duracion_formato(path)
    if not duration or duration <= 0:
        raise RuntimeError("No he podido calcular la duracion maestra del video bueno.")
    return float(duration)


def duracion_formato(path):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        return 0.0
    return parse_duration_value((p.stdout or "").strip())


def duracion_audio_stream(path, selector):
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            str(selector),
            "-show_entries",
            "stream=duration:stream_tags=DURATION",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=60,
    )
    if p.returncode != 0:
        return 0.0
    try:
        streams = json.loads(p.stdout or "{}").get("streams") or []
    except Exception:
        return 0.0
    if not streams:
        return 0.0
    stream = streams[0]
    duration = parse_duration_value(stream.get("duration"))
    if not duration:
        duration = parse_duration_value((stream.get("tags") or {}).get("DURATION"))
    if not duration:
        duration = duracion_formato(path)
    return float(duration or 0.0)


def parse_duration_value(value):
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    if re.match(r"^[0-9]+(\.[0-9]+)?$", text):
        return float(text)
    match = re.match(r"^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)$", text)
    if not match:
        return 0.0
    return (int(match.group(1)) * 3600.0) + (int(match.group(2)) * 60.0) + float(match.group(3))


def contar_subtitulos(path):
    return len(ffprobe_streams(path, "s"))


def metadata_subtitulos(path, offset, origen):
    out = []
    for idx, stream in enumerate(ffprobe_streams(path, "s")):
        tags = stream.get("tags") or {}
        original = str(tags.get("title") or "").strip()
        title = f"{original} ? {origen}" if original else origen
        out.extend([f"-metadata:s:s:{offset + idx}", f"title={title}"])
    return out


def leer_tail(path, max_bytes=24000):
    try:
        if not os.path.isfile(path):
            return ""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def leer_csv(path):
    rows = []
    try:
        if not os.path.isfile(path):
            return rows
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split(";")
                if len(parts) >= 8:
                    rows.append({
                        "zona": parts[0],
                        "inicio": parts[2],
                        "delay": parts[3],
                        "puntuacion": parts[4],
                        "confianza": parts[5],
                        "pista_video": parts[6],
                        "pista_espanol": parts[7],
                    })
    except Exception:
        pass
    return rows


def formato_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"
