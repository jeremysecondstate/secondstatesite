$ErrorActionPreference = 'Stop'
$workRoot = 'C:/dev/secondstatesite/tmp/bookkeeper-20261106-0803'
$recordRoot = 'J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING'
$runRoot = Join-Path $recordRoot 'runs/2026-11-06-0803-source-and-ledger-review'
$baseline = Get-Content -Raw -LiteralPath (Join-Path $workRoot 'baseline-register-hashes.json') | ConvertFrom-Json -AsHashtable
$audit = Get-Content -Raw -LiteralPath (Join-Path $workRoot 'staging-audit.json') | ConvertFrom-Json -AsHashtable
if ($audit.status -ne 'PASS') { throw 'Staging audit did not pass' }
foreach ($name in $baseline.Keys) {
 if ((Get-FileHash -LiteralPath (Join-Path $recordRoot $name)).Hash.ToLower() -ne $baseline[$name]) { throw "Concurrent record edit: $name" }
}
foreach ($name in $audit.record_sha256.Keys) {
 if ((Get-FileHash -LiteralPath (Join-Path $workRoot "proposed-records/$name")).Hash.ToLower() -ne $audit.record_sha256[$name]) { throw "Staging changed: $name" }
}
if (Test-Path -LiteralPath $runRoot) { throw 'Run output already exists' }
$backupRoot = Join-Path $runRoot 'before-records'
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
foreach ($name in $baseline.Keys) { Copy-Item -LiteralPath (Join-Path $recordRoot $name) -Destination (Join-Path $backupRoot $name) }
$written = @()
foreach ($name in $audit.record_sha256.Keys) {
 $target = Join-Path $recordRoot $name
 $newBytes = [System.IO.File]::ReadAllBytes((Join-Path $workRoot "proposed-records/$name"))
 $stream = [System.IO.File]::Open($target, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
 $writeStarted = $false
 try {
  $oldBytes = [byte[]]::new($stream.Length)
  $stream.ReadExactly($oldBytes, 0, $oldBytes.Length)
  $oldHash = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($oldBytes)).ToLower()
  if ($oldHash -ne $baseline[$name]) { throw "Concurrent edit under exclusive lock: $name" }
  $writeStarted = $true
  $stream.Position = 0
  $stream.Write($newBytes, 0, $newBytes.Length)
  $stream.SetLength($newBytes.Length)
  $stream.Flush($true)
 } catch {
  if ($writeStarted) {
   $stream.Position = 0
   $stream.Write($oldBytes, 0, $oldBytes.Length)
   $stream.SetLength($oldBytes.Length)
   $stream.Flush($true)
  }
  throw
 } finally { $stream.Dispose() }
 if ((Get-FileHash -LiteralPath $target).Hash.ToLower() -ne $audit.record_sha256[$name]) { throw "Readback mismatch: $name" }
 $written += @{ name=$name; sha256=$audit.record_sha256[$name] }
}
foreach ($name in $baseline.Keys) {
 if (-not $audit.record_sha256.ContainsKey($name)) {
  if ((Get-FileHash -LiteralPath (Join-Path $recordRoot $name)).Hash.ToLower() -ne $baseline[$name]) { throw "Untouched register changed: $name" }
 }
}
$ledger = Join-Path (Split-Path $recordRoot -Parent) 'Second State Books — General Ledger.xlsm'
if ((Get-FileHash -LiteralPath $ledger).Hash.ToLower() -ne '45410605a93bf61fd948f0c128adadcf108a331d5157bc9515d824fbf27855b9') { throw 'Ledger changed during publication' }
@{published_utc=[DateTime]::UtcNow.ToString('o');run_directory=$runRoot;exclusive_concurrent_guards=$true;written=$written;ledger_unchanged=$true;method='Native .NET FileStream exclusive sharing; Python pywin32 unavailable under system runtime'} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $workRoot 'publish-records.json') -Encoding utf8
Write-Output 'Published three audited records with exclusive locks and dated backups.'
