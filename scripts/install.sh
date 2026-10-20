#!/usr/bin/env bash
# ai-brain 安装脚本（macOS / Linux）
# 用法: ./scripts/install.sh [--shim-only]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAIN_PY="$REPO_ROOT/brain.py"
BIN_DIR="$HOME/.ai-brain/bin"
SHIM_ONLY=0

[ "${1:-}" = "--shim-only" ] && SHIM_ONLY=1

command -v python3 >/dev/null || { echo "需要 python3"; exit 1; }
echo "[install] Python: $(python3 --version)"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/brain" <<EOF
#!/usr/bin/env bash
exec python3 "$BRAIN_PY" "\$@"
EOF
chmod +x "$BIN_DIR/brain"
echo "[install] brain 命令 -> $BIN_DIR/brain"

if [ "$SHIM_ONLY" = "1" ]; then
  echo
  echo "把下面一行写进 ~/.zshrc 或 ~/.bashrc："
  echo "  export PATH=\"\$HOME/.ai-brain/bin:\$PATH\""
  exit 0
fi

# 技能目录
install_skill() {
  local dst="$1"
  mkdir -p "$dst"
  cp "$REPO_ROOT/SKILL.md" "$REPO_ROOT/brain.py" "$dst/"
  echo "[install] 技能 -> $dst"
}
[ -d "$HOME/.claude" ] && install_skill "$HOME/.claude/skills/second-brain"
[ -d "$HOME/.workbuddy/skills" ] && install_skill "$HOME/.workbuddy/skills/second-brain"

# 入口文件
backup() { [ -f "$1" ] && cp "$1" "$1.bak.$(date +%Y%m%d%H%M%S)" && echo "          已备份 $1"; }
compile_to() {
  local target="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  backup "$out"
  python3 "$BRAIN_PY" compile --target "$target" --out "$out" >/dev/null
  echo "[install] $target -> $out"
}

if [ ! -f "$HOME/.ai-brain/config.json" ]; then
  echo "[install] 尚未初始化记忆仓库，跳过入口文件生成（初始化后执行 brain compile --target all）"
else
  [ -d "$HOME/.claude" ] && compile_to claude "$HOME/.claude/CLAUDE.md"
  [ -d "$HOME/.codex" ]  && compile_to codex  "$HOME/.codex/AGENTS.md"
  [ -d "$HOME/.cursor" ] && compile_to cursor "$HOME/.cursor/rules/brain.mdc"
  [ -d "$HOME/.gemini" ] && compile_to gemini "$HOME/.gemini/GEMINI.md"
fi

cat <<'EOF'

完成。剩余两步：
  1) export PATH="$HOME/.ai-brain/bin:$PATH"   （写进 shell 配置文件永久生效）
  2) brain init --repo git@github.com:<你>/brain-data.git --device macbook

Claude Code 钩子请手动合并：adapters/claude/hooks.json -> ~/.claude/settings.json
EOF
