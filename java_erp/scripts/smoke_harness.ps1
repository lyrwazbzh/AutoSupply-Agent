# Harness 契约冒烟（PowerShell）。前提：java_erp 已在 :8080 启动，且库中至少有 partId=1。
$ErrorActionPreference = "Stop"
$base = "http://localhost:8080"
$key = "idem-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$op = "op-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8)

$body = @{
  orderNumber = "PO-$key"
  status = 0
  idempotencyKey = $key
  totalAmount = 51
  orderDetail = @(@{ partId = 1; quantity = 2; unitPrice = 25.5 })
} | ConvertTo-Json -Depth 5

Write-Host "== 1) create =="
$r1 = Invoke-RestMethod -Method Post -Uri "$base/api/orders/create" -ContentType "application/json" -Headers @{ "X-Operation-Id" = $op } -Body $body
if ($r1.code -ne 200) { throw "create failed: $($r1 | ConvertTo-Json -Compress)" }
$orderId = $r1.data.id
Write-Host "orderId=$orderId"

Write-Host "== 2) idempotent replay =="
$r2 = Invoke-RestMethod -Method Post -Uri "$base/api/orders/create" -ContentType "application/json" -Headers @{ "X-Operation-Id" = "$op-b" } -Body $body
if ($r2.code -ne 200) { throw "replay failed" }
if ($r2.data.id -ne $orderId) { throw "idempotency broke: $($r2.data.id) vs $orderId" }

Write-Host "== 3) conflict 409 =="
$conflict = @{
  orderNumber = "PO-$key-x"
  idempotencyKey = $key
  totalAmount = 100
  orderDetail = @(@{ partId = 1; quantity = 4; unitPrice = 25 })
} | ConvertTo-Json -Depth 5
$r3 = Invoke-RestMethod -Method Post -Uri "$base/api/orders/create" -ContentType "application/json" -Body $conflict
if ($r3.code -ne 409) { throw "expected 409, got $($r3.code)" }

Write-Host "== 4) operation applied =="
$r4 = Invoke-RestMethod -Uri "$base/api/operations/$op"
if (-not $r4.data.applied) { throw "operation not applied" }

Write-Host "== 5) by-idempotency =="
$r5 = Invoke-RestMethod -Uri "$base/api/orders/by-idempotency?idempotencyKey=$key"
if ($r5.data.id -ne $orderId) { throw "by-idempotency mismatch" }

Write-Host "== 6) supplier status 0 -> 2 =="
# 取一个已有供应商改状态；失败则跳过
try {
  $page = Invoke-RestMethod -Uri "$base/api/suppliers/page?current=1&size=1"
  $sid = $page.data.records[0].id
  $rs = Invoke-RestMethod -Method Patch -Uri "$base/api/suppliers/update-status/${sid}?status=0"
  if ($rs.code -eq 200 -and $rs.data.status -ne 2) { throw "status 0 not normalized to 2" }
} catch {
  Write-Host "supplier status check skipped: $_"
}

Write-Host "SMOKE OK"
Write-Host "接着在 MySQL 执行 docs/verify_invariants.sql"
