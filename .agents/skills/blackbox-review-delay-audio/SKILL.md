---
name: blackbox-review-delay-audio
description: Revisar diagnosticos blackbox de Delay Audio, previews y jobs de Seguimiento antes de tocar medicion, exportacion, preview, edicion de trailer o seguimiento. Usar el area y job afectados para separar el fallo real del ruido.
---

# Blackbox Review delay audio

## Flujo

1. No editar codigo al empezar.
2. Elegir el area afectada: `delay`, `preview` o `seguimiento`.
3. Si se conoce el job, pasarlo con `-JobId`; si no, revisar el ultimo del area elegida.
4. Resumir solo la evidencia util e indicar si el fallo parece UI, API, motor, ffmpeg/mkvmerge, preview o diagnostico.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\blackbox-review-delay-audio\scripts\check_latest_blackbox.ps1
```

Job concreto de Delay Audio:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\blackbox-review-delay-audio\scripts\check_latest_blackbox.ps1 -Area delay -JobId "job_id"
```

Ultimo preview o job de Seguimiento:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\blackbox-review-delay-audio\scripts\check_latest_blackbox.ps1 -Area preview
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\blackbox-review-delay-audio\scripts\check_latest_blackbox.ps1 -Area seguimiento
```

## Fuentes

- Delay Audio y Seguimiento: `LEEME_CODEX.txt`, `errores.json`, `timeline.json`, `eventos.jsonl`, `comandos.json`, `resultado.json` y `logs_filtrados.txt`.
- Preview: `preview.json` y `preview.log`.
- `eventos.jsonl` es la verdad principal; `timeline.json` debe derivarse de sus eventos.

## Reglas

- No volcar logs enormes.
- No mostrar credenciales ni rutas sensibles innecesarias.
- Si no hay diagnosticos recientes, decirlo claro y no inventar.
- Si el fallo es visible, la UI manda sobre logs internos.
