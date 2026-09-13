[CmdletBinding()]
param(
    [string]$Domain = "localhost",
    [int]$Days = 365
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$certDir = Join-Path $root "deploy\certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null
$resolved = (Resolve-Path $certDir).Path

Write-Host "Generating a development certificate for $Domain in $resolved"
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if ($openssl) {
    $configPath = Join-Path $resolved "openssl.cnf"
    [IO.File]::WriteAllText($configPath, "[req]`ndistinguished_name=req_dn`n[req_dn]`n")
    try {
        & $openssl.Source req -x509 -nodes -newkey rsa:2048 `
            -config $configPath `
            -keyout (Join-Path $resolved "privkey.pem") `
            -out (Join-Path $resolved "fullchain.pem") `
            -days $Days `
            -subj "/CN=$Domain" `
            -addext "subjectAltName=DNS:$Domain,DNS:localhost,IP:127.0.0.1"
    } finally {
        Remove-Item -LiteralPath $configPath -Force -ErrorAction SilentlyContinue
    }
} else {
    docker run --rm `
        --volume "${resolved}:/certs" `
        alpine/openssl req -x509 -nodes -newkey rsa:2048 `
        -keyout /certs/privkey.pem `
        -out /certs/fullchain.pem `
        -days $Days `
        -subj "/CN=$Domain" `
        -addext "subjectAltName=DNS:$Domain,DNS:localhost,IP:127.0.0.1"
}

if ($LASTEXITCODE -ne 0) { throw "Certificate generation failed." }
Write-Host "Development certificate created. Browsers will warn until you trust it locally."