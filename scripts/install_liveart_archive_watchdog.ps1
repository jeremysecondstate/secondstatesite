param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$taskRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$taskPython = Join-Path $taskRepo '.venv\Scripts\pythonw.exe'
$taskHelper = Join-Path $taskRepo 'scripts\liveart_run_lifecycle.py'
$taskConfig = Join-Path $taskRepo 'private_data\liveart-worker-runs\config.json'
foreach ($taskRequired in @($taskPython, $taskHelper, $taskConfig)) {
    if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) {
        throw "Required file is missing: $taskRequired"
    }
}

$taskName = 'SecondState LiveArt Run Archive Watchdog'
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument ('"{0}" --config "{1}" watchdog --apply' -f $taskHelper, $taskConfig) -WorkingDirectory $taskRepo
$taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$taskDescription = 'Archive verified finished standalone LiveArt run chats after two hours of inactivity, including unread chats. Uses Codex archive; preserves active, uncertain, pinned and on-demand chats and all research state. No model or business-worker calls.'
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description $taskDescription -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, Actions, Triggers, Principal
