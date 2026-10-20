---
name: second-brain
description: 用户的跨设备、跨 AI 的长期记忆层（ai-brain）。当需要了解用户的偏好与禁忌、历史决策、项目背景，或需要把新的稳定事实/偏好永久记住时使用。也用于回答"我以前怎么说的""这个人是谁"这类需要长期记忆的问题。
---

# 第二大脑（ai-brain）

## 这个技能做什么

把用户的长期记忆放在一个**独立的私有 git 仓库**里，用 Markdown 存条目。
任何 AI 客户端只要能读文件或执行命令，就能共享同一份记忆——

- 换电脑：`git pull` 就带回全部记忆
- 换 AI：同一份文件被不同工具读取，不是各家各存一份
- 换会话：记忆不在对话里，所以不会随上下文丢失

## 什么时候必须用

| 场景 | 动作 |
| --- | --- |
| 会话开始 | 运行 `brain brief`，把输出当已知背景 |
| 需要细节（用户提到"之前""上次""我的习惯"） | `brain recall "<关键词>" -k 8` |
| 用户表达稳定偏好 / 纠正你的做法 | `brain add --type preference ...` |
| 用户做出有理由的决策 | `brain add --type decision ...`（含被否掉的方案） |
| 拿到可复用流程 | `brain add --type skill ...` |
| 会话结束 | `brain add --type journal ...` + `brain sync` |

## 命令

```bash
brain init --repo <私有仓库地址> --device <设备名>   # 首次，或换电脑
brain brief [--project <项目名>]                    # 启动简报（有字符预算）
brain recall "<关键词>" [-k 8] [--json]             # 检索
brain add --type <类型> --title "..." --body "..." [--tags a,b] [--scope global]
brain sync [-m "说明"]                              # 提交 + 拉取 + 推送
brain status                                        # 条目统计与同步状态
brain doctor                                        # 环境自检
```

类型：`identity` / `preference` / `fact` / `decision` / `project` / `skill` / `journal`

## 硬规则

1. **不许编造记忆。** 简报里没有的，就 `recall` 或直接问用户，不能凭印象补。
2. **一条只讲一件事。** 正文短、可独立阅读，方便日后检索与合并。
3. **不写敏感信息。** 密钥、密码、证件号、他人隐私一律不入库。
4. **冲突以对话为准。** 新结论写新条目，旧条目保留时间戳供追溯，不要偷偷改历史。
5. **控制上下文预算。** 先 `brief`（有截断），细节再 `recall`，不要把全部记忆倒进上下文。

## 命令不可用时

直接读写 `<记忆仓库>/memory/**/*.md`：frontmatter 里的 `type/tags/scope/created` 就是元数据，
文件路径就是分类。读取全部文件的 frontmatter + 正文前几行，效果等同 `brief`。
