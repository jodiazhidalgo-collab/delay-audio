from api.modulos.delay_audio import delay_audio_api, vista_delay_audio
from api.modulos.seguimiento.routes import (
    arr_workers_status,
    seguimiento_children,
    seguimiento_item_action,
    seguimiento_item_rename,
    seguimiento_item_video,
    seguimiento_media_search,
    seguimiento_move_browse,
    seguimiento_qbit_delete,
    seguimiento_status,
    seguimiento_subtitle_target_browse,
    seguimiento_trailer_audio,
    seguimiento_trailer_chapters,
    seguimiento_trailer_delete,
    seguimiento_trailer_info,
    seguimiento_trailer_job_start,
    seguimiento_trailer_job_status,
    seguimiento_trailer_language,
    set_arr_workers,
    vista_carpeta,
    vista_seguimiento,
)


def respuesta_api_post(path, data):
    if path == "/api" and data.get("v") == "seguimiento_qbit_delete":
        return seguimiento_qbit_delete(data)
    return {"ok": False, "error": "POST no permitido"}


def respuesta_api(q):
    v = q.get("v", ["delay_audio"])[0]

    if v == "seguimiento":
        return {"titulo": "Seguimiento", "activa": "seguimiento", "html": vista_seguimiento()}
    if v == "seguimiento_status":
        return seguimiento_status(q)
    if v == "arr_workers_status":
        return arr_workers_status()
    if v == "arr_workers_set":
        return set_arr_workers(q)
    if v == "seguimiento_children":
        return seguimiento_children(q)
    if v == "seguimiento_media_search":
        return seguimiento_media_search(q)
    if v == "seguimiento_move_browse":
        return seguimiento_move_browse(q)
    if v == "seguimiento_subtitle_target_browse":
        return seguimiento_subtitle_target_browse(q)
    if v == "seguimiento_item_action":
        return seguimiento_item_action(q)
    if v == "seguimiento_item_rename":
        return seguimiento_item_rename(q)
    if v == "seguimiento_item_video":
        return seguimiento_item_video(q)
    if v == "seguimiento_trailer_info":
        return seguimiento_trailer_info(q)
    if v == "seguimiento_trailer_delete":
        return seguimiento_trailer_delete(q)
    if v == "seguimiento_trailer_audio":
        return seguimiento_trailer_audio(q)
    if v == "seguimiento_trailer_job_start":
        return seguimiento_trailer_job_start(q)
    if v == "seguimiento_trailer_job_status":
        return seguimiento_trailer_job_status(q)
    if v == "seguimiento_trailer_chapters":
        return seguimiento_trailer_chapters(q)
    if v == "seguimiento_trailer_language":
        return seguimiento_trailer_language(q)
    if v == "delay_audio":
        return {"titulo": "Delay Audio", "activa": "delay_audio", "html": vista_delay_audio()}
    if v.startswith("delay_audio_"):
        return delay_audio_api(q)
    if v == "carpeta":
        n = q.get("n", ["cuarentena"])[0]
        return {"titulo": n, "activa": "seguimiento", "html": vista_carpeta(n)}

    return {"titulo": "Delay Audio", "activa": "delay_audio", "html": vista_delay_audio()}
