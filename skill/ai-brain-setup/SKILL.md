---
name: ai-brain-setup
description: 跨设备长期记忆的自举与接入。当用户在新电脑上、换机后、或说"我的记忆/之前的习惯/我们以前说过/把这个记下来/同步一下记忆/装一下大脑"时使用；也可用于修复记忆环境（找不到 brain 命令、记忆没同步、入口文件缺失、换机后记忆为空）。
---

# 第二大脑：自举 + 协议

用户有一套跨设备长期记忆（Markdown + git 私有仓库），本 Skill 负责**在一台新电脑上把它恢复出来**，
并在之后按协议读写。程序本身也在 GitHub 上，不依赖手工安装。

## 一、每次会话开始，先跑自检（必须）

Windows:

```
"%USERPROFILE%\.workbuddy\skills\ai-brain-setup\run.cmd" --status
```

> WorkBuddy 的数据目录如果不在用户目录下（例如装在 `D:\WorkBuddy`），
> 路径是 `<WorkBuddy数据目录>\.workbuddy\skills\ai-brain-setup\run.cmd`。
> 两个位置都试一次，哪个存在用哪个；`%USERPROFILE%\.workbuddy\skills` 通常是指向该目录的链接。

其它系统:

```
python3 ~/.workbuddy/skills/ai-brain-setup/scripts/ensure.py --status
```

- 退出码 `0` → 环境就绪，继续执行下面的「读记忆」。
- 退出码 `2` → 缺信息（通常是记忆库地址），按输出里的 `[NEED_REPO]` 指引问用户，**不要自己猜地址**。
- 退出码 `3` → 需要 GitHub 授权，见第三节。这是换机唯一不能自动完成的一步，如实告诉用户。
- 退出码 `4` → 其它失败，把输出原文贴给用户，不要自行编造"已恢复"。

自检是幂等的：已装好就只做检查，不会重复下载、不会改动现有配置。

## 二、读记忆（会话开始必做）

```
"%USERPROFILE%\.workbuddy\skills\ai-brain-setup\run.cmd" --no-brief --status   # 环境确认
```

然后取简报（把输出当作已知背景，不要重复问用户已经写在里面的信息）：

```
"%USERPROFILE%\.workbuddy\skills\ai-brain-setup\run.cmd"
```

带项目上下文时更准：

```
"%USERPROFILE%\.workbuddy\skills\ai-brain-setup\run.cmd" --project <目录名>
```

需要查细节时用 `brain recall "关键词"`；`brain` 不在 PATH 时用完整路径
`<程序根>\bin\brain.cmd recall "关键词"`，`<程序根>` 由自检输出里的 `程序根` 一行给出。

## 三、换机：唯一需要人手的一步

程序安装、运行时、入口文件、记忆库拉取都自动完成，**只有 GitHub 授权绕不过去**——
因为记忆存在用户的 GitHub 私有仓库里，WorkBuddy 账号和 GitHub 账号是两套体系。

按顺序尝试，成功一个即可：

1. 装了 GitHub CLI 且已登录 → 本脚本自动复用 `gh auth token`，全程无交互。
2. 有 PAT → 设 `BRAIN_TOKEN` 环境变量后重跑，或直接 `git config --global credential.helper manager` 后手工 clone 一次。
3. 都没有 → 让用户执行 `git clone <记忆库地址>`，弹窗登录一次，凭据进系统凭据管理器，之后一直有效。

**不要说"登录同一个 WorkBuddy 账号就能同步记忆"**——做不到，别给用户错误预期。

## 四、写记忆（稳定事实才写）

```
brain add --type preference --title "标题" --body "正文" --tags "标签"
```

- `--type`：`identity` / `preference` / `project` / `decision` / `fact` / `method` / `journal`
- 一条一个文件，写完自动 commit + 尽力 push，并自动刷新各客户端入口文件。
- 只写**长期有效**的东西：偏好、硬规则、决策与理由、项目背景、可复用方法。
- 临时进展、一次性的调试信息 → 用 `journal`，别塞进 `preference`。
- 写入前先 `brain recall "关键词"` 查重，已有同类条目就补充或标 `已废止`，不要堆同义条目。
- 绝不批量删除记忆；`brain sync` 有误删拦截（≥3 条或 ≥30% 会拒绝，退出码 3）。

## 五、边界（要如实告诉用户）

| 情况 | 实际行为 |
|---|---|
| 新电脑完全没网 | 若本机已有记忆副本可读；没有则只能等联网 |
| GitHub 未授权 | 自检返回退出码 3，记忆拉不下来（不是 Skill 的缺陷） |
| 用户不用 GitHub | 可把 `defaults.json` 的 `repo` 换成任意私有 git 地址（自建 Gitea 等） |
| 两台机器同时改同一条 | 自动保留一份「冲突副本」，等 `brain distill` 合并，不丢字 |
| 程序更新 | `git -C <程序根> pull`，或删掉程序目录重跑自检（记忆库不受影响） |

## 六、多个 AI 客户端怎么分工（用户问到时按这个答）

三层责任要分清，不要笼统说"每个 AI 都得装一遍"：

| 层 | 数量 | 说明 |
|---|---|---|
| **记忆数据** | 全机唯一一份 | `<数据目录>/memory/`，所有 AI 共用同一个 git 仓库 |
| **入口/协议文件** | 每个 AI 一份，自动生成 | 告诉该 AI"开场读 memory、结束写 memory"，是纯文本，不是 Skill |
| **本自举 Skill** | 只装在 WorkBuddy | 它是安装器，跑一次把上面两层装好；其他 AI 没有 WorkBuddy 的技能机制，装不了也不需要有 |

因此：

- **本机**：本 Skill 只装 WorkBuddy 一份。它执行 `refresh` 时会自动为**已安装**的客户端生成对应入口：
  Claude Code → `~/.claude/CLAUDE.md`（区块合并，保留手写内容）；
  WorkBuddy / Claude Code 技能 → `~/.workbuddy/skills/second-brain/`、`~/.claude/skills/second-brain/`；
  Codex → `~/.codex/AGENTS.md`（区块追加，保留原有规则）；
  Cursor → `~/.cursor/rules/brain.mdc`；Gemini CLI → `~/.gemini/GEMINI.md`。
  某客户端目录不存在则跳过，不造空目录。
- **新电脑**：同样只装 WorkBuddy 一份即可。**前提是这台机器上要用到哪个 AI，就先让那个 AI 的配置目录存在**
  （装过并至少启动过一次），否则 refresh 会判定"未安装"而跳过；之后补装了别的 AI，重跑一次
  `<程序根>\bin\brain.cmd sync`（或 `scripts/refresh.py`）即可补上入口，不必重装本 Skill。
- **只有 Codex、没有 WorkBuddy 的机器**：`install-skill.ps1` 用不上（它往 WorkBuddy 技能目录装）。
  改为直接跑自举脚本 `python <程序根>/scripts/ensure.py`（需系统有 Python 3.8+），
  它照样完成安装、拉库、部署 Codex 入口。

## 七、安全

- 记忆库是**私有**仓库，里面是用户的完整画像；不要贴到公开渠道、不要写进公开 issue。
- 不要把 token 写进任何文件；脚本只在 clone 那一刻临时使用，随后把 remote 还原成无 token 的地址。
- 隐私敏感条目（证件号、密钥）不要进记忆库；记忆库只放"AI 该知道的偏好与背景"。
