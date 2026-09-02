# Windows：加载 Node（若有）→ 启动 Python 数据 API + Web 盯盘
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\start_watch.ps1
#   powershell -File .\start_watch.ps1 --no-wechat
#   powershell -File .\start_watch.ps1 -Stop          # 停服务并释放端口
#   powershell -File .\start_watch.ps1 --force      # 强制重启

param(
    [switch]$Stop,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$nodeHook = Join-Path $env:USERPROFILE ".openclaw\use-node24.ps1"
if (Test-Path $nodeHook) {
    . $nodeHook
    Write-Host "[start_watch] loaded use-node24.ps1"
}

$py = $env:MYQUAN_PYTHON
if (-not $py) {
    foreach ($c in @(
        "E:\Miniconda3\python.exe",
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )) {
        if ($c -and (Test-Path -LiteralPath $c)) { $py = $c; break }
    }
}
if (-not $py) { throw "python not found; set MYQUAN_PYTHON" }

$startArgs = @()
if ($Stop) { $startArgs += "--stop" }
if ($Args) { $startArgs += $Args }

Write-Host "[start_watch] $py start_watch.py $($startArgs -join ' ')"
& $py (Join-Path $Root "start_watch.py") @startArgs
exit $LASTEXITCODE
