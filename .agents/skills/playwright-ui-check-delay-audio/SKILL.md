---
name: playwright-ui-check-delay-audio
description: Validar visualmente delay audio en navegador. Usar despues de cambios de interfaz o cuando el usuario reporte comportamiento visible, botones, pestanas, tarjetas, estado, consola, red o persistencia localStorage.
---

# Playwright UI Check delay audio

## Flujo

1. Abrir `http://192.168.1.159:9004/`.
2. Comprobar que carga la herramienta real, no una pagina en blanco.
3. Revisar consola y red si hay fallo visible.
4. Probar solo el flujo afectado por el cambio.
5. Si se tocan pestanas, filtros o secciones, comprobar persistencia tras recargar.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-delay-audio\scripts\ui_check.ps1
```

Para repetir usando la instalacion ya preparada:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\playwright-ui-check-delay-audio\scripts\ui_check.ps1 -SkipInstall
```

Opciones utiles:

- `-Url "http://192.168.1.159:9004/"`
- `-TimeoutMs 30000`

El script guarda captura y `resultado.json` en `_codex_runtime/artifacts/ui-check/`.
Si Playwright falta, lo instala aislado en `_codex_runtime/playwright-ui-check/`.

## Reglas

- La validacion visible manda sobre logs internos cuando el fallo es de UI.
- No uses esta skill para cambiar codigo; solo para comprobar y recoger evidencia.
- No hagas pruebas destructivas ni procesos reales sin permiso.
- En respuesta final, indica URL, resultado visible, consola/red y captura si procede.
