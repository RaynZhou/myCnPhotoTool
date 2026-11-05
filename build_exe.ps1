# 构建单文件 exe：独立 venv → 装依赖 → PyInstaller onefile/windowed
# 用法：.\build_exe.ps1        正常构建
#      .\build_exe.ps1 -Clean  先删 build/ 与 dist/
param(
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv-build"

if (-not (Test-Path $venv)) {
    python -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $root "requirements.txt")
& $py -m pip install -r (Join-Path $root "requirements-build.txt")

if ($Clean) {
    foreach ($d in "build", "dist") {
        $p = Join-Path $root $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

# 入口是真实 .py 文件；--windowed 等于 --noconsole
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name PhotoPrint `
    --paths $root (Join-Path $root "photoprint\app\__main__.py")

if (-not (Test-Path (Join-Path $root "dist\PhotoPrint.exe"))) {
    throw "构建结束但未产出 dist\PhotoPrint.exe"
}
$mb = [math]::Round((Get-Item (Join-Path $root "dist\PhotoPrint.exe")).Length / 1MB, 1)
Write-Host "OK 产物：$root\dist\PhotoPrint.exe（$mb MB）"
