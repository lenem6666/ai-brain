# 安装 `brain` 命令（让所有工具都能调用）

`brain` 只是 `brain.py` 的薄封装，目的是让编译出来的入口文件**跨机器通用**——
文件里只写 `brain brief`，不写 `C:\...\python.exe` 这种本机路径。

仓库自带 `bin/brain.cmd`（Windows）与 `bin/brain.sh`（macOS/Linux 用 `scripts/install.sh` 生成），
脚本用**自身位置**推导安装根目录，所以克隆到任何路径都能直接跑，换机不用改。

## Windows

```powershell
# 1) 装运行时 + 各客户端入口文件（安装根 = 仓库所在目录）
powershell -ExecutionPolicy Bypass -File scripts\install.ps1

# 2) 把 <安装根>\bin 加入用户 PATH（只需一次；示例克隆在 D:\ai-brain）
setx PATH "D:\ai-brain\bin;$env:PATH"
```

重开终端，验证：

```powershell
brain --version
brain doctor
```

> 旧版文档里的 `-ShimOnly` 参数并不存在（`install.ps1` 只做完整安装）。
> 现在也不需要它：`bin/brain.cmd` 随仓库分发，加入 PATH 即可。

## 每小时自动同步（跨机收敛）

没有这一步，A 机的写入要等下次会话钩子或手工 `sync` 才会到达 B 机。
Windows 计划任务每小时跑一次（当前用户即可，不需要管理员）：

```powershell
schtasks /create /tn "ai-brain-sync" /tr "\"D:\ai-brain\bin\sync-task.cmd\"" /sc hourly /mo 1 /f
schtasks /run /tn "ai-brain-sync"          # 立刻跑一次验证
Get-Content D:\ai-brain\logs\sync.log -Tail 6
```

`sync-task.cmd` 会自己探测 git 路径——计划任务的 PATH 通常不含 git，
不探测的话会静默失败（本项目踩过这个坑）。日志里应看到 `已同步到远端`。

macOS / Linux 用 cron 等价：

```bash
(crontab -l 2>/dev/null; echo "17 * * * * $HOME/.ai-brain/bin/brain sync -m auto-sync >> $HOME/.ai-brain/sync.log 2>&1") | crontab -
```

## macOS / Linux

```bash
chmod +x scripts/install.sh && ./scripts/install.sh --shim-only
export PATH="$HOME/.ai-brain/bin:$PATH"     # 写进 ~/.zshrc 或 ~/.bashrc 永久生效
brain --version
```

## 不想改 PATH？

在入口文件里用绝对路径调用也可以，但**换电脑后必须重新 `compile`**，
否则路径失效。PATH 方案的好处是：同一份 `CLAUDE.md` / `AGENTS.md`
可以在所有机器上通用，不需要每次重新生成。

## 手动创建（兜底）

Windows `%USERPROFILE%\.ai-brain\bin\brain.cmd`：

```bat
@echo off
python "D:\path\to\ai-brain\brain.py" %*
```

macOS / Linux `~/.ai-brain/bin/brain`：

```bash
#!/usr/bin/env bash
exec python3 "/path/to/ai-brain/brain.py" "$@"
```

记得 `chmod +x`。
