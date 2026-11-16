$ErrorActionPreference = "Stop"

$baseDir = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
$propertiesPath = Join-Path $PSScriptRoot "maven-wrapper.properties"
$properties = ConvertFrom-StringData (Get-Content -Raw -LiteralPath $propertiesPath)
$distributionUrl = if ($env:MAVEN_DISTRIBUTION_URL) { $env:MAVEN_DISTRIBUTION_URL } else { $properties.distributionUrl }
$expectedSha = $properties.distributionSha512Sum.ToLowerInvariant()
$distRoot = Join-Path $PSScriptRoot "dists"
$distDir = Join-Path $distRoot "apache-maven-3.9.9"
$archive = Join-Path $distRoot "apache-maven-3.9.9-bin.tar.gz"
$maven = Join-Path $distDir "bin\mvn.cmd"

if (-not (Test-Path -LiteralPath $maven)) {
    New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -UseBasicParsing -Uri $distributionUrl -OutFile $archive
    }
    $sha512 = [System.Security.Cryptography.SHA512]::Create()
    $stream = [System.IO.File]::OpenRead($archive)
    try {
        $actualSha = ([System.BitConverter]::ToString($sha512.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha512.Dispose()
    }
    if ($actualSha -ne $expectedSha) {
        Remove-Item -LiteralPath $archive -Force
        throw "Maven distribution SHA-512 mismatch."
    }
    if (Test-Path -LiteralPath $distDir) {
        Remove-Item -LiteralPath $distDir -Recurse -Force
    }
    & tar.exe -xzf $archive -C $distRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract Maven distribution."
    }
}

& $maven @args
exit $LASTEXITCODE
