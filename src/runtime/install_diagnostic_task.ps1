param(
    [switch]$Remove,
    [switch]$Preview,
    [switch]$Verify,
    [string]$TaskName = 'okww-custom-diagnostics-v1',
    [string]$PythonExe,
    [string]$Root,
    [string]$SourceRepo
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $PythonExe) { $PythonExe = Join-Path $repo '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Local .venv Python is required.'
}
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $SourceRepo) { $SourceRepo = $repo }
$SourceRepo = [IO.Path]::GetFullPath($SourceRepo)
$description = "okww diagnostics uploader owned by $SourceRepo"
if ($existing -and $existing.Description -ne $description) {
    throw 'Task name belongs to another installation. Export and inspect it before migration.'
}
if ($Remove) {
    if ($existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    return
}
$silentPython = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $silentPython -PathType Leaf)) {
    throw 'pythonw.exe is required for background upload without console windows.'
}
$PythonExe = [IO.Path]::GetFullPath($silentPython)
$arguments = '-E -s -m src.runtime.diagnostic_uploader'
if ($Root) {
    if ($Root.Contains('"')) { throw 'Invalid spool path.' }
    $arguments += ' --root "' + [IO.Path]::GetFullPath($Root) + '"'
}
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $repo
if ($Verify) {
    if ($existing -and $existing.Description -eq $description -and
        $existing.Actions.Execute -eq $pythonExe -and
        $existing.Actions.Arguments -eq $arguments -and
        $existing.Actions.WorkingDirectory -eq $repo) { exit 0 }
    exit 1
}
if ($Preview) {
    $action | Select-Object Execute, Arguments, WorkingDirectory | ConvertTo-Json
    return
}
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if ($existing) {
    if ($existing.Actions.Execute -eq $pythonExe -and $existing.Actions.Arguments -eq $arguments -and $existing.Actions.WorkingDirectory -eq $repo) {
        Write-Output 'Task already matches this installation.'
        return
    }
    # Ownership was checked above. Stop the old action before replacing it so
    # an already-running snapshot cannot keep uploading to a retired NAS.
    Stop-ScheduledTask -TaskName $TaskName
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description | Out-Null
}
Write-Output 'Installed for the current signed-in user; automatic upload and weekly log retention enabled.'
