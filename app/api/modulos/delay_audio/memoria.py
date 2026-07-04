import json
import os


MEMORIA_PATH = "/config/delay_audio_memoria.json"
DEFAULT_MEMORIA = {
    "ref_path": "",
    "esp_path": "",
    "output_path": "",
}


def leer_memoria():
    data = dict(DEFAULT_MEMORIA)
    try:
        if os.path.isfile(MEMORIA_PATH):
            with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update({k: str(saved.get(k, v) or v) for k, v in DEFAULT_MEMORIA.items()})
    except Exception:
        pass
    return data


def guardar_memoria(key, path):
    data = leer_memoria()
    if key in DEFAULT_MEMORIA:
        data[key] = str(path or DEFAULT_MEMORIA[key])
    os.makedirs(os.path.dirname(MEMORIA_PATH), exist_ok=True)
    with open(MEMORIA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data
