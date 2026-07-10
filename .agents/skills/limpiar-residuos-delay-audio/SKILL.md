---
name: limpiar-residuos-delay-audio
description: Limpiar residuos seguros de Codex y pruebas en delay audio. Crea y mantiene _codex_runtime y borra solo basura sintetica conocida.
---

# Limpiar Residuos delay audio

## Cuando usarla

Usar dentro del cierre final de `cerrar-git-delay-audio`.

## Zonas

`logs/` y `config/` son sagrados: contienen runtime real.

Codex debe usar:

- `_codex_runtime/tmp/`
- `_codex_runtime/test-data/`
- `_codex_runtime/artifacts/`

## Flujo

1. Confirmar raiz del proyecto.
2. Crear `_codex_runtime/tmp`, `_codex_runtime/test-data` y `_codex_runtime/artifacts` si faltan.
3. Borrar basura Python segura: `__pycache__`, `*.pyc`, `.pytest_cache`.
4. Borrar solo residuos sinteticos conocidos dentro de `_codex_runtime`.
5. Borrar carpetas vacias dentro de `_codex_runtime` salvo las raices `tmp`, `test-data` y `artifacts`.
6. Aplicar retencion a `_codex_runtime`: tmp/test-data 2 dias, artifacts 7 dias por defecto.

## Comando

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\limpiar-residuos-delay-audio\scripts\clean_residues.ps1
```

Modo lectura:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .agents\skills\limpiar-residuos-delay-audio\scripts\clean_residues.ps1 -DryRun
```

## Reglas

- No borrar jobs reales.
- No borrar previews reales, resultados reales, logs reales ni configuracion real.
- Solo borrar basura Python segura y runtime sintetico de Codex.
- Si hay duda, informar y no borrar.
