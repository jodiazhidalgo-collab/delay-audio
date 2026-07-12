param(
    [string]$Message = "Actualizar delay audio"
)

$ErrorActionPreference = "Stop"

function Assert-GitSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action fallo con codigo $LASTEXITCODE."
    }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
Set-Location -LiteralPath $root

function Get-GitSafeDirectory([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -match '^([A-Za-z]):\\') {
        $drive = Get-PSDrive -Name $Matches[1] -ErrorAction SilentlyContinue
        if ($drive -and $drive.DisplayRoot) {
            $relative = $fullPath.Substring(3).Replace('\', '/')
            return ($drive.DisplayRoot.TrimEnd('\') + '\' + $relative).Replace('\', '/')
        }
    }
    return $fullPath.Replace('\', '/')
}

$safeDirectory = Get-GitSafeDirectory ([string]$root)
$gitCommonArgs = @("-c", "safe.directory=$safeDirectory")

$cleanScript = Join-Path $root ".agents\skills\limpiar-residuos-delay-audio\scripts\clean_residues.ps1"
if (Test-Path -LiteralPath $cleanScript) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $cleanScript
    if ($LASTEXITCODE -ne 0) {
        throw "La limpieza segura fallo con codigo $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
    Write-Output "SIN_GIT: este proyecto no tiene .git. No inicializo repos ni configuro remotos."
    exit 0
}

$inside = git @gitCommonArgs rev-parse --is-inside-work-tree 2>$null
if ($LASTEXITCODE -ne 0 -or $inside.Trim() -ne "true") {
    Write-Output "SIN_GIT: git rev-parse no confirma repo. No inicializo repos."
    exit 0
}

$status = @(git @gitCommonArgs status --short)
Assert-GitSuccess "git status inicial"
if ($status.Count -eq 0) {
    Write-Output "GIT_LIMPIO: no hay cambios para commit."
} else {
    Write-Output "--- CAMBIOS ---"
    $status
    git @gitCommonArgs add -A
    Assert-GitSuccess "git add"
    git @gitCommonArgs commit -m $Message
    Assert-GitSuccess "git commit"
}

$remotes = @(git @gitCommonArgs remote)
Assert-GitSuccess "git remote"
if ($remotes.Count -gt 0) {
    $branch = (git @gitCommonArgs rev-parse --abbrev-ref HEAD).Trim()
    Assert-GitSuccess "git rev-parse de rama"
    $upstream = git @gitCommonArgs rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $upstream) {
        git @gitCommonArgs push
        Assert-GitSuccess "git push"
    } elseif ($remotes -contains "origin" -and $branch -and $branch -ne "HEAD") {
        git @gitCommonArgs push -u origin $branch
        Assert-GitSuccess "git push -u origin"
    } else {
        Write-Output "SIN_UPSTREAM: hay remoto, pero no se puede determinar push seguro."
    }
} else {
    Write-Output "SIN_REMOTO: commit local hecho si habia cambios, sin push."
}

$finalStatus = @(git @gitCommonArgs status --short)
Assert-GitSuccess "git status final"
Write-Output "--- STATUS FINAL ---"
$finalStatus
if ($finalStatus.Count -ne 0) {
    throw "Git no ha quedado limpio."
}
Write-Output "GIT_LIMPIO_FINAL"
