#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_loop.py — 闭环验证：专测"会不会丢 / 会不会卡 / 会不会被覆盖"。

validate.py 验的是"功能对不对"，本脚本验的是"失败路径会不会把数据搞坏"：
离线写、双机并发、同一条目冲突、误删、坏文件、全量恢复、入口文件被覆盖、
MCP 协议、钩子、真机与远端一致性。

用法:
    python scripts/verify_loop.py          # 全部
    python scripts/verify_loop.py --quick  # 跳过真机部分
退出码: 0 全绿；1 有失败。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "brain.py"
PY = Path(os.environ.get("BRAIN_PY") or sys.executable)
QUICK = "--quick" in sys.argv
REAL_HOME = Path(os.environ.get("BRAIN_REAL_HOME") or ROOT)

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

RESULTS = []


def sh(cmd, cwd=None, env=None, timeout=180, input_text=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=e, timeout=timeout,
                          input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")


def git(repo, *args, expect=0):
    p = sh(["git", *args], cwd=repo)
    if expect is not None and p.returncode != expect:
        raise AssertionError(f"git {' '.join(args)} → {p.returncode}: {(p.stderr or p.stdout)[:300]}")
    return (p.stdout or "").strip()


def brain(home, *args, expect=0):
    p = sh([str(PY), str(BRAIN), *args], env={"BRAIN_HOME": str(home), "PYTHONUTF8": "1"})
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if expect is not None and p.returncode != expect:
        raise AssertionError(f"brain {' '.join(args)} → {p.returncode}（期望 {expect}）: {out[:300]}")
    return p.returncode, out


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        RESULTS.append((True, name, detail))
        print(f"  PASS  {name}\n        {detail}")
    except Exception as e:
        RESULTS.append((False, name, str(e)))
        print(f"  FAIL  {name}\n        {e}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def snapshot(repo):
    """memory 下所有 md 的 (相对路径, 内容sha) 集合。"""
    md = Path(repo) / "memory"
    return {(p.relative_to(md).as_posix(), sha(p)) for p in md.rglob("*.md")}


def rmtree(p):
    """Windows 上 .git/objects 是只读的，直接 rmtree 会 PermissionError。"""
    p = Path(p)
    if not p.exists():
        return
    for root, _, files in os.walk(p):
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o666)
            except Exception:
                pass
    shutil.rmtree(p, ignore_errors=True)


def fresh_clone(remote, dest):
    rmtree(dest)
    p = sh(["git", "clone", "-q", str(remote), str(dest)])
    if p.returncode != 0:
        raise AssertionError(f"clone 失败: {(p.stderr or '')[:200]}")
    return dest


def count_md(repo):
    return len(list((Path(repo) / "memory").rglob("*.md")))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="brain-loop-"))
    remote = tmp / "remote.git"
    dev1, dev2 = tmp / "home1", tmp / "home2"
    repo1, repo2 = tmp / "repo1", tmp / "repo2"
    sh(["git", "init", "--bare", "-q", "-b", "main", str(remote)])

    print(f"沙箱: {tmp}\n")

    # ---------------------------------------------------------------- 1 双机基线
    def t1():
        brain(dev1, "init", "--repo", str(remote), "--dir", str(repo1), "--device", "dev1")
        brain(dev1, "add", "--type", "preference", "--title", "基线偏好",
              "--body", "交付先给结论，再给论证。")
        brain(dev2, "init", "--repo", str(remote), "--dir", str(repo2), "--device", "dev2")
        _, out = brain(dev2, "brief")
        assert "基线偏好" in out, "第二台机器看不到第一条记忆"
        assert count_md(repo1) == count_md(repo2), "两机条目数不一致"
        return f"dev1 写入 → dev2 clone 可见，两机各 {count_md(repo1)} 条"

    # ---------------------------------------------------------------- 2 离线写入不丢
    def t2():
        git(repo1, "remote", "set-url", "origin", str(tmp / "no-such-remote.git"))
        rc, out = brain(dev1, "add", "--type", "fact", "--title", "离线写下的一条",
                        "--body", "断网时记录的事实，联网后必须自动补推。")
        assert rc == 0, "离线时 add 失败"
        files = list((repo1 / "memory" / "fact").glob("离线写下的一条-*.md"))
        assert files, "离线写入没有落盘"
        assert git(repo1, "log", "-1", "--pretty=%s"), "离线写入没有本地提交"
        _, st = brain(dev1, "status")
        assert "未同步" in st, "status 输出异常"
        git(repo1, "remote", "set-url", "origin", str(remote))
        brain(dev1, "sync")
        c = fresh_clone(remote, tmp / "verify-offline")
        hit = [p for p in (c / "memory").rglob("*.md") if "离线写下的一条" in p.read_text(encoding="utf-8")]
        assert hit, "恢复网络后没有补推到远端"
        return "断网 add 成功且本地提交 → 联网 sync 补推 → 远端可见"

    # ---------------------------------------------------------------- 3 同秒同名不覆盖
    def t3():
        before = count_md(repo1)
        for i in range(20):
            brain(dev1, "add", "--type", "fact", "--title", "同名并发", "--body",
                  f"第 {i} 条同名内容", "--no-commit", "--tags", "压测")
        brain(dev1, "sync")
        files = sorted((repo1 / "memory" / "fact").glob("同名并发-*.md"))
        assert len(files) == 20, f"20 次同名写入只落了 {len(files)} 个文件"
        shas = {sha(f) for f in files}
        assert len(shas) == 20, "有文件被同名覆盖"
        assert count_md(repo1) == before + 20, "总数不对，疑似覆盖"
        return "20 次同标题写入 → 20 个不同文件、20 份不同内容，0 覆盖"

    # ---------------------------------------------------------------- 4 双机并发不同条目
    def t4():
        brain(dev1, "add", "--type", "fact", "--title", "dev1 并发项", "--body", "A 端事实。")
        brain(dev2, "add", "--type", "fact", "--title", "dev2 并发项", "--body", "B 端事实。")
        brain(dev1, "sync")
        rc2, o2 = brain(dev2, "sync")
        assert "冲突" not in o2, f"并发新增不该冲突: {o2[:200]}"
        brain(dev1, "sync")
        _, out = brain(dev1, "recall", "并发项")
        assert "dev1 并发项" in out and "dev2 并发项" in out, "rebase 后条目不全"
        c = fresh_clone(remote, tmp / "verify-concurrent")
        names = " ".join(p.name for p in (c / "memory").rglob("*.md"))
        assert "dev1-并发项" in names and "dev2-并发项" in names, "远端缺条目"
        return "两端各自提交 → pull --rebase → 两条都在，0 冲突"

    # ---------------------------------------------------------------- 5 同一条目双机修改
    def t5():
        target = sorted((repo2 / "memory" / "fact").glob("dev2-并发项-*.md"))[0]
        rel = target.relative_to(repo2).as_posix()
        # dev1 先改并推送
        brain(dev1, "sync")
        f1 = repo1 / rel
        f1.write_text(f1.read_text(encoding="utf-8") + "\ndev1 追加的一行。\n", encoding="utf-8", newline="\n")
        brain(dev1, "sync")
        # dev2 在旧版本上改同一条，制造真冲突
        target.write_text(target.read_text(encoding="utf-8") + "\ndev2 追加的一行。\n",
                          encoding="utf-8", newline="\n")
        rc, out = brain(dev2, "sync", expect=None)
        rebase_open = (repo2 / ".git" / "rebase-merge").exists() or (repo2 / ".git" / "rebase-apply").exists()
        assert not rebase_open, f"仓库卡在 rebase 中间态（后续所有同步都会失败）: {out[:200]}"
        assert rc == 0, f"同步失败退出码 {rc}: {out[:300]}"
        # 远端必须同时保留两行
        c = fresh_clone(remote, tmp / "verify-conflict")
        blob = " ".join(p.read_text(encoding="utf-8") for p in (c / "memory").rglob("*.md"))
        assert "dev1 追加的一行" in blob, "远端丢了 dev1 的修改"
        assert "dev2 追加的一行" in blob, "远端丢了 dev2 的修改"
        return "同一条目双机改写 → 自动保留双版本（原条目 + conflict 副本），仓库未卡死，0 丢字"

    # ---------------------------------------------------------------- 6 全量恢复
    def t6():
        before = snapshot(repo2)          # repo2 作为对照
        rmtree(repo1)
        brain(dev1, "init", "--repo", str(remote), "--dir", str(repo1), "--device", "dev1")
        after = snapshot(repo1)
        assert before == after, (f"从远端恢复不完整：缺 {len(before - after)} 条，"
                                 f"多 {len(after - before)} 条")
        _, out = brain(dev1, "brief")
        assert len(out) > 500, "恢复后简报为空"
        return f"删掉整个本地仓库 → clone 远端 → {len(after)} 条逐字节一致，简报恢复"

    # ---------------------------------------------------------------- 7 误删：单条可救，批量拦截
    def t7():
        victim = sorted((repo1 / "memory" / "fact").glob("*.md"))[0]
        body = victim.read_text(encoding="utf-8")
        rel = victim.relative_to(repo1).as_posix()
        victim.unlink()
        brain(dev1, "sync")                       # 单条删除不拦截（正常操作）
        git(repo1, "checkout", "HEAD~1", "--", rel)
        assert victim.read_text(encoding="utf-8") == body, "单条误删无法从历史恢复"
        brain(dev1, "sync")
        # 批量删除要拦截
        total = count_md(repo1)
        victims = sorted((repo1 / "memory" / "fact").glob("*.md"))[:3]
        for v in victims:
            v.unlink()
        rc, out = brain(dev1, "sync", expect=None)
        assert rc == 3, f"批量删除未被拦截（退出码 {rc}）"
        assert "已拦截" in out, "无拦截提示"
        git(repo1, "checkout", "--", "memory")
        return f"单条删除 git 可逐字恢复；删 3/{total} 条被拦截（退出码 3）"

    # ---------------------------------------------------------------- 8 归档不进简报
    def t8():
        src = sorted((repo1 / "memory" / "fact").glob("*.md"))[0]
        arch = repo1 / "memory" / "_archive" / "fact" / src.name
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(arch))
        title = re.search(r"^title:\s*(.+)$", arch.read_text(encoding="utf-8"), re.M)
        title = title.group(1).strip() if title else src.stem
        _, brief = brain(dev1, "brief")
        assert title not in brief, f"归档条目仍出现在简报里: {title}"
        _, rec = brain(dev1, "recall", title, "--all")
        assert title in rec or src.stem in rec, "recall --all 查不到归档条目"
        shutil.move(str(arch), str(src))
        return "归档条目在 brief 中消失，recall --all 仍可追溯"

    # ---------------------------------------------------------------- 9 坏文件不炸
    def t9():
        bad = repo2 / "memory" / "fact" / "broken-000000.md"
        bad.write_text("这不是合法的记忆文件，没有 frontmatter。\n", encoding="utf-8", newline="\n")
        rc, out = brain(dev2, "brief")
        assert rc == 0, "一个坏文件就让 brief 崩了"
        assert len(out) > 300, "brief 内容异常"
        rc, st = brain(dev2, "status")
        assert rc == 0, "status 被坏文件搞崩"
        bad.unlink()
        return "非法 frontmatter 文件被跳过，brief / status 正常，其余条目不受影响"

    # ---------------------------------------------------------------- 10 编译幂等
    def t10():
        d1, d2 = tmp / "dist1", tmp / "dist2"
        brain(dev1, "compile", "--target", "all", "--out-dir", str(d1))
        time.sleep(1.1)
        brain(dev1, "compile", "--target", "all", "--out-dir", str(d2))
        a = sorted(p.relative_to(d1) for p in d1.rglob("*") if p.is_file())
        b = sorted(p.relative_to(d2) for p in d2.rglob("*") if p.is_file())
        assert a == b, "两次编译产物文件集不同"
        diff = [str(x) for x, y in zip(a, b) if sha(d1 / x) != sha(d2 / y)]
        assert not diff, f"两次编译字节不一致（含时间戳等易变内容）: {diff}"
        assert len(a) == 6, f"期望 6 个入口，实际 {len(a)}"
        return f"{len(a)} 个入口两次编译逐字节一致（可重复，无漂移）"

    # ---------------------------------------------------------------- 11 入口同源
    def t11():
        d = tmp / "dist1"
        bodies = {}
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            txt = f.read_text(encoding="utf-8")
            body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", txt, flags=re.S)
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
            bodies[f.parent.name] = hashlib.sha256(body.strip().encode()).hexdigest()[:10]
        assert len(set(bodies.values())) == 1, f"各入口正文不同源: {bodies}"
        return f"6 个客户端正文哈希一致（{list(bodies.values())[0]}）"

    # ---------------------------------------------------------------- 12 refresh 不覆盖用户手写内容
    def t12():
        fake_home = tmp / "fakehome"
        (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
        (fake_home / ".codex").mkdir(parents=True, exist_ok=True)
        user_text = "# 我自己的 Claude 规则\n\n- 手写内容，不能被记忆编译覆盖。\n"
        (fake_home / ".claude" / "CLAUDE.md").write_text(user_text, encoding="utf-8", newline="\n")
        (fake_home / ".codex" / "AGENTS.md").write_text("# 我的 Codex 规则\n\n- 保留这一行。\n",
                                                        encoding="utf-8", newline="\n")
        p = sh([str(PY), str(ROOT / "scripts" / "refresh.py")],
               env={"USERPROFILE": str(fake_home), "HOME": str(fake_home)})
        assert p.returncode == 0, f"refresh 失败: {(p.stderr or p.stdout)[:300]}"
        claude = (fake_home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        agents = (fake_home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
        assert "手写内容，不能被记忆编译覆盖" in claude, "refresh 覆盖了用户手写的 CLAUDE.md"
        assert "第二大脑" in claude, "refresh 没把记忆协议写进 CLAUDE.md"
        assert "保留这一行" in agents, "refresh 覆盖了用户手写的 AGENTS.md"
        assert "ai-brain" in agents, "AGENTS.md 里没有写入记忆区块"
        return "已有手写 CLAUDE.md / AGENTS.md → 用户内容保留，记忆区块追加成功"

    # ---------------------------------------------------------------- 13 MCP 协议
    def t13():
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "verify", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "brain_brief", "arguments": {"max_chars": 1500}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "brain_recall", "arguments": {"query": "基线偏好"}}},
        ]
        inp = "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs) + "\n"
        p = sh([str(PY), str(ROOT / "scripts" / "mcp_server.py")],
               env={"BRAIN_HOME": str(dev1)}, input_text=inp, timeout=90)
        lines = [l for l in (p.stdout or "").splitlines() if l.strip()]
        assert len(lines) >= 4, f"MCP 只回了 {len(lines)} 条: {(p.stdout or '')[:200]}"
        msgs = {}
        for l in lines:
            m = json.loads(l)
            if m.get("id") is not None:
                msgs[m["id"]] = m
        assert msgs[1]["result"]["serverInfo"]["name"] == "ai-brain", "initialize 异常"
        names = {t["name"] for t in msgs[2]["result"]["tools"]}
        assert {"brain_brief", "brain_recall", "brain_add", "brain_sync"} <= names, f"工具缺失: {names}"
        brief = msgs[3]["result"]["content"][0]["text"]
        assert "基线偏好" in brief, "MCP brief 返回空/缺内容"
        rec = msgs[4]["result"]["content"][0]["text"]
        assert "基线偏好" in rec, "MCP recall 无结果"
        return f"initialize / tools/list({len(names)} 个) / brief / recall 全部正常"

    # ---------------------------------------------------------------- 14 钩子
    def t14():
        rc, out = brain(dev1, "hook", "start", "--tool", "claude")
        assert rc == 0, "hook start 失败"
        assert "基线偏好" in out, "hook start 没输出简报"
        f = repo1 / "memory" / "fact" / "hook-dirty.md"
        f.write_text("---\nid: fact-hook\ntype: fact\ntitle: 钩子写入\ncreated: 2026-01-01\n---\n钩子测试\n",
                     encoding="utf-8", newline="\n")
        rc, out = brain(dev1, "hook", "stop", "--tool", "claude")
        assert rc == 0, "hook stop 失败"
        assert not git(repo1, "status", "--porcelain"), "hook stop 后仍有未提交变更"
        return "hook start 输出简报；hook stop 自动提交脏文件（退出码 0）"

    # ---------------------------------------------------------------- 真机检查
    def t15():
        _, out = brain(REAL_HOME, "status")
        entries = int(re.search(r"条目总数\s*:\s*(\d+)", out).group(1))
        dirty = re.search(r"未同步\s*:\s*(\d+)", out)
        assert entries > 50, f"真机条目只有 {entries} 条"
        cfg = json.loads((REAL_HOME / "config.json").read_text(encoding="utf-8"))
        repo = Path(cfg["data_repo"])
        git(repo, "fetch", "-q", "origin", expect=None)
        ab = git(repo, "rev-list", "--left-right", "--count", "HEAD...origin/main", expect=None)
        ahead, behind = (ab.split() + ["0", "0"])[:2]
        assert behind == "0", f"本地落后远端 {behind} 个提交（会覆盖别人）"
        assert ahead == "0", f"本地有 {ahead} 个提交没推（尚未闭环）"
        assert dirty and dirty.group(1) == "0", f"有 {dirty.group(1) if dirty else '?'} 项未提交"
        return f"{entries} 条，工作区干净，与远端 0/0 同步"

    def t16():
        cfg = json.loads((REAL_HOME / "config.json").read_text(encoding="utf-8"))
        repo = Path(cfg["data_repo"])
        local = snapshot(repo)
        c = fresh_clone(cfg["remote"], tmp / "verify-real-clone")
        remote_snap = snapshot(c)
        assert local == remote_snap, (f"远端与本地不一致：本地多 {len(local - remote_snap)} 条，"
                                      f"远端多 {len(remote_snap - local)} 条")
        return f"从 GitHub 全新 clone → {len(remote_snap)} 条与本地逐字节一致（灾难可恢复）"

    def t17():
        rc, out = brain(REAL_HOME, "doctor")
        bad = [l for l in out.splitlines() if re.search(r"[✗×]|FAIL|未通过", l)]
        assert rc == 0 and not bad, f"doctor 未全绿: {bad[:3] or out[:300]}"
        ok = len([l for l in out.splitlines() if re.search(r"[✓√]|OK|已", l)])
        return f"doctor 全绿（{ok} 项环境检查通过）"

    def t18():
        cfg = json.loads((REAL_HOME / "config.json").read_text(encoding="utf-8"))
        d = tmp / "real-dist"
        brain(REAL_HOME, "compile", "--target", "all", "--out-dir", str(d))
        fnames = {"claude": "CLAUDE.md", "workbuddy": "SKILL.md", "codex": "AGENTS.md"}
        targets = {
            "claude": Path.home() / ".claude" / "CLAUDE.md",
            "workbuddy": Path.home() / ".workbuddy" / "skills" / "second-brain" / "SKILL.md",
            "codex": Path.home() / ".codex" / "AGENTS.md",
        }
        checked, stale = 0, []
        for key, path in targets.items():
            if not path.exists():
                continue
            fresh = (d / key / fnames[key]).read_text(encoding="utf-8")
            # 只比正文指纹：入口文件里的快照段落是否与最新简报一致
            def body(t):
                t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
                t = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", t, flags=re.S)
                return re.sub(r"\s+", "", t)
            fresh_b = body(fresh)
            cur_b = body(path.read_text(encoding="utf-8"))
            # AGENTS.md 只放协议正文（快照靠 brain brief 现取），比对时也要按同样口径
            cut = fresh_b.find("附：当前记忆快照")
            probe = (fresh_b[:cut] if cut > 0 else fresh_b)[-300:].strip("#")
            checked += 1
            if probe not in cur_b:
                stale.append(str(path))
        assert checked >= 2, "没找到已部署的入口文件"
        assert not stale, f"入口文件落后于记忆库: {stale}"
        return f"{checked} 个已部署入口与最新记忆快照一致（无滞后）"

    print("闭环检查：\n")
    tests = [
        ("1 双机基线可见", t1),
        ("2 离线写入不丢", t2),
        ("3 同名并发不覆盖", t3),
        ("4 双机并发合并", t4),
        ("5 同条冲突不丢字/不卡死", t5),
        ("6 删库后全量恢复", t6),
        ("7 误删可救 + 批量拦截", t7),
        ("8 归档不进简报", t8),
        ("9 坏文件不炸", t9),
        ("10 编译幂等", t10),
        ("11 六入口同源", t11),
        ("12 不覆盖用户手写入口", t12),
        ("13 MCP 协议", t13),
        ("14 钩子闭环", t14),
    ]
    if not QUICK:
        tests += [
            ("15 真机与远端 0/0", t15),
            ("16 远端灾难恢复演练", t16),
            ("17 真机 doctor 全绿", t17),
            ("18 入口文件无滞后", t18),
        ]

    for name, fn in tests:
        check(name, fn)

    ok = sum(1 for r in RESULTS if r[0])
    total = len(RESULTS)
    print(f"\n结果: {ok}/{total} 通过" + ("" if ok == total else "  ← 有失败项"))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
