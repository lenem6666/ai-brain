#!/usr/bin/env python3
"""把工作区里的产物文件按策略同步到 git 仓库，并生成清单。

策略（2026-10-21 与用户确认）：
- 文档类：实体复制到 <out>/files/<项目>/<相对路径>，第二台电脑可直接打开。
- 媒体类：只记清单，实体不搬（视频与图片体积占比过高，且多为可再生）。
- 排除：隐藏目录（.inv100 等中间产物）、依赖目录、运行时目录。

用法：
    python scripts/sync_artifacts.py --dry-run
    python scripts/sync_artifacts.py
    python scripts/sync_artifacts.py --max-mb 50      # 超过多少 MB 只记清单
"""
import argparse
import io
import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

DOC_EXT = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".pdf", ".md", ".csv"}
MEDIA_EXT = {".mp4", ".mov", ".avi", ".mkv", ".png", ".jpg", ".jpeg", ".gif",
             ".webp", ".bmp", ".wav", ".mp3", ".m4a"}
SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "env", "runtime",
             "binaries", "dist", "build", ".git", ".workbuddy", "site-packages"}

LONG = "\\\\?\\"


def lp(p):
    """Windows 长路径前缀：深层目录相加后经常越过 260 字符。"""
    s = str(Path(p).resolve())
    if os.name == "nt" and not s.startswith(LONG):
        return LONG + s
    return s


def should_skip_dir(name):
    return name.startswith(".") or name in SKIP_DIRS


def scan(root, max_bytes):
    """遍历工作区，返回 (docs, media)。docs 待复制，media 只做清单。"""
    docs, media = [], []
    for proj in sorted(Path(root).glob("2026-*")):
        if not proj.is_dir():
            continue
        for cur, dirs, files in os.walk(proj):
            dirs[:] = [d for d in dirs if not should_skip_dir(d)]
            for f in files:
                src = Path(cur) / f
                ext = src.suffix.lower()
                if ext not in DOC_EXT and ext not in MEDIA_EXT:
                    continue
                try:
                    st = src.stat()
                except OSError:
                    continue
                rel = src.relative_to(root)
                rec = {"src": src, "rel": rel.as_posix(), "size": st.st_size,
                       "mtime": int(st.st_mtime), "project": proj.name}
                if ext in DOC_EXT and st.st_size <= max_bytes:
                    docs.append(rec)
                else:
                    rec["why"] = "媒体文件" if ext in MEDIA_EXT else f"单文件超过 {max_bytes // 1048576}MB"
                    media.append(rec)
    return docs, media


def main():
    ap = argparse.ArgumentParser(description="同步工作区产物到记忆仓库")
    ap.add_argument("--root", default=r"D:/WorkBuddy", help="工作区根目录")
    ap.add_argument("--out", help="输出根（默认 <data>/trail）")
    ap.add_argument("--max-mb", type=int, default=50, help="单文件实体同步上限（MB）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true", help="删除源已不存在的副本")
    a = ap.parse_args()

    root = Path(a.root)
    if not root.exists():
        print(f"[files] 工作区不存在：{root}")
        return 0

    if a.out:
        out = Path(a.out)
    else:
        base = Path(os.environ.get("BRAIN_DATA") or r"D:/ai-brain-data")
        if not base.exists():
            base = Path(os.environ.get("USERPROFILE") or Path.home()) / "ai-brain-data"
        out = base / "trail"
    dest_root = out / "files"

    max_bytes = a.max_mb * 1048576
    docs, media = scan(root, max_bytes)

    man_path = out / ".artifacts.json"
    old = {}
    if man_path.exists():
        try:
            old = json.loads(man_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}

    new_man = {}
    copied = unchanged = failed = 0
    copied_bytes = 0
    for rec in docs:
        key = rec["rel"]
        sig = f"{rec['mtime']}:{rec['size']}"
        dest = dest_root / rec["rel"]
        prev = old.get(key)
        if prev and prev.get("sig") == sig and dest.exists():
            new_man[key] = prev
            unchanged += 1
            continue
        if not a.dry_run:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(lp(rec["src"]), lp(dest))
            except (OSError, shutil.Error) as e:
                print(f"  [跳过] {rec['rel']} → {type(e).__name__}: {e}")
                failed += 1
                continue
        new_man[key] = {"sig": sig, "size": rec["size"], "project": rec["project"]}
        copied += 1
        copied_bytes += rec["size"]

    pruned = 0
    if a.prune and not a.dry_run:
        for key in list(old):
            if key not in new_man:
                victim = dest_root / key
                if victim.exists():
                    victim.unlink()
                    pruned += 1

    if not a.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        man_path.write_text(json.dumps(new_man, ensure_ascii=False, indent=1, sort_keys=True),
                            encoding="utf-8", newline="\n")
        write_report(out, docs, media, new_man)

    verb = "统计" if a.dry_run else "同步"
    print(f"[files] {verb}：复制/更新 {copied} 个（{copied_bytes / 1048576:.1f} MB），"
          f"未变 {unchanged} 个，失败 {failed} 个，清理 {pruned} 个")
    print(f"[files] 仅记清单（不同步实体）{len(media)} 个，"
          f"合计 {sum(m['size'] for m in media) / 1048576:.0f} MB")
    print(f"[files] 仓库内文档合计 {(sum(r['size'] for r in docs) if a.dry_run else sum(r['size'] for r in new_man.values())) / 1048576:.1f} MB")
    return 0


def write_report(out, docs, media, man):
    L = ["# 产物清单", "",
         f"> 由 `sync_artifacts.py` 自动生成　·　更新于 {datetime.now(CST):%Y-%m-%d %H:%M}", "",
         "文档类已实体同步到 `files/`，另一台电脑可直接打开；",
         "媒体类只在下面登记，实体没有搬（视频图片体积太大且可再生产）。", ""]

    by_proj = {}
    for rec in docs:
        by_proj.setdefault(rec["project"], []).append(rec)
    L.append("## 已同步的文档")
    L.append("")
    for proj in sorted(by_proj):
        items = sorted(by_proj[proj], key=lambda r: r["rel"])
        L.append(f"### {proj}　（{len(items)} 个，{sum(i['size'] for i in items) / 1048576:.1f} MB）")
        L.append("")
        for it in items:
            name = Path(it["rel"]).name
            sub = str(Path(it["rel"]).parent).replace("\\", "/")
            L.append(f"- `{name}`　{it['size'] / 1024:.0f} KB　—　{proj}/{sub}")
        L.append("")

    if media:
        L.append("## 未同步的媒体（仅登记）")
        L.append("")
        by_proj2 = {}
        for rec in media:
            by_proj2.setdefault(rec["project"], []).append(rec)
        for proj in sorted(by_proj2):
            items = sorted(by_proj2[proj], key=lambda r: -r["size"])
            total = sum(i["size"] for i in items) / 1048576
            L.append(f"### {proj}　（{len(items)} 个，{total:.0f} MB）")
            L.append("")
            for it in items[:40]:
                L.append(f"- `{Path(it['rel']).name}`　{it['size'] / 1048576:.1f} MB　—　{it['why']}")
            if len(items) > 40:
                L.append(f"- …… 另有 {len(items) - 40} 个，见同目录 `.artifacts.json`")
            L.append("")

    (out / "artifacts.md").write_text("\n".join(L).rstrip() + "\n",
                                      encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
