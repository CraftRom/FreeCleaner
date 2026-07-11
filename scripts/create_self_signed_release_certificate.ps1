[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\signing-secrets'),
    [string]$Subject = 'CN=FreeCleaner',
    [int]$ValidYears = 2
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$codeSigningOid = '1.3.6.1.5.5.7.3.3'
$outputDirectoryPath = [IO.Path]::GetFullPath($OutputDirectory)
$pfxPath = Join-Path $outputDirectoryPath 'freecleaner-release-signing.pfx'
$base64Path = Join-Path $outputDirectoryPath 'WINDOWS_SIGNING_CERTIFICATE_BASE64.txt'
$passwordPath = Join-Path $outputDirectoryPath 'WINDOWS_SIGNING_CERTIFICATE_PASSWORD.txt'
$thumbprintPath = Join-Path $outputDirectoryPath 'CERTIFICATE_THUMBPRINT.txt'
$sha256Path = Join-Path $outputDirectoryPath 'CERTIFICATE_SHA256.txt'

$createdThumbprint = $null
$validatedThumbprint = $null

function Remove-CertificateIfPresent {
    param([string]$Thumbprint)
    if ([string]::IsNullOrWhiteSpace($Thumbprint)) {
        return
    }
    $path = "Cert:\CurrentUser\My\$Thumbprint"
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

try {
    New-Item -ItemType Directory -Path $outputDirectoryPath -Force | Out-Null

    foreach ($path in @($pfxPath, $base64Path, $passwordPath, $thumbprintPath, $sha256Path)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }

    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$_-+='
    $randomBytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($randomBytes)
    } finally {
        $rng.Dispose()
    }
    $password = -join ($randomBytes | ForEach-Object { $alphabet[[int]$_ % $alphabet.Length] })
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force

    Write-Host '[1/6] Creating a code-signing certificate...'
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -FriendlyName 'FreeCleaner Release Signing' `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears($ValidYears)

    if (-not $certificate -or -not $certificate.HasPrivateKey) {
        throw 'Certificate creation did not produce a private key.'
    }
    $createdThumbprint = $certificate.Thumbprint
    $expectedThumbprint = $certificate.Thumbprint

    $createdEkus = @($certificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    if ($createdEkus -notcontains $codeSigningOid) {
        throw "Created certificate is missing the Code Signing EKU ($codeSigningOid)."
    }

    Write-Host '[2/6] Exporting the certificate and private key to PFX...'
    Export-PfxCertificate `
        -Cert $certificate `
        -FilePath $pfxPath `
        -Password $securePassword `
        -ChainOption EndEntityCertOnly `
        -Force | Out-Null

    if (-not (Test-Path -LiteralPath $pfxPath)) {
        throw 'PFX export did not create a file.'
    }

    # Remove the original certificate before re-importing, so validation proves
    # that the private key is really present in the exported PFX.
    Remove-CertificateIfPresent -Thumbprint $createdThumbprint

    Write-Host '[3/6] Re-importing and validating the generated PFX...'
    Import-PfxCertificate `
        -FilePath $pfxPath `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -Password $securePassword `
        -Exportable | Out-Null

    $validatedCertificate = Get-ChildItem -Path 'Cert:\CurrentUser\My' -CodeSigningCert |
        Where-Object { $_.Thumbprint -eq $expectedThumbprint } |
        Select-Object -First 1

    if (-not $validatedCertificate) {
        throw 'The exported PFX cannot be re-imported as a usable code-signing certificate.'
    }
    if (-not $validatedCertificate.HasPrivateKey) {
        throw 'The exported PFX lost its private key.'
    }
    $validatedThumbprint = $validatedCertificate.Thumbprint

    $validatedEkus = @($validatedCertificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    if ($validatedEkus -notcontains $codeSigningOid) {
        throw "The exported PFX is missing the Code Signing EKU ($codeSigningOid)."
    }

    Write-Host '[4/6] Converting the validated PFX to Base64...'
    $pfxBytes = [IO.File]::ReadAllBytes($pfxPath)
    $base64 = [Convert]::ToBase64String($pfxBytes)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($validatedCertificate.RawData)
    } finally {
        $sha.Dispose()
    }
    $sha256 = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''

    Write-Host '[5/6] Writing GitHub secret values...'
    [IO.File]::WriteAllText($base64Path, $base64, [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($passwordPath, $password, [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($thumbprintPath, $validatedCertificate.Thumbprint, [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($sha256Path, $sha256, [Text.Encoding]::ASCII)

    if ([string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $base64Path -Raw))) {
        throw 'Generated Base64 secret is empty.'
    }
    if ([string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $passwordPath -Raw))) {
        throw 'Generated password secret is empty.'
    }

    Write-Host '[6/6] Removing temporary local PFX and certificate...'
    Remove-Item -LiteralPath $pfxPath -Force
    Remove-CertificateIfPresent -Thumbprint $validatedThumbprint
    $createdThumbprint = $null
    $validatedThumbprint = $null

    Write-Host ''
    Write-Host 'FreeCleaner signing secrets were created and validated successfully.'
    Write-Host "Output directory: $outputDirectoryPath"
    Write-Host 'Replace BOTH GitHub Actions secrets with the complete file contents:'
    Write-Host '  WINDOWS_SIGNING_CERTIFICATE_BASE64.txt'
    Write-Host '  WINDOWS_SIGNING_CERTIFICATE_PASSWORD.txt'
} catch {
    Write-Error $_
    foreach ($path in @($pfxPath, $base64Path, $passwordPath, $thumbprintPath, $sha256Path)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
    throw
} finally {
    Remove-CertificateIfPresent -Thumbprint $createdThumbprint
    Remove-CertificateIfPresent -Thumbprint $validatedThumbprint
}
