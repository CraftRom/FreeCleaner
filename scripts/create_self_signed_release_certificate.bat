@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem Uses only CMD and the Windows PowerShell PKI module included with Windows.
set "GENERATOR=%~dp0create_self_signed_release_certificate.ps1"

if not exist "%GENERATOR%" (
    echo ERROR: Missing generator script:
    echo %GENERATOR%
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%GENERATOR%"
if errorlevel 1 (
    echo.
    echo ERROR: Certificate generation or PFX validation failed.
    exit /b 1
)

echo.
echo The signing-secrets folder contains the two values for GitHub Actions.
echo Replace BOTH existing secrets, then delete the local folder.
start "" explorer.exe "%~dp0..\signing-secrets"
exit /b 0
