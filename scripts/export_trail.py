#!/usr/bin/env python3
"""把 WorkBuddy 的本地会话历史导出成可同步的 Markdown。

背景：WorkBuddy 登录同一账号只同步「设置 + Memory + 连接器配置」，
任务与对话记录留在本机（官方明确不同步）。本脚本把 jsonl 里的对话正文
抽出来，落成 Markdown，交给 git 私有仓库带到第二台电脑。

用法：
    python scripts/export_trail.py                 # 增量导出
    python scripts/export_trail.py --full          # 全量重建
    python scripts/export_trail.py --dry-run       # 只报告，不写文件
    python scripts/export_trail.py --projects DIR  # 指定 .workbuddy/projects
    python scripts/export_trail.py --out DIR       # 指定输出根（默认 <data>/trail）

设计要点：
- jsonl 中 99% 是工具输出与 provider 元数据，只保留 user/assistant 的可见文本。
- 用户提问常被 <system-reminder> 包裹，真实问题在 <user_query> 里；
  早期实现按 `^<system-reminder` 整条丢弃，导致 476 轮提问只剩 11 轮（已修正）。
- 上下文压缩摘要 <cb_summary> 单独保留，它是会话的骨架。
- 增量靠「源文件 mtime+size」，存 .manifest.json；跨机器不共享，仅作本机优化。
"""
import argparse
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

TAG_QUERY = re.compile(r"<user_query>(.*?)</user_query>", re.S)
TAG_SUMMARY = re.compile(r"<cb_summary>(.*?)</cb_summary>", re.S)
XML_BLOCK = re.compile(r"<([a-zA-Z][\w:-]*)\b[^>]*>.*?</\1>", re.S)
FENCE = re.compile(r"^\s*```", re.M)

MSG_TYPES = ("input_text", "output_text", "text")


# ---------------------------------------------------------------- 工具函数

def home():
    return Path(os.environ.get("USERPROFILE") or Path.home())


def find_projects(explicit=None):
    """定位 .workbuddy/projects 目录，按 显式参数 → 默认安装 → 用户目录 探测。"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("WB_DATA"):
        cands.append(Path(os.environ["WB_DATA"]) / "projects")
    cands += [
        Path(r"D:/WorkBuddy/.workbuddy/projects"),
        home() / ".workbuddy" / "projects",
        Path.home() / ".workbuddy" / "projects",
    ]
    for c in cands:
        if c and c.exists() and c.is_dir():
            return c
    return None


def find_db(projects):
    """workbuddy.db 通常与 projects 同级。"""
    for p in (projects.parent / "workbuddy.db",):
        if p.exists():
            return p
    return None


def load_titles(db):
    """从 sqlite 读会话标题。只读打开，加 immutable 避免与运行中的客户端抢锁。"""
    if not db:
        return {}
    out = {}
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}{suffix}", uri=True, timeout=3)
            try:
                rows = con.execute(
                    "SELECT id, COALESCE(NULLIF(custom_title,''), title), cwd, created_at, updated_at, "
                    "COALESCE(NULLIF(custom_title,''), title, '') FROM sessions"
                ).fetchall()
                for r in rows:
                    out[r[0]] = {"title": (r[1] or "").strip(), "cwd": r[2] or "",
                                 "created": r[3], "updated": r[4]}
                return out
            finally:
                con.close()
        except sqlite3.Error:
            continue
    return out


def ms_to_dt(ms):
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, CST)
    except (OSError, ValueError, OverflowError):
        return None


def iso_to_dt(s):
    """jsonl 里的 timestamp 实际是毫秒整数，历史版本可能是 ISO 字符串，两种都吃。"""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return ms_to_dt(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(CST)
    except (ValueError, OSError):
        return None


def slug(text, limit=32):
    """标题转文件名片段：保留中英文数字，其余折叠成短横线。"""
    s = re.sub(r"[\s/\\:*?\"<>|]+", "-", (text or "").strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s[:limit].rstrip("-") or "未命名")


def fenced(text):
    """正文里若含 ``` 会破坏 Markdown 结构，改用更长的围栏包裹。"""
    if not FENCE.search(text):
        return None
    return "````"


def clean_user(raw):
    """返回 (提问正文, 压缩摘要或 None)。"""
    summary = None
    m = TAG_SUMMARY.search(raw)
    if m:
        summary = m.group(1).strip()
    q = TAG_QUERY.search(raw)
    if q:
        return q.group(1).strip(), summary
    stripped = XML_BLOCK.sub("", raw).strip()
    return stripped, summary


def blocks_text(content):
    if not isinstance(content, list):
        return ""
    parts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") in MSG_TYPES:
            t = b.get("text")
            if t:
                parts.append(t)
    return "\n".join(parts)


# ---------------------------------------------------------------- 解析单个会话

def parse_session(path):
    """返回 dict：id / title / cwd / created / updated / turns / body(list of (role, text))"""
    sid = path.stem
    created = updated = None
    turns = []
    summaries = []
    cwd = ""
    try:
        fh = io.open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            if '"role"' not in line and '"session-meta"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ts = iso_to_dt(o.get("timestamp"))
            if ts:
                created = created or ts
                updated = ts
            if not cwd and o.get("cwd"):
                cwd = o["cwd"]
            role = o.get("role")
            if role not in ("user", "assistant"):
                continue
            txt = blocks_text(o.get("content"))
            if not txt.strip():
                continue
            if role == "user":
                body, summ = clean_user(txt)
                if summ:
                    summaries.append(summ)
                if body and len(body) >= 2:
                    turns.append(("user", body))
            else:
                turns.append(("assistant", txt.strip()))
    if not turns:
        return None
    return {"id": sid, "cwd": cwd, "created": created, "updated": updated,
            "turns": turns, "summaries": summaries}


def render_md(info, meta):
    title = meta.get("title") or ""
    first_q = next((t for r, t in info["turns"] if r == "user"), "")
    if not title:
        title = first_q[:40].replace("\n", " ").strip() or "未命名会话"
    created = info["created"] or ms_to_dt(meta.get("created"))
    updated = info["updated"] or ms_to_dt(meta.get("updated"))
    project = Path(info["cwd"]).name if info.get("cwd") else ""
    u = sum(1 for r, _ in info["turns"] if r == "user")
    a = len(info["turns"]) - u

    L = []
    L.append("---")
    L.append(f"id: {info['id']}")
    L.append(f"title: {title}")
    L.append(f"project: {project}")
    L.append(f"workspace: {info.get('cwd') or ''}")
    L.append(f"created: {created.isoformat() if created else ''}")
    L.append(f"updated: {updated.isoformat() if updated else ''}")
    L.append(f"turns: u={u} a={a}")
    L.append("source: workbuddy-jsonl")
    L.append("---")
    L.append("")
    L.append(f"# {title}")
    L.append("")
    stamp = f"{created:%Y-%m-%d %H:%M}" if created else "时间未知"
    end = f"{updated:%Y-%m-%d %H:%M}" if updated else "?"
    L.append(f"> 项目 `{project or '未关联'}`　·　{stamp} → {end}　·　{u} 轮提问")
    if info.get("cwd"):
        L.append(f"> 原始路径 `{info['cwd']}`（本机路径，另一台机器上可能不存在）")
    L.append("")

    if info["summaries"]:
        L.append("## 上下文摘要（原客户端压缩生成）")
        L.append("")
        for s in info["summaries"]:
            L.append(s)
            L.append("")

    L.append("## 对话")
    L.append("")
    for role, text in info["turns"]:
        who = "用户" if role == "user" else "AI"
        L.append(f"### {who}")
        L.append("")
        fence = fenced(text)
        if fence:
            L.append(fence + "text")
            L.append(text)
            L.append(fence)
        else:
            L.append(text)
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="导出 WorkBuddy 会话历史为 Markdown")
    ap.add_argument("--projects", help=".workbuddy/projects 目录")
    ap.add_argument("--out", help="输出根目录（默认 <data>/trail）")
    ap.add_argument("--full", action="store_true", help="忽略缓存，全量重建")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    a = ap.parse_args()

    projects = find_projects(a.projects)
    if not projects:
        print("[trail] 未找到 .workbuddy/projects，跳过导出")
        return 0

    if a.out:
        out = Path(a.out)
    else:
        cfg = Path(os.environ.get("BRAIN_DATA") or r"D:/ai-brain-data")
        if not cfg.exists():
            cfg = home() / "ai-brain-data"
        out = cfg / "trail"

    titles = load_titles(find_db(projects))
    man_path = out / ".manifest.json"
    old = {}
    if man_path.exists() and not a.full:
        try:
            old = json.loads(man_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}

    files = sorted(projects.rglob("*.jsonl"))
    new_man = {}
    written = skipped = failed = 0
    total_chars = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        key = f.stem
        sig = f"{int(st.st_mtime)}:{st.st_size}"
        prev = old.get(key)
        if prev and prev.get("sig") == sig and not a.full:
            new_man[key] = prev
            skipped += 1
            continue
        info = parse_session(f)
        if not info:
            failed += 1
            continue
        meta = titles.get(info["id"], {})
        md = render_md(info, meta)
        created = info["created"] or ms_to_dt(meta.get("created")) or datetime.now(CST)
        name = f"{created:%Y-%m-%d}-{slug(meta.get('title') or info['turns'][0][1])}-{info['id'][:8]}.md"
        rel = f"{created:%Y-%m}/" + name
        dest = out / rel
        total_chars += len(md)
        if not a.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(md, encoding="utf-8", newline="\n")
        new_man[key] = {"sig": sig, "md": rel, "title": meta.get("title", ""),
                        "turns": len(info["turns"]), "chars": len(md)}
        written += 1

    # 清掉失效的 md：manifest 记录过但源已不存在，或文件名规则变化留下的孤儿
    removed = 0
    keep = {rec.get("md") for rec in new_man.values() if rec.get("md")}
    for key, rec in old.items():
        if key not in new_man and rec.get("md"):
            victim = out / rec["md"]
            if victim.exists() and not a.dry_run:
                victim.unlink()
                removed += 1
    for month_dir in out.glob("20*"):
        if not month_dir.is_dir():
            continue
        for md in month_dir.glob("*.md"):
            rel = f"{month_dir.name}/{md.name}"
            if rel not in keep:
                if not a.dry_run:
                    md.unlink()
                removed += 1

    if not a.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(new_man, ensure_ascii=False, indent=1, sort_keys=True),
                            encoding="utf-8", newline="\n")
        write_index(out, new_man)

    verb = "统计" if a.dry_run else "导出"
    print(f"[trail] {verb}：新增/更新 {written} 个，未变 {skipped} 个，"
          f"无内容 {failed} 个，清理失效 {removed} 个")
    print(f"[trail] 本次写入正文 {total_chars} 字符（约 {total_chars * 3 / 1048576:.2f} MB）")
    print(f"[trail] 输出目录 {out}")
    return 0


def write_index(out, man):
    """按时间倒序生成总索引，便于在第二台电脑上浏览。"""
    rows = []
    for rec in man.values():
        md = rec.get("md")
        if not md:
            continue
        rows.append(rec)
    rows.sort(key=lambda r: r["md"], reverse=True)
    L = ["# 任务历史索引", "",
         f"> 由 `export_trail.py` 自动生成　·　共 {len(rows)} 个会话　·　"
         f"更新于 {datetime.now(CST):%Y-%m-%d %H:%M}", ""]
    cur_month = None
    for r in rows:
        month = r["md"][:7]
        if month != cur_month:
            L.append(f"\n## {month}\n")
            cur_month = month
        title = (r.get("title") or "").strip() or Path(r["md"]).stem
        L.append(f"- [{title}]({r['md']})　·　{r.get('turns', 0)} 轮")
    (out / "index.md").write_text("\n".join(L).rstrip() + "\n",
                                  encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
