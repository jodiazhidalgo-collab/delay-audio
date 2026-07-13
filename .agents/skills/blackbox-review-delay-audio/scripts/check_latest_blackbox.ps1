param(
    [ValidateSet("delay", "preview", "seguimiento")]
    [string]$Area = "delay",
    [string]$JobId = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")

function Read-JsonSafe([string]$Path) {
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Output ("JSON_INVALIDO: {0}: {1}" -f (Split-Path -Leaf $Path), $_.Exception.Message)
        return $null
    }
}

function Show-SelectedFields($Object, [string[]]$Names) {
    if ($null -eq $Object) { return }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name) {
            $value = $Object.$name
            if ($null -ne $value -and "$value".Length -le 300) {
                Write-Output ("{0}: {1}" -f $name.ToUpperInvariant(), $value)
            }
        }
    }
}

function Show-TextTail([string]$Path, [string]$Label, [int]$Lines = 15) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    Write-Output ("--- {0} ---" -f $Label)
    Get-Content -LiteralPath $Path -Tail $Lines -Encoding UTF8 | ForEach-Object {
        if ($_.Length -gt 700) {
            $_.Substring(0, 700) + "... [recortado]"
        } else {
            $_
        }
    }
}

function Show-SubtitleSync($ResultObject) {
    if ($null -eq $ResultObject) { return }
    if (-not ($ResultObject.PSObject.Properties.Name -contains "export")) { return }
    $export = $ResultObject.export
    if ($null -eq $export -or -not ($export.PSObject.Properties.Name -contains "subtitle_sync")) { return }
    $sync = $export.subtitle_sync
    if ($null -eq $sync) { return }
    Write-Output "--- SUBTITULOS ---"
    Write-Output ("ESTADO: {0}" -f $sync.status)
    Write-Output ("PISTAS_ORIGEN: {0}" -f $sync.tracks)
    Write-Output ("DELAY_MS: {0}" -f $sync.delay_ms)
    Write-Output ("FPS: {0} -> {1}" -f $sync.esp_fps, $sync.ref_fps)
    Write-Output ("ESCALA: requerida {0} | aplicada {1}" -f $sync.required_scale, $sync.applied_scale)
    Write-Output ("ESTRUCTURA_VERIFICADA: {0}" -f $sync.structure_verified)
}

switch ($Area) {
    "delay" { $diagRoot = Join-Path $root "logs\delay_audio" }
    "preview" { $diagRoot = Join-Path $root "logs\delay_audio_preview" }
    "seguimiento" { $diagRoot = Join-Path $root "logs\seguimiento_trailer_jobs" }
}

if (-not (Test-Path -LiteralPath $diagRoot -PathType Container)) {
    Write-Output ("SIN_DIAGNOSTICOS: no existe {0}" -f $diagRoot)
    exit 0
}

if (-not [string]::IsNullOrWhiteSpace($JobId)) {
    $requestedId = $JobId.Trim()
    $cleanId = [System.IO.Path]::GetFileName($requestedId)
    if ($cleanId -ne $requestedId -or $cleanId -notmatch '^[A-Za-z0-9_.-]+$') {
        throw "JobId no valido."
    }
    $jobPath = Join-Path $diagRoot $cleanId
    if (-not (Test-Path -LiteralPath $jobPath -PathType Container)) {
        Write-Output ("SIN_JOB: no existe {0} en el area {1}" -f $cleanId, $Area)
        exit 0
    }
    $job = Get-Item -LiteralPath $jobPath
} else {
    $job = Get-ChildItem -LiteralPath $diagRoot -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if (-not $job) {
    Write-Output ("SIN_JOBS: no hay jobs en el area {0}" -f $Area)
    exit 0
}

Write-Output "AREA: $Area"
Write-Output "JOB: $($job.FullName)"
Write-Output "UPDATED: $($job.LastWriteTime)"

if ($Area -eq "preview") {
    $preview = Join-Path $job.FullName "preview.json"
    if (Test-Path -LiteralPath $preview -PathType Leaf) {
        Write-Output "--- PREVIEW ---"
        $json = Read-JsonSafe $preview
        Show-SelectedFields $json @("id", "created", "window_sec", "clip_sec", "max_offset_ms", "ok", "status", "error")
    } else {
        Write-Output "SIN_PREVIEW_JSON"
    }
    Show-TextTail (Join-Path $job.FullName "preview.log") "PREVIEW LOG" 20
    exit 0
}

$readme = Join-Path $job.FullName "LEEME_CODEX.txt"
if (Test-Path -LiteralPath $readme -PathType Leaf) {
    Write-Output "--- LEEME_CODEX.txt ---"
    Get-Content -LiteralPath $readme -TotalCount 40 -Encoding UTF8
} else {
    Write-Output "SIN_LEEME_CODEX"
}

$resultado = Join-Path $job.FullName "resultado.json"
if (Test-Path -LiteralPath $resultado -PathType Leaf) {
    Write-Output "--- RESULTADO ---"
    $json = Read-JsonSafe $resultado
    Show-SelectedFields $json @("ok", "status", "estado", "error", "codigo_error", "delay_ms", "confidence", "ruta_salida", "output_path")
    Show-SubtitleSync $json
    if ($json -and $json.PSObject.Properties.Name -contains "result") {
        Show-SelectedFields $json.result @("ok", "status", "estado", "error", "codigo_error", "delay_ms", "confidence", "ruta_salida", "output_path")
        Show-SubtitleSync $json.result
    }
} else {
    Write-Output "SIN_RESULTADO_JSON"
}

$errors = Join-Path $job.FullName "errores.json"
if (Test-Path -LiteralPath $errors -PathType Leaf) {
    Write-Output "--- ERRORES ---"
    $items = Read-JsonSafe $errors
    Write-Output ("ERRORS: {0}" -f @($items).Count)
    @($items) | Select-Object -First 5 | ForEach-Object {
        if ($_ -is [string]) {
            Write-Output $_
        } else {
            Show-SelectedFields $_ @("fase", "stage", "codigo", "code", "error", "mensaje", "message", "returncode")
        }
    }
} else {
    Write-Output "SIN_ERRORES_JSON"
}

$timeline = Join-Path $job.FullName "timeline.json"
if (Test-Path -LiteralPath $timeline -PathType Leaf) {
    Write-Output "--- TIMELINE ---"
    $timelineJson = Read-JsonSafe $timeline
    if ($timelineJson -and $timelineJson.PSObject.Properties.Name -contains "phases") {
        Write-Output ("PHASES: {0}" -f @($timelineJson.phases).Count)
        @($timelineJson.phases) | Select-Object -Last 5 | ForEach-Object {
            Show-SelectedFields $_ @("fase", "phase", "estado", "status", "inicio", "fin", "duracion_ms", "error")
        }
    } else {
        Show-SelectedFields $timelineJson @("status", "estado", "last_event", "error")
    }
} else {
    Write-Output "SIN_TIMELINE_JSON"
}

$commands = Join-Path $job.FullName "comandos.json"
if (Test-Path -LiteralPath $commands -PathType Leaf) {
    Write-Output "--- COMANDOS ---"
    $commandItems = Read-JsonSafe $commands
    Write-Output ("COMMANDS: {0}" -f @($commandItems).Count)
    @($commandItems) | Select-Object -Last 3 | ForEach-Object {
        Show-SelectedFields $_ @("fase", "phase", "returncode", "codigo_error", "error")
    }
} else {
    Write-Output "SIN_COMANDOS_JSON"
}

Show-TextTail (Join-Path $job.FullName "eventos.jsonl") "ULTIMOS EVENTOS" 5
Show-TextTail (Join-Path $job.FullName "logs_filtrados.txt") "LOGS FILTRADOS" 15
