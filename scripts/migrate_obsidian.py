#!/usr/bin/env python3
"""把 Obsidian 记忆库迁移成 ai-brain 的「一条一文件」格式。

规则：
- 00-Profile  → preference（按 ## 小节拆分）
- 01-Plans    → project   （按 ## 小节拆分）
- 02-Workflows→ skill     （按 ## 小节拆分）
- 03-Decisions→ decision  （按 ## 小节拆分）
- 10-Projects → project   （按 ## 小节拆分，scope = 项目名）
- 50-Daily-Reviews → journal（整篇一条，不拆）
- 90-System / raw / _index / .obsidian → 跳过

正文里出现旧系统（Obsidian / CodexMemory）的条目会被标注为「历史机制，已取代」，
避免迁移后 AI 又跑去读旧索引。

用法：
  python migrate_obsidian.py --src "D:/Codex/Obsidian/CodexMemory" --dst "D:/ai-brain-data" [--dry-run]
"""
import argparse
import hashlib
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

MAPPING = {
    "00-Profile": ("preference", "global"),
    "01-Plans": ("project", "global"),
    "02-Workflows": ("skill", "global"),
    "03-Decisions": ("decision", "global"),
    "10-Projects": ("project", None),
    "50-Daily-Reviews": ("journal", "global"),
}
SKIP_DIRS = {"90-System", "raw", ".obsidian", ".git"}
SUPERSEDED_HINT = (
    "> 历史记录：此机制已于 2026-10-20 由 ai-brain 取代，正文仅作背景参考，不要再按它执行。\n\n"
)


def slugify(title):
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", title.strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s[:40] or "note")


def now_iso():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def read_text(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def split_front(text):
    """返回 (frontmatter dict, 正文)"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, body


def split_sections(body):
    """按 ## 切分；返回 [(标题, 内容)]，无 ## 时整篇作为一节"""
    lines = body.splitlines()
    sections, cur_title, cur = [], "概述", []
    for ln in lines:
        if re.match(r"^##\s+\S", ln):
            if any(x.strip() for x in cur):
                sections.append((cur_title, "\n".join(cur).strip()))
            cur_title = re.sub(r"^##\s+", "", ln).strip()
            cur = []
        elif re.match(r"^#\s+\S", ln):
            continue  # 一级标题是文件标题，不重复
        else:
            cur.append(ln)
    if any(x.strip() for x in cur):
        sections.append((cur_title, "\n".join(cur).strip()))
    return sections


def clean_title(t):
    t = t.strip()
    # 只删「## 2026-10-03：」这种前置日期，保留标题里本来就有的日期含义
    t = re.sub(r"^[\d]{4}-[\d]{2}-[\d]{2}\s*[：:\-—]?\s*", "", t)
    t = re.sub(r"[（(].*?[）)]", "", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" \t-—·、:：,，。")
    return t


def journal_title(path, body):
    m = re.search(r"^#\s+(.+)$", body, re.M)
    if m:
        t = clean_title(m.group(1))
        if t and not re.fullmatch(r"[\d\-]+", t):
            return t
    d = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
    return f"工作日志 {d.group(1)}" if d else f"工作日志 {path.stem}"


def guess_date(fm, body, fallback):
    for key in ("created", "updated"):
        v = fm.get(key, "")
        if re.match(r"\d{4}-\d{2}-\d{2}", v or ""):
            return v[:10] + "T00:00:00+08:00"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", body)
    if m:
        return m.group(1) + "T00:00:00+08:00"
    return fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src, dst = Path(a.src), Path(a.dst)
    if not src.exists():
        sys.exit(f"源目录不存在: {src}")
    now = now_iso()

    made, skipped, notes = 0, 0, []

    for path in sorted(src.rglob("*.md")):
        rel = path.relative_to(src)
        parts = rel.parts
        if len(parts) < 2:
            skipped += 1
            notes.append(f"跳过 {rel}（根级索引）")
            continue
        top = parts[0]
        if top in SKIP_DIRS or "raw" in parts or path.stem.startswith("_index"):
            skipped += 1
            continue
        if top not in MAPPING:
            skipped += 1
            continue

        mtype, scope_rule = MAPPING[top]
        scope = scope_rule or path.stem.lower()
        text = read_text(path)
        fm, body = split_front(text)
        created = guess_date(fm, body, now)

        if mtype == "journal":
            chunks = [(journal_title(path, body), body)]
        else:
            chunks = split_sections(body)

        for title, content in chunks:
            content = content.strip()
            if len(re.sub(r"\s", "", content)) < 12:
                continue
            title = clean_title(title)
            if not title:
                continue
            # 太短的标题脱离文件后没有辨识度，补上所属文件
            if mtype != "journal" and len(title) <= 4:
                stem = re.sub(r"^Codex-", "", path.stem).replace("-", " ")
                title = f"{stem} · {title}"
            legs = content
            if "Obsidian" in content or "CodexMemory" in content:
                legs = SUPERSEDED_HINT + content
            sid = hashlib.sha1(f"{title}{created}{rel}".encode()).hexdigest()[:6]
            meta_lines = [
                "---",
                f"id: {mtype}-{created[:10].replace('-', '')}-{sid}",
                f"type: {mtype}",
                f"scope: {scope}",
                f"tags: [迁移, obsidian, {top}]",
                f"created: {created}",
                f"source: obsidian@zyl001",
                f"title: {title}",
                f"origin: {rel.as_posix()}",
                "---",
                "",
                legs.rstrip(),
                "",
            ]
            out = dst / "memory" / mtype / f"{slugify(title)}-{sid}.md"
            if not a.dry_run:
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists():
                    notes.append(f"已存在，跳过 {out.name}")
                    continue
                io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(meta_lines))
            made += 1
            notes.append(f"[{mtype}] {title}  ← {rel.as_posix()}")

    print(f"\n生成 {made} 条，跳过 {skipped} 个文件/目录")
    for n in notes:
        print("  " + n)
    if a.dry_run:
        print("\n（dry-run，未写盘）")


if __name__ == "__main__":
    main()
