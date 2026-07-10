# Taller Delay Audio

Contrato funcional de Taller. Cualquier cambio de comportamiento debe actualizar este documento en el mismo cambio.

## Objetivo y entradas

Taller crea un vídeo final con la imagen y calidad de `Video Bueno` y el audio español elegido en `Audio Español`.

- `Video Bueno` es la referencia maestra: manda la imagen, duración, FPS objetivo y vídeo final.
- `Audio Español` aporta la pista que se mide y, cuando corresponde, se exporta. Su imagen se usa únicamente para verificar el origen temporal.
- Las pistas seleccionadas en cada tarjeta son las que recibe el motor.
- Al cambiar una entrada se limpian el resultado anterior y `delayHintMs`.
- La pestaña `Trailer` / `Editar Video` de Seguimiento es otro flujo y no comparte este contrato.

## Controles que se conservan

- `Solo medir`: analiza y muestra el resultado, pero nunca exporta.
- `Medir y exportar`: con el híbrido activo solo exporta si la puerta estricta lo autoriza; mientras el interruptor de rollback siga desactivado conserva la autorización legacy existente.
- `Película` y `Tráiler`: seleccionan el perfil de análisis.
- Selección de pistas, `Editar`, preview, `delayHintMs` y carpeta de salida mantienen su función actual.
- `Editar` solo guarda una ayuda visual para orientar candidatos. No corrige FPS, no modifica originales y no sustituye la medición.

La pestaña, entradas, pistas, ajustes, trabajo en curso y último resultado se conservan en `localStorage` y deben reaparecer tras recargar.
Mientras un trabajo está activo, Taller bloquea cambios de entradas, pistas, modo, perfil, ayuda visual y salida para no perder su identificador ni abrir un segundo job distinto.

## Contrato del motor híbrido

El motor separa siempre la evidencia visual de la evidencia de audio:

1. La imagen compara `Video Bueno` con el vídeo español original.
2. El audio compara las pistas seleccionadas, usando un temporal corregido únicamente si el plan FPS fue confirmado.
3. El camino rápido necesita coincidencia visual fuerte y al menos dos zonas de audio coherentes.
4. Si falta corroboración, el descubrimiento amplía zonas solo por una duda concreta registrada.
5. Ningún score aislado, una sola zona o una confianza heredada autorizan exportación.

El resultado híbrido contiene `state`, `delay_ms`, `visual`, `audio`, `fps_correction`, `decision`, `export_allowed` y, si se intentó exportar, `export`.

## Perfiles

### Película

Usa ventanas de audio largas y posiciones separadas a lo largo de la obra. Prueba primero el candidato visual con un camino estrecho; si no queda corroborado, descubre y ordena candidatos de audio. Solo escala por falta de clúster repetido, empate o corroboración insuficiente, con un máximo de siete zonas visuales y ocho de audio.

### Tráiler

Usa ventanas cortas adaptadas a su duración y radios de búsqueda menores. Mantiene las mismas reglas de seguridad y coherencia que Película, con un máximo de cuatro zonas visuales y seis de audio.

## Corrección FPS

- FPS nominales distintos crean un plan; no aplican una corrección por sí solos.
- Antes de crear el audio corregido, el híbrido confirma el tempo mediante duración e imagen del vídeo español original.
- Solo un plan confirmado puede generar el `.mka` temporal y aplicar `atempo` al audio español.
- La verificación visual posterior sigue usando el vídeo original, nunca el `.mka`.
- Si duración, imagen o cadencia variable no confirman el plan, el estado es `FPS_NO_CONFIRMADOS` y la exportación queda bloqueada.
- FPS iguales se muestran como corrección no necesaria.
- FPS ausentes, no finitos o con un tempo inválido se consideran no confirmados y nunca autorizan un resultado.

## Estados finales

- `OK_VERIFICADO`: imagen y audio sostienen el mismo delay con evidencia suficiente.
- `NO_FIABLE`: el análisis terminó, pero no reúne evidencia suficiente.
- `MONTAJE_DISTINTO`: ningún delay fijo explica las distintas zonas.
- `FPS_NO_CONFIRMADOS`: no se ha confirmado una corrección de velocidad segura.
- `SIN_ZONAS_VALIDAS`: no hay zonas útiles suficientes para decidir.
- `AUDIO_VIDEO_ORIGEN_DUDOSO`: imagen y audio no confirman el mismo origen temporal.
- `ERROR_TECNICO`: una dependencia o ejecución impidió completar el análisis.

La web muestra de forma compacta delay final, estado, verificación y zonas visuales válidas, zonas de audio coherentes, estado FPS, motivo traducido y exportación realizada, en curso, no solicitada, bloqueada o fallida. Solo `OK_VERIFICADO` muestra un delay como final; los estados rechazados muestran `--`.

## Autorización de exportación

La única autorización válida es:

- `requested_mode == "exportar"`;
- `state == "OK_VERIFICADO"`;
- `export_allowed is True`;
- contrato completo, sin contradicciones y con FPS seguro.

`MEDIA`, `ALTA`, `result.ok` o un resultado legacy no sustituyen esta puerta. `Solo medir` se congela al crear el job y no puede convertirse después en exportación por cambiar los ajustes.

La exportación conserva el vídeo bueno, prepara el audio español, sincroniza los subtítulos procedentes de `Audio Español`, crea un MKV temporal, lo valida y solo entonces publica la salida final.

## Temporales y limpieza

- Los fragmentos de medición viven dentro del job y se eliminan al terminar cada etapa.
- El audio corregido por FPS y el audio normalizado de exportación son temporales propios del job.
- La salida se construye primero como `.delay-audio-part`; un error no debe publicar ese archivo como salida final.
- La limpieza borra únicamente temporales creados por el job y nunca originales ni una salida ya publicada.
- Si un temporal propio no puede eliminarse, se registra como error técnico; no se oculta.

## Caja negra

La trazabilidad mínima incluye:

- `fps_plan.started`, `fps_plan.confirmed` o `fps_plan.rejected`;
- `visual_gate.started`, zonas puntuadas o reemplazadas y `visual_gate.finished`;
- `audio_narrow.started` y `audio_narrow.finished`;
- `audio_discovery.started`, candidatos ordenados y `audio_discovery.finished`;
- `visual_final.started`, candidatos puntuados y `visual_final.finished`;
- `decision.ok_verificado` o el estado de rechazo concreto;
- `export_gate.allowed` o `export_gate.blocked`;
- creación y limpieza de temporales.

Cada evento guarda solo fase, duración, perfil, posición de zona, candidato, puntuación, margen, motivo y decisión que sean útiles para diagnosticar el job.

## Rollback

`hybrid.enabled` es el interruptor de activación. Para volver al motor anterior en trabajos nuevos se desactiva y se reconstruye el servicio. Los resultados híbridos incompletos, desconocidos o con error nunca caen silenciosamente a la puerta legacy: se bloquean como `NO_FIABLE` o `ERROR_TECNICO`. Los jobs legacy existentes pueden seguir mostrándose con su render histórico, pero no se convierten en autorización híbrida.

## Pruebas obligatorias

- Unitarias de mapeo temporal, signos de delay, límites y planes FPS.
- Decisiones con una zona, zonas contradictorias, coincidencia, contradicción visual, estados incompletos y errores técnicos.
- Perfiles Película y Tráiler con sus límites propios.
- `Solo medir` y `Medir y exportar`, incluida la puerta estricta.
- Material real o controlado con delay positivo, negativo y cero; FPS iguales y conversión confirmada.
- Validación en la web real de resultado compacto, persistencia tras recarga, escritorio, móvil, consola y red.
