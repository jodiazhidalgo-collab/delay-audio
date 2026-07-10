param(
    [string]$Reason = "manual",
    [string[]]$Include = @("AGENTS.md", ".gitignore", "app", "config", ".agents", ".codex"),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
$backupDir = Join-Path $root "_backups"
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$safeReason = ($Reason.ToLowerInvariant() -replace '[^a-z0-9_-]+', '-').Trim('-')
if ([string]::IsNullOrWhiteSpace($safeReason)) { $safeReason = "manual" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipPath = Join-Path $backupDir "$stamp-$safeReason.zip"

$skipPatterns = @(
    '(^|[\\/])_backups([\\/]|$)',
    '(^|[\\/])\.git([\\/]|$)',
    '(^|[\\/])\.playwright-mcp([\\/]|$)',
    '(^|[\\/])_codex_runtime([\\/]|$)',
    '(^|[\\/])logs([\\/]|$)',
    '(^|[\\/])__pycache__([\\/]|$)',
    '\.pyc$',
    '\.pyo$',
    '\.log$'
)

function Get-RelativePathCompat([string]$basePath, [string]$targetPath) {
    $baseUri = New-Object System.Uri(($basePath.TrimEnd('\') + '\'))
    $targetUri = New-Object System.Uri($targetPath)
    $relativeUri = $baseUri.MakeRelativeUri($targetUri)
    return [System.Uri]::UnescapeDataString($relativeUri.ToString()).Replace('/', '\')
}

function Test-Skipped([string]$relativePath) {
    foreach ($pattern in $skipPatterns) {
        if ($relativePath -match $pattern) { return $true }
    }
    return $false
}

$files = New-Object System.Collections.Generic.List[object]
$seen = @{}
foreach ($item in $Include) {
    $target = Join-Path $root $item
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $resolved = Resolve-Path -LiteralPath $target
    foreach ($pathInfo in $resolved) {
        $abs = $pathInfo.Path
        if ((Get-Item -LiteralPath $abs).PSIsContainer) {
            Get-ChildItem -LiteralPath $abs -File -Recurse -Force | ForEach-Object {
                $rel = Get-RelativePathCompat $root $_.FullName
                if ((-not (Test-Skipped $rel)) -and (-not $seen.ContainsKey($rel))) {
                    $seen[$rel] = $true
                    $files.Add($_)
                }
            }
        } else {
            $rel = Get-RelativePathCompat $root $abs
            if ((-not (Test-Skipped $rel)) -and (-not $seen.ContainsKey($rel))) {
                $seen[$rel] = $true
                $files.Add((Get-Item -LiteralPath $abs))
            }
        }
    }
}

if ($DryRun) {
    [pscustomobject]@{
        ZipPath = $zipPath
        FileCount = $files.Count
        Mode = "DryRun"
    }
    return
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $files) {
        $entryName = (Get-RelativePathCompat $root $file.FullName).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $entryName) | Out-Null
    }
} finally {
    $zip.Dispose()
}

Get-Item -LiteralPath $zipPath | Select-Object FullName, Length, LastWriteTime
