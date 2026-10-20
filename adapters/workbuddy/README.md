# WorkBuddy 适配

**能力等级：自动加载技能 + 指令驱动写**

## 安装

```bash
# 用户级技能（所有项目可用）
cp -r . ~/.workbuddy/skills/second-brain
```

Windows 上通常是 `D:\WorkBuddy\.workbuddy\skills\second-brain`，
macOS / Linux 上是 `~/.workbuddy/skills/second-brain`。

## 说明

WorkBuddy 启动时扫描技能目录，读到 `SKILL.md` 的 frontmatter（`name` / `description`），
在匹配到"用户偏好 / 历史决策 / 项目背景 / 永久记忆"这类意图时会自动加载本技能。

因此 `SKILL.md` 里的 `description` 是触发关键词所在，改它要谨慎。

## 可选：会话级自动同步

如果当前客户端支持钩子或在启动脚本里执行命令，加一行：

```bash
brain hook start --tool workbuddy
```

没有钩子也没关系：技能里的协议会要求模型在会话开始执行 `brief`、结束执行 `sync`。
