---
name: backup-delay-audio
description: Crear backups fechados de delay audio antes de cambios delicados. Usar antes de editar AGENTS, .codex, skills, frontend, backend, motor, Docker, configuracion funcional o cualquier zona donde el usuario espere salvavidas local.
---

# Backup delay audio

## Cuando usarla

Usar solo antes de cambios delicados: AGENTS, `.codex`, skills, frontend, backend, motor, Docker, configuracion funcional o cuando el usuario espere un salvavidas local.

No usar en turnos de solo lectura ni para cambios triviales faciles de revertir.

## Flujo

1. Identificar que archivos o carpetas se van a tocar.
2. Ejecutar `git status --short` si el repo tiene Git y avisar si la carpeta esta sucia.
3. Crear un motivo corto, en minusculas y con guiones.
4. Ejecutar `scripts/create_backup.ps1` desde la raiz del proyecto.
5. Verificar que el ZIP aparece en `_backups/`.
6. Informar el nombre del backup antes de editar.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\backup-delay-audio\scripts\create_backup.ps1 -Reason "motivo-corto"
```

Para comprobar sin crear ZIP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\backup-delay-audio\scripts\create_backup.ps1 -Reason "motivo-corto" -DryRun
```

## Reglas

- No borrar backups antiguos.
- No meter `_backups/` en Git.
- Si solo se toca una zona pequena, el backup puede ser de instrucciones/configuracion; si se toca motor o frontend, incluir `app/`.
- Si hay cambios previos, no los presentes como propios; separa cambios previos y cambios nuevos.
