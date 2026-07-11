@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem FreeCleaner self-signed release certificate generator.
rem Uses only CMD and the Windows PowerShell PKI module.

set "FC_OUTPUT_DIR=%~dp0..\signing-secrets"
set "FC_PFX_FILE=%FC_OUTPUT_DIR%\freecleaner-release-signing.pfx"
set "FC_BASE64_FILE=%FC_OUTPUT_DIR%\WINDOWS_SIGNING_CERTIFICATE_BASE64.txt"
set "FC_PASSWORD_FILE=%FC_OUTPUT_DIR%\WINDOWS_SIGNING_CERTIFICATE_PASSWORD.txt"
set "FC_THUMBPRINT_FILE=%FC_OUTPUT_DIR%\CERTIFICATE_THUMBPRINT.txt"
set "FC_SHA256_FILE=%FC_OUTPUT_DIR%\CERTIFICATE_SHA256.txt"

if not exist "%FC_OUTPUT_DIR%" mkdir "%FC_OUTPUT_DIR%"
if errorlevel 1 goto :error

set "FC_OUTPUT_DIR=%FC_OUTPUT_DIR%"
set "FC_PFX_FILE=%FC_PFX_FILE%"
set "FC_BASE64_FILE=%FC_BASE64_FILE%"
set "FC_PASSWORD_FILE=%FC_PASSWORD_FILE%"
set "FC_THUMBPRINT_FILE=%FC_THUMBPRINT_FILE%"
set "FC_SHA256_FILE=%FC_SHA256_FILE%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "& {" ^
  "$ErrorActionPreference='Stop';" ^
  "$alphabet='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$_-+=';" ^
  "$bytes=New-Object byte[] 48;" ^
  "$rng=[Security.Cryptography.RandomNumberGenerator]::Create();" ^
  "try{$rng.GetBytes($bytes)}finally{$rng.Dispose()};" ^
  "$password=-join($bytes|ForEach-Object{$alphabet[[int]$_ %% $alphabet.Length]});" ^
  "$secure=ConvertTo-SecureString $password -AsPlainText -Force;" ^
  "$cert=New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=FreeCleaner' -FriendlyName 'FreeCleaner Release Signing' -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(2);" ^
  "if(-not $cert){throw 'Certificate creation failed.'};" ^
  "Export-PfxCertificate -Cert $cert -FilePath $env:FC_PFX_FILE -Password $secure -ChainOption EndEntityCertOnly -Force|Out-Null;" ^
  "$pfxBytes=[IO.File]::ReadAllBytes($env:FC_PFX_FILE);" ^
  "$base64=[Convert]::ToBase64String($pfxBytes);" ^
  "$sha=[Security.Cryptography.SHA256]::Create();" ^
  "try{$hashBytes=$sha.ComputeHash($cert.RawData)}finally{$sha.Dispose()};" ^
  "$sha256=($hashBytes|ForEach-Object{$_.ToString('x2')})-join '';" ^
  "[IO.File]::WriteAllText($env:FC_BASE64_FILE,$base64,[Text.Encoding]::ASCII);" ^
  "[IO.File]::WriteAllText($env:FC_PASSWORD_FILE,$password,[Text.Encoding]::ASCII);" ^
  "[IO.File]::WriteAllText($env:FC_THUMBPRINT_FILE,$cert.Thumbprint,[Text.Encoding]::ASCII);" ^
  "[IO.File]::WriteAllText($env:FC_SHA256_FILE,$sha256,[Text.Encoding]::ASCII);" ^
  "Remove-Item -LiteralPath $env:FC_PFX_FILE -Force;" ^
  "Remove-Item -LiteralPath ('Cert:\CurrentUser\My\'+$cert.Thumbprint) -Force;" ^
  "Write-Host 'FreeCleaner signing secrets created.';" ^
  "}"

if errorlevel 1 goto :error
if not exist "%FC_BASE64_FILE%" goto :error
if not exist "%FC_PASSWORD_FILE%" goto :error

echo.
echo Ready: %FC_OUTPUT_DIR%
echo Add the following files as GitHub Actions secrets:
echo   WINDOWS_SIGNING_CERTIFICATE_BASE64.txt
echo   WINDOWS_SIGNING_CERTIFICATE_PASSWORD.txt
echo.
echo Delete the signing-secrets directory after the secrets are saved.
start "" explorer.exe "%FC_OUTPUT_DIR%"
exit /b 0

:error
echo.
echo ERROR: Certificate generation failed.
del /f /q "%FC_PFX_FILE%" 2>nul
exit /b 1
