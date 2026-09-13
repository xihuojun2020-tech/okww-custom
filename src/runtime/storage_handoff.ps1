param([string]$SourceRepo, [string]$Journal, [ValidateSet('Pause','Restore')][string]$Mode)
$ErrorActionPreference = 'Stop'
$description = "okww diagnostics uploader owned by $([IO.Path]::GetFullPath($SourceRepo))"
$saved = @()
if (Test-Path -LiteralPath $Journal) {
    $saved = @(Get-Content -LiteralPath $Journal -Raw -Encoding UTF8 | ConvertFrom-Json)
}
if ($Mode -eq 'Pause') {
    $owned = @(Get-ScheduledTask | Where-Object { $_.Description -eq $description })
    foreach ($task in $owned) {
        foreach ($action in $task.Actions) {
            if ($action.Arguments -notmatch 'src\.runtime\.diagnostic_uploader') {
                throw 'Owned task has an unexpected action; refusing to stop it.'
            }
            $working = $action.WorkingDirectory
            if ($working -ne $SourceRepo) {
                $binding = Join-Path $working 'source.json'
                if (-not (Test-Path -LiteralPath $binding)) { throw 'Uploader binding missing.' }
                $source = (Get-Content -LiteralPath $binding -Raw -Encoding UTF8 | ConvertFrom-Json).source_repo
                if ($source -ne $SourceRepo) { throw 'Uploader binding belongs to another installation.' }
            }
        }
    }
    if (-not (Test-Path -LiteralPath $Journal)) {
        $saved = @($owned | ForEach-Object {
            @{ Name=$_.TaskName; Path=$_.TaskPath; Enabled=$_.Settings.Enabled;
               Xml=(Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath) }
        })
        ConvertTo-Json -InputObject @($saved) -Depth 8 | Set-Content -LiteralPath ($Journal + '.partial') -Encoding UTF8
        Move-Item -LiteralPath ($Journal + '.partial') -Destination $Journal -Force
    }
    foreach ($task in $owned) {
        Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-Null
        Stop-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
    }
} else {
    foreach ($entry in $saved) {
        $task = Get-ScheduledTask -TaskName $entry.Name -TaskPath $entry.Path -ErrorAction SilentlyContinue
        if ($task -and $task.Description -eq $description -and $entry.Enabled) {
            Enable-ScheduledTask -TaskName $entry.Name -TaskPath $entry.Path | Out-Null
        }
    }
}
