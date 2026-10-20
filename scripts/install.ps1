#Requires -Version 5.1
<#
  ai-brain 安装脚本（Windows）
  用法:
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1                  # 全量安装
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -ShimOnly        # 只装 brain 命令
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Python "C:\Python312\python.exe"
#>
param(
    [switch]$ShimOnly,
    [switch]$Force,
    [string]$Python
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BrainPy  = Join-Path $RepoRoot "brain.py"
$UserHome = $env:USERPROFILE

if (-not (Test-Path $BrainPy)) { throw "找不到 brain.py: $BrainPy" }

# ---------- 1) 定位 Python 3 ----------
$PyExe  = $null
$PyArgs = @()

if ($Python) {
    if (-not (Test-Path $Python) -and -not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        throw "指定的 Python 不可用: $Python"
    }
    $PyExe = $Python
} else {
    $cands = @(
        @{ Exe = "python";  Args = @() },
        @{ Exe = "python3"; Args = @() },
        @{ Exe = "py";      Args = @("-3") }
    )
    foreach ($c in $cands) {
        try {
            if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
            $out = & $c.Exe @($c.Args) --version 2>$null
            if ("$out" -match "Python 3") { $PyExe = $c.Exe; $PyArgs = $c.Args; break }
        } catch { }
    }
}
if (-not $PyExe) {
    throw "未找到 Python 3。请安装 https://www.python.org/downloads/ 或用 -Python 指定路径。"
}
$ver = (& $PyExe @PyArgs --version 2>&1) -join " "
Write-Host "[install] Python: $PyExe $($PyArgs -join ' ') ($ver)"

# ---------- 2) brain 命令 shim ----------
$BinDir = Join-Path $UserHome ".ai-brain\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Shim   = Join-Path $BinDir "brain.cmd"
$invoke = (@($PyExe) + $PyArgs + @("`"$BrainPy`"", "%*")) -join " "
Set-Content -Path $Shim -Value @("@echo off", "$invoke") -Encoding ASCII
Write-Host "[install] brain 命令 -> $Shim"

function Backup-File($p) {
    if (Test-Path $p) {
        $bak = "$p.bak." + (Get-Date -Format "yyyyMMddHHmmss")
        Copy-Item $p $bak
        Write-Host "          已备份 $p -> $bak"
    }
}

if ($ShimOnly) {
    Write-Host ""
    Write-Host "下一步：把 $BinDir 加入 PATH（只需一次）"
    Write-Host "  setx PATH `"$BinDir;%PATH%`""
    Write-Host "重开终端后运行：brain --version"
    exit 0
}

# ---------- 3) 技能目录 ----------
$skillTargets = @()
if (Test-Path (Join-Path $UserHome ".claude")) {
    $skillTargets += (Join-Path $UserHome ".claude\skills\second-brain")
}
if (Test-Path "D:\WorkBuddy\.workbuddy\skills") {
    $skillTargets += "D:\WorkBuddy\.workbuddy\skills\second-brain"
} elseif (Test-Path (Join-Path $UserHome ".workbuddy\skills")) {
    $skillTargets += (Join-Path $UserHome ".workbuddy\skills\second-brain")
}

foreach ($t in $skillTargets) {
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    Copy-Item (Join-Path $RepoRoot "SKILL.md") $t -Force
    Copy-Item (Join-Path $RepoRoot "brain.py") $t -Force
    Write-Host "[install] 技能 -> $t"
}

# ---------- 4) 各工具入口文件 ----------
$cfg = Join-Path $UserHome ".ai-brain\config.json"
if (-not (Test-Path $cfg)) {
    Write-Host "[install] 尚未初始化记忆仓库，跳过入口文件（初始化后执行 brain compile --target all）"
} else {
    $entries = @()
    if (Test-Path (Join-Path $UserHome ".claude")) {
        $entries += @{ Target = "claude"; Out = (Join-Path $UserHome ".claude\CLAUDE.md") }
    }
    if (Test-Path (Join-Path $UserHome ".codex")) {
        $entries += @{ Target = "codex";  Out = (Join-Path $UserHome ".codex\AGENTS.md") }
    }
    if (Test-Path (Join-Path $UserHome ".cursor")) {
        $entries += @{ Target = "cursor"; Out = (Join-Path $UserHome ".cursor\rules\brain.mdc") }
    }
    if (Test-Path (Join-Path $UserHome ".gemini")) {
        $entries += @{ Target = "gemini"; Out = (Join-Path $UserHome ".gemini\GEMINI.md") }
    }
    if ($entries.Count -eq 0) {
        Write-Host "[install] 未检测到 Claude/Codex/Cursor/Gemini 目录，跳过入口文件"
    }
    foreach ($e in $entries) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $e.Out) | Out-Null
        Backup-File $e.Out
        & $PyExe @PyArgs $BrainPy compile --target $e.Target --out $e.Out | Out-Null
        Write-Host "[install] $($e.Target) -> $($e.Out)"
    }
}

Write-Host ""
Write-Host "完成。剩余两步："
Write-Host "  1) setx PATH `"$BinDir;%PATH%`"   （重开终端生效）"
Write-Host "  2) brain init --repo git@github.com:<你>/brain-data.git --device win-office"
Write-Host ""
Write-Host "Claude Code 钩子请手动合并：adapters\claude\hooks.json -> ~\.claude\settings.json"
