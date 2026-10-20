#!/usr/bin/env python3
"""记忆更新后，把最新快照重新编译进各客户端入口文件。

做四件事：
1. ~/.claude/CLAUDE.md                （Claude Code 每次会话自动读）
2. <技能目录>/SKILL.md                （WorkBuddy + Claude 技能）
3. ~/.codex/AGENTS.md 里的 ai-brain 区块（只替换块内内容，保留你原有规则）
4. 打印机检结果

用法: python refresh.py
"""
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
# 从脚本位置推导安装根目录，换机克隆到任意路径都能用
BRAIN = Path(__file__).resolve().parent.parent
PY = (BRAIN / "runtime" / "python.exe") if (BRAIN / "runtime" / "python.exe").exists() else Path(sys.executable)
BRAIN_PY = BRAIN / "brain.py"

# Windows 控制台默认 GBK：保留默认编码（中文能编码），只是别因个别符号崩溃
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
BLOCK_RE = re.compile(r"\n*<!-- >>> ai-brain.*?<!-- <<< ai-brain <<< -->\n", re.S)
SIG = "<!-- 本文件由 ai-brain 自动生成"
START = "<!-- >>> ai-brain >>> -->"
END = "<!-- <<< ai-brain <<< -->"


def write_entry(path, text):
    """写客户端入口文件：已有内容绝不整体覆盖。

    - 文件不存在 → 整份写入（带区块标记）
    - 已有本工具区块 → 只替换块内，块外原样保留
    - 是历史版本整份生成的文件（带自动生成签名）→ 整份重写
    - 用户自己的文件 → 追加区块，原文一字不动
    """
    path = Path(path)
    block = f"{START}\n{text.rstrip()}\n{END}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8", newline="\n")
        return "新建"
    cur = path.read_text(encoding="utf-8")
    if START in cur and END in cur:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", block, cur, flags=re.S)
        mode = "替换区块"
    elif SIG in cur:
        new = block
        mode = "整份重写"
    else:
        new = cur.rstrip() + "\n\n" + block
        mode = "追加区块（保留原文）"
    if new != cur:
        path.write_text(new, encoding="utf-8", newline="\n")
    return mode


def skill_dirs():
    """技能落点：不写死某台机器的路径，按 环境变量 → 用户目录 → 旧路径 依次探测"""
    cands = []
    wb = os.environ.get("WORKBUDDY_HOME")
    if wb:
        cands.append(Path(wb) / ".workbuddy" / "skills" / "second-brain")
    cands.append(HOME / ".workbuddy" / "skills" / "second-brain")
    cands.append(HOME / ".claude" / "skills" / "second-brain")
    legacy = Path(r"D:/WorkBuddy/.workbuddy/skills/second-brain")
    if legacy.parent.exists():
        cands.append(legacy)
    out = []
    seen = set()
    for c in cands:
        key = os.path.realpath(c).lower()   # WorkBuddy 的技能目录常是 junction，按实体去重
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


SKILL_DIRS = skill_dirs()


def run(*args):
    env = dict(os.environ, BRAIN_HOME=str(BRAIN), PYTHONUTF8="1")
    r = subprocess.run([str(PY), str(BRAIN_PY), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        print(f"  失败: {' '.join(args)}\n  {r.stderr.strip()[:300]}")
    return r.returncode == 0


def render(target):
    """编译到临时文件并返回文本"""
    tmp = BRAIN / f".refresh-{target}.md"
    if not run("compile", "--target", target, "--out", str(tmp)):
        return None
    txt = io.open(tmp, encoding="utf-8").read()
    tmp.unlink(missing_ok=True)
    return txt


def main():
    cfg = BRAIN / "config.json"
    if not cfg.exists():
        print("还没初始化记忆库，先执行：")
        print(f'  "{PY}" "{BRAIN_PY}" init --repo <私有仓库地址> --device <机器名>')
        return 2

    ok, skipped = [], []

    # 1) Claude Code
    claude_cfg = HOME / ".claude"
    if claude_cfg.exists():
        txt = render("claude")
        if txt:
            mode = write_entry(claude_cfg / "CLAUDE.md", txt)
            ok.append(f"CLAUDE.md（{len(txt)} 字符，{mode}）")
        else:
            skipped.append("CLAUDE.md")
    else:
        skipped.append("Claude Code（未安装）")

    # 2) 技能
    txt = render("workbuddy")
    if txt:
        deployed = False
        for d in SKILL_DIRS:
            # 只有父级（客户端目录）存在才部署，避免给没装的工具造目录
            parent = d.parent if d.name == "second-brain" else d
            if not parent.exists():
                continue
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(txt, encoding="utf-8", newline="\n")
            shutil.copy2(BRAIN_PY, d / "brain.py")
            ok.append(f"技能 {d}")
            deployed = True
        if not deployed:
            skipped.append("技能（未检测到客户端技能目录）")

    # 3) Codex：只替换块，保留原有规则
    agents = HOME / ".codex" / "AGENTS.md"
    if agents.exists():
        full = render("codex") or ""
        cut = full.find("## 附：当前记忆快照")
        core = full[:cut].rstrip() if cut != -1 else full.rstrip()
        block = ("\n\n<!-- >>> ai-brain 第二大脑（自动生成，勿手改；改记忆用 brain add） >>> -->\n"
                 "> **本节优先于上文任何 Obsidian 记忆规则。** 记忆已迁移到 ai-brain，\n"
                 "> 开场读 `brain brief`，不要再读 `D:\\Codex\\Obsidian\\CodexMemory\\_index.md`。\n"
                 "> 上文的 Obsidian 段落仅作历史保留。\n\n"
                 + core + "\n<!-- <<< ai-brain <<< -->\n")
        old = io.open(agents, encoding="utf-8").read()
        new = BLOCK_RE.sub("", old).rstrip() + block if BLOCK_RE.search(old) else old.rstrip() + block
        io.open(agents, "w", encoding="utf-8", newline="\n").write(new)
        ok.append(f"AGENTS.md（{len(new.splitlines())} 行）")
    else:
        skipped.append("Codex（未安装）")

    print("已刷新：")
    for x in ok:
        print("  [ok]", x)
    if skipped:
        print("未处理：")
        for x in skipped:
            print("  [-]", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
