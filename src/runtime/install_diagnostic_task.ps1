param(
    [switch]$Remove,
    [string]$TaskName = 'okww-custom-diagnostics-v1'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$pythonExe = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Local .venv Python is required.'
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$description = "okww diagnostics uploader owned by $repo"
if ($existing -and $existing.Description -ne $description) {
    throw 'Task name belongs to another installation. Export and inspect it before migration.'
}
if ($Remove) {
    if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    return
}
if ($existing) { Write-Output 'Task already installed; no changes made.'; return }
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument '-m src.runtime.diagnostic_uploader' -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description | Out-Null
Write-Output 'Installed for the current signed-in user; no credentials stored. Enable upload separately.'
