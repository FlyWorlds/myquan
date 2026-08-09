# 一套启动：加载 Node24 → OpenClaw+微信自检（由 index.py watch 内完成）→ 盯盘
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\start_watch.ps1
#   powershell -File .\start_watch.ps1 -- --no-open
#   powershell -File .\start_watch.ps1 -- --restart-gateway --no-open

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

$watchArgs = @("index.py", "watch", "--interval", "5", "--port", "8765", "--no-open")
if ($args.Count -gt 0) {
    # 允许: start_watch.ps1 -- --restart-gateway
    $extra = @($args)
    if ($extra.Count -gt 0 -and $extra[0] -eq "--") {
        $extra = $extra[1..($extra.Count - 1)]
    }
    $watchArgs += $extra
}

Write-Host "[start_watch] $py $($watchArgs -join ' ')"
& $py @watchArgs
exit $LASTEXITCODE
