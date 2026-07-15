#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

from capitulos_10m import apply_chapters_10m as apply_chapters_10m_mkv


SUPPORTED_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv"}
SUBTITLE_LANGUAGE_ALIASES = {
    "es": "spa",
    "spa": "spa",
    "spanish": "spa",
    "espanol": "spa",
    "español": "spa",
    "castellano": "spa",
    "castilian": "spa",
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "ingles": "eng",
    "inglés": "eng",
    "fr": "fra",
    "fra": "fra",
    "fre": "fra",
    "french": "fra",
    "frances": "fra",
    "francés": "fra",
    "de": "deu",
    "deu": "deu",
    "ger": "deu",
    "german": "deu",
    "aleman": "deu",
    "alemán": "deu",
    "it": "ita",
    "ita": "ita",
    "italian": "ita",
    "italiano": "ita",
    "pt": "por",
    "por": "por",
    "portuguese": "por",
    "portugues": "por",
    "português": "por",
    "ja": "jpn",
    "jpn": "jpn",
    "japanese": "jpn",
    "japones": "jpn",
    "japonés": "jpn",
    "ru": "rus",
    "rus": "rus",
    "russian": "rus",
    "ruso": "rus",
    "ca": "cat",
    "cat": "cat",
    "catalan": "cat",
    "catalán": "cat",
    "gl": "glg",
    "glg": "glg",
    "galician": "glg",
    "gallego": "glg",
    "eu": "eus",
    "eus": "eus",
    "baq": "eus",
    "basque": "eus",
    "euskera": "eus",
}
SUBTITLE_SUFFIX_QUALIFIERS = {
    "cc",
    "default",
    "forced",
    "forzado",
    "forzados",
    "full",
    "hearingimpaired",
    "hi",
    "lyrics",
    "sdh",
    "sign",
    "signs",
}


def run_cmd(cmd, timeout=120):
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def write_progress(progress_path, phase, percent, label):
    if not progress_path:
        return
    try:
        value = max(0, min(100, int(round(float(percent)))))
    except Exception:
        value = 0
    data = {
        "phase": phase,
        "percent": value,
        "label": label,
        "updated_at": time.time(),
    }
    tmp_path = f"{progress_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, progress_path)


def tail_lines(lines, limit=80):
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def parse_ffmpeg_out_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text) / 1000000.0)
    except Exception:
        pass
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def run_ffmpeg_with_progress(cmd, total_seconds, progress_path, phase, label, timeout=21600):
    write_progress(progress_path, phase, 0, label)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    deadline = time.time() + timeout
    output = []
    last_percent = -1
    duration = max(0.0, float(total_seconds or 0))

    while True:
        if process.stdout is None:
            break
        if time.time() > deadline:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, timeout)
        if process.poll() is not None:
            tail = process.stdout.read()
            if tail:
                output.extend(tail.splitlines())
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.5)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        text = line.strip()
        if text:
            output = tail_lines(output + [text])
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        if key in {"out_time_ms", "out_time_us", "out_time"} and duration > 0:
            seconds = parse_ffmpeg_out_time(value)
            if seconds is None:
                continue
            percent = max(0, min(99, int((seconds / duration) * 100)))
            if percent != last_percent:
                write_progress(progress_path, phase, percent, label)
                last_percent = percent
        elif key == "progress" and value.strip() == "end":
            write_progress(progress_path, phase, 100, label)

    return subprocess.CompletedProcess(cmd, process.wait(), "\n".join(output), "")


def parse_mkvmerge_percent(text):
    for pattern in (r"#GUI#progress\s+([0-9]{1,3})\s*%?", r"Progress:\s*([0-9]{1,3})\s*%"):
        match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
        if match:
            return max(0, min(100, int(match.group(1))))
    return None


def run_mkvmerge_with_progress(cmd, progress_path, phase, label, timeout=21600):
    write_progress(progress_path, phase, 0, label)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    deadline = time.time() + timeout
    output = []
    last_percent = -1

    while True:
        if process.stdout is None:
            break
        if time.time() > deadline:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, timeout)
        if process.poll() is not None:
            tail = process.stdout.read()
            if tail:
                output.extend(tail.splitlines())
            break
        readable, _, _ = select.select([process.stdout], [], [], 0.5)
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        text = line.strip()
        if text:
            output = tail_lines(output + [text])
        percent = parse_mkvmerge_percent(text)
        if percent is not None and percent != last_percent:
            write_progress(progress_path, phase, percent, label)
            last_percent = percent

    return subprocess.CompletedProcess(cmd, process.wait(), "\n".join(output), "")


def json_cmd(cmd, timeout=120):
    proc = run_cmd(cmd, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "No pude leer el archivo").strip())
    return json.loads(proc.stdout or "{}")


def human_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            rounded = round(value, 1)
            text = str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"
            return f"{text} {unit}"
        value /= 1024
    return f"{size} B"


def duration_label(value):
    try:
        seconds = max(0, int(round(float(value))))
    except Exception:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_positive_int(value):
    try:
        number = int(str(value).strip())
    except Exception:
        return None
    return number if number >= 0 else None


def duration_seconds(path):
    try:
        data = json_cmd([
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ], timeout=45)
        return float((data.get("format") or {}).get("duration") or 0)
    except Exception:
        return 0.0


def lang_label(value):
    raw = str(value or "").strip()
    low = raw.lower()
    if not raw or low in {"und", "undefined", "undetermined", "unknown"}:
        return "UND"
    if low in {"spa", "es", "es-es", "spanish", "castilian"}:
        return "Espanol"
    if low in {"eng", "en", "en-us", "en-gb", "english"}:
        return "Ingles"
    if low in {"rus", "ru", "russian"}:
        return "RUS"
    return raw.upper() if len(raw) <= 3 else raw


def subtitle_language_from_filename(subtitle_path):
    stem = Path(subtitle_path).stem
    tokens = [
        token.lower()
        for token in re.split(r"[.\s_\-\[\]()]+", stem)
        if token.strip()
    ]
    while tokens and tokens[-1] in SUBTITLE_SUFFIX_QUALIFIERS:
        tokens.pop()
    if not tokens:
        return "und"
    return SUBTITLE_LANGUAGE_ALIASES.get(tokens[-1], "und")


def stream_title(stream):
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    return str(tags.get("title") or tags.get("handler_name") or "").strip()


def stream_lang(stream):
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    return lang_label(tags.get("language") or stream.get("language") or "")


def clean_channel_layout(value):
    text = str(value or "").strip()
    return text.replace("(side)", "").replace("(SIDE)", "").replace("(Side)", "").strip()


def stream_flags(stream):
    disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
    flags = []
    if disposition.get("default"):
        flags.append("default")
    if disposition.get("forced"):
        flags.append("forzado")
    return flags


def video_streams(data):
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    return [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]


def audio_streams(data):
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    return [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]


def subtitle_streams(data):
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    return [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "subtitle"]


def mkv_subtitle_tracks(path):
    if path.suffix.lower() != ".mkv":
        return []
    data = json_cmd(["mkvmerge", "-J", str(path)], timeout=60)
    tracks = data.get("tracks") if isinstance(data.get("tracks"), list) else []
    out = []
    for track in tracks:
        if not isinstance(track, dict) or track.get("type") != "subtitles":
            continue
        track_id = track.get("id")
        if track_id is None:
            continue
        props = track.get("properties") if isinstance(track.get("properties"), dict) else {}
        count = (
            parse_positive_int(props.get("num_index_entries"))
            or parse_positive_int(props.get("tag_number_of_frames"))
            or parse_positive_int(props.get("number_of_frames"))
        )
        out.append({
            "id": str(track_id),
            "codec": str(track.get("codec") or ""),
            "language": str(props.get("language") or props.get("language_ietf") or ""),
            "name": str(props.get("track_name") or ""),
            "default": bool(props.get("default_track")),
            "forced": bool(props.get("forced_track")),
            "count": count,
        })
    return out


def mkv_track_type_counts(path):
    data = json_cmd(["mkvmerge", "-J", str(path)], timeout=60)
    tracks = data.get("tracks") if isinstance(data.get("tracks"), list) else []
    counts = {"video": 0, "audio": 0, "subtitles": 0}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_type = str(track.get("type") or "")
        if track_type in counts:
            counts[track_type] += 1
    return counts


def ffprobe_data(path):
    return json_cmd([
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ], timeout=60)


def ffprobe_subtitle_counts(path):
    try:
        data = json_cmd([
            "ffprobe",
            "-v",
            "error",
            "-count_packets",
            "-select_streams",
            "s",
            "-print_format",
            "json",
            "-show_entries",
            "stream=index,nb_frames,nb_read_frames,nb_read_packets",
            str(path),
        ], timeout=120)
    except Exception:
        return {}

    counts = {}
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        index = stream.get("index")
        if index is None:
            continue
        count = (
            parse_positive_int(stream.get("nb_read_packets"))
            or parse_positive_int(stream.get("nb_read_frames"))
            or parse_positive_int(stream.get("nb_frames"))
        )
        if count is not None:
            counts[str(index)] = count
    return counts


def media_info(video_path):
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"ok": False, "error": "Formato soportado: MKV, MP4 o AVI"}

    data = ffprobe_data(path)
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    mkv_subs = mkv_subtitle_tracks(path)
    subtitle_counts = {} if path.suffix.lower() == ".mkv" else ffprobe_subtitle_counts(path)

    out = {
        "format": str(fmt.get("format_name") or path.suffix.lstrip(".").upper()).upper(),
        "duration": duration_label(fmt.get("duration")),
        "size": human_size(path.stat().st_size),
        "video": [],
        "audio": [],
        "subtitles": [],
    }

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        stream_type = str(stream.get("codec_type") or "").lower()
        codec = str(stream.get("codec_name") or "").upper()
        title = stream_title(stream)
        lang = stream_lang(stream)
        flags = stream_flags(stream)

        if stream_type == "video":
            stream_id = str(stream.get("index") if stream.get("index") is not None else "")
            dims = ""
            try:
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
                if width and height:
                    dims = f"{width}x{height}"
            except Exception:
                dims = ""
            bits = [x for x in (lang, codec, dims, str(stream.get("profile") or "").strip(), title, " / ".join(flags)) if x]
            out["video"].append({
                "id": stream_id,
                "label": " / ".join(bits) or "Video",
                "selectable": bool(stream_id),
            })
        elif stream_type == "audio":
            stream_id = str(stream.get("index") if stream.get("index") is not None else "")
            channels = ""
            try:
                ch = int(stream.get("channels") or 0)
                if ch:
                    channels = f"{ch}ch"
            except Exception:
                channels = ""
            layout = clean_channel_layout(stream.get("channel_layout"))
            bits = [x for x in (lang, codec, layout, channels, title, " / ".join(flags)) if x]
            out["audio"].append({
                "id": stream_id,
                "label": " / ".join(bits) or "Audio",
                "convertible": bool(stream_id),
            })
        elif stream_type == "subtitle":
            bits = [x for x in (lang, codec, title, " / ".join(flags)) if x]
            label = " / ".join(bits) or "Subtitulo"
            if path.suffix.lower() == ".mkv":
                track_index = len(out["subtitles"])
                track = mkv_subs[track_index] if track_index < len(mkv_subs) else {}
                track_id = str(track.get("id") or "")
                count = track.get("count")
            else:
                track_id = str(stream.get("index") if stream.get("index") is not None else "")
                count = (
                    subtitle_counts.get(track_id)
                    or parse_positive_int(stream.get("nb_frames"))
                    or parse_positive_int(stream.get("nb_read_frames"))
                    or parse_positive_int(stream.get("nb_read_packets"))
                )
            out["subtitles"].append({
                "id": track_id,
                "label": label,
                "removable": bool(track_id),
                "count": count,
            })

    return {"ok": True, "path": str(path), "name": path.name, "info": out}


def copy_stat(src, dst):
    stat = src.stat()
    try:
        os.chmod(dst, stat.st_mode & 0o777)
        os.chown(dst, stat.st_uid, stat.st_gid)
    except Exception:
        pass


def validate_duration(original, candidate):
    before = duration_seconds(original)
    after = duration_seconds(candidate)
    if before <= 0 or after <= 0:
        return
    tolerance = max(2.0, before * 0.03)
    if abs(before - after) > tolerance:
        raise RuntimeError("La duracion del temporal no coincide con el original")


def temp_path_for(path, tag="sin-trailer"):
    stamp = f"{int(time.time())}-{os.getpid()}"
    return path.with_name(f".{path.stem}.{tag}-{stamp}.tmp{path.suffix}")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_srt_to_mkv(video_path, subtitle_path, progress_path=None):
    path = Path(video_path)
    subtitle = Path(subtitle_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el MKV"}
    if path.suffix.lower() != ".mkv":
        return {"ok": False, "error": "El destino debe ser MKV"}
    if not subtitle.exists() or not subtitle.is_file():
        return {"ok": False, "error": "No encuentro el SRT"}
    if subtitle.suffix.lower() != ".srt":
        return {"ok": False, "error": "El subtitulo debe ser SRT"}

    language = subtitle_language_from_filename(subtitle)
    source_size = subtitle.stat().st_size
    source_digest = file_sha256(subtitle)
    original_stat = path.stat()
    counts_before = mkv_track_type_counts(path)
    subtitles_before = mkv_subtitle_tracks(path)
    tmp_path = temp_path_for(path, "add-srt")
    cmd = [
        "mkvmerge",
        "-o",
        str(tmp_path),
        str(path),
        "--language",
        f"0:{language}",
        "--track-name",
        "0:",
        "--default-track-flag",
        "0:no",
        "--forced-display-flag",
        "0:no",
        str(subtitle),
    ]
    if progress_path:
        cmd.insert(1, "--gui-mode")

    try:
        if progress_path:
            proc = run_mkvmerge_with_progress(
                cmd,
                progress_path,
                "subtitle_add",
                "Añadiendo subtítulo",
                timeout=21600,
            )
        else:
            proc = run_cmd(cmd, timeout=21600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "mkvmerge fallo").strip())
        if not tmp_path.exists() or tmp_path.stat().st_size <= 4096:
            raise RuntimeError("No se genero un temporal MKV valido")

        counts_after = mkv_track_type_counts(tmp_path)
        if counts_after["video"] != counts_before["video"]:
            raise RuntimeError("La comprobacion de video no coincide")
        if counts_after["audio"] != counts_before["audio"]:
            raise RuntimeError("La comprobacion de audio no coincide")
        if counts_after["subtitles"] != counts_before["subtitles"] + 1:
            raise RuntimeError("La comprobacion de subtitulos no coincide")

        subtitles_after = mkv_subtitle_tracks(tmp_path)
        if len(subtitles_after) != len(subtitles_before) + 1:
            raise RuntimeError("No se encontro la nueva pista de subtitulo")
        added_track = subtitles_after[-1]
        if added_track.get("language") != language:
            raise RuntimeError("El idioma del subtitulo añadido no coincide")
        if added_track.get("name"):
            raise RuntimeError("El nombre de la pista de subtitulo no quedo vacio")
        if added_track.get("default"):
            raise RuntimeError("La pista de subtitulo quedo como predeterminada")
        if added_track.get("forced"):
            raise RuntimeError("La pista de subtitulo quedo como forzada")

        validate_duration(path, tmp_path)
        if not subtitle.exists() or subtitle.stat().st_size != source_size or file_sha256(subtitle) != source_digest:
            raise RuntimeError("El SRT original cambio durante el proceso")

        copy_stat(path, tmp_path)
        try:
            os.utime(tmp_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        except Exception:
            pass
        os.replace(tmp_path, path)

        if not subtitle.exists() or subtitle.stat().st_size != source_size or file_sha256(subtitle) != source_digest:
            raise RuntimeError("El SRT original no se conservo intacto")

        refreshed = media_info(path)
        return {
            "ok": True,
            "message": "Subtítulo añadido al MKV",
            "language": language,
            "added_track": added_track,
            "source_preserved": True,
            "info": refreshed.get("info"),
            "path": str(path),
            "name": path.name,
        }
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def remux_mkv_temporal(candidate, original, progress_path=None, phase="audio", label="Remuxando"):
    remux_path = temp_path_for(original, "mkvmerge")
    cmd = ["mkvmerge", "-o", str(remux_path), str(candidate)]
    if progress_path:
        cmd.insert(1, "--gui-mode")

    if progress_path:
        proc = run_mkvmerge_with_progress(cmd, progress_path, phase, label, timeout=21600)
    else:
        proc = run_cmd(cmd, timeout=21600)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "mkvmerge fallo remuxeando el MKV").strip())
    if not remux_path.exists() or remux_path.stat().st_size <= 4096:
        raise RuntimeError("No se genero un temporal remuxeado valido")
    validate_duration(original, remux_path)
    return remux_path


def parse_rename_ids(ids):
    video_ids = []
    audio_ids = []
    subtitle_ids = []
    for item in ids or []:
        raw = str(item or "").strip()
        if raw.startswith("video:"):
            value = raw.split(":", 1)[1].strip()
            if value:
                video_ids.append(value)
        elif raw.startswith("audio:"):
            value = raw.split(":", 1)[1].strip()
            if value:
                audio_ids.append(value)
        elif raw.startswith("subtitle:"):
            value = raw.split(":", 1)[1].strip()
            if value:
                subtitle_ids.append(value)
    return video_ids, audio_ids, subtitle_ids


def stream_ordinal_by_index(streams, selected_id):
    selected = str(selected_id or "").strip()
    for ordinal, stream in enumerate(streams):
        if str(stream.get("index")) == selected:
            return ordinal
    return None


def run_mkvpropedit_language(path, selectors, include_ietf=True):
    cmd = ["mkvpropedit", str(path)]
    for selector in selectors:
        cmd.extend(["--edit", selector, "--set", "language=spa"])
        if include_ietf:
            cmd.extend(["--set", "language-ietf=es"])
    return run_cmd(cmd, timeout=21600)


def rename_mkv_language_es(path, video_ids, audio_ids, subtitle_ids):
    data = ffprobe_data(path)
    videos = video_streams(data)
    audios = audio_streams(data)
    subtitles = mkv_subtitle_tracks(path)
    selectors = []

    for video_id in video_ids:
        ordinal = stream_ordinal_by_index(videos, video_id)
        if ordinal is None:
            return {"ok": False, "error": "La pista de video elegida no existe"}
        selectors.append(f"track:v{ordinal + 1}")

    for audio_id in audio_ids:
        ordinal = stream_ordinal_by_index(audios, audio_id)
        if ordinal is None:
            return {"ok": False, "error": "La pista de audio elegida no existe"}
        selectors.append(f"track:a{ordinal + 1}")

    subtitle_by_id = {str(item.get("id")): index for index, item in enumerate(subtitles)}
    for subtitle_id in subtitle_ids:
        ordinal = subtitle_by_id.get(str(subtitle_id))
        if ordinal is None:
            return {"ok": False, "error": "El subtitulo elegido no existe"}
        selectors.append(f"track:s{ordinal + 1}")

    if not selectors:
        return {"ok": False, "error": "Selecciona video, audio o subtitulo"}

    proc = run_mkvpropedit_language(path, selectors, include_ietf=True)
    if proc.returncode != 0:
        proc = run_mkvpropedit_language(path, selectors, include_ietf=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "mkvpropedit fallo cambiando idioma").strip())

    refreshed = media_info(path)
    return {
        "ok": True,
        "message": "Idioma renombrado a ES",
        "info": refreshed.get("info"),
        "path": str(path),
        "name": path.name,
    }


def rename_mp4_language_es(path, video_ids, audio_ids, subtitle_ids):
    before = ffprobe_data(path)
    videos_before = video_streams(before)
    audios_before = audio_streams(before)
    subtitles_before = subtitle_streams(before)
    video_ordinals = []
    audio_ordinals = []
    subtitle_ordinals = []

    for video_id in video_ids:
        ordinal = stream_ordinal_by_index(videos_before, video_id)
        if ordinal is None:
            return {"ok": False, "error": "La pista de video elegida no existe"}
        video_ordinals.append(ordinal)

    for audio_id in audio_ids:
        ordinal = stream_ordinal_by_index(audios_before, audio_id)
        if ordinal is None:
            return {"ok": False, "error": "La pista de audio elegida no existe"}
        audio_ordinals.append(ordinal)

    for subtitle_id in subtitle_ids:
        ordinal = stream_ordinal_by_index(subtitles_before, subtitle_id)
        if ordinal is None:
            return {"ok": False, "error": "El subtitulo elegido no existe"}
        subtitle_ordinals.append(ordinal)

    if not video_ordinals and not audio_ordinals and not subtitle_ordinals:
        return {"ok": False, "error": "Selecciona video, audio o subtitulo"}

    tmp_path = temp_path_for(path, "idioma-es")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
    ]
    for ordinal in video_ordinals:
        cmd.extend([f"-metadata:s:v:{ordinal}", "language=spa"])
    for ordinal in audio_ordinals:
        cmd.extend([f"-metadata:s:a:{ordinal}", "language=spa"])
    for ordinal in subtitle_ordinals:
        cmd.extend([f"-metadata:s:s:{ordinal}", "language=spa"])
    cmd.extend(["-movflags", "+faststart", str(tmp_path)])

    try:
        proc = run_cmd(cmd, timeout=21600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg fallo cambiando idioma").strip())
        if not tmp_path.exists() or tmp_path.stat().st_size <= 4096:
            raise RuntimeError("No se genero un temporal valido")

        after = ffprobe_data(tmp_path)
        if len(video_streams(after)) != len(videos_before):
            raise RuntimeError("El temporal no conservo todas las pistas de video")
        if len(audio_streams(after)) != len(audios_before):
            raise RuntimeError("El temporal no conservo todas las pistas de audio")
        if len(subtitle_streams(after)) != len(subtitles_before):
            raise RuntimeError("El temporal no conservo todos los subtitulos")
        validate_duration(path, tmp_path)
        copy_stat(path, tmp_path)
        os.replace(tmp_path, path)
        refreshed = media_info(path)
        return {
            "ok": True,
            "message": "Idioma renombrado a ES",
            "info": refreshed.get("info"),
            "path": str(path),
            "name": path.name,
        }
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def remove_mkv_subtitles(path, selected, progress_path=None):
    current = mkv_subtitle_tracks(path)
    subtitle_ids = {str(item.get("id")) for item in current}
    selected_ids = [str(item) for item in selected if str(item) in subtitle_ids]
    if not selected_ids:
        return {"ok": False, "error": "No hay subtitulos validos seleccionados"}

    keep = [str(item.get("id")) for item in current if str(item.get("id")) not in set(selected_ids)]
    tmp_path = temp_path_for(path)
    if keep:
        cmd = ["mkvmerge", "-o", str(tmp_path), "--subtitle-tracks", ",".join(keep), str(path)]
    else:
        cmd = ["mkvmerge", "-o", str(tmp_path), "--no-subtitles", str(path)]
    if progress_path:
        cmd.insert(1, "--gui-mode")

    try:
        if progress_path:
            proc = run_mkvmerge_with_progress(cmd, progress_path, "subtitle", "Eliminando", timeout=21600)
        else:
            proc = run_cmd(cmd, timeout=21600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "mkvmerge fallo").strip())
        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("No se genero un temporal valido")
        remaining = mkv_subtitle_tracks(tmp_path)
        expected = len(current) - len(selected_ids)
        if len(remaining) != expected:
            raise RuntimeError("La comprobacion de subtitulos no coincide")
        validate_duration(path, tmp_path)
        copy_stat(path, tmp_path)
        os.replace(tmp_path, path)
        return {
            "ok": True,
            "message": f"Subtitulos eliminados ({len(selected_ids)})",
            "removed": selected_ids,
            "remaining": len(remaining),
        }
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def remove_ffmpeg_subtitles(path, selected, progress_path=None):
    before = media_info(path)
    if not before.get("ok"):
        return before
    current = before["info"].get("subtitles") or []
    subtitle_ids = {str(item.get("id")) for item in current if item.get("removable")}
    selected_ids = [str(item) for item in selected if str(item) in subtitle_ids]
    if not selected_ids:
        return {"ok": False, "error": "No hay subtitulos validos seleccionados"}

    tmp_path = temp_path_for(path)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0",
    ]
    for track_id in selected_ids:
        cmd.extend(["-map", f"-0:{track_id}"])
    cmd.extend(["-c", "copy", "-map_metadata", "0", "-map_chapters", "0"])
    if path.suffix.lower() == ".mp4":
        cmd.extend(["-movflags", "+faststart"])
    if progress_path:
        cmd.extend(["-progress", "pipe:1", "-nostats"])
    cmd.append(str(tmp_path))

    try:
        if progress_path:
            proc = run_ffmpeg_with_progress(cmd, duration_seconds(path), progress_path, "subtitle", "Eliminando", timeout=21600)
        else:
            proc = run_cmd(cmd, timeout=21600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg fallo").strip())
        if not tmp_path.exists() or tmp_path.stat().st_size <= 0:
            raise RuntimeError("No se genero un temporal valido")

        after = media_info(tmp_path)
        if not after.get("ok"):
            raise RuntimeError(after.get("error") or "No pude verificar el temporal")
        remaining = after["info"].get("subtitles") or []
        expected = len(current) - len(selected_ids)
        if len(remaining) != expected:
            raise RuntimeError("La comprobacion de subtitulos no coincide")
        validate_duration(path, tmp_path)
        copy_stat(path, tmp_path)
        os.replace(tmp_path, path)
        return {
            "ok": True,
            "message": f"Subtitulos eliminados ({len(selected_ids)})",
            "removed": selected_ids,
            "remaining": len(remaining),
        }
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def convert_audio_ac3(video_path, audio_id, progress_path=None):
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"ok": False, "error": "Formato soportado: MKV, MP4, AVI, M2TS, TS, MOV o WMV"}

    selected_id = str(audio_id or "").strip()
    if not selected_id:
        return {"ok": False, "error": "Selecciona una pista de audio"}

    before = ffprobe_data(path)
    videos_before = video_streams(before)
    audios_before = audio_streams(before)
    if not videos_before:
        return {"ok": False, "error": "El archivo no tiene pista de video"}
    if not audios_before:
        return {"ok": False, "error": "El archivo no tiene pistas de audio"}

    audio_ordinal = None
    for index, stream in enumerate(audios_before):
        if str(stream.get("index")) == selected_id:
            audio_ordinal = index
            break
    if audio_ordinal is None:
        return {"ok": False, "error": "La pista de audio elegida no existe"}

    tmp_path = temp_path_for(path, "audio-ac3")
    remux_path = None
    final_path = None
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        f"-c:a:{audio_ordinal}",
        "ac3",
        f"-b:a:{audio_ordinal}",
        "640k",
        f"-ac:a:{audio_ordinal}",
        "6",
        f"-disposition:a:{audio_ordinal}",
        "default",
        "-max_interleave_delta",
        "0",
    ]
    if path.suffix.lower() == ".mp4":
        cmd.extend(["-movflags", "+faststart"])
    if progress_path:
        cmd.extend(["-progress", "pipe:1", "-nostats"])
    cmd.append(str(tmp_path))

    try:
        if progress_path:
            proc = run_ffmpeg_with_progress(cmd, duration_seconds(path), progress_path, "audio", "Convirtiendo", timeout=21600)
        else:
            proc = run_cmd(cmd, timeout=21600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "ffmpeg fallo convirtiendo el audio").strip())
        if not tmp_path.exists() or tmp_path.stat().st_size <= 4096:
            raise RuntimeError("No se genero un temporal valido")

        after = ffprobe_data(tmp_path)
        videos_after = video_streams(after)
        audios_after = audio_streams(after)
        if len(videos_after) < len(videos_before):
            raise RuntimeError("El temporal perdio pistas de video")
        if len(audios_after) != len(audios_before):
            raise RuntimeError("El temporal no conservo todas las pistas de audio")
        if audio_ordinal >= len(audios_after):
            raise RuntimeError("No pude verificar la pista convertida")

        converted = audios_after[audio_ordinal]
        if str(converted.get("codec_name") or "").lower() != "ac3":
            raise RuntimeError("La pista elegida no quedo como AC-3")
        try:
            channels = int(converted.get("channels") or 0)
        except Exception:
            channels = 0
        if channels != 6:
            raise RuntimeError("La pista elegida no quedo como AC-3 5.1")

        final_path = tmp_path
        if path.suffix.lower() == ".mkv":
            remux_path = remux_mkv_temporal(tmp_path, path, progress_path=progress_path, phase="audio", label="Remuxando")
            after = ffprobe_data(remux_path)
            videos_after = video_streams(after)
            audios_after = audio_streams(after)
            if len(videos_after) < len(videos_before):
                raise RuntimeError("El remux perdio pistas de video")
            if len(audios_after) != len(audios_before):
                raise RuntimeError("El remux no conservo todas las pistas de audio")
            if audio_ordinal >= len(audios_after):
                raise RuntimeError("No pude verificar la pista convertida tras remux")
            converted = audios_after[audio_ordinal]
            if str(converted.get("codec_name") or "").lower() != "ac3":
                raise RuntimeError("La pista elegida no quedo como AC-3 tras remux")
            try:
                channels = int(converted.get("channels") or 0)
            except Exception:
                channels = 0
            if channels != 6:
                raise RuntimeError("La pista elegida no quedo como AC-3 5.1 tras remux")
            final_path = remux_path

        validate_duration(path, final_path)
        copy_stat(path, final_path)
        os.replace(final_path, path)
        if final_path == tmp_path:
            tmp_path = None
        else:
            remux_path = None
        refreshed = media_info(path)
        return {
            "ok": True,
            "message": "Audio convertido a AC-3 5.1",
            "converted_audio": selected_id,
            "audio_tracks": len(audios_after),
            "info": refreshed.get("info"),
            "path": str(path),
            "name": path.name,
        }
    finally:
        for leftover in (tmp_path, remux_path):
            try:
                if leftover is not None and leftover.exists():
                    leftover.unlink()
            except Exception:
                pass


def remove_subtitles(video_path, ids, progress_path=None):
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"ok": False, "error": "Formato soportado: MKV, MP4 o AVI"}
    if path.suffix.lower() == ".mkv":
        result = remove_mkv_subtitles(path, ids, progress_path=progress_path)
    else:
        result = remove_ffmpeg_subtitles(path, ids, progress_path=progress_path)
    if result.get("ok"):
        refreshed = media_info(path)
        result["info"] = refreshed.get("info")
        result["path"] = str(path)
        result["name"] = path.name
    return result


def rename_language_es(video_path, ids):
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() == ".avi":
        return {"ok": False, "error": "AVI no soporta idioma interno fiable"}
    if path.suffix.lower() not in {".mkv", ".mp4"}:
        return {"ok": False, "error": "Idioma ES soportado en MKV y MP4"}

    video_ids, audio_ids, subtitle_ids = parse_rename_ids(ids)
    if not video_ids and not audio_ids and not subtitle_ids:
        return {"ok": False, "error": "Selecciona video, audio o subtitulo"}
    if path.suffix.lower() == ".mkv":
        return rename_mkv_language_es(path, video_ids, audio_ids, subtitle_ids)
    return rename_mp4_language_es(path, video_ids, audio_ids, subtitle_ids)


def apply_chapters_to_video(video_path, video_id=""):
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() != ".mkv":
        return {"ok": False, "error": "Capitulos cada 10 min solo disponible en MKV"}

    selected_id = str(video_id or "").strip()
    if selected_id:
        data = ffprobe_data(path)
        if stream_ordinal_by_index(video_streams(data), selected_id) is None:
            return {"ok": False, "error": "La pista de video elegida no existe"}

    result = apply_chapters_10m_mkv(path)
    if result.get("ok"):
        refreshed = media_info(path)
        result["info"] = refreshed.get("info")
        result["path"] = str(path)
        result["name"] = path.name
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("info", "delete", "add_subtitle", "convert_audio", "rename_language", "chapters_10m"))
    parser.add_argument("--path", required=True)
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--subtitle-path", default="")
    parser.add_argument("--progress-path", default="")
    args = parser.parse_args()

    try:
        if args.action == "info":
            payload = media_info(args.path)
        elif args.action == "add_subtitle":
            payload = add_srt_to_mkv(args.path, args.subtitle_path, progress_path=args.progress_path)
        elif args.action == "convert_audio":
            payload = convert_audio_ac3(args.path, args.id[0] if args.id else "", progress_path=args.progress_path)
        elif args.action == "rename_language":
            payload = rename_language_es(args.path, args.id)
        elif args.action == "chapters_10m":
            payload = apply_chapters_to_video(args.path, args.id[0] if args.id else "")
        else:
            payload = remove_subtitles(args.path, args.id, progress_path=args.progress_path)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
