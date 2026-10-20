# Gemini CLI 适配

**能力等级：自动读 + 指令驱动写**

## 安装

```bash
brain compile --target gemini --out ~/.gemini/GEMINI.md
```

## 说明

Gemini CLI 启动时读取 `GEMINI.md`（当前目录或家目录）。
它支持 MCP，因此也可以走 `scripts/mcp_server.py` 的原生工具调用路线——
比"读 Markdown 再执行命令"更稳，适合记忆量大之后切换。

## 与其他工具共存

同一份 `GEMINI.md` 由 `brain compile` 生成，内容与其他工具一致，
唯一差别是文件路径和 frontmatter。改记忆只用 `brain add`，不要手改入口文件，
否则下次 `compile` 会覆盖。
