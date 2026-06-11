# install_app.ps1 — install and optionally launch Energy GO by server type (Windows).
# Contract:  contracts/serving/launch_scripts.md
# Spec:      REBUILD_SPEC.md §9.1–§9.5
# Requires:  PowerShell 5.1+ or pwsh 7+
# Exit codes: 0=ok 1=bad-arg 2=preflight 3=dep-install 4=config 5=launch 6=no-gpu
[CmdletBinding()]
param(
    [Parameter(HelpMessage="Server role: dev, training, serving, full.")]
    [string]$ServerType = "",

    [Parameter(HelpMessage="Accelerator: cpu or gpu (default: auto-detect).")]
    [string]$Accel = "",

    [Parameter(HelpMessage="Path to site YAML config (default: config/site_gansu.yaml).")]
    [string]$Site = "config/site_gansu.yaml",

    [Parameter(HelpMessage="Checkpoint ID or path (required for serving/full).")]
    [string]$Checkpoint = "",

    [Parameter(HelpMessage="FastAPI listen port (default: 8000, range 1-65535).")]
    [string]$BackendPort = "8000",

    [Parameter(HelpMessage="Frontend listen port (default: 5173, range 1-65535).")]
    [string]$FrontendPort = "5173",

    [Parameter(HelpMessage="Install only; do not start processes.")]
    [switch]$NoLaunch,

    [Parameter(HelpMessage="Stop services and remove .venv, node_modules, dist, .run.")]
    [switch]$Uninstall,

    [Parameter(HelpMessage="With -Uninstall: also remove checkpoints/.")]
    [switch]$Purge,

    [Parameter(HelpMessage="Show this help and exit.")]
    [switch]$Help
)

# ── strict mode ───────────────────────────────────────────────────────────────
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WorkDir = (Get-Location).Path

# ── helpers ───────────────────────────────────────────────────────────────────
function Die {
    param([int]$Code, [string]$Message)
    Write-Error "ERROR [$Code]: $Message"
    exit $Code
}

function Warn { param([string]$Msg); Write-Warning $Msg }
function Info { param([string]$Msg); Write-Host $Msg }

# ── --Help ────────────────────────────────────────────────────────────────────
if ($Help) {
    @"
Usage: install_app.ps1 -ServerType <TYPE> [OPTIONS]

Install and optionally launch Energy GO for the given server role.
Run from the project root directory.

Server types (-ServerType):
  dev        Full stack: JAX, training, serving, frontend dev server (HMR).
  training   JAX + training only; no Node/frontend installed.
  serving    JAX CPU + FastAPI + built frontend bundle; no training deps.
  full       training + serving on one box.

Options:
  -ServerType <dev|training|serving|full>  (required)
  -Accel <cpu|gpu>          Accelerator variant (default: auto-detect gpu->cpu).
  -Site <PATH>              Site YAML config (default: config/site_gansu.yaml).
  -Checkpoint <ID_OR_PATH>  Checkpoint ID or path (required for serving/full).
  -BackendPort <PORT>       FastAPI listen port  (default: 8000, range 1-65535).
  -FrontendPort <PORT>      Frontend dev/static port (default: 5173, range 1-65535).
  -NoLaunch                 Install only; do not start processes.
  -Uninstall                Stop services and remove .venv, node_modules, dist, .run.
  -Purge                    With -Uninstall: also remove checkpoints/.
  -Help                     Show this help and exit.

Exit codes:
  0  Success.
  1  Invalid argument (unknown -ServerType, -Accel, bad port, etc.).
  2  Preflight failure (unsupported OS/arch, toolchain install failed).
  3  Dependency install failure.
  4  Config/checkpoint error (YAML not found, missing -Checkpoint).
  5  Launch failure (port in use, process failed to start).
  6  GPU accelerator requested but no GPU detected.
"@
    exit 0
}

# ── validate -ServerType ──────────────────────────────────────────────────────
if ([string]::IsNullOrEmpty($ServerType)) {
    Die 1 "-ServerType is required. Remediation: Pass -ServerType <dev|training|serving|full>."
}
$ValidTypes = @("dev", "training", "serving", "full")
if ($ServerType -notin $ValidTypes) {
    Die 1 "Unknown -ServerType '$ServerType'. Remediation: Valid values are dev, training, serving, full."
}

# ── validate -Accel ───────────────────────────────────────────────────────────
if (-not [string]::IsNullOrEmpty($Accel)) {
    if ($Accel -notin @("cpu", "gpu")) {
        Die 1 "Unknown -Accel '$Accel'. Remediation: Valid accelerator values are cpu and gpu. Use -Accel cpu for environments without CUDA/Metal."
    }
}

# ── -Purge requires -Uninstall ────────────────────────────────────────────────
if ($Purge -and -not $Uninstall) {
    Die 1 "-Purge must be combined with -Uninstall. Remediation: Use install_app.ps1 -ServerType <TYPE> -Uninstall -Purge."
}

# ── uninstall / purge ─────────────────────────────────────────────────────────
if ($Uninstall) {
    Set-Location $WorkDir

    # Stop processes from .run/pids.json
    $PidsFile = Join-Path $WorkDir ".run\pids.json"
    if (Test-Path $PidsFile) {
        $PidsData = Get-Content $PidsFile -Raw | ConvertFrom-Json
        $PidsData.PSObject.Properties | ForEach-Object {
            $Pid_ = [int]$_.Value
            $Proc = Get-Process -Id $Pid_ -ErrorAction SilentlyContinue
            if ($Proc) {
                Info "Stopping PID $Pid_ ($($_.Name))..."
                Stop-Process -Id $Pid_ -Force -ErrorAction SilentlyContinue
            } else {
                Warn "PID $Pid_ not running (already stopped)."
            }
        }
    }

    $Removed = @()
    foreach ($Dir in @(".venv", "node_modules", "dist", ".run")) {
        $FullPath = Join-Path $WorkDir $Dir
        if (Test-Path $FullPath) {
            Remove-Item $FullPath -Recurse -Force
            $Removed += $Dir
        }
    }

    if ($Purge) {
        $CkptPath = Join-Path $WorkDir "checkpoints"
        if (Test-Path $CkptPath) {
            Remove-Item $CkptPath -Recurse -Force
            $Removed += "checkpoints"
        }
        # Remove *.run artifact files at project root
        Get-ChildItem $WorkDir -Filter "*.run" -File | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    if ($Removed.Count -gt 0) {
        Info "Removed: $($Removed -join ', ')"
    } else {
        Info "Nothing to remove."
    }
    exit 0
}

# ── OS / arch preflight ───────────────────────────────────────────────────────
$OSName = [System.Environment]::OSVersion.Platform
if ($OSName -ne "Win32NT") {
    Die 2 "Unsupported OS: $OSName. Remediation: Supported OSes are macOS and Windows."
}
$Arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
if ($Arch -notin @("X64", "Arm64")) {
    Die 2 "Unsupported arch: $Arch. Remediation: Supported architectures are x64 and arm64."
}

# ── serving always uses CPU ───────────────────────────────────────────────────
if ($ServerType -eq "serving" -and $Accel -eq "gpu") {
    Warn "serving type always uses CPU accelerator; -Accel gpu ignored."
    $Accel = "cpu"
}

# ── GPU detection ─────────────────────────────────────────────────────────────
function Test-GPU {
    if ($env:JAX_PLATFORM_NAME -eq "cpu") { return $false }
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidiaSmi) {
        $result = & nvidia-smi 2>&1
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

if ($Accel -eq "gpu") {
    if (-not (Test-GPU)) {
        Die 6 "GPU accelerator requested but no GPU detected. Remediation: Use -Accel cpu or install CUDA drivers and ensure nvidia-smi is in PATH. See STACK.md."
    }
}

# Auto-detect
if ([string]::IsNullOrEmpty($Accel)) {
    if ($ServerType -eq "serving") {
        $Accel = "cpu"
    } elseif (Test-GPU) {
        $Accel = "gpu"
        Info "Auto-detected GPU accelerator."
    } else {
        $Accel = "cpu"
        Info "No GPU detected; using CPU accelerator."
    }
}

# ── port validation ───────────────────────────────────────────────────────────
function Validate-Port {
    param([string]$PortStr, [string]$FlagName)
    $PortInt = 0
    if (-not [int]::TryParse($PortStr, [ref]$PortInt)) {
        Die 1 "Invalid $FlagName: '$PortStr' is not an integer. Remediation: Provide an integer in range 1-65535."
    }
    if ($PortInt -lt 1 -or $PortInt -gt 65535) {
        Die 1 "Invalid $FlagName: $PortStr is out of range 1-65535. Remediation: Provide an integer in range 1-65535."
    }
    return $PortInt
}
$BackendPortInt  = Validate-Port $BackendPort  "-BackendPort"
$FrontendPortInt = Validate-Port $FrontendPort "-FrontendPort"

# ── config resolve ────────────────────────────────────────────────────────────
Set-Location $WorkDir

$EffectiveCheckpoint = $Checkpoint
if ($ServerType -in @("serving", "full")) {
    if ([string]::IsNullOrEmpty($EffectiveCheckpoint)) {
        $LastCkptFile = Join-Path $WorkDir ".run\last_checkpoint"
        if (Test-Path $LastCkptFile) {
            $EffectiveCheckpoint = (Get-Content $LastCkptFile -Raw).Trim()
        }
    }
    if ([string]::IsNullOrEmpty($EffectiveCheckpoint)) {
        Die 4 "-Checkpoint is required for -ServerType $ServerType and no .run\last_checkpoint found. Remediation: Pass -Checkpoint <id-or-path> or create .run\last_checkpoint."
    }
}

if (-not (Test-Path $Site)) {
    Die 4 "Site YAML not found: '$Site'. Remediation: Pass -Site <path> or create $Site."
}

# ── toolchain preflight ───────────────────────────────────────────────────────
$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $UvCmd) {
    Info "uv not found; attempting to install via winget..."
    & winget install --id astral-sh.uv -e --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Die 2 "uv install failed. Remediation: Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
    }
    $env:PATH += ";$env:USERPROFILE\.local\bin"
}

if ($ServerType -in @("dev", "serving", "full")) {
    $NodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if (-not $NodeCmd) {
        Info "Node not found; attempting to install via winget..."
        & winget install --id OpenJS.NodeJS.LTS -e --silent 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Die 2 "Node install via winget failed. Remediation: Install Node LTS manually: https://nodejs.org"
        }
    }
}

# ── select pyproject extras ───────────────────────────────────────────────────
$JaxExtras = if ($Accel -eq "gpu") { "jax-gpu-cuda" } else { "jax-cpu" }

$Extras = switch ($ServerType) {
    "dev"      { "$JaxExtras,training,serving,frontend-dev" }
    "training" { "$JaxExtras,training" }
    "serving"  { "jax-cpu,serving" }
    "full"     { "$JaxExtras,training,serving" }
}

# ── create / update virtualenv ────────────────────────────────────────────────
$VenvPath = Join-Path $WorkDir ".venv"
if (-not (Test-Path $VenvPath)) {
    Info "Creating virtualenv (.venv)..."
    & uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) {
        Die 2 "Failed to create virtualenv. Remediation: Ensure Python 3.11 is available ('uv python install 3.11')."
    }
}

# ── install dependencies ──────────────────────────────────────────────────────
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
Info "Installing extras: [$Extras]..."
$InstallOutput = & uv pip install --python $PythonExe -e ".[$Extras]" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error ($InstallOutput -join "`n")
    Die 3 "Dependency install failed. Remediation: Check internet connection and pyproject extras. Run: uv pip install -e `".[$Extras]`" manually."
}
$InstallStr = $InstallOutput -join "`n"
if ($InstallStr -match "Installed \d+ package|Downloading") {
    Info $InstallStr
} else {
    Info "Environment up to date. Nothing to do."
}

# ── frontend build ────────────────────────────────────────────────────────────
if ($ServerType -in @("dev", "serving", "full")) {
    $PkgJson = Join-Path $WorkDir "package.json"
    if (Test-Path $PkgJson) {
        Info "Running npm ci..."
        & npm ci --quiet 2>&1
        if ($LASTEXITCODE -ne 0) {
            Die 3 "npm ci failed. Remediation: Ensure Node LTS and npm are installed and package-lock.json is current."
        }
        if ($ServerType -in @("serving", "full")) {
            Info "Building frontend bundle (npm run build)..."
            & npm run build --quiet 2>&1
            if ($LASTEXITCODE -ne 0) {
                Die 3 "npm run build failed. Remediation: Check vite.config.ts and package.json build script."
            }
        }
    } else {
        Info "package.json not found; skipping frontend step."
    }
}

# ── launch ────────────────────────────────────────────────────────────────────
if ($NoLaunch) {
    Info "Install complete (-NoLaunch; processes not started)."
    exit 0
}

New-Item -ItemType Directory -Path ".run" -Force | Out-Null
$Pids = @{}

function Test-PortFree {
    param([int]$Port, [string]$Label)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Die 5 "$Label port $Port is already in use. Remediation: Use -$($Label)Port <other-port> or stop the existing process."
    }
}

$UvicornExe = Join-Path $VenvPath "Scripts\uvicorn.exe"
$PythonExe2 = Join-Path $VenvPath "Scripts\python.exe"

# FastAPI
if ($ServerType -in @("serving", "full", "dev")) {
    Test-PortFree $BackendPortInt "Backend"
    $ReloadArg = if ($ServerType -eq "dev") { @("--reload") } else { @() }
    $ApiProc = Start-Process -FilePath $UvicornExe `
        -ArgumentList (@("energy_go.serving.app:app", "--host", "0.0.0.0", "--port", "$BackendPortInt") + $ReloadArg) `
        -RedirectStandardOutput "$env:TEMP\energy_go_api_$BackendPortInt.log" `
        -RedirectStandardError  "$env:TEMP\energy_go_api_$BackendPortInt.err.log" `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 1
    if ($ApiProc.HasExited) {
        Die 5 "FastAPI failed to start. Remediation: Check logs at $env:TEMP\energy_go_api_$BackendPortInt.log."
    }
    $Pids["api"] = $ApiProc.Id
    Info "FastAPI started  ->  http://localhost:$BackendPortInt  (PID $($ApiProc.Id))"
}

# Training harness
if ($ServerType -in @("training", "full")) {
    $TrainProc = Start-Process -FilePath $PythonExe2 `
        -ArgumentList @("-m", "energy_go.harness.train", "--site", $Site) `
        -RedirectStandardOutput "$env:TEMP\energy_go_training.log" `
        -RedirectStandardError  "$env:TEMP\energy_go_training.err.log" `
        -PassThru -WindowStyle Hidden
    $Pids["training"] = $TrainProc.Id
    Info "Training harness started  (PID $($TrainProc.Id))"
}

# Vite dev server
if ($ServerType -eq "dev") {
    Test-PortFree $FrontendPortInt "Frontend"
    $ViteProc = Start-Process -FilePath "npx" `
        -ArgumentList @("vite", "--port", "$FrontendPortInt") `
        -RedirectStandardOutput "$env:TEMP\energy_go_frontend_$FrontendPortInt.log" `
        -RedirectStandardError  "$env:TEMP\energy_go_frontend_$FrontendPortInt.err.log" `
        -PassThru -WindowStyle Hidden
    $Pids["frontend"] = $ViteProc.Id
    Info "Vite dev server started  ->  http://localhost:$FrontendPortInt  (PID $($ViteProc.Id))"
}

# Write .run/ state files
$Pids | ConvertTo-Json | Set-Content ".run\pids.json"
$EffectiveCheckpoint  | Set-Content ".run\last_checkpoint"
$ServerType           | Set-Content ".run\server_type"

Info ""
Info "Energy GO ($ServerType) is running."
Info "  Backend:  http://localhost:$BackendPortInt"
if ($ServerType -eq "dev") { Info "  Frontend: http://localhost:$FrontendPortInt" }
Info "  Stop:     pwsh scripts/install_app.ps1 -ServerType $ServerType -Uninstall"
