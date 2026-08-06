# 行情复盘推送：拉行情 → 生成复盘 → OpenClaw 微信推送
# 由计划任务在周一/周五 15:00 调用；也可手工：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\review_push.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir "review_push_$stamp.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $line
}

try {
    $nodeHook = Join-Path $env:USERPROFILE ".openclaw\use-node24.ps1"
    if (Test-Path $nodeHook) {
        . $nodeHook
        Write-Log "loaded use-node24.ps1"
    } else {
        Write-Log "warn: missing $nodeHook (openclaw may still work if PATH ok)"
    }

    $py = $env:MYQUAN_PYTHON
    if (-not $py) {
        foreach ($c in @(
            "E:\Miniconda3\python.exe",
            "C:\Users\EDY\Miniconda3\python.exe",
            (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        )) {
            if ($c -and (Test-Path -LiteralPath $c)) {
                $py = $c
                break
            }
        }
    }
    if (-not $py) {
        throw "找不到 python。请设置环境变量 MYQUAN_PYTHON 为 python.exe 绝对路径。"
    }

    Set-Location -LiteralPath $Root
    Write-Log "cwd=$Root"
    Write-Log "python=$py"
    Write-Log "start: index.py review"

    & $py "index.py" "review" 2>&1 | ForEach-Object {
        $s = "$_"
        Add-Content -Path $Log -Value $s -Encoding UTF8
        Write-Host $s
    }
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    Write-Log "done exit=$code log=$Log"
    exit $code
}
catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    exit 1
}
