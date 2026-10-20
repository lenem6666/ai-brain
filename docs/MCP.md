# MCP 接入

支持 MCP 的客户端可以**直接调用** `brief` / `recall` / `add` / `sync`，
不用"先读 Markdown 再执行终端命令"，这是比静态入口文件更稳的一档。

服务端：`scripts/mcp_server.py`，stdio 传输，仅标准库，无需安装依赖。

## Claude Desktop

`claude_desktop_config.json`（Windows: `%APPDATA%\Claude\`，macOS: `~/Library/Application Support/Claude/`）：

```json
{
  "mcpServers": {
    "ai-brain": {
      "command": "python",
      "args": ["D:/path/to/ai-brain/scripts/mcp_server.py"]
    }
  }
}
```

## Cursor

`~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "ai-brain": {
      "command": "python",
      "args": ["D:/path/to/ai-brain/scripts/mcp_server.py"]
    }
  }
}
```

## Gemini CLI

```bash
gemini mcp add ai-brain python D:/path/to/ai-brain/scripts/mcp_server.py --scope user
```

## 通过 MCP 暴露的工具

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `brain_brief` | `project?`, `max_chars?` | 读长期记忆简报，会话开头调用一次 |
| `brain_recall` | `query`, `k?` | 按关键词检索，返回命中条目正文 |
| `brain_add` | `type`, `title`, `body`, `tags?`, `scope?` | 写入一条永久记忆 |
| `brain_sync` | `message?` | 提交 + 拉取 + 推送 |

## 排查

```bash
# 手工验证协议（应返回三段合法 JSON-RPC）
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"brain_brief","arguments":{}}}' \
  | python scripts/mcp_server.py
```

- 返回 `未初始化` → 先执行 `brain init --repo ...`
- 客户端看不到工具 → 检查 `command` 是否在 PATH，必要时写 Python 绝对路径
- 中文乱码 → 确保用 Python 3.8+，脚本已强制 UTF-8 输出
