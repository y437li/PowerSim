# run_app.ps1 — launch an already-installed Energy GO server type (Windows).
# Assumes install_app.ps1 has been run first (no dependency install).
# Contract:  contracts/serving/launch_scripts.md §6
# Spec:      REBUILD_SPEC.md §9.3 (run_app performs steps 4+6 only)
# Requires:  PowerShell 5.1+ or pwsh 7+
[CmdletBinding()]
param(
    [Parameter(HelpMessage="Server role: dev, training, serving, full.")]
    [string]$ServerType = "",

    [Parameter(HelpMessage="Accelerator: cpu or gpu (default: cpu).")]
    [string]$Accel = "cpu",

    [Parameter(HelpMessage="Path to site YAML config (default: config/site_gansu.yaml).")]
    [string]$Site = "config/site_gansu.yaml",

    [Parameter(HelpMessage="Checkpoint ID or path (required for serving/full).")]
    [string]$Checkpoint = "",

    [Parameter(HelpMessage="FastAPI listen port (default: 8000, range 1-65535).")]
    [string]$BackendPort = "8000",

    [Parameter(HelpMessage="Frontend listen port (default: 5173, range 1-65535).")]
    [string]$FrontendPort = "5173",

    [Parameter(HelpMessage="Show this help and exit.")]
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WorkDir = (Get-Location).Path

function Die {
    param([int]$Code, [string]$Message)
    Write-Error "ERROR [$Code]: $Message"
    exit $Code
}
function Info { param([string]$Msg); Write-Host $Msg }

if ($Help) {
    @"
Usage: run_app.ps1 -ServerType <TYPE> [OPTIONS]

Launch an already-installed Energy GO server type.
Run install_app.ps1 first if .venv is absent.

Options:
  -ServerType <dev|training|serving|full>  (required)
  -Accel <cpu|gpu>          Accelerator variant (default: cpu).
  -Site <PATH>              Site YAML config (default: config/site_gansu.yaml).
  -Checkpoint <ID_OR_PATH>  Checkpoint for serving/full.
  -BackendPort <PORT>       FastAPI listen port  (default: 8000, range 1-65535).
  -FrontendPort <PORT>      Frontend port (default: 5173, range 1-65535).
  -Help                     Show this help and exit.
"@
    exit 0
}

# ── validate ──────────────────────────────────────────────────────────────────
if ([string]::IsNullOrEmpty($ServerType)) {
    Die 1 "-ServerType is required. Remediation: Pass -ServerType <dev|training|serving|full>."
}
if ($ServerType -notin @("dev", "training", "serving", "full")) {
    Die 1 "Unknown -ServerType '$ServerType'. Remediation: Valid values are dev, training, serving, full."
}

# ── check .venv exists ────────────────────────────────────────────────────────
Set-Location $WorkDir
$VenvPath = Join-Path $WorkDir ".venv"
if (-not (Test-Path $VenvPath)) {
    Write-Error "ERROR: No virtualenv found at $WorkDir\.venv."
    Write-Error "Remediation: Run install_app.ps1 -ServerType $ServerType first to install the environment."
    exit 1
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
$EffectiveCheckpoint = $Checkpoint
if ($ServerType -in @("serving", "full")) {
    if ([string]::IsNullOrEmpty($EffectiveCheckpoint)) {
        $LastCkptFile = Join-Path $WorkDir ".run\last_checkpoint"
        if (Test-Path $LastCkptFile) {
            $EffectiveCheckpoint = (Get-Content $LastCkptFile -Raw).Trim()
        }
    }
    if ([string]::IsNullOrEmpty($EffectiveCheckpoint)) {
        Die 4 "-Checkpoint is required for -ServerType $ServerType. Remediation: Pass -Checkpoint <id-or-path>."
    }
}

if (-not (Test-Path $Site)) {
    Die 4 "Site YAML not found: '$Site'. Remediation: Pass -Site <path> or run install_app.ps1 first."
}

# ── launch ────────────────────────────────────────────────────────────────────
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
$PythonExe  = Join-Path $VenvPath "Scripts\python.exe"

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

if ($ServerType -in @("training", "full")) {
    $TrainProc = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "energy_go.harness.train", "--site", $Site) `
        -RedirectStandardOutput "$env:TEMP\energy_go_training.log" `
        -RedirectStandardError  "$env:TEMP\energy_go_training.err.log" `
        -PassThru -WindowStyle Hidden
    $Pids["training"] = $TrainProc.Id
    Info "Training harness started  (PID $($TrainProc.Id))"
}

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

$Pids | ConvertTo-Json | Set-Content ".run\pids.json"
$EffectiveCheckpoint  | Set-Content ".run\last_checkpoint"
$ServerType           | Set-Content ".run\server_type"

Info ""
Info "Energy GO ($ServerType) is running."
Info "  Stop:  pwsh scripts/install_app.ps1 -ServerType $ServerType -Uninstall"
