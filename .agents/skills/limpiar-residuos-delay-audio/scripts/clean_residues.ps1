param(
    [switch]$DryRun,
    [int]$TmpDays = 2,
    [int]$ArtifactsDays = 7
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$runtime = Join-Path $root "_codex_runtime"
$requiredDirs = @(
    (Join-Path $runtime "tmp"),
    (Join-Path $runtime "test-data"),
    (Join-Path $runtime "artifacts")
)

$removed = New-Object System.Collections.Generic.List[string]
$kept = New-Object System.Collections.Generic.List[string]

function Is-UnderRoot([string]$path) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    return $resolved.StartsWith($root.Path, [System.StringComparison]::OrdinalIgnoreCase)
}

function Remove-SafeTarget([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    if (-not (Is-UnderRoot $path)) {
        throw "Ruta fuera del proyecto: $path"
    }
    if ($DryRun) {
        $script:removed.Add("DRYRUN $path")
    } else {
        Remove-Item -LiteralPath $path -Recurse -Force
        $script:removed.Add($path)
    }
}

foreach ($dir in $requiredDirs) {
    if (-not (Test-Path -LiteralPath $dir)) {
        if ($DryRun) {
            $kept.Add("CREARIA $dir")
        } else {
            New-Item -ItemType Directory -Path $dir | Out-Null
            $kept.Add("CREADO $dir")
        }
    } else {
        $kept.Add("OK $dir")
    }
}

Get-ChildItem -LiteralPath $root -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" -or $_.Name -eq ".pytest_cache" } |
    ForEach-Object { Remove-SafeTarget $_.FullName }

Get-ChildItem -LiteralPath $root -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    ForEach-Object { Remove-SafeTarget $_.FullName }

if (Test-Path -LiteralPath $runtime) {
    Get-ChildItem -LiteralPath $runtime -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "codex_test_*" -or $_.Name -like "codex_tmp_*" -or $_.Name -like "unit_test_*" } |
        ForEach-Object { Remove-SafeTarget $_.FullName }

    $now = Get-Date
    $retentionRules = @(
        @{ Path = Join-Path $runtime "tmp"; Days = $TmpDays },
        @{ Path = Join-Path $runtime "test-data"; Days = $TmpDays },
        @{ Path = Join-Path $runtime "artifacts"; Days = $ArtifactsDays }
    )

    foreach ($rule in $retentionRules) {
        if (-not (Test-Path -LiteralPath $rule.Path)) { continue }
        Get-ChildItem -LiteralPath $rule.Path -Force -ErrorAction SilentlyContinue |
            Where-Object { ($now - $_.LastWriteTime).TotalDays -gt $rule.Days } |
            ForEach-Object { Remove-SafeTarget $_.FullName }
    }

    $protected = @{}
    foreach ($dir in $requiredDirs) {
        $protected[(Resolve-Path -LiteralPath $dir).Path.ToLowerInvariant()] = $true
    }
    Get-ChildItem -LiteralPath $runtime -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        ForEach-Object {
            $full = $_.FullName
            if ($protected.ContainsKey($full.ToLowerInvariant())) { return }
            if (-not (Get-ChildItem -LiteralPath $full -Force -ErrorAction SilentlyContinue)) {
                Remove-SafeTarget $full
            }
        }
}

Write-Output "--- LIMPIEZA ---"
Write-Output ("MODO: {0}" -f ($(if ($DryRun) { "DRYRUN" } else { "REAL" })))
Write-Output ("REMOVIDOS: {0}" -f $removed.Count)
$removed | Select-Object -First 80
Write-Output "--- CONSERVADO/CREADO ---"
$kept | Select-Object -First 20
