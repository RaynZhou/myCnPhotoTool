# 手工验收：启动 exe → 断言进程存活且窗口标题正确 → 打印体积与启动耗时
# 先跑 build_exe.ps1；本脚本不构建
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exe)) { throw "未找到 $exe，先跑 build_exe.ps1" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$started = Get-Date
$p = Start-Process -FilePath $exe -PassThru

$found = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $candidate = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { break }
    if ($candidate.MainWindowTitle -like "*相片打印助手*") { $found = $candidate; break }
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

if ($null -eq $found) {
    Write-Host "FAIL 窗口未出现（体积 $sizeMb MB，等待 $elapsed s）"
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    exit 1
}
Write-Host "OK 窗口标题：$($found.MainWindowTitle)（体积 $sizeMb MB，启动 $elapsed s）"
Stop-Process -Id $p.Id -Force
exit 0
