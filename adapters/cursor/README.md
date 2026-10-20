# Cursor 适配

**能力等级：自动读（alwaysApply 规则）+ 指令驱动写**

## 安装

```bash
# 全局规则（所有项目生效）
brain compile --target cursor --out ~/.cursor/rules/brain.mdc

# 或项目级
brain compile --target cursor --out ./.cursor/rules/brain.mdc --project 项目名
```

## 说明

- 生成的 `.mdc` 带 `alwaysApply: true`，每个会话都会加载，无需手动 `@` 引用。
- 规则文件体积会随记忆增长，建议保持 `--brief-chars 3500` 左右的预算；
  记忆条目多时，`brief` 只列索引，细节由 `brain recall` 按需拉取。
- Cursor 的 Agent 模式可执行终端命令，因此读写都可用；Composer 模式只能读规则，
  此时让它输出"记忆补丁"，由你手动 `brain add`。

## 建议

把 `~/.cursor/rules/brain.mdc` 加进一个 dotfiles 仓库统一管理，
换电脑时和其他工具配置一起恢复。
