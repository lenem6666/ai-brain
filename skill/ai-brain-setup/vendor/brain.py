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
  distill   记忆体检 + 蒸馏（合并重复、提炼日志、归档过时）
  hook      start / stop，供各工具钩子调用

设计约束:
  1. 记忆与技能分离：本脚本属于公开技能仓库，用户数据在私有仓库。
  2. 条目一文件：并发写入几乎不产生 git 冲突。
  3. 索引不落盘：brief 时实时生成，避免索引文件冲突。
  4. 上下文有预算：brief 默认截断，细节靠 recall 按需拉取。
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _git_candidates():
    """候选 git，按"能用 https"的可靠性排序。

    坑：某些便携版把 mingw64/bin 放进 PATH，那里的 git.exe 缺少
    git-remote-https 助手，clone https 仓库会报
    "git: 'remote-https' is not a git command"。Git for Windows 的 cmd/git.exe
    才能正确解析 libexec，所以 PATH 之后紧跟常见安装位置。
    """
    out = []
    p = shutil.which("git")
    if p:
        out.append(p)
    for c in (
        os.environ.get("BRAIN_GIT", ""),
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        os.path.expandvars(r"%ProgramFiles%\Git\cmd\git.exe"),
        r"D:\Program Files (x86)\WorkBuddy\resources\vendor\PortableGit\cmd\git.exe",
        "/usr/bin/git",
        "/usr/local/bin/git",
    ):
        if c and Path(c).exists() and c not in out:
            out.append(c)
    return out or ["git"]


GIT = _git_candidates()[0]
_GIT_RETRIED = False


def _git_next():
    """切换到下一个候选（只切一次，避免死循环）。"""
    global GIT, _GIT_RETRIED
    if _GIT_RETRIED:
        return None
    for c in _git_candidates():
        if c != GIT:
            _GIT_RETRIED = True
            GIT = c
            return c
    return None


VERSION = "0.2.0"

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


def _git_env():
    """给 git 子进程补一个能用的 GIT_EXEC_PATH。

    坑：某些精简版 Git（便携包）把 git-remote-https.exe 放在 mingw64/bin，
    而 git --exec-path 指向空的 libexec/git-core，于是 clone https 会报
    "git: 'remote-https' is not a git command"（从 PowerShell 启动时必现）。
    这里只在"默认位置确实没有助手"时，才把 GIT_EXEC_PATH 指到有助手的那一层。
    """
    env = dict(os.environ)
    if env.get("GIT_EXEC_PATH"):
        return env
    p = Path(GIT)
    probes = [
        p.parent,
        p.parent.parent / "mingw64" / "bin",
        p.parent.parent / "mingw64" / "libexec" / "git-core",
        p.parent.parent / "libexec" / "git-core",
    ]
    for d in probes:
        if (d / "git-remote-https.exe").exists():
            default = p.parent.parent / "mingw64" / "libexec" / "git-core"
            if d != default:
                env["GIT_EXEC_PATH"] = str(d)
            return env
    return env


def run_git(args, cwd=None, timeout=90, check=False):
    """执行 git，返回 (code, stdout, stderr)。"""
    try:
        p = subprocess.run(
            # core.quotepath=false：否则 git 会把中文路径输出成 "\346\226..." 转义，
            # 后续按路径做 checkout / show 全部失败（冲突处理曾因此取不到文件）。
            [GIT, "-c", "core.quotepath=false"] + args,
            env=_git_env(),
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
    err = (p.stderr or "")
    # 当前 git 缺少 https 助手（便携版常见）→ 换一个候选重试一次
    if p.returncode != 0 and ("remote helper" in err or "is not a git command" in err):
        alt = _git_next()
        if alt:
            info(f"当前 git 无法访问 https，改用 {alt}")
            return run_git(args, cwd=cwd, timeout=timeout, check=check)
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


ARCHIVE = "_archive"          # 归档目录：memory/_archive/...，默认不进简报、不参与检索
RETIRED_TAGS = ("已废止", "已合并")


def is_archived(meta):
    return bool(meta.get("status") == "archived"
                or ARCHIVE in Path(str(meta.get("_path", ""))).parts
                or meta.get("superseded_by"))


def is_retired(meta):
    """不该进简报的条目：已被取代、已合并、已归档。仍可 recall --all 查到。"""
    return is_archived(meta) or any(t in (meta.get("tags") or []) for t in RETIRED_TAGS)


def load_entries(include_archived=False):
    md = memory_dir()
    out = []
    if not md.exists():
        return out
    for p in sorted(md.rglob("*.md")):
        if p.name.startswith("."):
            continue
        if not include_archived and ARCHIVE in p.parts:
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
    # 只用「标题 + 秒级时间」会在同一秒内写出同名文件、静默覆盖上一条，
    # 因此掺入纳秒与进程号，保证连续写入也不撞名。
    return hashlib.sha1(
        f"{title}{now_iso()}{time.time_ns()}{os.getpid()}".encode()
    ).hexdigest()[:6]


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

    # 固定 LF：Windows 的 core.autocrlf=true 会把检出文件转成 CRLF，
    # 导致同一份记忆在不同系统上字节不一致、diff 全是噪音。
    ga = target / ".gitattributes"
    if not ga.exists():
        write_text(ga, "* text=auto eol=lf\n")

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

    # 把初始骨架提交并推到远端：
    # 否则第二台设备 clone 到的是空库，各自产生无关根提交，历史永远合不起来。
    if (target / ".git").exists():
        ensure_git_identity(target)
        run_git(["add", "-A"], cwd=target)
        if run_git(["status", "--porcelain"], cwd=target)[1]:
            run_git(["commit", "-m", "init: ai-brain skeleton"], cwd=target)
        if run_git(["remote"], cwd=target)[1]:
            branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target)[1] or "main"
            c, out, _ = run_git(["ls-remote", "--heads", "origin", branch], cwd=target, timeout=30)
            if c == 0 and out:
                c2, _, err = run_git(["pull", "--rebase", "--autostash", "--no-edit"],
                                     cwd=target, timeout=120)
                if c2 != 0:
                    info(f"拉取失败（离线可继续）: {err.splitlines()[-1] if err else ''}")
                run_git(["push"], cwd=target, timeout=120)
            else:
                c2, _, err = run_git(["push", "-u", "origin", branch], cwd=target, timeout=120)
                if c2 != 0:
                    info(f"推送失败（离线可继续，稍后 brain sync）: "
                         f"{err.splitlines()[-1] if err else ''}")

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
    for _ in range(5):            # 极端情况（同秒同名）兜底，绝不覆盖已有条目
        if not p.exists():
            break
        sid = short_id(a.title)
        meta["id"] = f"{a.type}-{today().replace('-', '')}-{sid}"
        p = memory_dir() / a.type / f"{slugify(a.title or a.type)}-{sid}.md"
    write_text(p, dump_front(meta, body))
    info(f"已写入 {meta['id']} → {p.relative_to(data_repo())}")
    if not a.no_commit:
        repo = data_repo()
        cmd_sync(argparse.Namespace(message=f"add: {a.title or meta['id']}",
                                    no_pull=True, no_push=True, force=False))
        # 尽力推送：成功则其他设备立刻可见；失败（离线 / 远端已前进）静默跳过，
        # 由下一次 brain sync 的 pull --rebase 收敛。不阻塞写入。
        if run_git(["remote"], cwd=repo)[1]:
            run_git(["push"], cwd=repo, timeout=15)


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
    entries = load_entries(include_archived=getattr(a, "all", False))
    if not entries:
        info("记忆为空")
        return
    if not getattr(a, "all", False):
        # 已归档默认不参与检索；--all 才翻旧账
        entries = [m for m in entries if ARCHIVE not in Path(str(m["_path"])).parts]
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

    def section(title, items, with_body=False, limit=40, body_lines=6):
        if not items:
            return
        chunk = [f"\n## {title}"]
        for m in items[:limit]:
            chunk.append(entry_line(m))
            if with_body and m["_body"]:
                lines = [ln for ln in m["_body"].strip().splitlines() if ln.strip()]
                for line in lines[:body_lines]:
                    chunk.append(f"  {line}")
                if len(lines) > body_lines:
                    chunk.append(f"  …（另有 {len(lines) - body_lines} 行，需要时用 recall）")
        parts.extend(chunk)

    def by_type(t):
        # 已废止 / 已合并 / 已归档的条目不进简报，否则 AI 会照着过时规则执行；
        # 它们仍留在仓库里，需要时用 recall 查得到。
        return [m for m in entries if m["_type"] == t and not is_retired(m)]

    section("身份（必须遵守）", by_type("identity"), with_body=True, limit=3, body_lines=14)
    section("长期偏好与硬规则", [m for m in by_type("preference")
                          if (m.get("scope") or "global") == "global"],
            with_body=True, limit=25, body_lines=4)
    proj = [m for m in by_type("project") if a.project and a.project.lower() in (
        (m.get("scope") or "") + " " + " ".join(m.get("tags") or []) + " " + title_of(m)).lower()]
    section(f"当前项目：{a.project}", proj, with_body=True, limit=10)
    section("最近决策", sorted(by_type("decision"), key=age_days)[:8], with_body=False)
    section("习惯与偏好（按场景）", [m for m in by_type("preference")
                            if (m.get("scope") or "global") != "global"], with_body=False, limit=15)
    section("可复用方法", by_type("skill"), limit=12)
    # 事实类最容易"用到时想不起来"：路径、端口、环境坑，给一个不占正文的紧凑分区
    section("事实与约束", by_type("fact"), limit=10)

    recent = sorted(by_type("journal"), key=age_days)[:8]
    section("近期动态（日志，仅作背景）", recent, limit=8)

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

## 三·补、定期蒸馏（记忆 >80 条或每月一次）

日志是原料，不是结论。长期不蒸馏，简报会被重复与过时条目稀释。

1. `brain distill --task` 生成体检报告与任务包（路径会打印出来）
2. **你**读任务包，按其中的规则产出 `distill-plan.json`（只输出计划，不改文件）
3. `brain distill --apply distill-plan.json` 执行合并/归档，然后 `python scripts/refresh.py`

硬约束：不许臆造，数字/路径/命令/硬规则原样保留；归档只针对已废止、已被取代或纯日志，不得归档还生效的偏好。

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


# ---------------------------------------------------------------- 命令: distill

def _squash(s):
    """去掉排版符号与空白，只留语义字符，用于相似度与长度统计。"""
    return re.sub(r"[\s*#`>\-—·、,，。.;；:：!！?？()（）\[\]【】\"'“”‘’/\\]+", "", s)


def _jaccard(a, b):
    A, B = tokenize(a), tokenize(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def distill_groups(entries, days=30, threshold=0.72):
    """找出该合并 / 该提炼 / 该归档的候选。只做分析，不写盘。"""
    groups = []
    used = set()

    # 1) 同标题：一条记忆只讲一件事，标题相同基本就是重复或演进关系
    by_title = {}
    for m in entries:
        key = re.sub(r"[\s　]+", "", title_of(m)).lower()
        if len(key) < 4:
            continue
        by_title.setdefault(key, []).append(m)
    for _, ms in by_title.items():
        if len(ms) > 1:
            groups.append({"kind": "same-title",
                           "reason": f"标题相同：{title_of(ms[0])}（{len(ms)} 条）",
                           "items": ms})
            used.update(m["id"] for m in ms)

    # 2) 正文高度重叠：先按词集快速筛，再算序列相似度，避免 O(n²) 直接上 difflib
    cand = [m for m in entries
            if m["id"] not in used and len(_squash(m["_body"])) >= 60]
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            a, b = cand[i], cand[j]
            if a["_type"] != b["_type"] or a["id"] in used or b["id"] in used:
                continue
            if _jaccard(a["_body"], b["_body"]) < 0.45:
                continue
            r = difflib.SequenceMatcher(None, _squash(a["_body"])[:900],
                                        _squash(b["_body"])[:900]).ratio()
            if r >= threshold:
                groups.append({"kind": "near-dup",
                               "reason": f"正文相似度 {r:.0%}",
                               "items": [a, b]})
                used.update((a["id"], b["id"]))

    # 3) 老日志：日志是原料，不是结论，放着不提炼就是噪音
    olds = [m for m in entries if m["_type"] == "journal" and age_days(m) >= days]
    if olds:
        groups.append({"kind": "stale-journal",
                       "reason": f"{len(olds)} 条日志超过 {days} 天未提炼",
                       "items": olds})

    # 4) 已废止 / 已合并：不进简报但仍在仓库，挪进 _archive 减少噪音
    retired = [m for m in entries
               if m["id"] not in used
               and any(t in (m.get("tags") or []) for t in RETIRED_TAGS)]
    if retired:
        groups.append({"kind": "retired",
                       "reason": f"{len(retired)} 条已废止/已合并，建议归档",
                       "items": retired})

    # 5) 过短：独立存在没有信息量
    thin = [m for m in entries
            if m["id"] not in used and m["_type"] != "identity"
            and len(_squash(m["_body"])) < 15]
    if thin:
        groups.append({"kind": "too-thin",
                       "reason": f"{len(thin)} 条正文不足 15 字，补全或归档",
                       "items": thin})
    return groups


def render_report(groups, entries, total, journal_chars):
    lines = [f"# 记忆体检报告 · {today()}", "",
             f"- 条目 {len(entries)} 条，正文合计 {total} 字",
             f"- 其中日志 {journal_chars} 字（占 {journal_chars * 100 // max(1, total)}%）",
             f"- 发现 {len(groups)} 组待处理", ""]
    for i, g in enumerate(groups, 1):
        lines.append(f"## {i}. {g['kind']} · {g['reason']}")
        for m in g["items"]:
            lines.append(f"- `{m['id']}` [{m['_type']}] {title_of(m)}"
                         f"（{len(_squash(m['_body']))} 字，{age_days(m):.0f} 天前）")
        lines.append("")
    return "\n".join(lines)


def render_task(groups, entries):
    lines = [f"# 记忆蒸馏任务 · {today()}", "",
             "你在帮用户整理长期记忆库。目标：把重复、过时、过长的条目，合并成更少更准的条目。",
             "",
             "## 硬性规则",
             "",
             "1. **不许臆造**。只能使用现有条目里出现过的信息；拿不准就保留原文。",
             "2. **数字、路径、命令、硬规则必须原样保留**，这些是用户真正要复用的东西。",
             "3. 合并后每条正文 ≤ 400 字，一条只讲一件事；删掉寒暄、重复、无信息量的过渡句。",
             "4. 日志是原料不是结论：提炼成 `preference` / `decision` / `skill` / `fact`，不要留 `journal`。",
             "5. 只输出计划，不改文件。",
             "",
             "## 输出格式（保存为 distill-plan.json，UTF-8）",
             "",
             "```json",
             "{",
             '  "merges": [',
             '    {"type": "preference", "title": "合并后的标题", "body": "合并后的正文",',
             '     "tags": ["标签"], "absorb": ["要吸收掉的条目 id", "..."],',
             '     "keep": "（可选）保留哪条原 id，不填则新建一条"}',
             "  ],",
             '  "update": [{"id": "要改写的 id", "title": "新标题（可省略）", "body": "改写后的正文"}],',
             '  "archive": ["要归档的 id", "..."]',
             "}",
             "```",
             "",
             "规则：`absorb` 里列出的条目会被标记为「已合并」，不进简报，但保留可追溯；",
             "`archive` 用于已废止、已被新方案取代、或纯日志类条目。**不要归档还生效的偏好与硬规则。**",
             "", "---", "", "## 候选条目", ""]
    for i, g in enumerate(groups, 1):
        lines.append(f"### 组 {i} · {g['kind']} · {g['reason']}")
        lines.append("")
        for m in g["items"]:
            body = m["_body"].strip().replace("\n", " ")
            lines.append(f"- `{m['id']}` [{m['_type']}] **{title_of(m)}**"
                         f"（{len(_squash(m['_body']))} 字）  ")
            lines.append(f"  {body[:260]}{'…' if len(body) > 260 else ''}")
        lines.append("")
    return "\n".join(lines)


def _write_meta(path, meta, body):
    write_text(path, dump_front(meta, body))


def apply_plan(path, repo):
    """执行蒸馏计划：合并 / 改写 / 归档。不删除任何正文，只改写与移动。"""
    if not path.exists():
        die(f"计划文件不存在: {path}")
    try:
        plan = json.loads(read_text(path))
    except Exception as e:
        die(f"计划文件不是合法 JSON: {e}")

    entries = {m["id"]: m for m in load_entries(include_archived=True)}
    mem = memory_dir()
    created, updated, merged, archived, missing = [], [], [], [], []

    def meta_of(m):
        return {k: v for k, v in m.items() if not k.startswith("_")}

    # ---- 改写
    for u in plan.get("update", []) or []:
        m = entries.get(u.get("id"))
        if not m:
            missing.append(u.get("id"))
            continue
        meta = meta_of(m)
        if u.get("title"):
            meta["title"] = u["title"]
        meta["updated"] = today()
        _write_meta(m["_path"], meta, u.get("body") or m["_body"])
        updated.append(m["id"])

    # ---- 合并
    for g in plan.get("merges", []) or []:
        absorb_ids = [x for x in (g.get("absorb") or []) if x in entries]
        if not absorb_ids:
            missing.extend(g.get("absorb") or [])
            continue
        src = [entries[x] for x in absorb_ids]
        mtype = g.get("type") or src[0]["_type"]
        title = g.get("title") or title_of(src[0])
        body = (g.get("body") or "").strip()
        if not body:
            missing.append(f"merge:{title}(正文为空)")
            continue
        tags = g.get("tags") or []
        tags = [tags] if isinstance(tags, str) else list(tags)
        keep = g.get("keep")

        if keep and keep in entries:
            m = entries[keep]
            meta = meta_of(m)
            meta["title"] = title
            meta["type"] = mtype
            meta["tags"] = tags or meta.get("tags") or []
            meta["updated"] = today()
            _write_meta(m["_path"], meta, body)
            new_id = keep
            updated.append(keep)
        else:
            sid = short_id(title)
            new_id = f"{mtype}-{today().replace('-', '')}-{sid}"
            dest = mem / mtype / f"{slugify(title)}-{sid}.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_meta(dest, {
                "id": new_id, "type": mtype, "scope": "global",
                "tags": tags or ["蒸馏"], "created": now_iso(),
                "source": f"distill@{load_config().get('device', HOST)}",
                "title": title, "confidence": "high",
            }, body)
            created.append(new_id)

        for m in src:
            if m["id"] == new_id:
                continue
            meta = meta_of(m)
            t = list(meta.get("tags") or [])
            if "已合并" not in t:
                t.append("已合并")
            meta["tags"] = t
            meta["superseded_by"] = new_id
            _write_meta(m["_path"], meta, m["_body"])
            merged.append(m["id"])

    # ---- 归档：移到 memory/_archive/<type>/，保留正文与 git 历史
    for eid in plan.get("archive", []) or []:
        m = entries.get(eid)
        if not m:
            missing.append(eid)
            continue
        if ARCHIVE in m["_path"].parts:
            continue
        meta = meta_of(m)
        meta["status"] = "archived"
        meta["archived"] = today()
        dest = mem / ARCHIVE / m["_type"] / m["_path"].name
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_meta(dest, meta, m["_body"])
        m["_path"].unlink()
        archived.append(eid)

    print(f"新建 {len(created)} 条，改写 {len(updated)} 条，标记已合并 {len(merged)} 条，归档 {len(archived)} 条")
    if missing:
        print(f"跳过 {len(missing)} 个无法处理的项：{', '.join(str(x) for x in missing[:6])}")
    if not (created or updated or merged or archived):
        info("没有任何改动")
        return

    # 归档是计划内的批量移动，属于有意操作，这里放行误删拦截
    cmd_sync(argparse.Namespace(message=f"distill: 合并 {len(merged)} / 归档 {len(archived)}",
                                no_pull=True, no_push=False, force=True))
    print("\n记得刷新入口文件，否则 AI 读到的还是旧快照：")
    print("  python scripts/refresh.py")


def cmd_distill(a):
    cfg = require_config()
    repo = Path(cfg["data_repo"])
    if a.apply:
        return apply_plan(Path(a.apply), repo)

    entries = load_entries()
    groups = distill_groups(entries, days=a.days, threshold=a.threshold)
    total = sum(len(_squash(m["_body"])) for m in entries)
    journal_chars = sum(len(_squash(m["_body"])) for m in entries if m["_type"] == "journal")

    if a.json:
        print(json.dumps([{
            "kind": g["kind"], "reason": g["reason"],
            "items": [{"id": m["id"], "type": m["_type"], "title": title_of(m),
                       "chars": len(_squash(m["_body"]))} for m in g["items"]],
        } for g in groups], ensure_ascii=False, indent=2))
        return

    print(f"记忆 {len(entries)} 条 / 正文 {total} 字（日志占 {journal_chars} 字）")
    if not groups:
        info("没有需要蒸馏的内容")
        return
    for i, g in enumerate(groups, 1):
        print(f"\n[{i}] {g['kind']} · {g['reason']}")
        for m in g["items"][:8]:
            print(f"    - {m['id']}  [{m['_type']}] {title_of(m)}"
                  f"（{len(_squash(m['_body']))} 字，{age_days(m):.0f} 天前）")
        if len(g["items"]) > 8:
            print(f"    … 另 {len(g['items']) - 8} 条")

    out_dir = repo / "distill"
    out_dir.mkdir(parents=True, exist_ok=True)
    gi = out_dir / ".gitignore"
    if not gi.exists():
        write_text(gi, "# 报告与任务包属于临时产物，不进记忆库\n*\n")
    stamp = today().replace("-", "")
    if a.task:
        p = out_dir / f"task-{stamp}.md"
        write_text(p, render_task(groups, entries))
        info(f"任务包 → {p}")
    if a.report or not a.task:
        p = out_dir / f"report-{stamp}.md"
        write_text(p, render_report(groups, entries, total, journal_chars))
        info(f"报告 → {p}")

    print("\n下一步：让 AI 读任务包产出 distill-plan.json，然后执行")
    print("  brain distill --apply distill-plan.json")


def cmd_compile(a):
    cfg = require_config()
    repo_path = Path(cfg["data_repo"])
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_brief(argparse.Namespace(max_chars=a.brief_chars, project=a.project))
    brief = buf.getvalue()
    # 编译产物要被 git 跟踪/比对，不能带"分钟级"时间戳，否则每次编译都产生假 diff
    brief = re.sub(r"^# 大脑简报 · .*$", "# 记忆快照（由 brain compile 生成）",
                   brief, count=1, flags=re.M)

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

def guard_deletions(repo, force=False):
    """拦截批量删除。返回 True 表示放行。

    动机：AI 一旦"误操作删库"，靠 git 历史能救回来，但前提是别先把它推上去、
    又覆盖了别人的历史。所以在提交前先拦一次，让人确认。
    """
    code, out, _ = run_git(["diff", "--cached", "--name-status", "--", "memory"], cwd=repo)
    if code != 0 or not out:
        return True
    deleted = [l.split("\t", 1)[-1] for l in out.splitlines() if l.startswith("D")]
    if not deleted:
        return True
    tracked = run_git(["ls-tree", "-r", "--name-only", "HEAD", "--", "memory"], cwd=repo)[1]
    total = len(tracked.splitlines()) or 0
    ratio = len(deleted) / total if total else 0.0
    if force:
        info(f"已放行批量删除：{len(deleted)} 条（--force）")
        return True
    if len(deleted) >= 3 or (total and ratio >= 0.3):
        info(f"已拦截：本次将删除 {len(deleted)}/{total} 条记忆（{ratio:.0%}）")
        for d in deleted[:10]:
            info(f"  - {d}")
        if len(deleted) > 10:
            info(f"  … 另 {len(deleted) - 10} 条")
        info("确认无误请加 --force 重跑；只想撤销请用 git checkout -- memory/")
        return False
    return True


CONFLICT_TAG = "冲突副本"


def refresh_entries():
    """闭环最后一跳：记忆变了就重编译各客户端入口文件，避免新会话读到旧快照。

    只在标准安装（BRAIN_HOME == 程序目录）下生效，测试/多档案环境不会误写用户入口；
    设置 BRAIN_AUTO_REFRESH=0 可关闭。失败只提示，不影响同步本身。
    """
    if os.environ.get("BRAIN_AUTO_REFRESH", "1") == "0":
        return
    here = Path(__file__).resolve().parent
    try:
        if Path(BRAIN_HOME).resolve() != here:
            return
    except Exception:
        return
    script = here / "scripts" / "refresh.py"
    if not script.exists():
        return
    try:
        p = subprocess.run([sys.executable, str(script)], cwd=str(here), timeout=180,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0:
            info("入口文件已刷新")
        else:
            info(f"入口刷新失败（记忆不受影响）: {((p.stderr or '') + (p.stdout or '')).strip()[:160]}")
    except Exception as e:
        info(f"入口刷新跳过: {e}")


def _git_path(repo, name):
    code, out, _ = run_git(["rev-parse", "--git-path", name], cwd=repo)
    if code != 0 or not out:
        return None
    p = Path(out)
    return p if p.is_absolute() else Path(repo) / p


def _rebase_in_progress(repo):
    for n in ("rebase-merge", "rebase-apply"):
        p = _git_path(repo, n)
        if p and p.exists():
            return True
    return False


def _current_branch(repo):
    code, out, _ = run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo)
    if code == 0 and out:
        return out
    p = _git_path(repo, "rebase-merge/head-name")
    if p and p.exists():
        return p.read_text(encoding="utf-8").strip().rsplit("/", 1)[-1]
    return "main"


def _resolve_rebase_conflict(repo, branch):
    """冲突兜底：既不丢字，也不留下卡死的 rebase 现场。

    条目一文件的设计下，"冲突"就是同一事实存在两个版本。这里把本地版本另存为
    一条新记忆（打「冲突副本」标签），原条目取远端版本，提交后重新 rebase。
    保留双方、等人 distill 合并，比任何自动取舍都安全，也不会让人卡在
    "rebase 中间态 → 之后每次同步都失败"的死循环里。
    """
    code, out, _ = run_git(["diff", "--name-only", "--diff-filter=U"], cwd=repo)
    paths = [l.strip() for l in out.splitlines() if l.strip()]
    local = {}
    for rel in paths:
        c, o, _ = run_git(["show", f"REBASE_HEAD:{rel}"], cwd=repo)
        if c != 0:
            c, o, _ = run_git(["show", f":3:{rel}"], cwd=repo)
        if c == 0:
            local[rel] = o
    run_git(["rebase", "--abort"], cwd=repo)
    # 关键：把分支指回远端最新，本地改动全部保留在暂存区。
    # 若只是 abort 后重跑 pull --rebase，被重放的本地提交仍会再冲突一次（死循环）。
    c, _, err = run_git(["reset", "--soft", f"origin/{branch}"], cwd=repo)
    if c != 0:
        info(f"对齐远端失败，已回滚到本地提交: {err.splitlines()[-1] if err else ''}")
        return []

    saved = []
    for rel, txt in local.items():
        if not txt.strip():
            continue
        src = Path(repo) / rel
        try:
            meta, body = parse_front(txt)
        except Exception:
            meta, body = {}, txt
        etype = meta.get("type") or (src.parent.name if src.parent.name != ARCHIVE else "fact")
        title = meta.get("title") or src.stem
        sid = short_id(title)
        meta.update({
            "id": f"{etype}-{today().replace('-', '')}-{sid}",
            "type": etype,
            "created": now_iso(),
            "source": f"conflict@{load_config().get('device', HOST)}",
            "title": f"{title}（冲突副本）",
        })
        tags = [t for t in (meta.get("tags") or []) if t != CONFLICT_TAG]
        meta["tags"] = tags + [CONFLICT_TAG]
        dst = src.parent / f"{slugify(title)}-conflict-{sid}.md"
        note = (f"\n\n> 同步冲突副本：{now_iso()} 自动保留的本地版本，"
                f"原条目已取远端版本。核对后合并到原条目，再删除本副本。\n")
        write_text(dst, dump_front(meta, body.rstrip() + note))
        c, _, err = run_git(["checkout", f"origin/{branch}", "--", rel], cwd=repo)
        if c != 0:
            info(f"取远端版本失败 {rel}: {err.splitlines()[-1] if err else ''}")
        saved.append(dst.relative_to(repo).as_posix())
    run_git(["add", "-A"], cwd=repo)
    run_git(["commit", "-m", f"merge: 冲突保留双版本（{len(saved)} 条）"], cwd=repo)
    for s in saved:
        info(f"已保留本地版本 → {s}")
    return saved


def cmd_sync(a):
    cfg = require_config()
    repo = Path(cfg["data_repo"])
    code, _, _ = run_git(["rev-parse", "--git-dir"], cwd=repo)
    if code != 0:
        info("记忆目录不是 git 仓库，跳过同步")
        return

    # 上次同步若中断在 rebase 中间态，先修好再继续，避免把冲突标记当成正常内容提交
    if _rebase_in_progress(repo):
        info("检测到上次中断的同步，正在恢复…")
        _resolve_rebase_conflict(repo, _current_branch(repo))

    head0 = run_git(["rev-parse", "HEAD"], cwd=repo)[1]
    run_git(["add", "-A"], cwd=repo)
    ensure_git_identity(repo)
    if not guard_deletions(repo, force=getattr(a, "force", False)):
        run_git(["reset"], cwd=repo)  # 撤回暂存，保持工作区原样
        sys.exit(3)

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
            if _rebase_in_progress(repo):
                saved = _resolve_rebase_conflict(repo, branch)
                if saved:
                    info(f"同步冲突：已保留双版本 {len(saved)} 条，原条目取远端版")
                else:
                    info("同步冲突：已回滚到本地提交，未丢数据")
            else:
                last = err.splitlines()[-1] if err else ""
                info(f"拉取失败（可能离线）: {last}")
                info("本地提交已保留，未丢数据；联网后重跑 brain sync 即可收敛")
                sys.exit(4)
    if has_remote and not a.no_push:
        push_args = ["push"] if remote_has_branch else ["push", "-u", "origin", branch]
        code, _, err = run_git(push_args, cwd=repo, timeout=180)
        if code != 0:
            info(f"推送失败（可能离线/无权限）: {err.splitlines()[-1] if err else ''}")
            return
        info("已同步到远端")

    # 记忆有变化（本地提交或拉到别人的提交）→ 重编译入口文件，闭环最后一跳
    if not getattr(a, "no_refresh", False):
        head1 = run_git(["rev-parse", "HEAD"], cwd=repo)[1]
        if head1 and head0 and head1 != head0:
            refresh_entries()


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
    retired = [m for m in entries if any(t in (m.get("tags") or []) for t in RETIRED_TAGS)]
    if retired:
        print(f"已合并/废止 : {len(retired)} 条（不进简报，recall 可查）")
    arch = len(load_entries(include_archived=True)) - len(entries)
    if arch:
        print(f"已归档   : {arch} 条（memory/_archive，需 recall --all）")
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
        print("配置     : 未初始化 [FAIL]")
        ok = False
    else:
        repo = Path(cfg["data_repo"])
        print(f"配置     : {CONFIG_PATH} [OK]")
        print(f"记忆仓库 : {repo} {'[OK]' if repo.exists() else '[FAIL]'}")
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
            print(f"远端连通 : {'[OK]' if c == 0 else '[FAIL] ' + (err.splitlines()[-1] if err else '')}")
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
        head0 = run_git(["rev-parse", "HEAD"], cwd=repo)[1]
        if run_git(["remote"], cwd=repo)[1]:
            run_git(["pull", "--rebase", "--autostash", "--no-edit"], cwd=repo, timeout=25)
        head1 = run_git(["rev-parse", "HEAD"], cwd=repo)[1]
        if head0 and head1 and head0 != head1:   # 拉到新记忆 → 顺手刷新入口
            refresh_entries()
        cmd_brief(argparse.Namespace(max_chars=6000, project=None))
    elif a.phase == "stop":
        if run_git(["status", "--porcelain"], cwd=repo)[1]:
            try:
                cmd_sync(argparse.Namespace(
                    message=f"auto: {a.tool}@{cfg.get('device', HOST)}",
                    no_pull=True, no_push=False, force=False))
            except SystemExit:
                # 批量删除被拦截时不要让钩子整体失败：原因已打印，交给人工确认
                pass


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
    s.add_argument("--all", action="store_true", help="连已归档的旧条目一起搜")
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
    s.add_argument("--force", action="store_true", help="放行批量删除（默认拦截 ≥3 条或 ≥30% 的删除）")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("distill", help="记忆体检：找重复/过时/过长，生成蒸馏任务包")
    s.add_argument("--days", type=int, default=30, help="日志超过多少天算待提炼")
    s.add_argument("--threshold", type=float, default=0.72, help="正文相似度阈值")
    s.add_argument("--task", action="store_true", help="生成给 AI 的任务包")
    s.add_argument("--report", action="store_true", help="只出体检报告")
    s.add_argument("--json", action="store_true", help="机器可读输出")
    s.add_argument("--apply", help="执行蒸馏计划 JSON")
    s.set_defaults(func=cmd_distill)

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
        # 只兜住无法编码的字符，不改编码：Windows PowerShell 控制台是 GBK，
        # 强制 UTF-8 会让中文变成"閿欒"这种乱码（换机后第一次运行就踩）。
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
