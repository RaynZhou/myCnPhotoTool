# 手工验收：启动 exe → 断言进程存活且窗口标题正确 → 打印体积与启动耗时
# 先跑 build_exe.ps1；本脚本不构建
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exe)) { throw "未找到 $exe，先跑 build_exe.ps1" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$started = Get-Date
# onefile 下真实窗口属子进程（引导父进程无窗口）→ 必须按映像名而非父 PID 取标题。
# 但 PhotoPrint 就是产品 exe 名，绝不能按名全机强杀（会打掉用户自己开着的实例、丢 last_job）。
# 归属边界用"排除法"：只排除快照时已存在的 PhotoPrint；从快照起到清理二次枚举为止
# （≈轮询 30s + 关窗 2s）新起的外部实例仍会被当成本轮 own，匹配与清理都可能误伤——
# dev-only 手工脚本可接受的窄 TOCTOU。
$before = @(Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
if ($before.Count -gt 0) {
    Write-Host "注：检测到 $($before.Count) 个既存 PhotoPrint 实例，本轮不碰也不回收（历史孤儿需手工清）"
}
Start-Process -FilePath $exe | Out-Null

function Get-OwnPhotoPrint {
    Get-Process -Name "PhotoPrint" -ErrorAction SilentlyContinue |
        Where-Object { $before -notcontains $_.Id }
}

# 先礼貌关窗（走 closeEvent 落 last_job），仍没退的再强杀——把"误伤外部实例"的后果从
# 强杀丢数据降为正常关窗。只对"本轮 own"（含 TOCTOU 窗口内误纳者）生效。
# 注意：CloseMainWindow() 是 .NET 方法，对"枚举后已自行退出"的对象会抛 MethodInvocationException，
# 且该异常不受 -EA SilentlyContinue 管辖（必须 try/catch）；一旦在清理里抛出会中断脚本、
# 让本轮 own 残留并落进下次的 $before 被永久豁免。故先判 HasExited、再包 try/catch 兜底。
function Stop-OwnPhotoPrint {
    foreach ($proc in @(Get-OwnPhotoPrint)) {
        if (-not $proc.HasExited) { try { [void]$proc.CloseMainWindow() } catch { } }
    }
    Start-Sleep -Seconds 2
    @(Get-OwnPhotoPrint) | Where-Object { -not $_.HasExited } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

$found = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $own = @(Get-OwnPhotoPrint)
    $found = $own | Where-Object { $_.MainWindowTitle -like "*相片打印助手*" } | Select-Object -First 1
    if ($found) { break }
    if ($own.Count -eq 0) { break }   # 本轮进程全没了（崩/退），别再空等 30s
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
$alive = @(Get-OwnPhotoPrint)

if ($null -eq $found) {
    # 区分"本轮进程已崩/退"与"进程活着但本会话无可枚举窗口"（无交互桌面）
    $state = if ($alive.Count -gt 0) { "本轮进程存活 $($alive.Count) 个但无窗口（本会话无交互桌面？）" }
             else { "本轮进程已退出（崩溃或未能启动）" }
    Write-Host "FAIL 窗口未出现（体积 $sizeMb MB，等待 $elapsed s）：$state"
    Stop-OwnPhotoPrint
    exit 1
}
Write-Host "OK 窗口标题：$($found.MainWindowTitle)（体积 $sizeMb MB，启动 $elapsed s，PID $($found.Id)）"
Stop-OwnPhotoPrint
exit 0
