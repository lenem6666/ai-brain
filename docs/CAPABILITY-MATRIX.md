# 各工具能力矩阵

记忆能否共享，取决于三个动作能否发生：**读得到、写得了、同步得掉**。
不同客户端的钩子机制不同，因此能力分三档。

## 三档能力

| 档位 | 含义 | 机制 |
| --- | --- | --- |
| A 全自动 | 读、写、同步都由程序完成 | 技能/规则自动加载 + 生命周期钩子 |
| B 协议驱动 | 自动读，写和同步靠入口文件的硬性步骤约束模型 | 静态入口文件（`AGENTS.md` 等） |
| C 快照注入 | 手动粘贴一段记忆快照 | 自定义指令 / 项目说明 |

## 明细

| 客户端 | 档位 | 入口文件 | 读 | 写 | 同步 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | **A** | `~/.claude/CLAUDE.md` + `skills/second-brain/` | 自动（SessionStart 钩子注入） | 自动 | 自动（Stop 钩子） | 钩子是唯一能做到"关窗即同步"的机制 |
| WorkBuddy | **B+** | `~/.workbuddy/skills/second-brain/SKILL.md` | 自动（按 description 触发） | 模型执行 `brain add` | 模型执行 `brain sync` | 技能可被自动召回，写靠协议 |
| Codex CLI | **B** | `~/.codex/AGENTS.md`（全局）/ `./AGENTS.md`（项目） | 自动 | 模型执行 | 模型执行 | 无钩子；建议加每小时定时 `sync` |
| Cursor | **B** | `~/.cursor/rules/brain.mdc`（`alwaysApply: true`） | 自动 | Agent 模式可执行终端命令 | 模型执行 | Composer 模式只能读 |
| Gemini CLI | **B** | `~/.gemini/GEMINI.md` | 自动 | 模型执行 | 模型执行 | 也可走 MCP（升到 A-） |
| Claude Desktop | **A-** | MCP 配置 | 工具调用 | 工具调用 | 工具调用 | 需用户先说"回忆一下"才会调 |
| ChatGPT 网页 | **C** | 自定义指令（1500 字符） | 手动粘贴 | 手动 | 手动 | 建议只放"身份 + 硬规则" |
| Claude.ai 网页 | **C** | Profile 偏好设置 | 手动粘贴 | 手动 | 手动 | 容量比 ChatGPT 宽松 |
| 豆包 / Kimi / 通义 | **C** | 角色设定 / 系统提示 | 手动粘贴 | 手动 | 手动 | 同上 |
| VS Code + Copilot | **B-** | `.github/copilot-instructions.md` | 自动 | 手动 | 手动 | 可把 `CLAUDE.md` 内容复制过去 |

## 降级策略

不同档位不是"能不能用"，而是"自动化程度"：

1. **A / B 档**：什么都不用做，正常对话即可。
2. **C 档**：每次要它"记得"时，粘贴一次快照：
   ```bash
   brain brief --max-chars 1500
   ```
   对话里需要细节时，粘贴 `brain recall "关键词"` 的输出。
3. **任何档位都能用的一条兜底**：每小时系统计划任务执行 `brain sync`，
   保证即使模型漏写、你忘记同步，变更也会进入远端。

## 实测记录（v0.1）

`scripts/validate.py` 覆盖前 6 行，8/8 通过（约 19 秒）。完整报告见
[VIDEO-VALIDATION.md](VIDEO-VALIDATION.md)。

| 场景 | 结果 |
| --- | --- |
| 设备 1 写入 → 设备 2 全新 clone → `brief` | 条目完整可见 |
| 两台设备各自离线新增 → 先后 `sync` | `pull --rebase` 自动合并，无冲突 |
| 改坏一条 → 提交 → `checkout HEAD~1` | 正文逐字恢复 |
| 删除 3/4 条后 `sync` | 拦截，退出码 3；`--force` 放行 |
| 不调用 `brain.py`，纯标准库解析 `memory/` | 条目数与 `brain status` 一致 |
| 6 个客户端入口文件 | 正文 sha 一致（同源编译） |
| 首次推送（远端无分支） | 自动改用 `push -u origin main` |
| `init` 后立即推送骨架 | 第二台设备 clone 即有共同根提交，不再产生无关历史 |
| 未配置全局 git 身份 | 自动设置仓库级兜底身份，`commit` 成功 |
| Windows `core.autocrlf=true` | 记忆仓库固定 `eol=lf`，跨系统字节一致 |
| MCP `initialize` / `tools/list` / `tools/call` | 均返回合法 JSON-RPC 结果 |
| 简报超字符预算 | 尾部截断并提示用 `recall` 取细节 |
