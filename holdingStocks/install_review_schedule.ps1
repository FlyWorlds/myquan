# Install/uninstall/status: Mon+Fri 15:00 market review WeChat push (Task Scheduler)
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_review_schedule.ps1 install
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_review_schedule.ps1 uninstall
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_review_schedule.ps1 status

param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "uninstall", "status")]
    [string]$Mode = "install"
)

$ErrorActionPreference = "Stop"
$TaskName = "myquan-market-review-mon-fri-1500"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PushScript = Join-Path $Root "review_push.ps1"

if (-not (Test-Path -LiteralPath $PushScript)) {
    throw "Missing script: $PushScript"
}

function Get-TaskOrNull {
    try {
        return Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    }
    catch {
        return $null
    }
}

if ($Mode -eq "uninstall") {
    $t = Get-TaskOrNull
    if ($null -eq $t) {
        Write-Host "Task not found: $TaskName"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Uninstalled: $TaskName"
    exit 0
}

if ($Mode -eq "status") {
    $t = Get-TaskOrNull
    if ($null -eq $t) {
        Write-Host "Not installed: $TaskName"
        exit 1
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task: $TaskName"
    Write-Host "State: $($t.State)"
    Write-Host "LastRun: $($info.LastRunTime)  Result=$($info.LastTaskResult)"
    Write-Host "NextRun: $($info.NextRunTime)"
    exit 0
}

# install
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PushScript`""
$taskAction = New-ScheduledTaskAction -Execute $psExe -Argument $argList -WorkingDirectory $Root
$taskTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Friday -At 15:00
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-TaskOrNull
if ($null -ne $existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed old task, reinstalling..."
}

Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Principal $taskPrincipal -Description "myquan market review WeChat push Mon/Fri 15:00" -Force | Out-Null

Write-Host "Installed: $TaskName"
Write-Host "  When: Monday and Friday 15:00"
Write-Host "  Script: $PushScript"
Write-Host "  Status: powershell -File `"$PSCommandPath`" status"
Write-Host "  Uninstall: powershell -File `"$PSCommandPath`" uninstall"
Write-Host "  Manual run: powershell -File `"$PushScript`""
exit 0
