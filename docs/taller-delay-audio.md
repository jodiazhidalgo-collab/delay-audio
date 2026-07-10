# Taller Delay Audio

Contrato corto para tocar Taller sin perder la intencion funcional.

## Objetivo

Taller sirve para crear un video final usando la imagen/calidad del `Video Bueno` y el audio espanol sacado de otra version. Normalmente el `Audio Espanol` puede venir de un archivo con peor calidad de imagen; ahi solo interesa su audio.

## Entradas

- `Video Bueno`: referencia maestra. Manda la imagen, duracion, FPS objetivo y video final.
- `Audio Espanol`: fuente de la pista espanola que se medira y, si procede, se exportara.
- Las pistas elegidas en cada tarjeta son las que se pasan al motor.
- Al cambiar cualquiera de las dos entradas se limpia el resultado anterior y la ayuda visual.

## Ajustes

- `Modo: Solo medir`: mide el delay y no exporta.
- `Modo: Medir y exportar`: mide y, si la confianza llega a MEDIA, crea el MKV final.
- `Tipo: Pelicula`: perfil para videos largos; usa zonas largas y busqueda amplia.
- `Tipo: Trailer`: el mismo proceso, pero para videos pequenos; usa segmentos y busqueda adaptados a duraciones cortas.
- `Tipo: Trailer` no tiene relacion con la pestana `Trailer` de Seguimiento.

## Reglas

- `Editar` abre el ajuste visual: solo guarda `delayHintMs` para orientar la medicion. No corrige FPS, no modifica archivos y no sustituye al motor.
- El motor siempre mide despues; la ayuda visual solo encamina cuando el desfase inicial es grande.
- Si los FPS no coinciden, el boton principal corrige tempo/FPS del audio espanol antes de medir y, si procede, exportar.
- La correccion FPS crea un audio temporal propio del job y lo limpia al terminar.
- Si las duraciones difieren 10 segundos o mas, se avisa en amarillo. Es aviso visual, no bloqueo.
- La exportacion conserva el video bueno, prepara el audio espanol, sincroniza subtitulos del archivo de `Audio Espanol` si existen y valida el MKV final.
- La pestana `Trailer` / `Editar Video` es otro flujo: pistas, AC-3 5.1, capitulos e idioma. No mezclarlo con Taller.
- Mantener UI compacta y movil: no anadir explicativos largos ni botones nuevos sin necesidad.
- Si cambias comportamiento de Taller, actualiza este documento en el mismo cambio.
