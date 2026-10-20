# Claude Code 适配

**能力等级：全自动（读 + 写 + 同步都由钩子完成）**

## 安装

```bash
# 1) 技能：放到用户级技能目录
cp -r . ~/.claude/skills/second-brain

# 2) 全局指令：生成 CLAUDE.md（含当前记忆快照）
brain compile --target claude --out ~/.claude/CLAUDE.md

# 3) 钩子：把 hooks.json 的 hooks 段合并进 ~/.claude/settings.json
```

钩子说明：

| 事件 | 命令 | 作用 |
| --- | --- | --- |
| SessionStart | `brain hook start --tool claude` | 先 `git pull`（25s 超时，失败不阻塞），再把简报打印进上下文 |
| Stop | `brain hook stop --tool claude` | 有未提交变更就提交并推送，会话结束即同步 |

## 注意

- `SessionStart` 的输出会进入上下文，简报有字符预算（默认 6000），不会吃掉太多 token。
- 钩子失败不影响正常使用：拉取失败时只跳过，不阻塞会话。
- 项目级记忆：在项目根目录放一份 `CLAUDE.md`（`brain compile --target claude --project <项目名>`），
  全局 `~/.claude/CLAUDE.md` 管跨项目记忆，两者会被同时读取。
