# 网页版 AI 适配（ChatGPT / Claude.ai / 豆包 / Kimi 等）

**能力等级：半自动（需手动粘贴一次）**

网页版 AI 不能读本地文件、不能执行命令，所以走"快照注入"路线。

## 安装

```bash
# 生成可直接粘贴的自定义指令（含当前记忆快照）
brain compile --target chatgpt --out custom-instructions.md
```

然后把 `custom-instructions.md` 的正文粘贴到：

| 产品 | 位置 | 长度限制（约） |
| --- | --- | --- |
| ChatGPT | 设置 → 个性化 → 自定义指令 | 1500 字符 / 框 |
| ChatGPT Project | 项目 → 项目说明 | 较宽松 |
| Claude.ai | Settings → Profile → Personal preferences | 数千字符 |
| 豆包 / Kimi | 角色设定 / 系统提示 | 较宽松 |

## 用完就扔的"快照文件"

记忆每天都在长，指令框容量有限。推荐两种用法：

1. **小记忆量**：直接粘贴，月底更新一次。
2. **大记忆量**：只粘"身份 + 硬规则 + 索引"（`brain brief --max-chars 1500`），
   对话需要细节时，把 `brain recall "关键词"` 的输出手动贴进去。

## 更彻底的做法

网页版 AI 也支持 MCP（如 Claude Desktop）时，改用 `scripts/mcp_server.py`，
让它直接调用 `brief` / `recall` / `add`，就不需要粘贴快照了。
