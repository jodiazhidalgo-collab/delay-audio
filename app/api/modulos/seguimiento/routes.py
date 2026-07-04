import http.client
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from api.modulos.diagnostico.blackbox import (
    attach as diag_attach,
    classify_error as diag_classify_error,
    event as diag_event_raw,
    finish_job as diag_finish_job_raw,
    init_job as diag_init_job_raw,
    record_command as diag_record_command_raw,
    record_error as diag_record_error_raw,
)

MEDIA_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".m2ts",
    ".ts",
    ".mov",
    ".wmv",
}
TEMP_SIZE_EXTENSIONS = {".delay-audio-part", ".tmp"}

ARR_WORKER_CONTAINERS = ("arr-orchestrator",)
DOCKER_SOCKET = "/var/run/docker.sock"
TRAILER_TRACKS_MOTOR = "/motor/delay_audio/eliminar_trailer_pistas.py"
TRAILER_JOB_ROOT = "/logs/seguimiento_trailer_jobs"
TRAILER_JOBS_LOCK = threading.Lock()
TRAILER_JOBS = {}
ARR_READ_BASE_URL = os.environ.get("ARR_READ_BASE_URL", "http://buscador-puente-arr:9003").rstrip("/")
ARR_READ_CACHE_TTL_SEC = int(os.environ.get("ARR_READ_CACHE_TTL_SEC", "5"))
ARR_READ_TIMEOUT_SEC = float(os.environ.get("ARR_READ_TIMEOUT_SEC", "3"))
ARR_READ_CACHE_LOCK = threading.Lock()
ARR_READ_CACHE = {"ts": 0.0, "data": None}
LOG_ERROR_LOCK = threading.Lock()
LOG_ERROR_STATE = {}
LOG_ERROR_SUMMARY_COUNTS = {2, 10, 50, 100, 250, 500, 1000}
BTDIGG_RD_TRACKING_FILE = os.environ.get("BTDIGG_RD_TRACKING_FILE", "/btdigg-rd-data/seguimiento_actual.json")
BTDIGG_RD_TIMEOUT_SEC = float(os.environ.get("BTDIGG_RD_TIMEOUT_SEC", "4"))
BTDIGG_RD_RECENT_VISIBLE_SEC = int(os.environ.get("BTDIGG_RD_RECENT_VISIBLE_SEC", "180"))
RDT_BASE_URL = os.environ.get("RDT_BASE", "http://rdtclient:6500").rstrip("/")
RDT_USER = os.environ.get("RDT_USER", "admin")
RDT_PASS = os.environ.get("RDT_PASS", "")
QBIT_BASE_URL = os.environ.get("QBIT_BASE_URL", "http://qbittorrent:8080").rstrip("/")
QBIT_USER = os.environ.get("QBIT_USER", "admin")
QBIT_PASS = os.environ.get("QBIT_PASS", "CAMBIAR_EN_ENTORNO_REAL")
QBIT_CACHE_TTL_SEC = int(os.environ.get("QBIT_CACHE_TTL_SEC", "5"))
QBIT_TIMEOUT_SEC = float(os.environ.get("QBIT_TIMEOUT_SEC", "4"))
QBIT_CACHE_LOCK = threading.Lock()
QBIT_CACHE = {"ts": 0.0, "data": None}
SEARCHABLE_MEDIA_FOLDERS = {"media_movies", "media_tv"}
MEDIA_MOVE_ROOT = Path(os.environ.get("MEDIA_MOVE_ROOT", "/data/media")).resolve()
MOVE_DESTINATIONS = {
    "move_movies": {
        "label": "Movies",
        "path": "/data/media/movies",
    },
    "move_tv": {
        "label": "TV",
        "path": "/data/media/tv",
    },
    "move_infantiles": {
        "label": "Infantiles",
        "path": "/data/media/infantiles",
    },
    "move_movies_automatizacion": {
        "label": "Movies Automatizacion",
        "path": "/data/downloads/torrents/complete/movies_automatizacion",
    },
    "move_complete": {
        "label": "Complete Movies",
        "path": "/data/downloads/torrents/complete/movies",
    },
    "move_queue": {
        "label": "Queue Movies",
        "path": "/data/downloads/torrents/queue/movies",
    },
    "move_repetidas_error": {
        "label": "Repetidas / Error",
        "path": "/data/media/repetidas_vs_error",
    },
    "move_hospital": {
        "label": "Hospital",
        "path": "/data/media/Hospital",
    },
}

FOLDER_BY_ID = {
    "complete_movies": {
        "id": "complete_movies",
        "name": "Complete Movies",
        "path": "/data/downloads/torrents/complete/movies",
        "real_path": "/data/downloads/torrents/complete/movies",
        "lazy_children": True,
    },
    "queue_movies": {
        "id": "queue_movies",
        "name": "Queue Movies",
        "path": "/data/downloads/torrents/queue/movies",
        "real_path": "/data/downloads/torrents/queue/movies",
        "lazy_children": True,
    },
    "movies_automatizacion": {
        "id": "movies_automatizacion",
        "name": "Movies Automatizacion",
        "path": "/data/downloads/torrents/complete/movies_automatizacion",
        "real_path": "/data/downloads/torrents/complete/movies_automatizacion",
        "lazy_children": True,
    },
    "complete_taller": {
        "id": "complete_taller",
        "name": "Taller",
        "path": "/data/downloads/torrents/complete/taller",
        "real_path": "/data/downloads/torrents/complete/taller",
        "flat_files": True,
        "lazy_children": True,
        "limit": 0,
    },
    "media_movies": {
        "id": "media_movies",
        "name": "Media Movies",
        "path": "/data/media/movies",
        "real_path": "/data/media/movies",
        "lazy_children": True,
    },
    "media_movies_trailer": {
        "id": "media_movies_trailer",
        "name": "Media Movies",
        "path": "/data/media/movies",
        "real_path": "/data/media/movies",
        "nested": True,
        "limit": 20,
        "child_prefix": "trailer",
    },
    "hospital": {
        "id": "hospital",
        "name": "Hospital",
        "path": "/data/media/Hospital",
        "real_path": "/data/media/Hospital",
        "lazy_children": True,
        "limit": 0,
    },
    "complete_tv": {
        "id": "complete_tv",
        "name": "Complete TV",
        "path": "/data/downloads/torrents/complete/tv",
        "real_path": "/data/downloads/torrents/complete/tv",
        "lazy_children": True,
    },
    "queue_tv": {
        "id": "queue_tv",
        "name": "Queue TV",
        "path": "/data/downloads/torrents/queue/tv",
        "real_path": "/data/downloads/torrents/queue/tv",
        "lazy_children": True,
    },
    "media_tv": {
        "id": "media_tv",
        "name": "Media TV",
        "path": "/data/media/tv",
        "real_path": "/data/media/tv",
        "lazy_children": True,
    },
    "trailers": {
        "id": "trailers",
        "name": "Movies Automatizacion Trailer",
        "path": "/data/downloads/torrents/complete/trailers_automatizacion",
        "real_path": "/data/downloads/torrents/complete/trailers_automatizacion",
        "nested": True,
        "limit": 20,
        "child_limit": 0,
        "child_include_dirs": True,
    },
    "repetidas_error": {
        "id": "repetidas_error",
        "name": "Repetidas / Error",
        "path": "/data/media/repetidas_vs_error",
        "real_path": "/data/media/repetidas_vs_error",
        "lazy_children": True,
        "limit": 0,
    },
}

SECTIONS = [
    {
        "id": "movies",
        "label": "Movies",
        "folder_ids": [
            "complete_movies",
            "movies_automatizacion",
            "complete_taller",
            "media_movies",
            "repetidas_error",
            "hospital",
        ],
    },
    {
        "id": "tv",
        "label": "TV",
        "folder_ids": [
            "complete_tv",
            "complete_taller",
            "media_tv",
            "repetidas_error",
        ],
    },
    {
        "id": "trailers",
        "label": "Trailer",
        "folder_ids": ["trailers", "media_movies_trailer"],
    },
    {
        "id": "taller",
        "label": "Taller",
        "folder_ids": [],
    },
]


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


def diagnostico_finish(job, status, result=None):
    try:
        diag_finish_job_raw(job, status, result or {})
    except Exception:
        pass


def write_log_error_line(message):
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("/logs/seguimiento_base.log", "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def write_log_error_state():
    try:
        payload = {
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "items": LOG_ERROR_STATE,
        }
        with open("/logs/seguimiento_base_repetidos.json", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log_error(message):
    text = str(message or "").strip()
    if not text:
        return
    now = time.time()
    should_write = False
    with LOG_ERROR_LOCK:
        item = LOG_ERROR_STATE.get(text)
        if not item:
            LOG_ERROR_STATE[text] = {
                "count": 1,
                "first_ts": now,
                "last_ts": now,
                "first_at": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
                "last_at": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            }
            write_log_error_line(text)
            write_log_error_state()
            return
        item["count"] += 1
        item["last_ts"] = now
        item["last_at"] = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
        count = int(item["count"])
        should_write = count in LOG_ERROR_SUMMARY_COUNTS or count % 1000 == 0
        first_at = item["first_at"]
        last_at = item["last_at"]
        write_log_error_state()
    if should_write:
        write_log_error_line(f"REPETIDO {count} veces entre {first_at} y {last_at}: {text}")


class DockerSocketConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


def docker_request(method, path):
    if not os.path.exists(DOCKER_SOCKET):
        raise RuntimeError("Docker no esta disponible para Delay Audio")
    conn = DockerSocketConnection(DOCKER_SOCKET)
    try:
        conn.request(method, path)
        res = conn.getresponse()
        raw = res.read()
        text = raw.decode("utf-8", errors="replace")
        payload = json.loads(text) if text.strip() else {}
        return res.status, payload, text
    finally:
        conn.close()


def docker_container_state(name):
    status, payload, _ = docker_request("GET", f"/containers/{quote(name, safe='')}/json")
    if status == 404:
        raise RuntimeError(f"No encuentro el contenedor {name}")
    if status >= 400:
        raise RuntimeError(f"Docker devolvio HTTP {status}")
    state = payload.get("State") or {}
    return {
        "name": name,
        "running": bool(state.get("Running")),
        "status": str(state.get("Status") or ""),
    }


def arr_workers_status():
    try:
        containers = [docker_container_state(name) for name in ARR_WORKER_CONTAINERS]
        running_count = sum(1 for item in containers if item["running"])
        if running_count == len(containers):
            state = "on"
        elif running_count == 0:
            state = "off"
        else:
            state = "mixed"
        return {
            "ok": True,
            "enabled": running_count == len(containers),
            "state": state,
            "containers": containers,
        }
    except Exception as exc:
        log_error(f"Control ARR no disponible: {exc}")
        return {"ok": False, "enabled": False, "state": "error", "containers": [], "error": str(exc)}


def set_arr_workers(q):
    desired = str(q.get("enabled", [""])[0]).strip().lower() in {"1", "true", "on", "si", "sí"}
    order = ARR_WORKER_CONTAINERS if desired else tuple(reversed(ARR_WORKER_CONTAINERS))
    action = "start" if desired else "stop"
    try:
        for name in order:
            status, _, text = docker_request("POST", f"/containers/{quote(name, safe='')}/{action}")
            if status not in (204, 304):
                raise RuntimeError(f"{name}: Docker HTTP {status} {text}".strip())
        status_data = arr_workers_status()
        if not status_data.get("ok"):
            return {"ok": False, "error": status_data.get("error", "No se pudo leer el estado"), "arr_workers": status_data}
        return {"ok": True, "arr_workers": status_data}
    except Exception as exc:
        log_error(f"No se pudo cambiar control ARR: {exc}")
        return {"ok": False, "error": str(exc), "arr_workers": arr_workers_status()}


def empty_arr_status(error=None):
    return {
        "ok": True,
        "source": "arr-readonly",
        "stale": True,
        "updated_at": None,
        "monitoring": 0,
        "counts": {
            "total": 0,
            "downloading": 0,
            "waiting": 0,
            "stalled": 0,
            "error": 0,
            "finished": 0,
        },
        "items": [],
        "error": error or "",
    }


def arr_read_json(path):
    url = f"{ARR_READ_BASE_URL}{path}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=ARR_READ_TIMEOUT_SEC) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def arr_item_state(item):
    status = str(item.get("last_status") or "").lower()
    try:
        progress = float(item.get("last_progress") or 0)
    except (TypeError, ValueError):
        progress = 0

    if item.get("finished_seen_ts") or progress >= 100 or any(word in status for word in ("finished", "downloaded", "completed")):
        return "finished", "Terminado"
    if any(word in status for word in ("infringing", "error", "failed", "fallo", "could not add")):
        return "error", "Error"
    if "stalled" in status:
        return "stalled", "Parado"
    if "downloading" in status or progress > 0:
        return "downloading", "Descargando"
    return "waiting", "Esperando"


def clean_arr_item(item):
    state, label = arr_item_state(item)
    try:
        progress = float(item.get("last_progress") or 0)
    except (TypeError, ValueError):
        progress = 0
    return {
        "title": str(item.get("title") or "Sin titulo"),
        "category": str(item.get("category") or ""),
        "kind": str(item.get("kind") or ""),
        "progress": max(0, min(100, progress)),
        "status": str(item.get("last_status") or ""),
        "state": state,
        "state_label": label,
        "first_seen": item.get("first_seen"),
        "last_progress_ts": item.get("last_progress_ts"),
        "finished_seen_ts": item.get("finished_seen_ts"),
    }


def build_arr_status(raw):
    items = [clean_arr_item(item) for item in raw.get("items", []) if isinstance(item, dict)]
    counts = {
        "total": len(items),
        "downloading": 0,
        "waiting": 0,
        "stalled": 0,
        "error": 0,
        "finished": 0,
    }
    for item in items:
        if item["state"] in counts:
            counts[item["state"]] += 1

    return {
        "ok": bool(raw.get("ok", True)),
        "source": "arr-readonly",
        "stale": False,
        "updated_at": datetime.now(timezone.utc).timestamp(),
        "monitoring": int(raw.get("monitoring") or len(items)),
        "counts": counts,
        "items": items[:20],
        "error": "",
    }


def normalize_bt_hash(value):
    text = str(value or "").strip().lower()
    if len(text) == 40 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return ""


def btdigg_rd_read_tracking():
    path = Path(BTDIGG_RD_TRACKING_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError) as exc:
        log_error(f"No se pudo leer seguimiento BTDigg RD: {exc}")
        return []
    return data if isinstance(data, list) else []


def btdigg_rd_tracking_index():
    by_rdt_id = {}
    by_hash = {}
    for record in btdigg_rd_read_tracking():
        if not isinstance(record, dict):
            continue
        destino = str(record.get("destino") or "").strip().lower()
        if destino not in {"movies", "tv"}:
            continue
        rdt_id = str(record.get("rdt_id") or "").strip()
        torrent_hash = normalize_bt_hash(record.get("hash"))
        if not rdt_id and not torrent_hash:
            continue
        if rdt_id and rdt_id not in by_rdt_id:
            by_rdt_id[rdt_id] = record
        if torrent_hash and torrent_hash not in by_hash:
            by_hash[torrent_hash] = record
    return by_rdt_id, by_hash


def rdt_native_login_opener():
    if not RDT_PASS:
        raise RuntimeError("RDT_PASS no configurado")
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    payload = json.dumps({"userName": RDT_USER, "password": RDT_PASS}).encode("utf-8")
    req = Request(
        f"{RDT_BASE_URL}/Api/Authentication/Login",
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=BTDIGG_RD_TIMEOUT_SEC) as response:
        text = response.read().decode("utf-8", errors="replace").strip()
        if response.status >= 400:
            raise RuntimeError(f"RDT login HTTP {response.status}")
        if text and text not in {"Ok.", "Ok"}:
            raise RuntimeError(f"RDT login: {text[:120]}")
    return opener


def rdt_native_rows():
    opener = rdt_native_login_opener()
    req = Request(f"{RDT_BASE_URL}/Api/Torrents", headers={"Accept": "application/json"})
    with opener.open(req, timeout=BTDIGG_RD_TIMEOUT_SEC) as response:
        data = json.loads(response.read().decode("utf-8") or "[]")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("items", "torrents", "data", "results"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def rdt_row_id(row):
    for key in ("torrentId", "id", "Id", "torrent_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def rdt_row_hash(row):
    for key in ("hash", "hashString", "infoHash", "info_hash", "rdHash"):
        value = normalize_bt_hash(row.get(key))
        if value:
            return value
    return ""


def rdt_row_status(row):
    for key in ("statusText", "status", "Status", "rdStatusRaw", "rdStatus", "error", "errorMessage"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def rdt_row_title(row, record):
    for source in (record, row):
        for key in ("title", "name", "fileName", "filename", "downloadName", "torrentName"):
            value = str(source.get(key) or "").strip() if isinstance(source, dict) else ""
            if value:
                return value.strip().lstrip("/")
    return "Sin titulo"


def numeric_value(value):
    try:
        if value in ("", None):
            return 0.0
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def rdt_row_progress(row):
    for key in ("progress", "Progress", "downloadProgress", "percent", "percentage"):
        value = numeric_value(row.get(key))
        if value > 0:
            return max(0, min(100, value * 100 if value <= 1 else value))
    downloaded = numeric_value(row.get("downloaded") or row.get("downloadedBytes") or row.get("bytesDone"))
    total = numeric_value(row.get("size") or row.get("totalSize") or row.get("bytesTotal"))
    if downloaded > 0 and total > 0:
        return max(0, min(100, downloaded * 100 / total))
    return 0


def btdigg_rd_item_state(status, progress):
    text = str(status or "").lower()
    if progress >= 99.9 or any(word in text for word in ("finished", "downloaded", "complete", "completed")):
        return "finished", "Terminado"
    if any(word in text for word in ("error", "failed", "fallo")):
        return "error", "Error"
    if "stalled" in text:
        return "stalled", "Parado"
    if progress > 0 or any(word in text for word in ("downloading", "download", "metadata")):
        return "downloading", "Descargando"
    return "waiting", "Esperando"


def btdigg_rd_item(row, record):
    progress = rdt_row_progress(row)
    status = rdt_row_status(row)
    state, label = btdigg_rd_item_state(status, progress)
    destino = str(record.get("destino") or "").strip().lower()
    ts = numeric_value(record.get("ts"))
    return {
        "id": rdt_row_id(row) or rdt_row_hash(row) or str(record.get("id") or ""),
        "hash": rdt_row_hash(row) or normalize_bt_hash(record.get("hash")),
        "title": rdt_row_title(row, record),
        "category": destino if destino in {"movies", "tv"} else "movies",
        "kind": "btdigg-rd",
        "progress": progress,
        "status": status,
        "state": state,
        "state_label": label,
        "first_seen": ts or None,
        "last_progress_ts": ts or None,
        "finished_seen_ts": ts if state == "finished" else None,
    }


def recent_btdigg_rd_item(record):
    destino = str(record.get("destino") or "").strip().lower()
    ts = numeric_value(record.get("ts"))
    return {
        "id": str(record.get("rdt_id") or record.get("id") or normalize_bt_hash(record.get("hash"))),
        "hash": normalize_bt_hash(record.get("hash")),
        "title": rdt_row_title({}, record),
        "category": destino if destino in {"movies", "tv"} else "movies",
        "kind": "btdigg-rd-recent",
        "progress": 100,
        "status": "Terminado rapido",
        "state": "finished",
        "state_label": "Terminado",
        "first_seen": ts or None,
        "last_progress_ts": ts or None,
        "finished_seen_ts": ts or None,
    }


def btdigg_rd_recent_missing_items(seen_keys):
    now = time.time()
    items = []
    for record in btdigg_rd_read_tracking():
        if not isinstance(record, dict):
            continue
        destino = str(record.get("destino") or "").strip().lower()
        rdt_id = str(record.get("rdt_id") or "").strip()
        ts = numeric_value(record.get("ts"))
        if destino not in {"movies", "tv"} or not rdt_id or not ts:
            continue
        if now - ts < 0 or now - ts > BTDIGG_RD_RECENT_VISIBLE_SEC:
            continue
        key = rdt_id.lower()
        hash_key = normalize_bt_hash(record.get("hash"))
        if key in seen_keys or (hash_key and hash_key in seen_keys):
            continue
        seen_keys.add(key)
        if hash_key:
            seen_keys.add(hash_key)
        items.append(recent_btdigg_rd_item(record))
    return items


def fetch_btdigg_rd_status():
    by_rdt_id, by_hash = btdigg_rd_tracking_index()
    if not by_rdt_id and not by_hash:
        status = empty_arr_status()
        status["source"] = "btdigg-rd-readonly"
        status["stale"] = False
        status["updated_at"] = datetime.now(timezone.utc).timestamp()
        return status

    items = []
    seen_keys = set()
    try:
        for row in rdt_native_rows():
            record = by_rdt_id.get(rdt_row_id(row)) or by_hash.get(rdt_row_hash(row))
            if record:
                rdt_id = rdt_row_id(row).lower()
                torrent_hash = rdt_row_hash(row)
                if rdt_id:
                    seen_keys.add(rdt_id)
                if torrent_hash:
                    seen_keys.add(torrent_hash)
                items.append(btdigg_rd_item(row, record))
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        log_error(f"No se pudo leer RDT-Client para BTDigg RD: {exc}")
        status = empty_arr_status("btdigg rd no responde")
        status["source"] = "btdigg-rd-readonly"
        return status

    items.extend(btdigg_rd_recent_missing_items(seen_keys))

    counts = {
        "total": len(items),
        "downloading": 0,
        "waiting": 0,
        "stalled": 0,
        "error": 0,
        "finished": 0,
    }
    for item in items:
        state = item.get("state")
        if state in counts:
            counts[state] += 1
    return {
        "ok": True,
        "source": "btdigg-rd-readonly",
        "stale": False,
        "updated_at": datetime.now(timezone.utc).timestamp(),
        "monitoring": len(items),
        "counts": counts,
        "items": items[:20],
        "error": "",
    }


def merge_arr_statuses(statuses):
    items = []
    seen = set()
    errors = []
    stale = True
    for status in statuses:
        if not isinstance(status, dict):
            continue
        stale = stale and bool(status.get("stale"))
        error = str(status.get("error") or "").strip()
        if error and error not in errors:
            errors.append(error)
        for item in status.get("items", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("hash") or "").strip().lower()
            if not key:
                key = f"{str(item.get('category') or '').lower()}::{str(item.get('title') or '').lower()}"
            if key in seen:
                continue
            seen.add(key)
            items.append(item)

    counts = {
        "total": len(items),
        "downloading": 0,
        "waiting": 0,
        "stalled": 0,
        "error": 0,
        "finished": 0,
    }
    for item in items:
        state = item.get("state")
        if state in counts:
            counts[state] += 1

    return {
        "ok": True,
        "source": "arr-readonly+btdigg-rd-readonly",
        "stale": stale,
        "updated_at": datetime.now(timezone.utc).timestamp(),
        "monitoring": len(items),
        "counts": counts,
        "items": items[:20],
        "error": " | ".join(errors),
    }


def arr_status_counts(items):
    counts = {
        "total": len(items),
        "downloading": 0,
        "waiting": 0,
        "stalled": 0,
        "error": 0,
        "finished": 0,
    }
    for item in items:
        state = item.get("state")
        if state in counts:
            counts[state] += 1
    return counts


def arr_status_with_items(status, items):
    updated = dict(status)
    updated["monitoring"] = len(items)
    updated["counts"] = arr_status_counts(items)
    updated["items"] = items
    return updated


def prune_expired_btdigg_recent_items(status):
    if not isinstance(status, dict):
        return status

    now = time.time()
    items = []
    changed = False
    for item in status.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "btdigg-rd-recent":
            ts = numeric_value(
                item.get("finished_seen_ts")
                or item.get("last_progress_ts")
                or item.get("first_seen")
            )
            if not ts or now - ts < 0 or now - ts > BTDIGG_RD_RECENT_VISIBLE_SEC:
                changed = True
                continue
        items.append(item)

    if not changed:
        return status
    return arr_status_with_items(status, items)


def filter_arr_status(status, category):
    category = str(category or "").strip().lower()
    if category not in {"movies", "tv"}:
        return status

    items = []
    for item in status.get("items", []):
        item_category = str(item.get("category") or "").strip().lower()
        if item_category in {"movies", "tv"} and item_category != category:
            continue
        items.append(item)

    return arr_status_with_items(status, items)


def fetch_arr_status(category=""):
    now = time.time()
    with ARR_READ_CACHE_LOCK:
        cached = ARR_READ_CACHE.get("data")
        if cached and now - float(ARR_READ_CACHE.get("ts") or 0) < ARR_READ_CACHE_TTL_SEC:
            cached = prune_expired_btdigg_recent_items(cached)
            ARR_READ_CACHE["data"] = cached
            return filter_arr_status(cached, category)

        bridge_status = None
        bridge_error = ""
        try:
            bridge_status = build_arr_status(arr_read_json("/api/engine-status"))
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            bridge_error = "buscador puente arr no responde"
            log_error(f"No se pudo leer buscador puente arr por HTTP: {exc}")

        btdigg_status = fetch_btdigg_rd_status()
        if bridge_status is None:
            bridge_status = empty_arr_status(bridge_error)

        data = merge_arr_statuses([bridge_status, btdigg_status])
        if not data["items"] and bridge_error and btdigg_status.get("error"):
            data["error"] = f"{bridge_error} | {btdigg_status.get('error')}"

        if data["items"] or not data.get("error"):
            ARR_READ_CACHE["data"] = data
            ARR_READ_CACHE["ts"] = now
            return filter_arr_status(data, category)

        if cached:
            stale_status = dict(cached)
            stale_status["stale"] = True
            stale_status["error"] = data.get("error", "real-debrid no responde")
            stale_status = prune_expired_btdigg_recent_items(stale_status)
            return filter_arr_status(stale_status, category)
        return filter_arr_status(data, category)


def empty_qbit_status(category="", error=None):
    return {
        "ok": True,
        "source": "qbittorrent-readonly",
        "stale": True,
        "updated_at": None,
        "category": category,
        "total": 0,
        "shown": 0,
        "counts": {
            "downloading": 0,
            "waiting": 0,
            "stalled": 0,
            "stopped": 0,
            "error": 0,
            "finished": 0,
        },
        "items": [],
        "error": error or "",
    }


def qbit_state(item):
    raw = str(item.get("state") or "").lower()
    try:
        progress = float(item.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0

    if any(word in raw for word in ("error", "missing")):
        return "error", "Error"
    if progress >= 0.999 or raw in {"uploading", "stalledup", "forcedup", "queuedup", "pausedup", "stoppedup"}:
        return "finished", "Terminado"
    if "stalled" in raw:
        return "stalled", "Parado"
    if any(word in raw for word in ("paused", "stopped")):
        return "stopped", "Detenido"
    if "queued" in raw:
        return "waiting", "En cola"
    if "downloading" in raw or raw in {"forceddl", "metadl"}:
        return "downloading", "Descargando"
    return "waiting", "Esperando"


def human_size(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if number < 1024 or unit == "TB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return "0 B"


def human_speed(value):
    text = human_size(value)
    return f"{text}/s" if text != "0 B" else "0 B/s"


def clean_qbit_item(item):
    state, label = qbit_state(item)
    try:
        progress = float(item.get("progress") or 0) * 100
    except (TypeError, ValueError):
        progress = 0
    return {
        "hash": str(item.get("hash") or ""),
        "name": str(item.get("name") or "Sin nombre"),
        "category": str(item.get("category") or ""),
        "state": state,
        "state_label": label,
        "state_raw": str(item.get("state") or ""),
        "progress": max(0, min(100, progress)),
        "size": human_size(item.get("size")),
        "dlspeed": human_speed(item.get("dlspeed")),
        "upspeed": human_speed(item.get("upspeed")),
        "seeders": int(item.get("num_seeds") or item.get("num_complete") or 0),
        "added_on": int(item.get("added_on") or 0),
    }


def qbit_login_opener():
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    data = urlencode({"username": QBIT_USER, "password": QBIT_PASS}).encode("utf-8")
    req = Request(
        f"{QBIT_BASE_URL}/api/v2/auth/login",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(req, timeout=QBIT_TIMEOUT_SEC) as response:
        text = response.read().decode("utf-8", errors="replace").strip().lower()
        if response.status not in (200, 204) or (text and text != "ok."):
            raise RuntimeError("qBittorrent login fallido")
    return opener


def qbit_read_all():
    opener = qbit_login_opener()
    url = f"{QBIT_BASE_URL}/api/v2/torrents/info?sort=added_on&reverse=true"
    req = Request(url, headers={"Accept": "application/json"})
    with opener.open(req, timeout=QBIT_TIMEOUT_SEC) as response:
        data = json.loads(response.read().decode("utf-8") or "[]")
        return data if isinstance(data, list) else []


def qbit_post(path, data):
    opener = qbit_login_opener()
    encoded = urlencode(data).encode("utf-8")
    req = Request(
        f"{QBIT_BASE_URL}{path}",
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(req, timeout=QBIT_TIMEOUT_SEC) as response:
        text = response.read().decode("utf-8", errors="replace")
        if response.status not in (200, 204):
            raise RuntimeError(f"qBittorrent HTTP {response.status}: {text[:120]}")
        return text


def clear_qbit_cache():
    with QBIT_CACHE_LOCK:
        QBIT_CACHE["data"] = None
        QBIT_CACHE["ts"] = 0.0


def cached_qbit_all():
    now = time.time()
    with QBIT_CACHE_LOCK:
        cached = QBIT_CACHE.get("data")
        if cached is not None and now - float(QBIT_CACHE.get("ts") or 0) < QBIT_CACHE_TTL_SEC:
            return cached
        data = qbit_read_all()
        QBIT_CACHE["data"] = data
        QBIT_CACHE["ts"] = now
        return data


def delete_qbit_hashes(category, hashes):
    category = str(category or "").strip().lower()
    if category not in {"movies", "tv"}:
        raise RuntimeError("Categoria no permitida")

    clean_hashes = [str(item or "").strip() for item in hashes if str(item or "").strip()]
    if not clean_hashes:
        raise RuntimeError("No hay torrents seleccionados")

    raw_items = qbit_read_all()
    allowed_hashes = {
        str(item.get("hash") or "").strip()
        for item in raw_items
        if str(item.get("category") or "").strip().lower() == category
    }
    blocked = [item_hash for item_hash in clean_hashes if item_hash not in allowed_hashes]
    if blocked:
        raise RuntimeError("Hay torrents que ya no pertenecen a esta tarjeta")

    qbit_post(
        "/api/v2/torrents/delete",
        {
            "hashes": "|".join(clean_hashes),
            "deleteFiles": "true",
        },
    )
    clear_qbit_cache()
    return {
        "ok": True,
        "deleted": len(clean_hashes),
        "message": f"{len(clean_hashes)} borrado(s)",
    }


def fetch_qbit_status(category):
    category = str(category or "").strip().lower()
    try:
        raw_items = cached_qbit_all()
        filtered = [
            item for item in raw_items
            if str(item.get("category") or "").strip().lower() == category
        ]
        filtered.sort(key=lambda item: int(item.get("added_on") or 0), reverse=True)
        items = [clean_qbit_item(item) for item in filtered]
        counts = empty_qbit_status(category)["counts"]
        for item in filtered:
            state, _ = qbit_state(item)
            if state in counts:
                counts[state] += 1
        return {
            "ok": True,
            "source": "qbittorrent-readonly",
            "stale": False,
            "updated_at": datetime.now(timezone.utc).timestamp(),
            "category": category,
            "total": len(filtered),
            "shown": len(items),
            "counts": counts,
            "items": items,
            "error": "",
        }
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        log_error(f"No se pudo leer qBittorrent por HTTP: {exc}")
        return empty_qbit_status(category, "qBittorrent no responde")


def seguimiento_qbit_delete(data):
    hashes = data.get("hashes") if isinstance(data.get("hashes"), list) else []
    try:
        return delete_qbit_hashes(data.get("category") or "", hashes)
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
        log_error(f"No se pudo borrar qBittorrent: {exc}")
        return {"ok": False, "error": str(exc)}


def format_size(size):
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            rounded = round(value, 1)
            text = str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"
            return f"{text} {unit}"
        value /= 1024
    return f"{size} B"


def activity_time(st):
    return max(float(getattr(st, "st_mtime", 0) or 0), float(getattr(st, "st_ctime", 0) or 0))


def item_kind(path):
    if path.is_dir():
        return "folder"
    suffix = path.suffix.lower()
    if suffix in TEMP_SIZE_EXTENSIONS:
        return "temp"
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if suffix in {".srt", ".ass", ".sub"}:
        return "subtitle"
    if suffix == ".torrent":
        return "torrent"
    if suffix == ".json":
        return "json"
    if suffix in MEDIA_EXTENSIONS:
        return "video"
    return "file"


def read_text_content(path):
    try:
        data = path.read_bytes()
    except OSError as exc:
        log_error(f"No se pudo leer texto {path}: {exc}")
        return ""

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


def child_items(root, limit=5, prefix=None, suffixes=None, include_dirs=False):
    children = []
    allowed_suffixes = {suffix.lower() for suffix in suffixes or []}
    try:
        entries = []
        for entry in os.scandir(root):
            try:
                is_file = entry.is_file(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
                if not is_file and not (include_dirs and is_dir):
                    continue
                if prefix and not entry.name.lower().startswith(prefix.lower()):
                    continue
                path = Path(entry.path)
                if is_file and allowed_suffixes and path.suffix.lower() not in allowed_suffixes:
                    continue
                if is_dir and allowed_suffixes:
                    continue
                st = entry.stat(follow_symlinks=False)
                entries.append((entry.name, path, st, is_dir))
            except OSError as exc:
                log_error(f"No se pudo leer contenido {entry.path}: {exc}")

        entries.sort(key=lambda row: activity_time(row[2]), reverse=True)
        selected_entries = entries if limit is not None and limit <= 0 else entries[:limit]
        for name, path, st, is_dir in selected_entries:
            child = {
                "name": name,
                "kind": item_kind(path),
                "size": format_size(st.st_size),
                "mtime": activity_time(st),
                "can_expand": bool(is_dir),
            }
            if path.suffix.lower() == ".txt":
                child["text"] = read_text_content(path)
            children.append(child)
    except OSError as exc:
        log_error(f"No se pudo leer contenido interno {root}: {exc}")
    return children


def flat_file_items(root, limit=0):
    items = []
    try:
        base = Path(root).resolve()
        for current_root, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name not in {".", ".."}]
            for filename in filenames:
                path = Path(current_root) / filename
                try:
                    resolved = path.resolve()
                    parts = list(resolved.relative_to(base).parts)
                    st = resolved.stat()
                    item = {
                        "name": filename,
                        "kind": item_kind(resolved),
                        "size": format_size(st.st_size),
                        "mtime": activity_time(st),
                        "can_expand": False,
                        "children_source": "",
                        "parts": parts,
                    }
                    if resolved.suffix.lower() == ".txt":
                        item["text"] = read_text_content(resolved)
                    items.append(item)
                except (OSError, ValueError) as exc:
                    log_error(f"No se pudo leer archivo plano {path}: {exc}")
    except OSError as exc:
        log_error(f"No se pudo recorrer archivos planos {root}: {exc}")

    items.sort(key=lambda item: float(item.get("mtime") or 0), reverse=True)
    return items if limit <= 0 else items[:limit]


def child_sources():
    sources = {}
    for folder_id, folder in FOLDER_BY_ID.items():
        if folder.get("lazy_children") or folder.get("nested"):
            sources[folder_id] = folder
        for section in folder.get("extra_sections", []):
            section_id = section.get("id")
            if section_id and section.get("lazy_children"):
                sources[section_id] = section
    return sources


def resolve_child_root(source_id, item_name="", parts=None):
    source = child_sources().get(source_id)
    if not source:
        return None, "Origen no permitido"

    clean_parts, error = clean_action_parts(parts if parts is not None else [item_name])
    if error:
        return None, error

    try:
        base = Path(source["path"]).resolve()
        target = base.joinpath(*clean_parts).resolve()
        target.relative_to(base)
    except (KeyError, OSError, ValueError):
        return None, "Ruta no valida"

    if not target.is_dir():
        return None, "No accesible"

    return target, None


def clean_action_parts(parts):
    cleaned = []
    for raw_part in parts:
        part = str(raw_part or "").strip()
        if not part or part in {".", ".."} or "/" in part or "\\" in part:
            return None, "Ruta no valida"
        cleaned.append(part)

    if not cleaned:
        return None, "Elemento no valido"

    return cleaned, None


def resolve_action_target(source_id, parts):
    source = child_sources().get(source_id)
    if not source:
        return None, "Origen no permitido"

    clean_parts, error = clean_action_parts(parts)
    if error:
        return None, error

    try:
        base = Path(source["path"]).resolve()
        target = base.joinpath(*clean_parts).resolve()
        target.relative_to(base)
    except (KeyError, OSError, ValueError):
        return None, "Ruta no valida"

    if not target.exists():
        return None, "Ya no existe"

    return target, None


def unique_destination(folder, name):
    destination = folder / name
    if not destination.exists():
        return destination

    source_name = Path(name)
    stem = source_name.stem
    suffix = source_name.suffix
    for index in range(1, 1000):
        candidate_name = f"{stem} ({index}){suffix}" if suffix else f"{name} ({index})"
        candidate = folder / candidate_name
        if not candidate.exists():
            return candidate

    raise RuntimeError("No se pudo crear un nombre libre en destino")


def move_target_to_destination(target, action):
    destination_config = MOVE_DESTINATIONS.get(action)
    if not destination_config:
        return {"ok": False, "error": "Destino no permitido"}

    destination_folder = Path(destination_config["path"]).resolve()
    destination_folder.mkdir(parents=True, exist_ok=True)
    label = destination_config["label"]

    if target.parent.resolve() == destination_folder:
        return {"ok": True, "message": f"Ya estaba en {label}", "name": target.name}

    destination = unique_destination(destination_folder, target.name).resolve()
    try:
        destination.relative_to(destination_folder)
    except ValueError:
        return {"ok": False, "error": "Destino no valido"}

    shutil.move(str(target), str(destination))
    return {"ok": True, "message": f"Movido a {label}", "name": destination.name}


def clean_media_move_parts(parts):
    cleaned = []
    for raw_part in parts or []:
        part = str(raw_part or "").strip()
        if not part:
            continue
        if part in {".", ".."} or "/" in part or "\\" in part:
            return None, "Ruta no valida"
        cleaned.append(part)
    return cleaned, None


def resolve_media_move_folder(parts):
    clean_parts, error = clean_media_move_parts(parts)
    if error:
        return None, [], error

    try:
        root = MEDIA_MOVE_ROOT
        target = root.joinpath(*clean_parts).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return None, clean_parts or [], "Ruta no valida"

    if not root.is_dir():
        return None, clean_parts or [], "Raiz media no accesible"
    if not target.is_dir():
        return None, clean_parts or [], "Carpeta no accesible"

    return target, clean_parts or [], None


def media_move_label(parts):
    return "Media" if not parts else "/".join(parts)


def media_move_folder_items(root):
    items = []
    try:
        entries = []
        for entry in os.scandir(root):
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if entry.name in {".", ".."}:
                    continue
                path = Path(entry.path)
                st = entry.stat(follow_symlinks=False)
                entries.append((normalize_search_text(entry.name), entry.name, st))
            except OSError as exc:
                log_error(f"No se pudo leer carpeta destino {entry.path}: {exc}")
        entries.sort(key=lambda row: row[0])
        for _, name, st in entries:
            items.append({
                "name": name,
                "mtime": activity_time(st),
            })
    except OSError as exc:
        log_error(f"No se pudo listar destino {root}: {exc}")
    return items


def move_target_to_custom_destination(target, dest_parts):
    destination_folder, clean_parts, error = resolve_media_move_folder(dest_parts)
    if error:
        return {"ok": False, "error": error}

    try:
        target_resolved = target.resolve()
        destination_resolved = destination_folder.resolve()
        if target_resolved.parent == destination_resolved:
            return {"ok": True, "message": f"Ya estaba en {media_move_label(clean_parts)}", "name": target.name}
        if target_resolved.is_dir():
            try:
                destination_resolved.relative_to(target_resolved)
                return {"ok": False, "error": "No se puede mover una carpeta dentro de si misma"}
            except ValueError:
                pass

        destination = unique_destination(destination_resolved, target.name).resolve()
        destination.relative_to(destination_resolved)
    except (OSError, ValueError):
        return {"ok": False, "error": "Destino no valido"}

    shutil.move(str(target_resolved), str(destination))
    return {
        "ok": True,
        "message": f"Movido a {media_move_label(clean_parts)}",
        "name": destination.name,
        "destination_parts": clean_parts,
    }


def delete_target(target):
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True, "message": "Eliminado", "name": target.name}


def normalize_rename_name(target, raw_name):
    name = str(raw_name or "").strip()
    if not name:
        return None, "Escribe un nombre"
    if name in {".", ".."} or "/" in name or "\\" in name:
        return None, "Nombre no valido"
    if name.endswith(" ") or name.endswith("."):
        return None, "El nombre no puede terminar en punto o espacio"
    if len(name) > 240:
        return None, "Nombre demasiado largo"

    if target.is_file() and target.suffix:
        original_suffix = target.suffix
        new_suffix = Path(name).suffix
        if not new_suffix:
            name = f"{name}{original_suffix}"
        elif new_suffix.lower() != original_suffix.lower():
            return None, f"Mantengo la extension {original_suffix}"

    return name, None


def rename_target(target, raw_name):
    name, error = normalize_rename_name(target, raw_name)
    if error:
        return {"ok": False, "error": error}
    if name == target.name:
        return {"ok": True, "message": "Ya tenia ese nombre", "name": target.name}

    destination = target.with_name(name).resolve()
    try:
        destination.relative_to(target.parent.resolve())
    except ValueError:
        return {"ok": False, "error": "Destino no valido"}
    if destination.exists():
        return {"ok": False, "error": "Ya existe un elemento con ese nombre"}

    target.rename(destination)
    try:
        now = time.time()
        os.utime(destination, (now, now))
    except Exception:
        pass
    return {"ok": True, "message": "Renombrado", "name": destination.name}


def run_trailer_tracks_motor(action, target, ids=None):
    cmd = ["python", TRAILER_TRACKS_MOTOR, action, "--path", str(target)]
    for track_id in ids or []:
        cmd.extend(["--id", str(track_id)])
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=21630,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        payload = {"ok": False, "error": (proc.stderr or proc.stdout or "Respuesta no valida").strip()}
    if proc.returncode != 0 and payload.get("ok") is not True:
        payload.setdefault("error", (proc.stderr or "No se pudo procesar el video").strip())
    return payload


def trailer_job_json_read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def trailer_job_json_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def trailer_job_progress(job, phase, percent, label):
    data = {
        "phase": phase,
        "percent": max(0, min(100, int(round(float(percent))))),
        "label": label,
        "updated_at": time.time(),
    }
    trailer_job_json_write(job["progress_path"], data)
    return data


def active_trailer_job():
    with TRAILER_JOBS_LOCK:
        for job in TRAILER_JOBS.values():
            if job.get("status") == "running":
                return job
    return None


def create_trailer_job(action, target, ids, phase, label):
    running = active_trailer_job()
    if running:
        return None, f"Ya hay un proceso en marcha: {running.get('label', 'Editar video')}"

    os.makedirs(TRAILER_JOB_ROOT, exist_ok=True)
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    job_dir = os.path.join(TRAILER_JOB_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)
    job = {
        "id": job_id,
        "status": "running",
        "action": action,
        "phase": phase,
        "label": label,
        "target": str(target),
        "ids": [str(item) for item in ids],
        "job_dir": job_dir,
        "progress_path": os.path.join(job_dir, "progress.json"),
        "result_path": os.path.join(job_dir, "resultado.json"),
        "log_path": os.path.join(job_dir, "proceso.log"),
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": "",
    }
    diagnostico_init(job, "seguimiento_trailer", inputs={
        "action": action,
        "target": str(target),
        "ids": [str(item) for item in ids],
    }, settings={
        "phase": phase,
        "label": label,
    })
    trailer_job_progress(job, phase, 0, label)
    trailer_job_json_write(job["result_path"], {"ok": None, "running": True})
    with TRAILER_JOBS_LOCK:
        TRAILER_JOBS[job_id] = job
    thread = threading.Thread(target=run_trailer_job, args=(job,), daemon=True)
    thread.start()
    return job, None


def run_trailer_job(job):
    diagnostico_attach(job)
    cmd = [
        "python",
        TRAILER_TRACKS_MOTOR,
        job["action"],
        "--path",
        job["target"],
        "--progress-path",
        job["progress_path"],
    ]
    for track_id in job.get("ids") or []:
        cmd.extend(["--id", str(track_id)])

    try:
        diagnostico_event(job, job.get("phase") or "trailer_job", "started", "Arranca motor de trailer", {
            "action": job.get("action"),
            "target": job.get("target"),
            "ids": job.get("ids") or [],
        })
        started_at = time.time()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=21630,
        )
        diagnostico_command(job, job.get("phase") or "trailer_job", "eliminar_trailer_pistas.py", cmd, proc.returncode, started_at, proc.stdout, proc.stderr, proc.returncode == 0)
        with open(job["log_path"], "w", encoding="utf-8") as handle:
            if proc.stdout:
                handle.write(proc.stdout)
                if not proc.stdout.endswith("\n"):
                    handle.write("\n")
            if proc.stderr:
                handle.write(proc.stderr)

        try:
            payload = json.loads(proc.stdout or "{}")
        except Exception:
            payload = {"ok": False, "error": (proc.stderr or proc.stdout or "Respuesta no valida").strip()}
        if proc.returncode != 0 and payload.get("ok") is not True:
            payload.setdefault("error", (proc.stderr or "No se pudo procesar el video").strip())

        ok = payload.get("ok") is True
        job["status"] = "done" if ok else "error"
        job["result"] = payload
        job["error"] = "" if ok else str(payload.get("error") or "No se pudo procesar el video")
        job["updated_at"] = time.time()
        if ok:
            diagnostico_event(job, "finished", "done", "Trabajo trailer terminado OK", payload)
            diagnostico_finish(job, "done", payload)
        else:
            diagnostico_error(job, diag_classify_error(job["error"]), job.get("phase") or "trailer_job", job["error"], payload)
            diagnostico_finish(job, "error", payload)
        trailer_job_json_write(job["result_path"], payload)
        trailer_job_progress(job, "done" if ok else "error", 100, "Listo" if ok else "Aviso")
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        job["status"] = "error"
        job["result"] = payload
        job["error"] = str(exc)
        job["updated_at"] = time.time()
        diagnostico_error(job, diag_classify_error(str(exc)), job.get("phase") or "trailer_job", str(exc), {}, exc)
        diagnostico_finish(job, "error", payload)
        trailer_job_json_write(job["result_path"], payload)
        trailer_job_progress(job, "error", 100, "Aviso")


def get_trailer_job(job_id):
    clean_id = os.path.basename(str(job_id or "").strip())
    if not clean_id:
        return None
    with TRAILER_JOBS_LOCK:
        job = TRAILER_JOBS.get(clean_id)
        if job:
            return job
    job_dir = os.path.join(TRAILER_JOB_ROOT, clean_id)
    if not os.path.isdir(job_dir):
        return None
    result = trailer_job_json_read(os.path.join(job_dir, "resultado.json")) or {}
    progress = trailer_job_json_read(os.path.join(job_dir, "progress.json")) or {}
    status = "running" if result.get("running") else ("done" if result.get("ok") else "error")
    return {
        "id": clean_id,
        "status": status,
        "action": "",
        "phase": progress.get("phase", ""),
        "label": progress.get("label", ""),
        "target": "",
        "ids": [],
        "job_dir": job_dir,
        "progress_path": os.path.join(job_dir, "progress.json"),
        "result_path": os.path.join(job_dir, "resultado.json"),
        "log_path": os.path.join(job_dir, "proceso.log"),
        "created_at": 0,
        "updated_at": progress.get("updated_at", 0),
        "error": "" if result.get("ok") else str(result.get("error") or ""),
    }


def trailer_job_status_payload(job):
    progress = trailer_job_json_read(job["progress_path"])
    if not isinstance(progress, dict) or "percent" not in progress:
        progress = {"phase": job.get("phase", ""), "percent": 0, "label": job.get("label", "Procesando")}
    result = trailer_job_json_read(job["result_path"])
    if not isinstance(result, dict):
        result = job.get("result") or {}
    status = job.get("status") or ("running" if result.get("running") else ("done" if result.get("ok") else "error"))
    return {
        "ok": True,
        "job": job["id"],
        "status": status,
        "action": job.get("action", ""),
        "label": job.get("label") or progress.get("label", ""),
        "progress": progress,
        "result": None if status == "running" else result,
        "error": job.get("error", ""),
    }


def seguimiento_trailer_job_status(q):
    job = get_trailer_job(q.get("job", [""])[0])
    if not job:
        return {"ok": False, "error": "Proceso no encontrado"}
    return trailer_job_status_payload(job)


def seguimiento_trailer_job_start(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}

    action = str(q.get("action", [""])[0]).strip().lower()
    if action == "audio":
        audio_id = str(q.get("id", [""])[0]).strip()
        if not audio_id:
            return {"ok": False, "error": "Selecciona una pista de audio"}
        job, job_error = create_trailer_job("convert_audio", target, [audio_id], "audio", "Convirtiendo")
    elif action == "subtitle":
        ids = [str(item).strip() for item in q.get("id", []) if str(item).strip()]
        if not ids:
            return {"ok": False, "error": "Selecciona algun subtitulo"}
        job, job_error = create_trailer_job("delete", target, ids, "subtitle", "Eliminando")
    else:
        return {"ok": False, "error": "Accion no permitida"}

    if job_error:
        return {"ok": False, "error": job_error}
    return trailer_job_status_payload(job)


def seguimiento_trailer_info(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}
    try:
        return run_trailer_tracks_motor("info", target)
    except Exception as exc:
        log_error(f"No se pudo leer pistas de {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def seguimiento_trailer_delete(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}

    ids = [str(item).strip() for item in q.get("id", []) if str(item).strip()]
    if not ids:
        return {"ok": False, "error": "Selecciona algun subtitulo"}
    try:
        return run_trailer_tracks_motor("delete", target, ids)
    except Exception as exc:
        log_error(f"No se pudieron eliminar pistas de {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def seguimiento_trailer_audio(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}

    audio_id = str(q.get("id", [""])[0]).strip()
    if not audio_id:
        return {"ok": False, "error": "Selecciona una pista de audio"}
    try:
        return run_trailer_tracks_motor("convert_audio", target, [audio_id])
    except Exception as exc:
        log_error(f"No se pudo convertir audio de {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def seguimiento_trailer_chapters(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}

    video_id = str(q.get("id", [""])[0]).strip()
    if not video_id:
        return {"ok": False, "error": "Selecciona una pista de video"}
    try:
        return run_trailer_tracks_motor("chapters_10m", target, [video_id])
    except Exception as exc:
        log_error(f"No se pudieron aplicar capitulos de {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def seguimiento_trailer_language(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "Solo disponible para videos"}

    ids = []
    video_id = str(q.get("video_id", [""])[0]).strip()
    if video_id:
        ids.append(f"video:{video_id}")
    audio_id = str(q.get("audio_id", [""])[0]).strip()
    if audio_id:
        ids.append(f"audio:{audio_id}")
    ids.extend(f"subtitle:{str(item).strip()}" for item in q.get("id", []) if str(item).strip())
    if not ids:
        return {"ok": False, "error": "Selecciona video, audio o subtitulo"}
    try:
        return run_trailer_tracks_motor("rename_language", target, ids)
    except Exception as exc:
        log_error(f"No se pudo renombrar idioma de {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def scan_extra_section(section):
    root = Path(section["path"])
    result = {
        "id": section.get("id", ""),
        "label": section["label"],
        "path": section["real_path"],
        "exists": root.is_dir(),
        "lazy_children": bool(section.get("lazy_children")),
        "items": [],
        "error": None,
    }

    if not root.is_dir():
        result["error"] = "No accesible"
        return result

    try:
        entries = []
        for entry in os.scandir(root):
            try:
                if entry.is_dir(follow_symlinks=False):
                    st = entry.stat(follow_symlinks=False)
                    entries.append((entry.name, Path(entry.path), st))
            except OSError as exc:
                log_error(f"No se pudo leer entrada extra {entry.path}: {exc}")

        entries.sort(key=lambda row: activity_time(row[2]), reverse=True)
        for name, path, st in entries:
            result["items"].append(
                {
                    "name": name,
                    "kind": item_kind(path),
                    "size": None,
                    "mtime": activity_time(st),
                    "can_expand": bool(section.get("lazy_children") and path.is_dir()),
                    "children_source": section.get("id", ""),
                }
            )
    except OSError as exc:
        result["error"] = "Error leyendo"
        log_error(f"No se pudo escanear extra {section['real_path']}: {exc}")

    return result


def scan_folder(folder):
    root = Path(folder["path"])
    result = {
        "id": folder["id"],
        "name": folder["name"],
        "path": folder["real_path"],
        "exists": root.is_dir(),
        "count": 0,
        "last_change": None,
        "lazy_children": bool(folder.get("lazy_children")),
        "items": [],
        "extra_sections": [],
        "error": None,
    }

    if not root.is_dir():
        result["error"] = "No accesible"
        return result

    try:
        if folder.get("flat_files"):
            limit = int(folder["limit"]) if "limit" in folder else 0
            items = flat_file_items(root, limit=limit)
            result["items"] = [
                {**item, "children_source": folder["id"]}
                for item in items
            ]
            result["count"] = len(items)
            if items:
                result["last_change"] = max(float(item.get("mtime") or 0) for item in items)
            return result

        entries = []
        for entry in os.scandir(root):
            try:
                st = entry.stat(follow_symlinks=False)
                entries.append((entry.name, Path(entry.path), st))
            except OSError as exc:
                log_error(f"No se pudo leer entrada {entry.path}: {exc}")

        result["count"] = len(entries)
        if entries:
            result["last_change"] = max(activity_time(st) for _, _, st in entries)

        limit = int(folder["limit"]) if "limit" in folder else 8
        entries.sort(key=lambda row: activity_time(row[2]), reverse=True)
        selected_entries = entries if limit <= 0 else entries[:limit]
        for name, path, st in selected_entries:
            item = {
                "name": name,
                "kind": item_kind(path),
                "size": None if path.is_dir() else format_size(st.st_size),
                "mtime": activity_time(st),
                "can_expand": bool(folder.get("lazy_children") and path.is_dir()),
                "children_source": folder["id"],
            }
            if path.is_file() and path.suffix.lower() == ".txt":
                item["text"] = read_text_content(path)
            if folder.get("nested") and path.is_dir() and not folder.get("lazy_children"):
                child_limit = folder.get("child_limit")
                item["children"] = child_items(
                    path,
                    limit=5 if child_limit is None else int(child_limit),
                    prefix=folder.get("child_prefix"),
                    suffixes=folder.get("child_suffixes"),
                    include_dirs=bool(folder.get("child_include_dirs")),
                )
            result["items"].append(item)

        result["extra_sections"] = [
            scan_extra_section(section) for section in folder.get("extra_sections", [])
        ]
    except OSError as exc:
        result["error"] = "Error leyendo"
        log_error(f"No se pudo escanear {folder['real_path']}: {exc}")

    return result


def all_folder_ids():
    seen = []
    for section in SECTIONS:
        for folder_id in section["folder_ids"]:
            if folder_id not in seen:
                seen.append(folder_id)
    return seen


def section_by_id(section_id):
    for section in SECTIONS:
        if section["id"] == section_id:
            return section
    return None


def folder_ids_for_section(section_id):
    section = section_by_id(section_id)
    if section is None:
        return all_folder_ids()
    return list(section["folder_ids"])


def build_sections(scans, active_section_id=""):
    sections = []
    for section in SECTIONS:
        folders = []
        if not active_section_id or section["id"] == active_section_id:
            folders = [scans[folder_id] for folder_id in section["folder_ids"] if folder_id in scans]
        sections.append(
            {
                "id": section["id"],
                "label": section["label"],
                "folders": folders,
            }
        )
    return sections


def seguimiento_status(q=None):
    now = datetime.now(timezone.utc).timestamp()
    section_id = ""
    if q:
        section_id = str(q.get("section", [""])[0]).strip().lower()
    active_section_id = section_id if section_by_id(section_id) else ""
    folder_ids = folder_ids_for_section(section_id)
    scans = {folder_id: scan_folder(FOLDER_BY_ID[folder_id]) for folder_id in folder_ids}
    payload = {
        "ok": True,
        "updated_at": now,
        "sections": build_sections(scans, active_section_id),
        "folders": list(scans.values()),
        "arr_workers": arr_workers_status() if section_id in {"", "movies"} else {},
    }
    if q and q.get("include_arr", [""])[0] == "1":
        payload["arr_status"] = fetch_arr_status(section_id)
    if q and q.get("include_qbit", [""])[0] == "1":
        payload["qbit_status"] = fetch_qbit_status(q.get("qbit_category", [""])[0])
    return payload


def seguimiento_children(q):
    source_id = q.get("source", [""])[0]
    item_name = q.get("name", [""])[0]
    parts = [str(item).strip() for item in q.get("part", []) if str(item).strip()]
    root, error = resolve_child_root(source_id, item_name, parts if parts else None)
    if error:
        return {"ok": False, "items": [], "error": error}
    return {"ok": True, "items": child_items(root, limit=0, include_dirs=True), "error": ""}


def seguimiento_move_browse(q):
    folder, clean_parts, error = resolve_media_move_folder(q.get("part", []))
    if error:
        return {"ok": False, "items": [], "parts": clean_parts, "error": error}

    items = media_move_folder_items(folder)
    return {
        "ok": True,
        "root": str(MEDIA_MOVE_ROOT),
        "path": str(folder),
        "parts": clean_parts,
        "parent_parts": clean_parts[:-1],
        "items": items,
        "count": len(items),
        "error": "",
    }


def normalize_search_text(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def search_words(value):
    text = normalize_search_text(value)
    clean = "".join(ch if ch.isalnum() else " " for ch in text)
    return [part for part in clean.split() if part]


def media_search_score(name, tokens):
    words = search_words(name)
    if not words:
        return None
    key = normalize_search_text(name)
    score = 0
    for token in tokens:
        if len(token) == 1:
            if not words[0].startswith(token):
                return None
            continue
        if key.startswith(token) or words[0].startswith(token):
            continue
        if any(word.startswith(token) for word in words):
            score += 1
            continue
        if len(token) >= 3 and token in key:
            score += 3
            continue
        return None
    return score


def seguimiento_media_search(q):
    source_id = q.get("source", [""])[0]
    query = str(q.get("query", [""])[0] or "").strip()
    if source_id not in SEARCHABLE_MEDIA_FOLDERS:
        return {"ok": False, "items": [], "count": 0, "error": "Buscador no disponible"}

    folder = FOLDER_BY_ID.get(source_id)
    root = Path(folder["path"]) if folder else None
    if not root or not root.is_dir():
        return {"ok": False, "items": [], "count": 0, "error": "No accesible"}

    tokens = search_words(query)
    if not tokens:
        return {"ok": True, "items": [], "count": 0, "query": query}

    items = []
    try:
        entries = []
        for entry in os.scandir(root):
            try:
                score = media_search_score(entry.name, tokens)
                if score is None:
                    continue
                st = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                entries.append((score, entry.name, path, st))
            except OSError as exc:
                log_error(f"No se pudo leer entrada de busqueda {entry.path}: {exc}")

        entries.sort(key=lambda row: (row[0], normalize_search_text(row[1])))
        for _, name, path, st in entries:
            item = {
                "name": name,
                "kind": item_kind(path),
                "size": None if path.is_dir() else format_size(st.st_size),
                "mtime": activity_time(st),
                "can_expand": bool(folder.get("lazy_children") and path.is_dir()),
                "children_source": source_id,
            }
            if path.is_file() and path.suffix.lower() == ".txt":
                item["text"] = read_text_content(path)
            items.append(item)
    except OSError as exc:
        log_error(f"No se pudo buscar en {folder['real_path']}: {exc}")
        return {"ok": False, "items": [], "count": 0, "error": "Error buscando"}

    return {"ok": True, "items": items, "count": len(items), "query": query}


def seguimiento_item_action(q):
    action = q.get("action", [""])[0]
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}

    try:
        if action in MOVE_DESTINATIONS:
            return move_target_to_destination(target, action)
        if action == "move_custom":
            return move_target_to_custom_destination(target, q.get("dest_part", []))
        if action == "delete":
            confirmed = str(q.get("confirm", [""])[0]).strip().lower() in {"1", "true", "si", "sÃ­"}
            if not confirmed:
                return {"ok": False, "error": "Confirmacion requerida"}
            return delete_target(target)
    except Exception as exc:
        log_error(f"No se pudo ejecutar accion sobre {target}: {exc}")
        return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": "Accion no permitida"}


def seguimiento_item_rename(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}

    try:
        return rename_target(target, q.get("name", [""])[0])
    except Exception as exc:
        log_error(f"No se pudo renombrar {target}: {exc}")
        return {"ok": False, "error": str(exc)}


def seguimiento_item_video(q):
    source_id = q.get("source", [""])[0]
    target, error = resolve_action_target(source_id, q.get("part", []))
    if error:
        return {"ok": False, "error": error}
    if not target.is_file() or item_kind(target) != "video":
        return {"ok": False, "error": "No es un video"}

    try:
        st = target.stat()
        info = {}
        streams = {"ok": False, "streams": [], "error": ""}
        try:
            from api.modulos.delay_audio.routes import info_archivo, pistas_audio
            info = info_archivo(str(target)) or {}
            streams = pistas_audio(str(target)) or streams
        except Exception as exc:
            streams = {"ok": False, "streams": [], "error": str(exc)}
        return {
            "ok": True,
            "name": target.name,
            "path": str(target),
            "kind": "video",
            "size": format_size(st.st_size),
            "mtime": activity_time(st),
            "duration": info.get("duration", ""),
            "date": info.get("date", ""),
            "streams": streams.get("streams", []) if streams.get("ok") else [],
            "streams_ok": bool(streams.get("ok")),
            "streams_error": "" if streams.get("ok") else streams.get("error", "No pude leer audios"),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def vista_seguimiento():
    data = seguimiento_status()
    cards = []
    for section in data["sections"]:
        count = sum(folder.get("count", 0) for folder in section["folders"])
        cards.append(f'<button class="card"><span>{section["label"]}</span><b>{count}</b></button>')
    return f'<div class="grid">{"".join(cards)}</div>'


def vista_carpeta(nombre):
    folder = FOLDER_BY_ID.get(nombre)
    if not folder:
        return '<div class="box"><h2>No encontrado</h2></div>'
    scan = scan_folder(folder)
    rows = []
    for item in scan["items"]:
        rows.append(f'<div class="item"><b>{item["name"]}</b><div>{item["kind"]}</div></div>')
    if not rows:
        rows = ['<div class="empty">No hay nada aqui.</div>']
    return f'<div class="box"><h2>{scan["name"]}</h2><small>{scan["path"]}</small></div>{"".join(rows)}'
