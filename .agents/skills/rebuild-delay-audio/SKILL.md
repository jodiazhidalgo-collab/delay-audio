---
name: rebuild-delay-audio
description: Reconstruir y validar el servicio Docker independiente delay-audio desde su compose propio. Usar despues de cambios en web, backend, frontend, Docker, requisitos o configuracion funcional.
---

# Rebuild delay audio

## Flujo

1. Confirmar que el cambio afecta al servicio independiente `delay-audio`.
2. Ejecutar `git status --short` si hay Git para saber si hay cambios pendientes antes del rebuild.
3. Ejecutar el script desde la raiz del proyecto.
4. Revisar salida de rebuild, contenedor y HTTP.
5. Si falla, responder con causa probable, archivo tocado y error clave.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\rebuild-delay-audio\scripts\rebuild_and_check.ps1
```

## Reglas

- No pedir confirmacion para rebuild del servicio principal cuando el cambio lo requiera.
- No tocar otros servicios.
- Usar exclusivamente `/volume1/docker/delay audio/docker-compose.yaml` y el proyecto Compose `delayaudio`.
- No usar el compose maestro de `web` ni conectar el servicio a `web_default`.
- Usar bloque remoto limpio por SSH; no meter comandos largos con comillas anidadas.
- Validar siempre contenedor y HTTP `9004`.
- No declarar caida por un primer HTTP temporal tras rebuild; el script debe reintentar antes de fallar.
