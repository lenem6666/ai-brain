#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py — ai-brain 的可执行验收脚本。

不依赖 pytest，直接 python scripts/validate.py 跑完 8 项检查。
全程在临时目录里进行，不会碰你真实的 ~/.ai-brain。

用法:
    python scripts/validate.py [-v]

退出码: 0 全部通过；1 有失败。
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
VERBOSE = "-v" in sys.argv

RESULTS = []


def sh(cmd, env=None, cwd=None, timeout=180):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, env=e, cwd=cwd, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")


def brain(home, *args, expect=0):
    """调用 brain.py，返回 (returncode, stdout+stderr)。"""
    p = sh([sys.executable, str(BRAIN), *args], env={"BRAIN_HOME": str(home)})
    out = (p.stdout + p.stderr).strip()
    if VERBOSE:
        print(f"    $ brain {' '.join(args)}\n      {out[:400]}")
    if expect is not None and p.returncode != expect:
        raise AssertionError(f"期望退出码 {expect}，实际 {p.returncode}: {out[:300]}")
    return p.returncode, out


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        RESULTS.append((True, name, detail, time.time() - t0))
        print(f"  PASS  {name}  —  {detail}")
    except Exception as e:
        RESULTS.append((False, name, str(e), time.time() - t0))
        print(f"  FAIL  {name}  —  {e}")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="brain-validate-"))
    remote = tmp / "remote.git"
    dev1, dev2 = tmp / "home1", tmp / "home2"
    repo1 = tmp / "repo1"
    repo2 = tmp / "repo2"

    print(f"工作目录: {tmp}\n")
    sh(["git", "init", "--bare", "-b", "main", str(remote)])

    # ---------------------------------------------------------------- 1 读写闭环
    def t1():
        brain(dev1, "init", "--repo", str(remote), "--dir", str(repo1), "--device", "dev1")
        brain(dev1, "add", "--type", "preference", "--title", "默认中文",
              "--body", "所有交付物用简体中文，先结论后论证。", "--tags", "写作")
        rc, out = brain(dev1, "brief")
        assert "默认中文" in out, "简报里没有刚写入的条目"
        assert "身份与硬规则" in out, "简报缺少身份区"
        return "add → brief 立即可见，条目进入身份与硬规则区"

    # ---------------------------------------------------------------- 2 跨设备
    def t2():
        brain(dev2, "init", "--repo", str(remote), "--dir", str(repo2), "--device", "dev2")
        rc, out = brain(dev2, "brief")
        assert "默认中文" in out, "第二台设备看不到第一台的记忆"
        return "全新 clone 后简报含 dev1 写入的条目"

    # ---------------------------------------------------------------- 3 并发合并
    def t3():
        brain(dev1, "add", "--type", "fact", "--title", "dev1 并发", "--body", "A")
        brain(dev2, "add", "--type", "fact", "--title", "dev2 并发", "--body", "B")
        rc1, o1 = brain(dev1, "sync")
        rc2, o2 = brain(dev2, "sync")
        brain(dev1, "sync")
        rc, out = brain(dev1, "status")
        assert "fact" in out and "4" not in "", "状态异常"
        rc, brief = brain(dev1, "brief")
        assert "dev1 并发" in brief or "dev2 并发" in brief
        brain(dev1, "sync")
        rc, recall = brain(dev1, "recall", "并发")
        assert "dev1 并发" in recall and "dev2 并发" in recall, "合并后条目不全"
        assert "冲突" not in o2, f"出现冲突: {o2[:200]}"
        return "两端各自离线新增 → rebase 合并，两条都在"

    # ---------------------------------------------------------------- 4 版本回退
    def t4():
        target = next((repo1 / "memory" / "preference").glob("*.md"))
        before = target.read_text(encoding="utf-8").replace("\r\n", "\n")
        target.write_text(before + "\n被 AI 改坏了的一句话。\n", encoding="utf-8", newline="\n")
        brain(dev1, "sync", "-m", "bad edit")
        after_bad = target.read_text(encoding="utf-8")
        assert "被 AI 改坏了" in after_bad, "修改未生效"
        sh(["git", "checkout", "HEAD~1", "--", str(target.relative_to(repo1))], cwd=repo1)
        restored = target.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert restored == before, "回退后内容与原文不一致"
        assert "被 AI 改坏了" not in restored, "坏内容仍在"
        return "改坏 → 提交 → checkout HEAD~1，正文逐字恢复"

    # ---------------------------------------------------------------- 5 误删拦截
    def t5():
        entries = sorted((repo1 / "memory").rglob("*.md"))
        total = len(entries)
        victims = [e for e in entries if e.parent.name in ("fact", "preference")][:3]
        assert victims, "没有可删的测试条目"
        for v in victims:
            v.unlink()
        ratio = len(victims) / total
        should_block = len(victims) >= 3 or ratio >= 0.3
        assert should_block, f"测试设计错误：删 {len(victims)}/{total}"
        rc, out = brain(dev1, "sync", expect=None)
        assert rc == 3, f"期望被拦截(退出码3)，实际 {rc}: {out[:200]}"
        assert "已拦截" in out, "没有拦截提示"
        rc, out = brain(dev1, "sync", "--force", expect=0)
        assert "已放行" in out, "--force 未放行"
        return f"删 {len(victims)}/{total} 条（{ratio:.0%}）→ 拦截(退出码3)；--force 放行"

    # ---------------------------------------------------------------- 6 裸文件可读
    def t6():
        # 完全不调用 brain.py：只用标准库解析 memory/*.md
        md = repo1 / "memory"
        entries = []
        for p in md.rglob("*.md"):
            txt = p.read_text(encoding="utf-8")
            m = re.match(r"\A---\s*\n(.*?)\n---", txt, re.S)
            assert m, f"{p.name} 缺少 frontmatter"
            meta = dict(
                (k.strip(), v.strip())
                for k, v in (line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
            )
            assert meta.get("type"), f"{p.name} 缺少 type"
            entries.append(meta)
        rc, out = brain(dev1, "status")
        counted = int(re.search(r"条目总数\s*:\s*(\d+)", out).group(1))
        assert len(entries) == counted, f"裸解析 {len(entries)} 条 ≠ brain 统计 {counted} 条"
        return f"零依赖解析 {len(entries)} 条，与 brain status 一致（无 Python 也能读）"

    # ---------------------------------------------------------------- 7 入口一致性
    def t7():
        dist = tmp / "dist"
        brain(dev1, "compile", "--target", "all", "--out-dir", str(dist))
        bodies = {}
        for f in dist.rglob("*"):
            if not f.is_file():
                continue
            txt = f.read_text(encoding="utf-8")
            body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", txt, flags=re.S)
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
            bodies[f.parent.name] = hashlib.sha256(body.strip().encode()).hexdigest()[:12]
        assert len(bodies) == 6, f"期望 6 个目标，实际 {len(bodies)}"
        uniq = set(bodies.values())
        assert len(uniq) == 1, f"各入口文件正文不一致: {bodies}"
        return f"6 个客户端入口正文同源（body sha {list(uniq)[0]}）"

    # ---------------------------------------------------------------- 8 无绝对路径
    def t8():
        bad = []
        pat = re.compile(r"[A-Za-z]:[\\/]|/Users/|/home/[a-z]")
        for p in (repo1 / "memory").rglob("*.md"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    bad.append(f"{p.name}:{i}")
        assert not bad, f"记忆文件里出现本机绝对路径: {bad[:5]}"
        return "memory/*.md 不含本机绝对路径（换机可原样读取）"

    print("运行检查：\n")
    t_all = time.time()
    for name, fn in [
        ("1 读写闭环", t1),
        ("2 跨设备可见", t2),
        ("3 并发写入合并", t3),
        ("4 版本回退", t4),
        ("5 误删拦截", t5),
        ("6 零依赖可读", t6),
        ("7 入口文件同源", t7),
        ("8 无绝对路径", t8),
    ]:
        check(name, fn)

    ok = sum(1 for r in RESULTS if r[0])
    print(f"\n结果: {ok}/{len(RESULTS)} 通过，用时 {time.time() - t_all:.1f}s")
    if ok != len(RESULTS):
        print("\n失败项：")
        for good, name, detail, _ in RESULTS:
            if not good:
                print(f"  - {name}: {detail}")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
