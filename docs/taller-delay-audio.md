# Taller Delay Audio

Contrato corto para tocar Taller sin perder la intencion funcional.

- `Video Bueno` es la referencia maestra: video, duracion y FPS objetivo.
- `Audio Espanol` aporta la pista espanola que se medira y, si procede, se exportara.
- `Editar` abre el ajuste visual: solo guarda `delayHintMs` para orientar la medicion. No corrige FPS, no modifica archivos y no sustituye al motor.
- El motor siempre mide despues; la ayuda visual solo encamina cuando el desfase inicial es grande.
- Si los FPS no coinciden, el boton principal corrige tempo/FPS del audio espanol antes de medir y, si procede, exportar.
- Si las duraciones difieren 10 segundos o mas, se avisa en amarillo. Es aviso visual, no bloqueo.
- Mantener UI compacta y movil: no anadir explicativos largos ni botones nuevos sin necesidad.
- Si cambias comportamiento de Taller, actualiza este documento en el mismo cambio.
