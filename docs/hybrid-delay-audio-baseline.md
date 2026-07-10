# Línea base del motor híbrido de Delay Audio

Fotografía previa a la implementación del motor híbrido. Todos los datos proceden de código, jobs y material real existentes. Los originales no se modificaron.

## Flujo actual de Taller

1. `delay_audio.js` selecciona `Video Bueno`, `Audio Español` y sus pistas, conserva el estado en `localStorage` y llama a `da=start`.
2. `routes.py::iniciar()` valida las entradas, lee la configuración y ejecuta `planificar_correccion_fps()`.
3. Si los FPS nominales difieren, `preparar_audio_fps_medicion()` crea un `.mka` AC-3 con `atempo + aresample`; no existe confirmación por duración e imagen.
4. `routes.py::_ejecutar_job()` llama a `medir_delay_audio.py`. Cuando hay corrección FPS, `--esp` apunta al `.mka` y el índice español pasa a `0`; el vídeo español original permanece en `job["esp"]` solo en la API en memoria.
5. El motor extrae PCM mono a 8 kHz, crea envolventes de 20 ms, combina correlación de envolvente y derivada, agrupa delays y devuelve `delay_ms` y `confidence`.
6. `exportar_si_corresponde()` autoriza con `result.ok` y `confidence >= MEDIA`.
7. La exportación conserva el vídeo bueno sin recodificar, normaliza el audio español, añade subtítulos y crea primero un `.delay-audio-part` con `mkvmerge`.
8. La validación comprueba estructura, pistas, duración, primer paquete y demux inicial/final. No comprueba sincronía audiovisual.
9. Los temporales RAW, `.mka` y `.delay-audio-part` se limpian en sus rutas de job.
10. La web muestra delay, confianza, zonas y estado de exportación. La caja negra deriva `timeline.json` de `eventos.jsonl`.

## Diferencias actuales entre perfiles

| Parámetro | Película | Tráiler |
|---|---:|---:|
| Segmento | 240 s | 8–20 s según duración |
| Búsqueda | ±120 s | 5–30 s según duración |
| Zonas máximas | 10 | 10 |
| Distribución | ratios separados | uniforme |
| Tolerancia de clúster | 700 ms | 500 ms |

Ambos perfiles usan el mismo correlador, el mismo modelo de confianza y la misma puerta de exportación.

## Línea base de jobs reales

| Caso | Job | Metadatos instrumentados | FPS | Medición | Audio final | `mkvmerge` | Resultado |
|---|---|---:|---:|---:|---:|---:|---|
| Mr. Bean | `20260709_044722_93603664` | 0,28 s | no aplicada, 23.976/23.976 | 84,90 s | 55,15 s | 152,12 s | `96.540 ms`, MEDIA, clúster de 1 zona, exportado |
| Whistle 24→23.976 | `20260708_232123_7d45ef10` | 0,35 s | 45,15 s | 28,76 s | no, Solo medir | no | `15.028 ms`, ALTA, 10 zonas |
| Película 24/24 | `20260709_012603_9963907a` | 0,30 s | no aplicada | 83,76 s | 47,01 s | 197,04 s | `18.273 ms`, ALTA, 10 zonas, exportado |
| Tráiler sintético histórico | `20260708_232826_7041b9b9` | 0,32 s | 1,01 s | 3,59 s | 0,94 s | 0,41 s | `7.218 ms`, MEDIA, 2 zonas, exportado |

La detección FPS previa a crear el job no tenía temporización propia. Los tiempos de metadatos anteriores suman los cuatro `ffprobe` internos de duración y pistas.

## Línea base adicional con tráiler real

- Archivo: `/volume1/UGREEN/data/media/movies/A Working Man (2025)/A Working Man (2025)-trailer.mp4`.
- Perfil: `trailer`.
- Prueba: mismo archivo como referencia y fuente, sin exportación, dentro de `_codex_runtime`.
- Resultado: `0 ms`, `ALTA`, 10/10 zonas, score medio `0,999`.
- Comandos de extracción: 2,40 s; probes: 0,30 s.
- Observación: el resultado era evidente desde las primeras zonas, pero el motor antiguo agotó las diez.

La ejecución directa desde Windows sobre SMB mostró un `WinError 5` al reemplazar `timeline.json.tmp`; la repetición dentro del contenedor Linux terminó correctamente. Esto es una diferencia del entorno de prueba, no una caída del servicio.

## Por qué Mr. Bean fue autorizado

Los delays por zona fueron `600`, `13.180`, `33.020`, `55.940`, `76.040`, `96.540`, `115.380`, `118.200`, `-109.940` y `59.640 ms`: no había un delay fijo.

`recommended_delay()` permitió que la zona de `96.540 ms`, score `0,488`, formase sola el clúster ganador. Su regla concede `MEDIA` a una sola zona cuando el score medio supera `0,30`. Después `exportar_si_corresponde()` aceptó `MEDIA`, porque no existen todavía `state` ni `export_allowed`. La validación final solo demostró que el MKV era técnicamente legible.

## Rutas actuales de material obligatorio

- Mr. Bean bueno: `/volume1/UGREEN/data/media/Hospital/[superseed.byethost7.com] Mr.Beans.Holiday.2007.MULTI.HDR.2160p.WEB.DL.DTS.HD.MA.AC3-ChrisVPS.mkv.ts`.
- Mr. Bean español localizado: `/volume1/UGREEN/data/media/Hospital/Las vacaciones de Mr. Bean/Las vacaciones de Mr. Bean (2007).mkv`.
- Película normal: Enola Holmes 3, versiones 24 fps 4K HDR y 480p SDR bajo `media/movies` y `media/repetidas_vs_error`.
- Tráilers reales: Whistle, Enola Holmes 3, Espacio Tiempo y A Working Man bajo `media/movies`.

La pareja histórica Whistle 24→23.976 ya no está disponible. Sus jobs conservan la evidencia completa, pero los dos archivos Whistle actuales son 24 fps y no deben presentarse como sustitutos. La activación final queda condicionada a recuperar esa pareja o a una prueba real equivalente expresamente válida.

## Huecos confirmados antes de implementar

- No existe comparador visual automático.
- Los FPS nominales activan corrección sin confirmación.
- La ruta original española puede quedar sobrescrita por el `.mka` en `job.json`.
- Una única zona y `MEDIA` pueden exportar.
- No existe compuerta semántica de exportación.
- No hay fast path ni escalado adaptativo.
- La caja negra no registra hipótesis visuales, candidatos ni decisión de exportación.
- No había una suite automatizada en el repositorio.

## Puerta de Fase 0

La Fase 0 queda aprobada: se conoce dónde se autoriza Mr. Bean, cómo viaja el `.mka`, qué conserva la API como vídeo original y qué diferencias reales existen entre Película y Tráiler. La siguiente fase puede crear el comparador visual aislado sin conectarlo todavía a la exportación.
