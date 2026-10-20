# Codex CLI 适配

**能力等级：自动读 + 指令驱动写（无钩子）**

## 安装

```bash
brain compile --target codex --out ~/.codex/AGENTS.md      # 全局
brain compile --target codex --out ./AGENTS.md --project 项目名   # 项目级（可选）
```

## 工作原理

Codex 每次会话自动读取 `AGENTS.md`。文件里写死了三段协议：

1. 会话开始 → 执行 `brain brief`
2. 过程中 → `brain recall` 取细节
3. 结束 → `brain add` 写日志 + `brain sync`

Codex 没有 `SessionStart` / `Stop` 钩子，所以同步依赖模型按指令执行。
为提高可靠性，文件里把"必须执行"写成硬性步骤，而不是建议。

## 可选：外部定时同步

如果模型偶尔忘记 `sync`，可加一条系统计划任务，每小时执行：

```bash
brain sync -m "auto: hourly"
```

这样即使模型漏掉，变更也会在 1 小时内进入远端。
