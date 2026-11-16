param(
  [string]$BaseUrl = $(if ($env:ERP_BASE_URL) { $env:ERP_BASE_URL } else { "http://localhost:8080" }),
  [switch]$ReadOnly,
  [switch]$BootstrapFixture
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "smoke_harness.py"
$arguments = @($script, "--base-url", $BaseUrl)
if ($ReadOnly) { $arguments += "--read-only" }
if ($BootstrapFixture) { $arguments += "--bootstrap-fixture" }

& python @arguments
if ($LASTEXITCODE -ne 0) {
  throw "Java ERP smoke failed with exit code $LASTEXITCODE"
}
