param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][ValidateSet('win32','win64')][string]$Arch,
  [Parameter(Mandatory=$true)][string]$Version,
  [string]$OutputDir = 'dist'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ExePath)) {
  throw "Executable not found: $ExePath"
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
  $candidatePaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($candidate in $candidatePaths) {
    if ($candidate -and (Test-Path $candidate)) {
      $iscc = Get-Item $candidate
      break
    }
  }
}

if (-not $iscc) {
  throw "Inno Setup compiler not found. Install Inno Setup 6 and ensure ISCC.exe is available."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$fullExePath = (Resolve-Path $ExePath).Path
$fullOutputDir = (Resolve-Path $OutputDir).Path

& $iscc.Source `
  "/DMySourceExe=$fullExePath" `
  "/DMyAppArch=$Arch" `
  "/DMyAppVersion=$Version" `
  "/DMyOutputDir=$fullOutputDir" `
  "installer.iss"

if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup failed with exit code $LASTEXITCODE"
}
