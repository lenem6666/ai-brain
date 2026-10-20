#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-brain 自举：让一台只装了本 Skill 的电脑恢复全部记忆。

设计目标：换机时用户只需要「装 WorkBuddy -> 登录同账号 -> 装本 Skill」，
剩下的程序、运行时、入口文件、记忆库拉取全部由这里完成。

用法：
    python ensure.py                 检查并修复，最后打印记忆简报
    python ensure.py --status        只检查，不改动任何东西
    python ensure.py --repo URL      指定记忆库地址（默认读 defaults.json）
    python ensure.py --device NAME   指定本机设备名（默认主机名）
    python ensure.py --dir PATH      指定记忆库本地目录

退出码：
    0  就绪            2  缺信息（需要用户给仓库地址）
    3  需要 GitHub 授权  5  网络不通（国内需代理）
    4  其它失败
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENDOR = SKILL_DIR / "vendor"
PY = sys.executable or "python"


# ---------------------------------------------------------------- 基础工具

def say(msg=""):
    print(msg, flush=True)


def dec(raw):
    """子进程输出解码：brain 的输出跟随控制台编码，可能是 UTF-8 也可能是 GBK。"""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def run(cmd, cwd=None, timeout=120, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    try:
        p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                           capture_output=True, timeout=timeout, env=e)
        return p.returncode, dec(p.stdout), dec(p.stderr)
    except FileNotFoundError:
        return 127, "", "not found: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def load_defaults():
    p = SKILL_DIR / "defaults.json"
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


DEFAULTS = load_defaults()


def _probe(port, timeout=0.4):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def detect_proxy():
    """优先环境变量；否则探测本机常见代理端口（v2rayN: 10809 http / 10808 socks）。

    换机场景下用户往往没配 ~/.gitconfig 的代理，直连 GitHub 会失败，
    这里兜一层，让「装完就能用」在墙内也成立。
    """
    for k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "ALL_PROXY", "all_proxy"):
        v = os.environ.get(k)
        if v:
            return v
    if _probe(10809):
        return "http://127.0.0.1:10809"
    if _probe(10808):
        return "socks5h://127.0.0.1:10808"
    return ""


PROXY = detect_proxy()

NET_HINTS = ("could not connect", "failed to connect", "connection timed out", "timed out",
             "could not resolve host", "connection refused", "network is unreachable",
             "connection reset", "ssl", "tls", "proxy")
AUTH_HINTS = ("could not read username", "authentication failed", "terminal prompts disabled",
              "permission denied", "403", "repository not found", "support for password")


def is_net_error(text):
    low = (text or "").lower()
    return any(h in low for h in NET_HINTS)


def is_auth_error(text):
    low = (text or "").lower()
    return any(h in low for h in AUTH_HINTS)


def net_env():
    """给 brain.py 的子进程注入代理（git 认这些环境变量），不改用户的全局 git 配置。"""
    if not PROXY:
        return {}
    return {"HTTPS_PROXY": PROXY, "HTTP_PROXY": PROXY,
            "https_proxy": PROXY, "http_proxy": PROXY}


# ---------------------------------------------------------------- 环境探测

def find_git():
    """git 优先级：环境变量 -> PATH -> WorkBuddy 自带便携版 -> 系统安装位置。"""
    p = os.environ.get("BRAIN_GIT")
    if p and Path(p).exists():
        return p
    p = shutil.which("git")
    if p:
        return p

    cands = []
    for base in (os.environ.get("WORKBUDDY_HOME"), r"D:\WorkBuddy",
                 str(Path.home() / "WorkBuddy")):
        if not base:
            continue
        root = Path(base) / ".workbuddy" / "binaries" / "PortableGit" / "versions"
        if root.is_dir():
            items = sorted([d for d in root.iterdir() if d.is_dir()], reverse=True)
            cands += [d / "cmd" / "git.exe" for d in items]
            cands += [d / "mingw64" / "bin" / "git.exe" for d in items]
    cands += [
        Path(r"D:\Program Files (x86)\WorkBuddy\resources\vendor\PortableGit\cmd\git.exe"),
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
        Path("/usr/bin/git"), Path("/usr/local/bin/git"), Path("/opt/homebrew/bin/git"),
    ]
    for c in cands:
        if c.exists():
            return str(c)
    return ""


def find_gh():
    p = shutil.which("gh")
    if p:
        return p
    for c in (Path(r"C:\Program Files\GitHub CLI\gh.exe"),
              Path(os.environ.get("LOCALAPPDATA", "")) / "GitHubCLI" / "gh.exe",
              Path("/usr/local/bin/gh"), Path("/opt/homebrew/bin/gh")):
        if c.exists():
            return str(c)
    return ""


def gh_token():
    """已登录 gh 时直接取 token，避免非交互环境下卡在凭据弹窗。"""
    gh = find_gh()
    if not gh:
        return os.environ.get("BRAIN_TOKEN", "")
    code, out, _ = run([gh, "auth", "token"], timeout=20)
    if code == 0 and out.strip():
        return out.strip()
    return os.environ.get("BRAIN_TOKEN", "")


def resolve_root(explicit):
    if explicit:
        return Path(explicit).expanduser().resolve(), "参数 --root"

    env = os.environ.get("BRAIN_HOME")
    if env and (Path(env) / "brain.py").exists():
        return Path(env).resolve(), "环境变量 BRAIN_HOME"

    for c in (Path("D:/ai-brain"), Path.home() / ".ai-brain",
              Path(os.environ.get("LOCALAPPDATA", "") or Path.home()) / "ai-brain"):
        if (c / "brain.py").exists() or (c / "config.json").exists():
            return c, "已有安装"

    if Path("D:/").exists():
        return Path("D:/ai-brain"), "默认（D 盘）"
    return Path(os.environ.get("LOCALAPPDATA", "") or Path.home()) / "ai-brain", "默认（用户目录）"


def data_dir_of(root):
    cfg = root / "config.json"
    if not cfg.exists():
        return None
    try:
        return Path(json.loads(cfg.read_text(encoding="utf-8-sig"))["data_repo"])
    except Exception:
        return None


# ---------------------------------------------------------------- git 克隆

def git_clone(url, dest, git, shallow=True):
    """clone 到 dest。先试代理再试直连；克隆到临时目录再搬，绝不删 dest 里已有文件。

    shallow 只给程序仓库用：记忆库必须完整历史，浅克隆之后 push / rebase 会被服务端拒绝。
    返回 (ok, error)。
    """
    if not git:
        return False, "未找到 git"
    dest = Path(dest)
    tmp = dest.parent / (dest.name + ".clone-tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)

    attempts = []
    if PROXY and "github.com" in url:
        attempts.append(PROXY)
    attempts.append("")            # 直连兜底

    last = ""
    for proxy in attempts:
        shutil.rmtree(tmp, ignore_errors=True)
        args = [git]
        if proxy:
            args += ["-c", "http.https://github.com.proxy=%s" % proxy]
        if shallow:
            args += ["clone", "--depth", "1", url, str(tmp)]
        else:
            args += ["clone", url, str(tmp)]
        code, out, err = run(args, timeout=180)
        if code == 0 and (tmp / ".git").exists():
            dest.mkdir(parents=True, exist_ok=True)
            for item in tmp.iterdir():
                target = dest / item.name
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink()
                shutil.move(str(item), str(target))
            shutil.rmtree(tmp, ignore_errors=True)
            return True, ""
        last = (err or out).strip()
        if is_auth_error(last):
            break                  # 授权问题，换网络也没用
    shutil.rmtree(tmp, ignore_errors=True)
    return False, last


# ---------------------------------------------------------------- 安装程序

def install_program(root, git, status_only):
    """把程序放到 root：优先 clone 公开仓库拿最新版，网络不通时用 skill 自带副本。"""
    if (root / "brain.py").exists():
        return "already", "已存在"
    if status_only:
        return "missing", "未安装"

    root.mkdir(parents=True, exist_ok=True)
    repo = DEFAULTS.get("program_repo", "")
    err = ""

    if git and repo:
        ok, err = git_clone(repo, root, git)
        if ok and (root / "brain.py").exists():
            return "cloned", "从公开仓库下载"

    # 兜底：skill 里带的种子副本（没有 git / 断网也能用）
    if VENDOR.exists():
        for item in VENDOR.iterdir():
            dst = root / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        if (root / "brain.py").exists():
            return "vendor", "使用 Skill 内置副本" + ("（GitHub 未连通）" if err else "")
    return "failed", "安装失败：%s" % (err or "没有可用的内置副本")


# ---------------------------------------------------------------- 记忆库

def ensure_memory(root, repo, device, data_dir, status_only):
    """配置 + 拉取记忆库。返回 (state, message)。"""
    if (root / "config.json").exists():
        return "already", "已配置"
    if not repo:
        return "need_repo", "还没有记忆库地址"
    if status_only:
        return "need_config", "未配置记忆库"

    git = find_git()
    target = Path(data_dir).expanduser() if data_dir else (root / "data")

    if not (target / ".git").exists():
        ok, err = git_clone(repo, target, git, shallow=False)
        if not ok:
            if is_auth_error(err):
                token = gh_token()
                if token:
                    ok2, err2 = git_clone(repo.replace("https://github.com",
                                                       "https://x-access-token:%s@github.com" % token),
                                          target, git, shallow=False)
                    if ok2:
                        run([git, "remote", "set-url", "origin", repo], cwd=target, timeout=30)
                        ok = True
                    else:
                        err = err2
                if not ok:
                    return "need_auth", (err or "").splitlines()[-1] if err else "需要授权"
            elif is_net_error(err) or not err:
                return "need_net", (err or "").splitlines()[-1] if err else "连不上 GitHub"
            else:
                return "failed", (err or "").splitlines()[-1] if err else "拉取失败"

    # 目录已就绪，只写配置（init 检测到 .git 存在不会重复克隆）
    code, out, err = run([PY, str(root / "brain.py"), "init", "--repo", repo,
                          "--device", device, "--dir", str(target)],
                         timeout=180, env={"BRAIN_HOME": str(root), **net_env()})
    if code == 0:
        return "cloned", "记忆库已就绪"
    last = (err or out).strip().splitlines()
    return "failed", last[-1] if last else "初始化失败"


# ---------------------------------------------------------------- 入口与简报

def sync_and_refresh(root):
    notes = []
    code, out, err = run([PY, str(root / "brain.py"), "sync"], timeout=300,
                         env={"BRAIN_HOME": str(root), **net_env()})
    notes.append("同步成功" if code == 0 else "同步未完成（离线也不影响读）")

    ref = root / "scripts" / "refresh.py"
    if ref.exists():
        c2, _, _ = run([PY, str(ref)], timeout=120, env={"BRAIN_HOME": str(root)})
        if c2 == 0:
            notes.append("入口已刷新")
    return notes


def do_brief(root, project=""):
    args = [PY, str(root / "brain.py"), "brief"]
    if project:
        args += ["--project", project]
    code, out, err = run(args, timeout=120, env={"BRAIN_HOME": str(root)})
    return out if code == 0 else ""


def count_entries(root):
    d = data_dir_of(root)
    if not d or not (d / "memory").exists():
        return 0, 0
    active = len([p for p in (d / "memory").rglob("*.md") if "_archive" not in p.parts])
    arc_dir = d / "memory" / "_archive"
    arch = len(list(arc_dir.rglob("*.md"))) if arc_dir.exists() else 0
    return active, arch


# ---------------------------------------------------------------- 主流程

def main():
    # 被管道 / agent 捕获时输出裸 LF：Windows 默认把 \n 转成 \r\n，
    # 经 PowerShell 管道会在每行末尾留一个可见的 ^M（显示成 X）。
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(newline="\n")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="ai-brain 换机自举")
    ap.add_argument("--repo", default=DEFAULTS.get("repo", ""), help="私有记忆库地址")
    ap.add_argument("--device", default="", help="本机设备名")
    ap.add_argument("--dir", default="", help="记忆库本地目录")
    ap.add_argument("--root", default="", help="程序安装根目录")
    ap.add_argument("--project", default="", help="简报按项目过滤")
    ap.add_argument("--status", action="store_true", help="只检查，不改动")
    ap.add_argument("--no-brief", action="store_true", help="不打印简报")
    a = ap.parse_args()

    device = a.device or (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown").lower()
    root, root_src = resolve_root(a.root)
    git = find_git()

    say("ai-brain 自举")
    say("  技能目录 : %s" % SKILL_DIR)
    say("  程序根   : %s（%s）" % (root, root_src))
    say("  Python   : %s" % PY)
    say("  git      : %s" % (git or "未找到"))
    say("  代理     : %s" % (PROXY or "未使用"))

    state, msg = install_program(root, git, a.status)
    say("  程序     : %s（%s）" % (msg, state))
    if state == "failed":
        say("[FAIL] 无法安装程序，且没有可用的内置副本")
        return 4
    if state == "missing":
        say("[NEED_INSTALL] 程序还没安装，去掉 --status 再执行一次即可自动安装")
        return 2

    mstate, mmsg = ensure_memory(root, a.repo, device, a.dir, a.status)
    say("  记忆库   : %s（%s）" % (mmsg, mstate))

    if mstate == "need_repo":
        say("")
        say("[NEED_REPO] 需要你提供记忆库地址。")
        say("  在已经装了大脑的电脑上执行 brain brief，或直接给 GitHub 私有仓库地址")
        say("  （形如 https://github.com/<你>/brain-data.git）。")
        say("  也可以写进本 Skill 的 defaults.json 的 repo 字段，以后换机就不用再填。")
        return 2

    if mstate == "need_auth":
        say("")
        say("[NEED_AUTH] GitHub 还没有授权，这是换机唯一无法自动化的一步。")
        say("  任选一种：")
        say("    1) 装 GitHub CLI 后执行  gh auth login        （推荐，本脚本会自动复用凭据）")
        say("    2) 设置环境变量 BRAIN_TOKEN=<你的 PAT> 后重跑")
        say("    3) 手工执行  git clone %s" % a.repo)
        say("       弹窗里登录一次，凭据会存进系统凭据管理器，之后一直有效")
        say("  注意：这一步是 GitHub 授权，和 WorkBuddy 账号是两套体系。")
        return 3

    if mstate == "need_net":
        say("")
        say("[NEED_NET] 连不上 GitHub：%s" % mmsg)
        say("  国内网络请先开代理，然后重跑本脚本（会自动探测 127.0.0.1:10809/10808）；")
        say("  或设置 HTTPS_PROXY=http://127.0.0.1:10809 再执行。")
        return 5

    if mstate == "failed":
        say("[FAIL] 记忆库初始化失败：%s" % mmsg)
        return 4

    active, arch = count_entries(root)
    if a.status:
        say("")
        say("STATUS root=%s active=%d archived=%d git=%s proxy=%s"
            % (root, active, arch, "yes" if git else "no", "yes" if PROXY else "no"))
        return 0

    notes = sync_and_refresh(root)
    say("  动作     : %s" % "、".join(notes))
    active, arch = count_entries(root)
    say("")
    say("[OK] 记忆已就绪：%d 条活跃 / %d 条归档" % (active, arch))

    if not a.no_brief:
        brief = do_brief(root, a.project)
        if brief:
            say("")
            say("-" * 60)
            say(brief)

    say("")
    say("STATUS root=%s active=%d archived=%d device=%s" % (root, active, arch, device))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
