#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain.py — 跨设备、跨 AI 的「第二大脑」记忆层。

只依赖 Python 3.8+ 标准库与 git，无第三方包。
记忆本体是一个独立的私有 git 仓库（Markdown + YAML frontmatter），
因此任何能读文件、能执行命令的 AI 都能共享同一颗大脑。

核心命令:
  init      初始化/绑定记忆仓库
  add       写入一条记忆
  recall    检索记忆
  brief     输出「启动简报」（会话开头注入的上下文块）
  compile   为某个 AI 工具生成入口文件（CLAUDE.md / AGENTS.md / ...）
  sync      提交 + 拉取 + 推送（跨设备同步）
  status    查看状态
  doctor    环境自检
  hook      start / stop，供各工具钩子调用

设计约束:
  1. 记忆与技能分离：本脚本属于公开技能仓库，用户数据在私有仓库。
  2. 条目一文件：并发写入几乎不产生 git 冲突。
  3. 索引不落盘：brief 时实时生成，避免索引文件冲突。
  4. 上下文有预算：brief 默认截断，细节靠 recall 按需拉取。
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"

# ---------------------------------------------------------------- 常量

TYPES = ["identity", "preference", "fact", "decision", "project", "skill", "journal"]
TYPE_LABEL = {
    "identity": "身份与角色",
    "preference": "偏好与禁忌",
    "fact": "事实与知识",
    "decision": "决策与理由",
    "project": "项目上下文",
    "skill": "可复用方法",
    "journal": "工作日志",
}

BRAIN_HOME = Path(os.environ.get("BRAIN_HOME", Path.home() / ".ai-brain"))
CONFIG_PATH = BRAIN_HOME / "config.json"

HOST = (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown").lower()


# ---------------------------------------------------------------- 基础工具

def die(msg, code=1):
    print(f"[brain] 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg):
    print(f"[brain] {msg}")


def now_iso():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def today():
    return datetime.now().strftime("%Y-%m-%d")


def read_text(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


def write_text(p, s):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


def run_git(args, cwd=None, timeout=90, check=False):
    """执行 git，返回 (code, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["git"] + args,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        die("未找到 git，请先安装 Git 并加入 PATH")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    if check and p.returncode != 0:
        die(f"git {' '.join(args)} 失败: {p.stderr.strip()}")
    return p.returncode, p.stdout.strip(), p.stderr.strip()


# ---------------------------------------------------------------- 配置

def load_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        # utf-8-sig：兼容 Windows 工具（记事本 / PowerShell Set-Content）写入的 BOM
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception as e:
        die(f"配置文件损坏: {CONFIG_PATH} ({e})")


def save_config(cfg):
    write_text(CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def require_config():
    cfg = load_config()
    if not cfg:
        die("尚未初始化。先运行:  brain init --repo <你的私有仓库地址>")
    repo = Path(cfg["data_repo"])
    if not repo.exists():
        die(f"记忆仓库路径不存在: {repo}（换电脑请重新 init 并 clone）")
    return cfg


def data_repo():
    return Path(require_config()["data_repo"])


def memory_dir():
    return data_repo() / "memory"


# ---------------------------------------------------------------- Frontmatter

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_front(text):
    m = FM_RE.match(text)
    meta, body = {}, text
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                meta[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
            else:
                meta[k] = v
    return meta, body.strip()


def dump_front(meta, body):
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def load_entries():
    md = memory_dir()
    out = []
    if not md.exists():
        return out
    for p in sorted(md.rglob("*.md")):
        if p.name.startswith("."):
            continue
        try:
            meta, body = parse_front(read_text(p))
        except Exception:
            continue
        if not meta.get("id"):
            meta["id"] = p.stem
        meta["_path"] = p
        meta["_body"] = body
        meta["_type"] = meta.get("type") or p.parent.name
        out.append(meta)
    return out


# ---------------------------------------------------------------- 文本处理

def tokenize(q):
    q = q.lower()
    toks = set(re.findall(r"[a-z0-9_\-\.]{2,}", q))
    for seg in re.findall(r"[\u4e00-\u9fff]+", q):
        toks.add(seg)
        for i in range(len(seg) - 1):
            toks.add(seg[i:i + 2])
    return toks


def slugify(title):
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", title.strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s[:40] or "note")


def short_id(title):
    return hashlib.sha1(f"{title}{now_iso()}".encode()).hexdigest()[:6]


def age_days(meta):
    ts = meta.get("created") or ""
    try:
        dt = datetime.fromisoformat(ts)
        return max(0.0, (datetime.now().astimezone() - dt).total_seconds() / 86400)
    except Exception:
        return 999.0


def title_of(meta):
    if meta.get("title"):
        return meta["title"]
    for line in meta.get("_body", "").splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:60]
    return meta["id"]


# ---------------------------------------------------------------- 命令: init

def cmd_init(a):
    target = Path(a.dir).expanduser() if a.dir else BRAIN_HOME / "data"
    if a.repo and not target.exists():
        code, _, err = run_git(["clone", a.repo, str(target)], timeout=180)
        if code != 0:
            die(f"clone 失败: {err}")
        info(f"已克隆记忆仓库 → {target}")
    else:
        target.mkdir(parents=True, exist_ok=True)
        if not (target / ".git").exists():
            run_git(["init", "-b", "main"], cwd=target)
            info(f"已初始化记忆仓库 → {target}")
    if a.repo and not (target / ".git").exists():
        run_git(["remote", "add", "origin", a.repo], cwd=target)

    for d in ["memory"] + [f"memory/{t}" for t in TYPES]:
        (target / d).mkdir(parents=True, exist_ok=True)

    gi = target / ".gitignore"
    if not gi.exists():
        write_text(gi, "# 本地产物\n.cache/\n__pycache__/\n*.tmp\n.DS_Store\n")

    cfg = load_config() or {}
    cfg.update({
        "data_repo": str(target.resolve()),
        "remote": a.repo or cfg.get("remote", ""),
        "device": a.device or cfg.get("device") or HOST,
        "version": VERSION,
        "created": cfg.get("created") or now_iso(),
    })
    save_config(cfg)

    # 首次初始化时给一份身份模板，避免大脑开局是空的
    ident = memory_dir() / "identity" / "identity-core.md"
    if not ident.exists():
        write_text(ident, dump_front({
            "id": "identity-core",
            "type": "identity",
            "scope": "global",
            "title": "核心身份",
            "tags": ["核心", "长期"],
            "created": now_iso(),
            "source": cfg["device"],
        }, "我是谁、做什么、长期目标、必须遵守的硬规则。\n（改这一条：直接编辑本文件，或 brain add --type identity）\n"))

    if (target / ".git").exists():
        ensure_git_identity(target)

    info(f"设备名: {cfg['device']}")
    info(f"配置: {CONFIG_PATH}")
    info("下一步: brain add ... 写入第一条记忆；brain brief 查看启动简报")


# ---------------------------------------------------------------- 命令: add

def cmd_add(a):
    require_config()
    body = a.body or ""
    if a.file:
        body = read_text(a.file)
    if not body.strip():
        die("内容为空：用 --body 或 --file 提供正文")
    sid = short_id(a.title)
    meta = {
        "id": f"{a.type}-{today().replace('-', '')}-{sid}",
        "type": a.type,
        "scope": a.scope,
        "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
        "created": now_iso(),
        "source": f"{a.tool}@{load_config().get('device', HOST)}",
    }
    if a.title:
        meta["title"] = a.title
    if a.confidence:
        meta["confidence"] = a.confidence
    p = memory_dir() / a.type / f"{slugify(a.title or a.type)}-{sid}.md"
    write_text(p, dump_front(meta, body))
    info(f"已写入 {meta['id']} → {p.relative_to(data_repo())}")
    if not a.no_commit:
        cmd_sync(argparse.Namespace(message=f"add: {a.title or meta['id']}", no_pull=True, no_push=True))


# ---------------------------------------------------------------- 命令: recall

def score(meta, toks, q):
    title = (meta.get("title") or title_of(meta)).lower()
    tags = " ".join(meta.get("tags") or []).lower()
    body = meta.get("_body", "").lower()
    s = 0.0
    for t in toks:
        if t in title:
            s += 6
        if t in tags:
            s += 4
        c = body.count(t)
        if c:
            s += min(c, 4) * 1.5
    if q.lower() in body:
        s += 5
    if meta.get("_type") in ("identity", "preference"):
        s += 1.5
    s += max(0.0, 3.0 - age_days(meta) / 30.0)
    return s


def cmd_recall(a):
    require_config()
    entries = load_entries()
    if not entries:
        info("记忆为空")
        return
    toks = tokenize(a.query)
    ranked = sorted(((score(m, toks, a.query), m) for m in entries), key=lambda x: -x[0])
    hits = [(s, m) for s, m in ranked if s >= 1.0][:a.k]
    if a.json:
        print(json.dumps([{**{k: v for k, v in m.items() if not k.startswith("_")},
                           "score": round(s, 2), "body": m["_body"]} for s, m in hits],
                         ensure_ascii=False, indent=2))
        return
    if not hits:
        info(f"未命中：{a.query}")
        return
    for s, m in hits:
        print(f"\n[{m['_type']}] {title_of(m)}  ({m['id']}, 相关度 {s:.1f})")
        if m.get("tags"):
            print(f"  tags: {', '.join(m['tags'])}")
        excerpt = m["_body"].strip().splitlines()
        for line in excerpt[:a.lines]:
            print(f"  {line}")
        if len(excerpt) > a.lines:
            print("  ...")


# ---------------------------------------------------------------- 命令: brief

def entry_line(m):
    return f"- `{m['id']}` [{m['_type']}] {title_of(m)}"


def cmd_brief(a):
    require_config()
    cfg = load_config()
    entries = load_entries()
    budget = a.max_chars
    parts = []
    parts.append(f"# 大脑简报 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · 设备 {cfg.get('device', HOST)}")
    parts.append("> 由 ai-brain 生成。这是跨设备同步的长期记忆快照，不是本次对话内容。")

    def section(title, items, with_body=False, limit=40):
        if not items:
            return
        chunk = [f"\n## {title}"]
        for m in items[:limit]:
            chunk.append(entry_line(m))
            if with_body and m["_body"]:
                for line in m["_body"].strip().splitlines()[:12]:
                    chunk.append(f"  {line}")
        parts.extend(chunk)

    def by_type(t):
        return [m for m in entries if m["_type"] == t]

    section("身份与硬规则（必须遵守）", by_type("identity") + [m for m in by_type("preference")
                                                  if (m.get("scope") or "global") == "global"],
            with_body=True, limit=25)
    proj = [m for m in by_type("project") if a.project and a.project.lower() in (
        (m.get("scope") or "") + " " + " ".join(m.get("tags") or []) + " " + title_of(m)).lower()]
    section(f"当前项目：{a.project}", proj, with_body=True, limit=10)
    section("最近决策", sorted(by_type("decision"), key=age_days)[:8], with_body=False)
    section("习惯与偏好（按场景）", [m for m in by_type("preference")
                            if (m.get("scope") or "global") != "global"], with_body=False, limit=15)
    section("可复用方法", by_type("skill"), limit=12)

    recent = sorted([m for m in entries if m["_type"] in ("fact", "journal")], key=age_days)[:8]
    section("近期动态", recent, limit=8)

    total = len(entries)
    parts.append(f"\n## 索引统计\n- 条目总数 {total}；按类型 " +
                 "、".join(f"{t}:{len(by_type(t))}" for t in TYPES if by_type(t)))
    parts.append('\n## 使用约定\n- 需要细节时执行：`brain recall "<关键词>"`，不要凭猜测补全记忆。')
    parts.append("- 学到新的稳定事实/偏好时执行：`brain add --type ... --title ... --body ...`。")

    out = "\n".join(parts)
    if len(out) > budget:
        out = out[:budget] + f"\n\n…（已按 {budget} 字符预算截断，用 recall 取细节）"
    print(out)


# ---------------------------------------------------------------- 命令: compile

CORE = """<!-- 本文件由 ai-brain 自动生成，请勿手改；改记忆请用 `brain add` -->
# 第二大脑协议（ai-brain v{ver}）

你接入了用户的跨设备长期记忆层。记忆本体是本地 git 仓库 `{repo}`，
通过 git 在用户的多台电脑、多个 AI 客户端之间同步——**同一颗大脑，多个入口**。

`brain` 是记忆读写命令；若终端里找不到它，见 `{home}/scripts/install-shim.md`。
命令不可用时，直接读写 `{repo}/memory/` 下的 Markdown 文件即可，效果等同。

## 一、会话开始时（必须执行）

1. 运行 `brain brief --project <当前项目目录名>`，把输出当作已知背景。
2. 简报里已有的信息，不要重复询问用户。
3. 简报与本次对话冲突时，以对话为准，并把它写成一条新记忆（旧条目保留时间戳，供追溯）。

## 二、会话进行中

- 需要细节：`brain recall "<关键词>" -k 8`。**禁止**凭印象编造用户的历史、偏好或决定。
- 用户表达稳定偏好、纠正你的做法、给出可复用方法时，立即 `brain add`，不要等他提醒。
- 引用记忆时说明来源条目 id，方便用户核对。

## 三、会话结束时（必须执行）

1. 写日志：`brain add --type journal --title "<一句话主题>" --body "<做了什么 / 结论 / 待办>"`
2. 同步：`brain sync -m "session: <主题>"`（自动提交、拉取、推送）

## 四、写什么、不写什么

写：稳定偏好与禁忌、身份事实、项目背景、决策及其理由（含被否掉的方案）、可复用方法、用户的原话纠正。
不写：临时文件路径、中间调试输出、一次性搜索结果、任何密钥 / 密码 / 证件号。

## 五、记忆格式

一条记忆 = 一个 Markdown 文件，带 frontmatter：
`id / type / scope / tags / created / source / confidence`。
正文用短句、可独立阅读，**一条只讲一件事**，便于检索与合并。

---

## 附：当前记忆快照

{brief}
"""

TARGETS = {
    "claude":    ("CLAUDE.md", ""),
    "codex":     ("AGENTS.md", ""),
    "gemini":    ("GEMINI.md", ""),
    "cursor":    (".cursor/rules/brain.mdc",
                  "---\ndescription: 第二大脑长期记忆协议\nalwaysApply: true\n---\n\n"),
    "workbuddy": ("SKILL.md",
                  "---\nname: second-brain\ndescription: 用户的跨设备长期记忆层。当需要了解用户偏好、历史决策、项目背景，或需要记录新的稳定事实时使用。\n---\n\n"),
    "chatgpt":   ("custom-instructions.md", ""),
}


def cmd_compile(a):
    cfg = require_config()
    repo_path = Path(cfg["data_repo"])
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_brief(argparse.Namespace(max_chars=a.brief_chars, project=a.project))
    brief = buf.getvalue()

    home = Path(__file__).resolve().parent.as_posix()
    core = (CORE.replace("{ver}", VERSION)
                .replace("{repo}", repo_path.as_posix())
                .replace("{home}", home)
                .replace("{brief}", brief))

    targets = list(TARGETS) if a.target == "all" else [a.target]
    for t in targets:
        fname, prefix = TARGETS[t]
        out = Path(a.out) if (a.out and len(targets) == 1) else Path(a.out_dir or "dist") / t / fname
        write_text(out, prefix + core)
        info(f"{t:10s} → {out}")


# ---------------------------------------------------------------- 命令: sync

def cmd_sync(a):
    cfg = require_config()
    repo = Path(cfg["data_repo"])
    code, _, _ = run_git(["rev-parse", "--git-dir"], cwd=repo)
    if code != 0:
        info("记忆目录不是 git 仓库，跳过同步")
        return

    run_git(["add", "-A"], cwd=repo)
    ensure_git_identity(repo)
    code, out, _ = run_git(["status", "--porcelain"], cwd=repo)
    if out:
        msg = a.message or f"sync: {cfg.get('device', HOST)} {now_iso()}"
        code, _, err = run_git(["commit", "-m", msg], cwd=repo)
        if code != 0:
            info(f"提交失败（可能是未配置 git 用户）: {err}")
        else:
            info(f"已提交 {len(out.splitlines())} 项变更")

    has_remote = bool(run_git(["remote"], cwd=repo)[1])
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)[1] or "main"
    remote_has_branch = False
    if has_remote:
        c, out, _ = run_git(["ls-remote", "--heads", "origin", branch], cwd=repo, timeout=30)
        remote_has_branch = (c == 0 and bool(out))
    if has_remote and not a.no_pull and remote_has_branch:
        code, _, err = run_git(["pull", "--rebase", "--autostash", "--no-edit"], cwd=repo, timeout=180)
        if code != 0:
            last = err.splitlines()[-1] if err else ""
            info(f"拉取失败（可能离线或冲突）: {last}")
            info("冲突处理：条目一文件，保留双方即可；git status 查看后手工合并，再 brain sync")
            return
    if has_remote and not a.no_push:
        push_args = ["push"] if remote_has_branch else ["push", "-u", "origin", branch]
        code, _, err = run_git(push_args, cwd=repo, timeout=180)
        if code != 0:
            info(f"推送失败（可能离线/无权限）: {err.splitlines()[-1] if err else ''}")
            return
        info("已同步到远端")


# ---------------------------------------------------------------- 命令: status / doctor

def cmd_status(a):
    cfg = require_config()
    repo = Path(cfg["data_repo"])
    entries = load_entries()
    print(f"记忆仓库 : {repo}")
    print(f"设备名   : {cfg.get('device')}")
    print(f"远端     : {git_remote(repo) or '（未设置）'}")
    print(f"条目总数 : {len(entries)}")
    for t in TYPES:
        n = len([m for m in entries if m["_type"] == t])
        if n:
            print(f"  - {t:11s} {n:3d}  {TYPE_LABEL[t]}")
    code, out, _ = run_git(["log", "-1", "--pretty=%h %ad %s", "--date=short"], cwd=repo)
    print(f"最新提交 : {out or '（无）'}")
    dirty = run_git(["status", "--porcelain"], cwd=repo)[1]
    print(f"未同步   : {len(dirty.splitlines()) if dirty else 0} 项")


def git_remote(repo):
    return run_git(["remote", "get-url", "origin"], cwd=repo)[1]


def ensure_git_identity(repo):
    """没有全局 git 身份时，为记忆仓库设置本地身份，避免 commit 直接失败。"""
    name = run_git(["config", "user.name"], cwd=repo)[1]
    mail = run_git(["config", "user.email"], cwd=repo)[1]
    if not name:
        n = f"ai-brain@{HOST}"
        run_git(["config", "user.name", n], cwd=repo)
        info(f"已设置仓库级 git user.name = {n}（全局未配置）")
    if not mail:
        run_git(["config", "user.email", f"ai-brain@{HOST}.local"], cwd=repo)


def cmd_doctor(a):
    ok = True
    print(f"ai-brain v{VERSION}")
    print(f"Python   : {sys.version.split()[0]} ({sys.executable})")
    code, out, _ = run_git(["version"])
    print(f"Git      : {out or '未安装'}")
    ok &= code == 0
    cfg = load_config()
    if not cfg:
        print("配置     : 未初始化 ✗")
        ok = False
    else:
        repo = Path(cfg["data_repo"])
        print(f"配置     : {CONFIG_PATH} ✓")
        print(f"记忆仓库 : {repo} {'✓' if repo.exists() else '✗'}")
        ok &= repo.exists()
        name = run_git(["config", "user.name"], cwd=repo)[1]
        print(f"git 用户 : {name or '（未配置，提交会失败）'}")
        if not name:
            print("           修复: git config --global user.name 'Your Name'")
            ok = False
        remote = git_remote(repo) if repo.exists() else ""
        print(f"远端     : {remote or '（未设置，仅本地）'}")
        if remote:
            c, _, err = run_git(["ls-remote", "--exit-code", "-h", remote], cwd=repo, timeout=30)
            print(f"远端连通 : {'✓' if c == 0 else '✗ ' + (err.splitlines()[-1] if err else '')}")
            ok &= c == 0
    print("结论     : " + ("一切正常" if ok else "存在需修复项"))
    sys.exit(0 if ok else 2)


# ---------------------------------------------------------------- 命令: hook

def cmd_hook(a):
    cfg = load_config()
    if not cfg:
        return
    repo = Path(cfg["data_repo"])
    if a.phase == "start":
        if run_git(["remote"], cwd=repo)[1]:
            run_git(["pull", "--rebase", "--autostash", "--no-edit"], cwd=repo, timeout=25)
        cmd_brief(argparse.Namespace(max_chars=6000, project=None))
    elif a.phase == "stop":
        if run_git(["status", "--porcelain"], cwd=repo)[1]:
            cmd_sync(argparse.Namespace(message=f"auto: {a.tool}@{cfg.get('device', HOST)}", no_pull=True, no_push=False))


# ---------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(prog="brain", description="跨设备、跨 AI 的第二大脑记忆层")
    p.add_argument("--version", action="version", version=f"ai-brain {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化并绑定记忆仓库")
    s.add_argument("--repo", help="私有 git 仓库地址（留空则为本地仓库）")
    s.add_argument("--dir", help="本地目录（默认 ~/.ai-brain/data）")
    s.add_argument("--device", help="设备名，例如 macbook / win-office")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add", help="写入一条记忆")
    s.add_argument("--type", required=True, choices=TYPES)
    s.add_argument("--title", default="")
    s.add_argument("--body", default="")
    s.add_argument("--file", help="从文件读取正文")
    s.add_argument("--tags", default="")
    s.add_argument("--scope", default="global")
    s.add_argument("--confidence", default="")
    s.add_argument("--tool", default="cli")
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("recall", help="检索记忆")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=8)
    s.add_argument("--lines", type=int, default=6)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("brief", help="输出启动简报")
    s.add_argument("--max-chars", type=int, default=6000)
    s.add_argument("--project", default=None)
    s.set_defaults(func=cmd_brief)

    s = sub.add_parser("compile", help="生成各 AI 工具入口文件")
    s.add_argument("--target", default="all", choices=list(TARGETS) + ["all"])
    s.add_argument("--out", help="单目标输出文件路径")
    s.add_argument("--out-dir", default="dist")
    s.add_argument("--brief-chars", type=int, default=3500)
    s.add_argument("--project", default=None)
    s.set_defaults(func=cmd_compile)

    s = sub.add_parser("sync", help="提交并同步到远端")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--no-pull", action="store_true")
    s.add_argument("--no-push", action="store_true")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("status", help="查看状态")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("doctor", help="环境自检")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("hook", help="钩子入口")
    s.add_argument("phase", choices=["start", "stop"])
    s.add_argument("--tool", default="unknown")
    s.set_defaults(func=cmd_hook)
    return p


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
