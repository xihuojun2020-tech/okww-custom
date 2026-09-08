param(
    [Parameter(Mandatory=$true)][string]$SourceRepo,
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$TaskName
)
$ErrorActionPreference = 'Stop'
$SourceRepo = [IO.Path]::GetFullPath($SourceRepo)
$Bundle = [IO.Path]::GetFullPath($Bundle)
$Root = [IO.Path]::GetFullPath($Root)
$expected = "okww diagnostics uploader owned by $SourceRepo"
$old = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($old -and $old.Description -ne $expected) { throw 'Task belongs to another installation.' }
$binding = Get-Content -LiteralPath (Join-Path $Bundle 'ready.json') -Raw | ConvertFrom-Json
if ($binding.source_repo -ne $SourceRepo) { throw 'Runtime ownership mismatch.' }
$backupDirectory = Join-Path $Bundle 'migration'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backup = Join-Path $backupDirectory ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.xml')
$xml = $null
if ($old) {
    $xml = Export-ScheduledTask -TaskName $TaskName
    [IO.File]::WriteAllText($backup, $xml)
}
try {
    if ($old) {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Stop-ScheduledTask -TaskName $TaskName
    }
    # Stop only uploader command lines tied to this exact spool and app Python.
    # No process-name-wide killing; descendants also carry the spool in their arguments.
    $pythonDirectory = [IO.Path]::GetFullPath((Join-Path $SourceRepo '..\python'))
    foreach ($process in Get-CimInstance Win32_Process) {
        if (-not $process.ExecutablePath -or -not $process.CommandLine) { continue }
        if ((Split-Path -Parent $process.ExecutablePath) -ne $pythonDirectory) { continue }
        if ($process.CommandLine -notmatch '(?i)\s-m\s+src\.runtime\.diagnostic_uploader\s') { continue }
        if ($process.CommandLine -notmatch ([regex]::Escape($Root) + '(?:[\\/"\s]|$)')) { continue }
        # Recheck creation time and command line immediately before targeting the PID.
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)"
        if ($current -and $current.CreationDate -eq $process.CreationDate -and $current.CommandLine -eq $process.CommandLine) {
            $termination = Invoke-CimMethod -InputObject $current -MethodName Terminate
            if ($termination.ReturnValue -ne 0) { throw "Owned uploader stop failed: $($termination.ReturnValue)" }
        }
    }
    & (Join-Path $Bundle 'src/runtime/install_diagnostic_task.ps1') -SourceRepo $SourceRepo -Root $Root -TaskName $TaskName -PythonExe (Join-Path $Bundle 'python/pythonw.exe')
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    $installed = Get-ScheduledTask -TaskName $TaskName
    if ($installed.Actions.Execute -ne (Join-Path $Bundle 'python/pythonw.exe')) { throw 'Migrated task action mismatch.' }
    Write-Output "Migration completed. Original task backup: $backup"
} catch {
    if ($xml) {
        Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
    } else {
        $created = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($created -and $created.Description -eq $expected) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }
    }
    throw
}
