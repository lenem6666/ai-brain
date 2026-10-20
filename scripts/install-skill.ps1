param(
    [string]$Dest = "$env:USERPROFILE\.workbuddy\skills",
    [string]$Proxy = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = "lenem6666/ai-brain"
$zip  = Join-Path $env:TEMP "ai-brain-skill.zip"
$tmp  = Join-Path $env:TEMP "ai-brain-skill-tmp"

function Get-Zip($url, $out) {
    if ($Proxy) {
        Invoke-WebRequest -Uri $url -OutFile $out -Proxy $Proxy -UseBasicParsing
    } else {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
    }
}

Write-Host "[1/3] 下载 ai-brain ..."
$url = "https://codeload.github.com/$repo/zip/refs/heads/main"
try {
    Get-Zip $url $zip
} catch {
    if (-not $Proxy) {
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $c.Connect("127.0.0.1", 10809)
            $c.Close()
            Write-Host "      直连失败，改用本机代理 127.0.0.1:10809 重试 ..."
            $Proxy = "http://127.0.0.1:10809"
            Get-Zip $url $zip
        } catch { throw }
    } else { throw }
}

Write-Host "[2/3] 解压并安装 Skill ..."
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$src = Join-Path $tmp "ai-brain-main\skill\ai-brain-setup"
if (-not (Test-Path (Join-Path $src "SKILL.md"))) {
    throw "压缩包里没有找到 skill\ai-brain-setup\SKILL.md，仓库结构可能变了"
}

if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }
$target = Join-Path $Dest "ai-brain-setup"
if (Test-Path $target) {
    # 备份必须放在 skills 目录之外：那里的任何子目录带 SKILL.md 都会被当成一个技能
    $bak = Join-Path $env:TEMP ("ai-brain-setup.bak-" + (Get-Date -Format "yyyyMMddHHmmss"))
    Move-Item $target $bak
    Write-Host "      已存在旧版本，备份到 $bak"
}
Copy-Item -Recurse -Force $src $target

Remove-Item $zip -Force -ErrorAction SilentlyContinue
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[3/3] 完成 -> $target"
Write-Host ""
Write-Host "下一步：重启 WorkBuddy，在新对话里说「恢复我的记忆」。"
Write-Host "第一次会要一次 GitHub 授权（记忆库是私有仓库），之后不再需要。"
