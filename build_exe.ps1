# 构建单文件 exe：独立 venv → 装依赖 → PyInstaller onefile/windowed
# 用法：.\build_exe.ps1        正常构建
#      .\build_exe.ps1 -Clean  先删 build/ 与 dist/
param(
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv-build"

if ($Clean) {
    foreach ($d in "build", "dist") {
        $p = Join-Path $root $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

$py = Join-Path $venv "Scripts\python.exe"
# 判解释器真存在（只看目录会放过半残 venv，炸在后面 & $py 找不到命令）
if (-not (Test-Path $py)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "python -m venv 失败 rc=$LASTEXITCODE" }
}
& $py --version
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败 rc=$LASTEXITCODE" }
& $py -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "装运行时依赖失败 rc=$LASTEXITCODE" }
& $py -m pip install -r (Join-Path $root "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "装构建期依赖失败 rc=$LASTEXITCODE" }

# 入口是真实 .py 文件；--windowed 等于 --noconsole
# 原生命令非零退出不会被 ErrorActionPreference=Stop 拦下（那是 7.3+ 才有的），必须手查 $LASTEXITCODE
# 显式钉死输出路径到 $root（不依赖 CWD），否则从别处按绝对路径调用时 PyInstaller 会往 CWD 写 dist、
# 而下面的产物检查与 -Clean 都锚在 $root，会错报“未产出”或删错位置。
$buildStart = Get-Date
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PhotoPrint `
    --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") --specpath $root `
    --paths $root (Join-Path $root "photoprint\app\__main__.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 rc=$LASTEXITCODE" }

$exePath = Join-Path $root "dist\PhotoPrint.exe"
if (-not (Test-Path $exePath)) {
    throw "构建结束但未产出 dist\PhotoPrint.exe"
}
# 新鲜度：本次没真产出、但上一次残留 exe 还在原位时，不能对着旧 exe 报 OK
if ((Get-Item $exePath).LastWriteTime -lt $buildStart) {
    throw "dist\PhotoPrint.exe 时间戳早于本次构建，疑似上次残留"
}
$mb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "OK 产物：$exePath（$mb MB）"
