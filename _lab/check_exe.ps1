# 手工验收：启动 exe → 断言进程存活且窗口标题正确 → 打印体积与启动耗时
# 先跑 build_exe.ps1；本脚本不构建
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exe)) { throw "未找到 $exe，先跑 build_exe.ps1" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$started = Get-Date
# onefile 下真实窗口属子进程，父(引导)进程 MainWindowTitle 恒空——故按映像名轮询，
# 不看 Start-Process 返回的父 PID；起跑前先清残留 PhotoPrint，避免上轮孤儿被本轮秒匹配假阳性。
Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process -FilePath $exe | Out-Null

$found = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $found = Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*相片打印助手*" } | Select-Object -First 1
    if ($found) { break }
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$alive = @(Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue)

if ($null -eq $found) {
    # 区分“进程已崩/退”与“进程活着但本会话无可枚举窗口”（无交互桌面）
    $state = if ($alive.Count -gt 0) { "进程存活 $($alive.Count) 个但无窗口（本会话无交互桌面？）" }
             else { "进程已退出（崩溃或未能启动）" }
    Write-Host "FAIL 窗口未出现（体积 $sizeMb MB，等待 $elapsed s）：$state"
    Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue | Stop-Process -Force
    exit 1
}
Write-Host "OK 窗口标题：$($found.MainWindowTitle)（体积 $sizeMb MB，启动 $elapsed s，PID $($found.Id)）"
Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue | Stop-Process -Force
exit 0
