# 安装 `brain` 命令（让所有工具都能调用）

`brain` 只是 `brain.py` 的薄封装，目的是让编译出来的入口文件**跨机器通用**——
文件里只写 `brain brief`，不写 `C:\...\python.exe` 这种本机路径。

## Windows

```powershell
# 在仓库根目录执行（会生成 %USERPROFILE%\.ai-brain\bin\brain.cmd）
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -ShimOnly
```

然后把下面这个目录加入用户 PATH（只需一次）：

```powershell
setx PATH "$env:USERPROFILE\.ai-brain\bin;$env:PATH"
```

重开终端，验证：

```powershell
brain --version
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
