# 记忆蒸馏（brain distill）

记忆不是越积越好。日志、临时决策、被推翻的方案会不断堆积，最后把简报挤出有效信息。
`brain distill` 干的就是「体检 + 精简」：找出重复、过时、过长的条目，合并成更少更准的条目。

## 为什么需要它

| 问题 | 后果 |
| --- | --- |
| 同主题多条并存 | 简报里出现互相矛盾的偏好，AI 只能猜 |
| 日志长期不提炼 | 占了上下文预算，却不含结论 |
| 已废止条目留在原位 | recall 命中过时规则 |
| 一条几千年（超长条目） | 挤掉其他记忆的展示机会 |

## 三个动作

```bash
brain distill                  # 体检：只读，输出报告
brain distill --task           # 体检 + 生成给 AI 的任务包
brain distill --apply plan.json  # 按计划执行合并/改写/归档
```

体检会写两个文件到 `<记忆库>/distill/`（该目录自带 `.gitignore`，不进版本库）：

- `report-YYYYMMDD.md` — 人看：每组候选有多少字、多久没动
- `task-YYYYMMDD.md` — AI 看：候选清单 + 硬规则 + 输出格式

## 五类候选

| 类型 | 判定 | 建议动作 |
| --- | --- | --- |
| `same-title` | 标题归一化后相同 | 合并（通常是同一件事的演进） |
| `near-dup` | 词集 Jaccard ≥ 0.45 且正文相似度 ≥ 阈值（默认 0.72） | 合并 |
| `stale-journal` | `journal` 且超过 `--days`（默认 30）天 | 提炼成 preference / decision / skill |
| `retired` | 带 `已废止` / `已合并` 标签 | 归档 |
| `too-thin` | 正文不足 15 字 | 补全或归档 |

先用词集快速筛，再对少量候选算 `difflib` 相似度，避免 O(n²) 全量比较。

## 计划格式

```json
{
  "merges": [
    {"type": "decision", "title": "合并后的标题", "body": "≤400 字正文",
     "tags": ["标签"], "absorb": ["id1", "id2"], "keep": "id1"}
  ],
  "update": [{"id": "id", "title": "可选", "body": "改写后的正文"}],
  "archive": ["id3", "id4"]
}
```

- `keep` 有值：就地改写这条（保留 `created` 与来源），其余 `absorb` 标记 `superseded_by`
- `keep` 为空：新建一条，`absorb` 全部标记已合并
- `absorb` 的条目**不删除**，加 `superseded_by: <新 id>` 和 `已合并` 标签，不进简报但仍可 recall
- `archive` 的条目**不删除**，移动到 `memory/_archive/<type>/`，加 `status: archived`

## 安全边界

1. **不改写你没批准的内容。** `--apply` 只执行 JSON 里点名的条目，范围外一律不动。
2. **不物理删除。** 合并是加标记，归档是移动；正文全部留在 git 历史里。
3. **归档绕过误删拦截。** 归档本身是计划内批量移动，`apply` 内部以 `force` 提交；正常 `brain sync` 的拦截仍然生效。
4. **计划可审。** 合并后的正文就是要写进记忆的文字，执行前应当人看一眼——这正是 `--task` 与 `--apply` 分离的原因。

## 实测（93 条记忆）

| 指标 | 数值 |
| --- | --- |
| 体检耗时 | < 1 秒 |
| 查出候选组 | 5 组（4 组标题冲突 + 12 条已废止） |
| 合并 2 条 → 1 条 | 保留条目正文 300 字，被吸收条目标记 `已合并` + `superseded_by` |
| 归档 2 条 | 移入 `_archive/decision/`、`_archive/journal/`，`brief` 不再出现 |
| 简报是否受影响 | 被合并条目消失，新标题出现；归档条目不再命中 |
| `recall` 默认 | 不返回归档条目；`recall --all` 可翻出 |

## 建议节奏

- 每次 `brain sync` 后不必蒸馏；**每月一次**，或条目数超过 80 时做一次
- 只在「同主题已经出现多条」时合并，不要为了整齐强行归并
- 蒸馏完一定要跑 `python scripts/refresh.py`，否则入口文件里还是旧快照
