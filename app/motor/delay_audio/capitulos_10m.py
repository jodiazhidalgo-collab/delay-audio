from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET


INTERVAL_SECONDS = 600.0


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def _video_duration(path: Path) -> float:
    proc = _run([
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        str(path),
    ], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "ffprobe no pudo leer la duracion").strip())
    raw = json.loads(proc.stdout or "{}")
    duration = float((raw.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("duracion no valida")
    return duration


def _chapter_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    nanos = int(round((seconds - whole) * 1_000_000_000))
    if nanos >= 1_000_000_000:
        whole += 1
        nanos -= 1_000_000_000
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{nanos:09d}"


def _chapters_xml(duration: float) -> tuple[str, int]:
    root = ET.Element("Chapters")
    edition = ET.SubElement(root, "EditionEntry")
    ET.SubElement(edition, "EditionFlagDefault").text = "1"
    ET.SubElement(edition, "EditionFlagHidden").text = "0"

    count = 0
    start = 0.0
    while start < duration:
        end = min(start + INTERVAL_SECONDS, duration)
        count += 1
        atom = ET.SubElement(edition, "ChapterAtom")
        ET.SubElement(atom, "ChapterTimeStart").text = _chapter_time(start)
        ET.SubElement(atom, "ChapterTimeEnd").text = _chapter_time(end)
        ET.SubElement(atom, "ChapterFlagHidden").text = "0"
        ET.SubElement(atom, "ChapterFlagEnabled").text = "1"
        display = ET.SubElement(atom, "ChapterDisplay")
        ET.SubElement(display, "ChapterString").text = f"Capítulo {count:02d}"
        ET.SubElement(display, "ChapterLanguage").text = "spa"
        start += INTERVAL_SECONDS

    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n", count


def apply_chapters_10m(video_path: str | Path) -> dict[str, object]:
    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": "No encuentro el video"}
    if path.suffix.lower() != ".mkv":
        return {"ok": False, "error": "Capitulos cada 10 min solo disponible en MKV"}

    duration = _video_duration(path)
    xml_text, count = _chapters_xml(duration)
    tmp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-8", delete=False) as tmp:
            tmp.write(xml_text)
            tmp_path = Path(tmp.name)

        proc = _run([
            "mkvpropedit",
            str(path),
            "--tags",
            "all:",
            "--chapters",
            str(tmp_path),
        ], timeout=180)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "mkvpropedit fallo").strip())

        return {
            "ok": True,
            "message": f"Capitulos cada 10 min aplicados ({count})",
            "count": count,
            "video": str(path),
        }
    finally:
        if tmp_path:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
