---
name: cerrar-git-delay-audio
description: Cerrar Git de delay audio al finalizar cada turno que haya modificado archivos. Ejecuta limpieza segura, commit, push al remoto configurado y exige que Git termine limpio.
---

# Cerrar Git delay audio

## Cuando usarla

Usar al finalizar cada turno que haya modificado archivos en `delay audio`, salvo que el usuario diga que no cierre Git todavia.

No usar en turnos de solo lectura, revision o explicacion sin archivos modificados.

## Flujo

1. Confirmar que estas en la raiz del proyecto.
2. Ejecutar `limpiar-residuos-delay-audio`.
3. Ejecutar `git status --short` si existe repo Git.
4. Si hay cambios, ejecutar el script de cierre con mensaje corto.
5. Hacer push al remoto configurado si existe.
6. Confirmar que commit y push no han fallado.
7. Exigir que `git status --short` quede vacio.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\cerrar-git-delay-audio\scripts\close_git.ps1 -Message "mensaje corto"
```

## Pruebas sinteticas

- No crear repositorios de prueba en trabajos normales de web, motor, AGENTS, documentacion u otros archivos.
- Probar el bucle Git solo al modificar `close_git.ps1`, esta skill o `clean_residues.ps1`.
- Crear la prueba exclusivamente en `_codex_runtime/test-data/` y eliminarla al terminar.
- Si Git bloquea la prueba por `dubious ownership`, usar una configuracion temporal limitada al proceso o al repositorio sintetico.
- No usar `safe.directory=*`, no cambiar la proteccion global y no eliminar las excepciones exactas necesarias para los repositorios reales del NAS.

## Reglas

- No inicializar Git.
- No configurar remotos nuevos.
- Comprobar Git antes de editar; si ya esta sucio, avisar antes de mezclar trabajo nuevo.
- No borrar codigo ni tests para limpiar.
- No usar `git reset`, `git checkout` ni comandos destructivos.
- Si no hay repo Git, informar `SIN_GIT` y salir sin tocar remotos.
- Si hay secretos o runtime ignorado por `.gitignore`, no forzarlo al commit.
