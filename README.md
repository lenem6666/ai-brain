# ai-brain · 一颗大脑，所有 AI

> 把长期记忆从"某个 App 里"搬到"你自己的一个私有 git 仓库里"。  
> 换电脑 `git pull` 就回来了，换 AI 客户端读的是同一批文件。

![status](https://img.shields.io/badge/version-0.1.0-blue)

![python](https://img.shields.io/badge/python-3.8%2B-blue)

![deps](https://img.shields.io/badge/dependencies-none-brightgreen)

![license](https://img.shields.io/badge/license-MIT-green)

---

## 为什么现有方案不够

| 方案             | 问题                            |
| -------------- | ----------------------------- |
| 各家 App 的"记忆"功能 | 存在各自服务器里，只有那一个 App 能读；换工具记忆归零 |
| 每次对话粘贴一段背景     | 手动、易过期、无法累积，长文还超上下文           |
| 把偏好塞进系统提示      | 只能放静态规则，装不下"历史决策 + 项目背景"      |
| 用云数据库自建        | 每个客户端都要配密钥、写适配器，离线不可用         |

**根因**：记忆被绑定在"应用"上，而不是绑定在"你"身上。

## 方案：记忆 = 文件 + git，技能 = 一层薄协议

```
你的 GitHub 私有仓库 brain-data
        │  git pull / push（跨电脑同步）
        ├── 电脑 A ── Claude Code ──┐
        ├── 电脑 A ── Codex CLI  ──┤  读同一批 Markdown
        ├── 电脑 B ── Cursor     ──┤  写回同一个仓库
        └── 手机   ── Claude App ──┘  （MCP 直连）
```

三个设计决定：

1. **记忆用 Markdown + frontmatter，一条一文件。** 任何 LLM 都能直接读，  
   不需要向量库、不需要嵌入模型、不需要联网。一条一文件让并发写入几乎不产生 git 冲突。
2. **同步用 git，不用云数据库。** 天然版本化（能回滚"三个月前我是怎么想的"）、  
   离线可用、有冲突可人工裁决、零运维零费用。
3. **接入层是"协议文件"而不是插件。** 每个 AI 只认一种入口文件  
   （`CLAUDE.md` / `AGENTS.md` / `.cursor/rules` / `GEMINI.md` / `SKILL.md`），  
   同一份内容编译成不同格式，行为完全一致。

## 5 分钟上手（Windows 实测）

### 1. 克隆到 D 盘

```powershell
git clone https://github.com/<你>/ai-brain.git D:\ai-brain
```

安装根目录 = 你克隆到的位置，所以放在 `D:\ai-brain` 就全在 D 盘。换机时重复这一条即可。

### 2. 一条命令装好

```powershell
powershell -ExecutionPolicy Bypass -File D:\ai-brain\scripts\install.ps1
```

它会做四件事：

- 下载便携 Python 到 `D:\ai-brain\runtime`（11MB，不写注册表、不动系统 PATH）
- 生成 `brain` 命令到 `D:\ai-brain\bin`，并加入用户 PATH
- 检测已装的客户端，把入口文件写进去（Claude Code / Codex / WorkBuddy）
- 失败就报清楚，不会留下半装状态

已有系统 Python 想省这 11MB：加 `-SkipRuntime`。

### 3. 建私有记忆库

```powershell
gh repo create brain-data --private
brain init --repo https://github.com/<你>/brain-data.git --device win-office
brain doctor      # 自检：git 身份、远端连通、条目数
```

### 4. 灌入第一批记忆

```powershell
brain add --type identity --title "我是谁" --body "AI 自媒体创作者，做口播知识科普。长期目标：把内容生产流程产品化。"
brain add --type preference --title "交付默认格式" --body "中文、先结论后论证、表格优先于长段落。不要客套开头。" --tags "写作,风格"
brain add --type decision --title "剪辑用剪映不用达芬奇" --body "机器 i5-9500F/16G/1060-6G，达芬奇要求更高会卡。稳定性优先于功能。" --tags "工具,剪辑"
```

`--body` 支持长文本；长内容用 `--file` 直接读一篇 Markdown 更省事。

### 5. 入口文件不用管

`brain add` / `brain sync` 只要发现记忆有变化，就自动重编译 6 个客户端入口，
新会话不会读到旧快照。想手动强制刷新也可以：

```powershell
python D:\ai-brain\scripts\refresh.py
```

### 从已有笔记迁移（可选）

已经有一套 Obsidian / 文件夹笔记，可以直接搬进来：

```powershell
python D:\ai-brain\scripts\migrate_obsidian.py --src "D:\你的Vault" --dst D:\ai-brain-data --dry-run
```

按 `##` 小节拆成一条一文件，旧的机制类条目会自动标注「历史，已取代」，不会污染简报。

## 换机怎么装

### 方式 A：只装 Skill（推荐）

新电脑装好 WorkBuddy 并登录账号，执行：

```powershell
$d = "$env:USERPROFILE\.workbuddy\skills"
git clone --depth 1 https://github.com/lenem6666/ai-brain.git $env:TEMP\aib
New-Item -ItemType Directory -Force -Path $d | Out-Null
Copy-Item -Recurse -Force "$env:TEMP\aib\skill\ai-brain-setup" $d
Remove-Item -Recurse -Force $env:TEMP\aib
```

或用一键脚本（自动下载 zip，直连失败时自动试本机代理 10809）：

```powershell
iwr https://raw.githubusercontent.com/lenem6666/ai-brain/main/scripts/install-skill.ps1 -OutFile $env:TEMP\is.ps1
powershell -ExecutionPolicy Bypass -File $env:TEMP\is.ps1
```

重启 WorkBuddy，新对话里说「恢复我的记忆」。Skill 会自己完成：装程序（直接复用 WorkBuddy 自带的
Python，不额外装运行时）→ 拉私有记忆库 → 部署 `CLAUDE.md` / `AGENTS.md` / `SKILL.md` 等入口 → 打印简报。
之后每次新会话先跑一次自检（幂等，已就绪就只检查）。

**唯一要人做的一步**：私有库第一次拉取需要一次 GitHub 授权。脚本会优先复用 `gh auth token`、
系统凭据管理器或 `BRAIN_TOKEN`，都没有就明确提示你去 `git clone` 登录一次。
这一步和 WorkBuddy 账号无关——记忆存在 GitHub 私有仓库里，WorkBuddy 账号本身不携带记忆内容。

### 方式 B：手动装（可精确控制）

前提只有两个：**装 Git**，**这台机器能访问 GitHub**（私有库要登录一次）。

```powershell
# 0) 没装 git 先装（已装跳过）
winget install --id Git.Git -e

# 1) 装程序（公开仓库，不需要权限）
git clone https://github.com/<你>/ai-brain.git D:\ai-brain
powershell -ExecutionPolicy Bypass -File D:\ai-brain\scripts\install.ps1

# 2) 接上同一颗大脑（私有仓库，会弹一次 GitHub 登录）
brain init --repo https://github.com/<你>/brain-data.git --device home-pc

# 3) 再跑一次安装脚本：部署入口文件 + 注册每天 10:00 自动同步
powershell -ExecutionPolicy Bypass -File D:\ai-brain\scripts\install.ps1
schtasks /create /tn "ai-brain-sync" /tr "\"D:\ai-brain\bin\sync-task.cmd\"" /sc daily /st 10:00 /f

# 4) 验收
brain doctor
brain brief
```

要点：

- `--device` 每台机器取不同名字（`win-office` / `home-pc`），提交里能看出是谁写的。
- 私有库第一次 clone 会弹浏览器授权；CI 场景可用 PAT。
- 国内直连 GitHub 不通时，先给 git 配代理再执行第 2 步：
  `git config --global http.https://github.com.proxy http://127.0.0.1:10809`
- 记忆库默认落在安装目录下的 `data\`；想和主机一样独立放，加 `--dir D:\ai-brain-data`。
- 不需要改任何硬编码路径：`bin/brain.cmd` 用自身位置推导根目录，整个文件夹搬到别的盘也能跑。

## 换机实测（2026-10-20，实测数据）

在一台干净目录 + 干净用户目录里完整模拟"第二台电脑"：克隆公开仓库 → 跑安装脚本（真实下载 11MB 运行时）→ 拉私有记忆库 → 部署入口 → 自检。

| 步骤 | 结果 |
| --- | --- |
| 克隆技能仓库 | 423 KB（含 `bin/`、`docs/`、`templates/`） |
| 安装（含下载便携 Python） | 一次通过，运行时落在 `<安装根>\runtime` |
| 拉取私有记忆库 | 97 条（88 活跃 + 9 归档），与主机逐字节一致 |
| `brain doctor` | Python 3.13.14 / 配置 / 记忆仓库 / git 身份 / 远端连通 全 `[OK]` |
| `brain brief` | 正确显示身份与硬规则，设备名为新机 `sim-pc` |
| 入口部署 | `CLAUDE.md` 写入新机用户目录，正文与主机同源 |
| 中文输出 | PowerShell 下中文正常，不再是乱码 |

这一轮模拟暴露并修掉两个只在"新机 + PowerShell"才出现的问题：
便携 Git 的 `GIT_EXEC_PATH` 缺 https 助手（clone 报 `remote-https is not a git command`），
以及 `brain` 强制 UTF-8 输出导致 PowerShell 里中文变乱码。两处都已修并回归。

结论：换机 = clone → install → init（→ 再跑一次 install 部署入口），不需要手工改任何路径。
全部临时产物已清理，用户 PATH 无残留。


## 接入矩阵

| 工具                               | 读记忆             | 写记忆         | 自动同步    | 接入方式                                    |
| -------------------------------- | --------------- | ----------- | ------- | --------------------------------------- |
| **Claude Code**                  | 自动              | 自动          | 自动      | 技能 + `CLAUDE.md` + SessionStart/Stop 钩子 |
| **Codex CLI**                    | 自动              | 模型按协议执行     | 模型按协议执行 | `~/.codex/AGENTS.md`                    |
| **Cursor**                       | 自动（alwaysApply） | Agent 可执行命令 | 模型按协议执行 | `~/.cursor/rules/brain.mdc`             |
| **Gemini CLI**                   | 自动              | 模型按协议执行     | 模型按协议执行 | `~/.gemini/GEMINI.md` 或 MCP             |
| **WorkBuddy**                    | 自动（技能按描述触发）     | 模型按协议执行     | 模型按协议执行 | `~/.workbuddy/skills/second-brain/`     |
| **Claude Desktop / 支持 MCP 的客户端** | 工具调用            | 工具调用        | 工具调用    | `scripts/mcp_server.py`                 |
| **ChatGPT 网页 / 豆包 / Kimi**       | 手动粘贴快照          | 手动          | 手动      | 自定义指令（`brain compile --target chatgpt`） |

> 能力差异的根源是各产品的钩子机制，不是本方案。**有钩子的工具全自动，没有的靠协议约束模型行为**，  
> 再叠加一条系统计划任务 `brain sync`（每天 10:00）兜底，实际体验差别很小。

### 各工具细节

- [Claude Code](adapters/claude/README.md) · [Codex](adapters/codex/README.md) · [Cursor](adapters/cursor/README.md)
- [Gemini CLI](adapters/gemini/README.md) · [WorkBuddy](adapters/workbuddy/README.md) · [网页版 AI](adapters/chatgpt/README.md)
- [MCP 服务器配置](docs/MCP.md)

## 记忆怎么组织

```
brain-data/
└── memory/
    ├── identity/     我是谁、长期目标、不可妥协的规则
    ├── preference/   偏好、禁忌、风格（scope=global 全局生效，或按项目）
    ├── decision/     做过什么决定、为什么、否掉了什么
    ├── project/      项目背景、约束、当前状态
    ├── skill/        可复用的方法与流程
    ├── fact/         稳定事实（人、账号、机器配置…）
    └── journal/      会话日志（按天，可定期蒸馏后归档）
```

一条记忆长这样：

```markdown
---
id: preference-20261020-b164d2
type: preference
scope: global
title: 交付默认格式
tags: [写作, 风格]
created: 2026-10-20T08:50:00+08:00
source: win-office
confidence: high
---

中文、先结论后论证、表格优先于长段落。
禁止"好问题"这类客套开头。

---
**结构约定**：一条只讲一件事；正文可独立阅读（不依赖上下文）；
写了就要能被检索到（标题和 tags 用你以后会想起的词）。
```

## 上下文预算

记忆会无限增长，上下文有限。所以读记忆分两级：

| 层级    | 命令                        | 体积                 | 何时用       |
| ----- | ------------------------- | ------------------ | --------- |
| L0 简报 | `brain brief`             | 默认 4000 字符，超预算自动截断 | 每次会话开始，必读 |
| L1 检索 | `brain recall "<词>" -k 8` | 按需，几条              | 需要细节时     |

简报只放"身份 + 硬规则 + 近期决策 + 索引"，细节靠检索。  
这样 500 条记忆和 50 条记忆的启动成本几乎一样。

## 命令速查

```bash
brain init --repo <url> --device <名字>   # 绑定/换机
brain brief [--project X] [--max-chars N] # 启动简报
brain recall "<关键词>" [-k 8] [--json]   # 检索
brain recall "<关键词>" --all             # 连已归档的旧条目一起搜
brain add --type T --title "..." --body "..." [--tags a,b] [--scope X]
brain sync [-m "说明"]                    # 提交 + 拉取 + 推送
brain sync --force                        # 放行批量删除（默认 ≥3 条或 ≥30% 会被拦）
brain status                              # 统计与同步状态
brain doctor                              # 环境自检
brain compile --target all                # 生成各工具入口文件
brain distill [--task] [--report] [--json] # 记忆体检：重复/过时/过长
brain distill --apply plan.json           # 执行合并、提炼、归档
brain hook start|stop --tool claude       # 钩子入口
brain trail [--full] [--dry-run] [--no-files] # 导出 WorkBuddy 会话历史与产物清单
```

零依赖，纯标准库，`python3 brain.py <命令>` 与 `brain <命令>` 等价。

## 任务历史怎么跨设备

WorkBuddy 登录同一账号**只同步**账号设置、Memory 和连接器配置；
任务列表、对话记录、产物文件都留在本机（官方原文：
"WorkBuddy does not currently transfer task outputs between devices"）。
2026-08 那次"多端同步"是 PC ↔ 手机/小程序的远程查看，前提是电脑开机在线，不是 PC↔PC。

要把历史带过去，用 `brain trail`：

```bash
brain trail            # 增量导出（默认）
brain trail --full     # 全量重建
brain trail --dry-run  # 只统计，不写文件
```

它做两件事：

| 步骤 | 产物 | 说明 |
|---|---|---|
| 导出会话 | `trail/<年-月>/<日期>-<标题>-<id>.md` | 76 个会话 110 MB 原始 jsonl → 约 11 MB Markdown |
| 同步文档 | `trail/files/<项目>/…` | docx/xlsx/pptx/pdf/md/csv，实测 93 份 7.7 MB |
| 产物清单 | `trail/artifacts.md` | 媒体文件（mp4/png 等）只登记不搬，实测 327 个 1116 MB |

索引在 `trail/index.md`，按月份列出全部会话，点开即读。

三点实现细节：

1. **只留对话正文**。jsonl 里 99.5% 是工具输出与 provider 元数据，解析时丢弃，所以 110 MB 能压到 11 MB。
2. **用户提问要单独抽取**。提问多数包在 `<system-reminder>` 里，真实问题在 `<user_query>` 中；
   早期实现按 `^<system-reminder` 整条丢弃，476 轮提问只剩 11 轮，已修正。
3. **排除中间产物**。隐藏目录（`.inv100` 之类）里是 `_audit.py`、`_chk.py` 等可再生脚本，
   文档体积的 99% 集中在那里，不排除会把仓库撑到 280 MB。

**边界**：第二台电脑的 WorkBuddy **界面里不会出现这些任务卡片**——任务列表由本地 sqlite 驱动，
无法从外部注入。同步过去的是文件与内容：能打开、能全文搜索、能让 AI 读。

## 验证

不靠"应该可行"，有两层可执行验收，全程临时目录：

```bash
python scripts/validate.py       # 8 项功能验收，约 19 秒
python scripts/verify_loop.py    # 19 项闭环验证（失败路径 + 真机核对）
```

功能验收：

| # | 检查 | 实测 |
|---|---|---|
| 1 | 读写闭环 | PASS |
| 2 | 换机 clone 后记忆可见 | PASS |
| 3 | 两端离线并发写入 → rebase 合并 | PASS |
| 4 | 改坏后回退到上一版 | PASS |
| 5 | 批量删除被拦截 | PASS（退出码 3） |
| 6 | 不装任何依赖也能读记忆 | PASS |
| 7 | 6 个客户端入口正文同源 | PASS |
| 8 | 记忆文件不含本机绝对路径 | PASS |

闭环验证（专测"失败路径会不会把数据搞坏"）：

| # | 失败场景 | 实测 |
|---|---|---|
| 1 | A 机写入，B 机 clone 后可见 | PASS |
| 2 | 断网写入 → 联网自动补推 | PASS，本地提交不丢 |
| 3 | 20 次同秒同标题写入 | PASS，20 个文件、0 覆盖 |
| 4 | 双机各自新增 → rebase 合并 | PASS，0 冲突 |
| 5 | 同一条目双机改写（真冲突） | PASS，保留双版本，仓库不卡死 |
| 6 | 删掉整个本地仓库 → 从远端恢复 | PASS，逐字节一致 |
| 7 | 误删单条 / 批量删 3 条 | PASS，git 可救 / 退出码 3 拦截 |
| 8 | 归档条目是否污染简报 | PASS，brief 不含，recall --all 可查 |
| 9 | 手工塞入非法 frontmatter | PASS，跳过，不影响其余条目 |
| 10 | 连续两次编译 | PASS，逐字节一致 |
| 11 | 6 个入口正文同源 | PASS |
| 12 | 已有手写 CLAUDE.md / AGENTS.md | PASS，追加区块、原文保留 |
| 13 | MCP initialize / tools / call | PASS |
| 14 | 钩子 start / stop | PASS |
| 15 | 真机与远端是否 0/0 | PASS |
| 16 | GitHub 全新 clone 灾难演练 | PASS，96 条逐字节一致 |
| 17 | 真机 doctor | PASS |
| 18 | 已部署入口是否滞后于记忆库 | PASS |
| 19 | 写入后入口是否自动刷新 | PASS，`add`/`sync` 自动重编译，无需手工 refresh |

完整对照报告（含"为什么视频说的'一步'不成立"、性能数据、修掉的缺陷）：
[docs/VIDEO-VALIDATION.md](docs/VIDEO-VALIDATION.md)。

闭环最后一跳是自动的：`brain add` / `brain sync` 只要发现记忆有变化，就重编译 6 个入口文件，
新会话不会读到旧快照（不想要可设 `BRAIN_AUTO_REFRESH=0`）。

## 冲突策略：不丢字，也不卡死

一条一文件意味着"冲突"= 同一事实存在两个版本。`brain sync` 遇到 rebase 冲突时：

1. 把本地版本另存为新条目，打 `冲突副本` 标签；
2. 原条目取远端版本；
3. 分支对齐远端后重新提交、推送。

结果：双方内容都在，仓库不会停在 rebase 中间态（早期版本会卡死，已修）。副本留到你下次
`brain distill` 时合并。真离线（推送失败）也不会丢：本地提交照常保留，`brain sync` 以
退出码 4 明确报错，联网后重跑即收敛。

## 设计取舍（诚实版）

| 选择       | 好处              | 代价                                 |
| -------- | --------------- | ---------------------------------- |
| git 作同步层 | 版本化、离线、零成本、可自托管 | 需要处理冲突；大二进制不适合（本方案只存文本）            |
| 一条一文件    | 并发冲突极少，diff 清晰  | 条目多了是很多小文件，靠索引弥补                   |
| 检索用词法打分  | 无需嵌入模型，离线、毫秒级   | 语义近义匹配弱于向量检索，长记忆量后可升级              |
| 入口文件静态编译 | 任何工具都能用，零适配成本   | 记忆更新后要重新 `compile`（或让模型直接 `brief`） |
| 不自动写敏感信息 | 降低泄露面           | 需要用户自己判断什么该记                       |

## 常见问题

**Q：记忆会泄露吗？**  
仓库必须设为 private；`brain` 不会主动上传任何内容，只在你执行 `sync` 时推送。  
详见 [docs/SECURITY.md](docs/SECURITY.md)。

**Q：多台电脑同时写会冲突吗？**  
一条一文件 + `pull --rebase`，实测两台设备各自新增条目可自动合并。  
真冲突时（同一文件被两端改）git 会停下让你裁决，不会静默丢数据。

**Q：能不能不用 GitHub？**  
能。远端可以是自建 Gitea、公司 GitLab，甚至不要远端——把 `~/.ai-brain/data`  
放进 OneDrive / iCloud / Syncthing 同步目录即可（注意这时候没有版本历史兜底）。

**Q：和各家 "Memory" 功能冲突吗？**  
不冲突。App 自带记忆负责短期会话连续性，ai-brain 负责长期、可迁移、可审计的那部分。  
真有冲突以 ai-brain 为准——它是你写的，不是模型推断的。

**Q：AI 误删了我的记忆怎么办？**  
两道防线。第一，`brain sync` 提交前会拦截批量删除（≥3 条或 ≥30%），要求加 `--force` 确认；
第二，已提交的内容都在 git 历史里：

```bash
git -C ~/.ai-brain/data checkout HEAD~1 -- memory/    # 回到上一版
git -C ~/.ai-brain/data log --oneline                 # 看全部历史
```

注意 git 只保护"已提交"的内容——所以别把 `--no-commit` 当默认用法。

**Q：记忆越来越多会变慢吗？**  
`brief` / `recall` 是纯文件扫描，1 万条以内都是毫秒级。超过之后再考虑加 SQLite 索引层。

## 路线图

- [x] v0.1 文件记忆 + git 同步 + 6 种工具接入 + MCP + 8 项可执行验收
- [x] v0.2 `brain distill`：体检（同标题 / 近似重复 / 老日志 / 已废止 / 过短）+ 计划执行（合并、改写、归档）
- [ ] v0.3 可选向量检索（本地 sqlite + 轻量嵌入），保持无网络依赖
- [ ] v0.4 记忆健康度报告：过期条目、互相矛盾的偏好、从未被检索的死记忆
- [ ] v0.5 加密同步（git-crypt 集成 + 单条目加密选项）

## 目录结构

```
ai-brain/
├── SKILL.md                 技能入口（WorkBuddy / Claude 技能格式）
├── brain.py                 全部逻辑，单文件，零依赖
├── adapters/                各客户端安装说明 + 钩子配置
├── scripts/
│   ├── install.ps1           Windows 安装
│   ├── install.sh            macOS / Linux 安装
│   ├── refresh.py            记忆变更后刷新各客户端入口
│   ├── migrate_obsidian.py   从 Obsidian / 文件夹笔记迁移
│   ├── validate.py           8 项可执行验收
│   ├── mcp_server.py         MCP stdio 服务器
│   └── install-shim.md       brain 命令安装说明
├── docs/
│   ├── ARCHITECTURE.md      分层、数据模型、生命周期
│   ├── CAPABILITY-MATRIX.md 各工具能力与降级策略
│   ├── DISTILL.md           记忆蒸馏：五类候选、计划格式、安全边界
│   ├── VIDEO-VALIDATION.md  对"GitHub 第二大脑"说法的实测对照
│   ├── SECURITY.md          隐私边界与加密
│   └── MCP.md               MCP 客户端配置示例
└── templates/               记忆条目模板
```

## License

MIT。你的记忆数据永远属于你自己，不在本仓库内。
