#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py — 把 ai-brain 暴露成 MCP 工具（stdio，仅标准库）。

任何支持 MCP 的客户端（Claude Desktop / Cursor / Gemini CLI / 豆包等）
都可以直接调用 brief / recall / add / sync，而不必"读 Markdown 再执行命令"。

配置示例（Claude Desktop claude_desktop_config.json）:
{
  "mcpServers": {
    "ai-brain": {
      "command": "python",
      "args": ["D:/path/to/ai-brain/scripts/mcp_server.py"]
    }
  }
}

协议: JSON-RPC 2.0, 每行一条消息（MCP stdio 传输）。
"""

import json
import subprocess
import sys
from pathlib import Path

SERVER_NAME = "ai-brain"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
BRAIN = Path(__file__).resolve().parent.parent / "brain.py"

TOOLS = [
    {
        "name": "brain_brief",
        "description": "读取用户的长期记忆简报：身份、硬规则、偏好、近期决策与条目索引。会话开始时调用一次。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "当前项目名，用于筛选项目级记忆"},
                "max_chars": {"type": "integer", "description": "输出字符预算，默认 4000"},
            },
        },
    },
    {
        "name": "brain_recall",
        "description": "按关键词检索长期记忆，返回最相关的条目正文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，中英文均可"},
                "k": {"type": "integer", "description": "返回条数，默认 6"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "brain_add",
        "description": "写入一条永久记忆。type 取 identity/preference/fact/decision/project/skill/journal。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "string", "description": "逗号分隔"},
                "scope": {"type": "string", "description": "global 或项目名"},
            },
            "required": ["type", "title", "body"],
        },
    },
    {
        "name": "brain_sync",
        "description": "提交并同步记忆到远端（git commit + pull --rebase + push）。",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    },
]


def run_brain(args, timeout=120):
    p = subprocess.run(
        [sys.executable, str(BRAIN)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, text=True, encoding="utf-8", errors="replace",
    )
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    return out if p.returncode == 0 else f"{out}\n{err}".strip()


def call_tool(name, a):
    if name == "brain_brief":
        args = ["brief", "--max-chars", str(int(a.get("max_chars", 4000)))]
        if a.get("project"):
            args += ["--project", a["project"]]
        return run_brain(args)
    if name == "brain_recall":
        return run_brain(["recall", a["query"], "-k", str(int(a.get("k", 6)))])
    if name == "brain_add":
        args = ["add", "--type", a["type"], "--title", a["title"], "--body", a["body"],
                "--tool", "mcp"]
        if a.get("tags"):
            args += ["--tags", a["tags"]]
        if a.get("scope"):
            args += ["--scope", a["scope"]]
        return run_brain(args)
    if name == "brain_sync":
        return run_brain(["sync", "-m", a.get("message") or "mcp sync"])
    return f"未知工具: {name}"


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error:
        msg["error"] = {"code": -32603, "message": str(error)}
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        mid = req.get("id")

        if method == "initialize":
            reply(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            reply(mid, {"tools": TOOLS})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                text = call_tool(params.get("name"), params.get("arguments") or {})
                reply(mid, {"content": [{"type": "text", "text": text or "(空)"}], "isError": False})
            except Exception as e:
                reply(mid, error=e)
        elif method == "ping":
            reply(mid, {})
        elif mid is not None:
            reply(mid, error=f"未实现的方法: {method}")


if __name__ == "__main__":
    main()
