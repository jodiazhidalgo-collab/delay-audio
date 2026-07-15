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
- `Medir y exportar`: con el híbrido activo solo exporta si la puerta estricta lo autoriza. Una duda del híbrido nunca cae silenciosamente al motor legacy.
- `Película` y `Tráiler`: seleccionan el perfil de análisis.
- Selección de pistas, `Editar`, preview, `delayHintMs` y carpeta de salida mantienen su función actual.
- `Editar` aparece únicamente en `Audio Español`; `Video Bueno` sigue visible como referencia maestra, pero no muestra ese botón.
- El preview conserva las dos imágenes y muestra una sola línea amarilla para el desplazamiento español. La línea no se arrastra: `-` la mueve a la izquierda y retrocede únicamente el vídeo español; `+` la mueve a la derecha y avanza únicamente el vídeo español, siempre en pasos de 1 segundo. `Video Bueno` permanece fijo incluso al cruzar por `0`.
- `Editar` abre posiciones interiores equivalentes, no clips desde `t=0`, alrededor del 45 % del core para Película y del 40 % para Tráiler. La referencia conserva 30 segundos en Película y 12 en Tráiler; el español prepara un buffer bilateral de hasta 54 y 20 segundos respectivamente para mantener los márgenes de `±24` y `±8` sin mover la referencia. `Play` compara ventanas de 6 y 4 segundos.
- El número visible expresa el desplazamiento del vídeo español. Al aceptar, la interfaz lo convierte al convenio interno del motor (`tiempo_español = tiempo_referencia - delay`) sin cambiar el signo real usado por medición, FPS o exportación.
- `delayHintMs` es solo una semilla. Entra junto a `0`, puede centrar y acelerar el fast path y nunca autoriza por sí solo. Si el fast path no cierra, el descubrimiento obtiene sus propios candidatos de audio y la verificación visual final compara únicamente esos candidatos contra `0`: la semilla manual ya no reaparece como rival. Antes de puntuar, candidatos separados por menos de medio fotograma efectivo se agrupan en una sola posición visual, conservando como representante el primero —el clúster de audio en la fase final— y, por tanto, su delay exacto para exportar. La misma regla se aplica al `0` de control aunque sea implícito, sin convertirlo en candidato base. Con VFR no se aplica esta equivalencia. La medición final registra si la semilla ayudó, fue descartada y su error frente al resultado.
- El botón solo muestra `Ayuda recomendada` o `Ayuda muy recomendable` cuando existe un hint o resultado fiable que supera los umbrales del perfil. La diferencia total de duración puede avisarse aparte, pero no colorea `Editar` por sí sola.

La pestaña, entradas, pistas, ajustes, trabajo en curso y último resultado se conservan en `localStorage` y deben reaparecer tras recargar.
Mientras un trabajo está activo, Taller bloquea cambios de entradas, pistas, modo, perfil, ayuda visual y salida para no perder su identificador ni abrir un segundo job distinto.

## Contrato del motor híbrido

El motor separa siempre la evidencia visual de la evidencia de audio:

1. La imagen compara `Video Bueno` con el vídeo español original.
2. Todas las posiciones visuales, estrechas, de descubrimiento, expansión, FPS y preview se eligen sobre un `measurement_core` común que excluye introducciones, logos, títulos y colas finales. Los porcentajes son siempre del core del vídeo de referencia.
3. El audio compara las pistas seleccionadas. Con FPS distintos usa un `.mka` provisional después de descartar VFR no resuelto, pero crear ese temporal no confirma ni aplica todavía la corrección.
4. El camino rápido necesita coincidencia visual absoluta fuerte y tres anclas interiores de audio coherentes y distribuidas.
5. Si el camino rápido no cierra, el descubrimiento puede verificar la imagen por vía absoluta o relativa usando los SSIM que ya ha calculado. La equivalencia visual usa el menor de medio fotograma de referencia y medio fotograma español trasladado por `tempo`, con límite estricto; ningún grupo puede abarcar ese medio fotograma completo, no se encadena y nunca cambia el valor del representante. El `0` implícito tampoco compite cuando pertenece al mismo grupo. Solo si el único grupo efectivo contiene ese `0`, la vía relativa puede corroborar al representante contra sus controles externos simétricos de `±400 ms`; una pérdida clara continúa bloqueando y agrupar candidatos alejados de `0` no recibe esta autorización. La puerta de exportación comprueba también el grupo, el representante y esos controles. La vía relativa exige las zonas requeridas del perfil, al menos `max(2, required_strong)` victorias con mejora `>= 0.05`, media `>= 0.08` y cero pérdidas claras. Nunca autoriza sin clúster de audio único, puntuación y dispersión válidas y `timeline_model.compatible == true`.
6. Si falta corroboración, el descubrimiento amplía zonas solo por una duda concreta registrada.
7. Ningún score aislado, una sola zona o una confianza heredada autorizan exportación.

El resultado híbrido contiene `state`, `delay_ms`, `measurement_core`, `timeline_model`, `edit_hint`, `visual`, `audio`, `fps_correction`, `decision`, `export_allowed` y, si se intentó exportar, `export`. La evidencia visual declara `verification_mode: absolute | relative | none`; el modo relativo conserva objetivo, competidor, tipo de referencia, zonas comparables, victorias, empates, pérdidas y mejora media. `visual.candidate_equivalence` conserva umbral estricto, FPS, tempo, VFR, candidatos de entrada y efectivos, grupos, incorporación del `0` implícito, representante de `0` y controles externos usados.

## Perfiles

### Película

En obras de 90 minutos o más excluye 120 segundos al principio y al final. En películas más cortas usa `min(120, max(45, duración * 0.03))` y reduce el margen si hace falta para conservar un core razonable, con referencia mínima de 600 segundos. Usa ventanas de audio largas y posiciones separadas; solo escala por falta de clúster repetido, empate o corroboración insuficiente, con un máximo de siete zonas visuales y ocho de audio.

### Tráiler

Excluye en cada extremo `min(4, max(1.5, duración * 0.08))`, conservando al menos 8 segundos de core cuando la duración lo permite. Usa ventanas y radios menores, tres anclas temporales iniciales y un máximo de cuatro zonas visuales y seis de audio.

## Modelo temporal interior

Cada coincidencia de audio produce una pareja interior `(ref_time, esp_time)`. Sin NumPy ni OpenCV se ajusta de forma robusta `ref_time = slope * esp_time + intercept`: mediana de pendientes entre pares, mediana de intercepts, rechazo de un outlier aislado y un reajuste con inliers.

- `slope` y `drift_ms_per_sec` comprueban el tempo; el límite inicial es `abs(drift) <= 0.1 ms/s`.
- `intercept_ms` representa el delay fijo y las diferencias constantes de introducción.
- `residual_median_ms` y `residual_max_ms` detectan cortes, saltos o escenas añadidas dentro del cuerpo.
- Se exigen al menos tres inliers distribuidos por el core. Un outlier aislado puede rechazarse; varios grupos o residuos incompatibles bloquean.
- Una diferencia grande de duración total puede convivir con un modelo interior compatible. La duración es señal preliminar, nunca sustituto de las anclas.

## Corrección FPS

- FPS nominales distintos crean un plan; no aplican una corrección por sí solos.
- VFR no resuelto rechaza el plan antes de crear el audio corregido. La relación de duraciones total o recortada solo genera una señal o advertencia.
- Sin VFR, el plan pasa a `provisional:true` y genera un `.mka` temporal para medir varias anclas interiores; `confirmed` y `applied` siguen en `false`.
- Película y Tráiler exigen al menos tres anclas separadas, un clúster principal, modelo temporal compatible y ausencia de deriva progresiva.
- El delay provisional obtenido por audio se usa para comparar visualmente el tempo planificado frente al nominal mediante `t_esp = (t_ref - delay) * tempo`.
- La imagen usa siempre `Video Bueno` y el vídeo español original. El `.mka` se usa únicamente para audio.
- La confirmación visual conserva el camino SSIM absoluto y permite un camino relativo para encodes distintos: mejora de al menos `0.05` en dos zonas, media mínima `0.08` y ninguna zona contradictoria. Ese camino nunca basta sin modelo de audio estable y ausencia de VFR.
- Solo cuando pendiente, intercept, residuos, audio e imagen interior convergen se marcan `confirmed:true` y `applied:true`. Si la duración total también encaja se conserva `duration_audio_drift_and_visual_match`; si los bordes difieren se usa `interior_timeline_audio_and_visual_match`.
- Si audio, imagen, residuos, deriva o cadencia variable no confirman el plan, el estado es `FPS_NO_CONFIRMADOS` y la exportación queda bloqueada.
- FPS iguales se muestran como corrección no necesaria.
- FPS ausentes, no finitos o con un tempo inválido se consideran no confirmados y nunca autorizan un resultado.

## Estados finales

- `OK_VERIFICADO`: imagen y audio sostienen el mismo delay con evidencia suficiente, mediante verificación visual absoluta o relativa respaldada por el modelo temporal.
- `NO_FIABLE`: el análisis terminó, pero no reúne evidencia suficiente.
- `MONTAJE_DISTINTO`: ningún delay fijo explica las distintas zonas.
- `FPS_NO_CONFIRMADOS`: no se ha confirmado una corrección de velocidad segura.
- `SIN_ZONAS_VALIDAS`: no hay zonas útiles suficientes para decidir.
- `AUDIO_VIDEO_ORIGEN_DUDOSO`: imagen y audio no confirman el mismo origen temporal.
- `ERROR_TECNICO`: una dependencia o ejecución impidió completar el análisis.

La web muestra de forma compacta delay final, estado, zona útil, modo de verificación visual, anclas de audio coherentes, estado FPS, si Editar ayudó, motivo traducido y exportación realizada, en curso, no solicitada, bloqueada o fallida. La verificación absoluta enseña zonas válidas; la relativa enseña victorias, empates, pérdidas y mejora media para no confundir ambos criterios; una confirmación visual propia del plan de velocidad se identifica como `Verificación FPS`. Solo `OK_VERIFICADO` muestra un delay como final; los estados rechazados muestran `--`.

## Autorización de exportación

La única autorización válida es:

- `requested_mode == "exportar"`;
- `state == "OK_VERIFICADO"`;
- `export_allowed is True`;
- contrato completo, sin contradicciones, con FPS seguro, core válido y `timeline_model.compatible == true` con tres inliers.
- si la imagen se verificó por vía relativa, objetivo visual y clúster de audio coinciden dentro de la tolerancia y la evidencia relativa cumple íntegramente su contrato.

`MEDIA`, `ALTA`, `result.ok` o un resultado legacy no sustituyen esta puerta. `Solo medir` se congela al crear el job y no puede convertirse después en exportación por cambiar los ajustes.

La exportación conserva el vídeo bueno, prepara el audio español y sincroniza los subtítulos procedentes de `Audio Español`. Con FPS distintos confirmados, esos subtítulos reciben la misma transformación temporal que el audio (`tiempo final = tiempo original / tempo + delay`); con FPS iguales solo reciben el delay fijo. Los subtítulos de `Video Bueno` permanecen intactos. La salida se crea como MKV temporal y solo se publica cuando conserva la cantidad y los nombres de todos los subtítulos previstos. El nombre original y su marca de procedencia se separan con ` - `.

## Temporales y limpieza

- Los fragmentos de medición viven dentro del job y se eliminan al terminar cada etapa.
- El audio corregido por FPS y el audio normalizado de exportación son temporales propios del job.
- La salida se construye primero como `.delay-audio-part`; un error no debe publicar ese archivo como salida final.
- La limpieza borra únicamente temporales creados por el job y nunca originales ni una salida ya publicada.
- Al eliminar el último temporal también retira, si queda vacío, su directorio propio `job/tmp` o `job/fps`; no toca otros directorios.
- Si un temporal propio no puede eliminarse, se registra como error técnico; no se oculta.

## Caja negra

La trazabilidad mínima incluye:

- `fps_plan.started`, `fps_plan.provisional` o `fps_plan.rejected`;
- `measurement_core.built` con márgenes, inicio, final y duración útil;
- `timeline_anchor.matched` o `timeline_anchor.rejected` y `timeline_model.fitted` o `timeline_model.incompatible`;
- `visual_gate.started`, zonas puntuadas o reemplazadas y `visual_gate.finished`;
- `audio_narrow.started` y `audio_narrow.finished`;
- `audio_discovery.started`, candidatos ordenados y `audio_discovery.finished`;
- `fps_audio_evidence.finished` con soporte, dispersión y pendiente;
- `fps_visual_confirmation.started`, comparación por zona y decisión final;
- `edit_hint.used`, `edit_hint.helped` o `edit_hint.rejected` cuando existe ayuda;
- `visual_final.started`, candidatos puntuados y `visual_final.finished`;
- `visual_final.candidates_grouped` cuando se aplica equivalencia visual, con umbral, grupos y representante conservado;
- `decision.ok_verificado` o el estado de rechazo concreto;
- `export_gate.allowed` o `export_gate.blocked`;
- `subtitle_sync.planned` y `subtitle_sync.verified` con pistas de origen, delay, FPS, escala temporal requerida y aplicada, y verificación estructural;
- creación y limpieza de temporales.
- `decision.final` con estado, delay, autorización y motivo.

Cada evento guarda solo fase, duración, perfil, posición de zona, candidato, puntuación, margen, modelo, motivo y decisión útiles. El resultado separa tiempos de metadatos, core, anclas, FPS, visual, narrow, discovery y exportación.

## Rollback

`hybrid.enabled` es el interruptor de activación. Para volver al motor anterior en trabajos nuevos se desactiva y se reconstruye el servicio. Los resultados híbridos incompletos, desconocidos o con error nunca caen silenciosamente a la puerta legacy: se bloquean como `NO_FIABLE` o `ERROR_TECNICO`. Los jobs legacy existentes pueden seguir mostrándose con su render histórico, pero no se convierten en autorización híbrida.

## Pruebas obligatorias

- Unitarias de mapeo temporal, signos de delay, límites y planes FPS.
- Decisiones con una zona, zonas contradictorias, coincidencia, contradicción visual, estados incompletos y errores técnicos.
- Decisiones absolutas y relativas, incluido SSIM absoluto bajo, cero zonas absolutas válidas, pérdida relativa, audio inestable y objetivo visual distinto del clúster de audio.
- Equivalencia visual positiva y negativa en `23.976`, `24`, `25`, `30` y `60` FPS, justo dentro, en el límite y fuera de medio fotograma; VFR, no encadenado, controles externos y conservación del delay exacto.
- Perfiles Película y Tráiler con sus límites propios.
- `Solo medir` y `Medir y exportar`, incluida la puerta estricta.
- Material real o controlado con delay positivo, negativo y cero; FPS iguales y conversión confirmada.
- Validación en la web real de resultado compacto, persistencia tras recarga, escritorio, móvil, consola y red.
