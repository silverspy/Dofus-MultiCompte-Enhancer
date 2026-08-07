[CmdletBinding()]
param(
    [string]$OutputDirectory = "certificates",
    [string]$Subject = "CN=Dofus MultiCompte Enhancer Development"
)

$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This script requires Windows PowerShell or PowerShell on Windows."
}

$resolvedOutput = [IO.Path]::GetFullPath((Join-Path $PWD $OutputDirectory))
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null

$password = Read-Host "Choose a password for the development PFX" -AsSecureString
$certificate = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -HashAlgorithm SHA256 `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears(2)

$pfxPath = Join-Path $resolvedOutput "development-code-signing.pfx"
$cerPath = Join-Path $resolvedOutput "development-code-signing.cer"
Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $password | Out-Null
Export-Certificate -Cert $certificate -FilePath $cerPath | Out-Null

Write-Host "Development certificate created:"
Write-Host "  PFX: $pfxPath"
Write-Host "  Public certificate: $cerPath"
Write-Warning "Self-signed certificates are for local testing only and do not establish public SmartScreen trust."
