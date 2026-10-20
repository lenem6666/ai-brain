# 安全与隐私

记忆库是这个人的**长期画像**：偏好、决策、项目背景、工作习惯。
泄露的后果比一次对话泄露严重得多。以下是硬性边界。

## 1. 仓库必须私有

- GitHub / GitLab / Gitea 仓库一律设为 **private**。
- 只放文本，不放二进制、不放导出文件、不放附件。
- 提交前用 `brain status` 确认变更范围；不确定时先 `git diff`。

## 2. 永远不写进记忆的内容

| 类别 | 例子 |
| --- | --- |
| 凭据 | 密码、API Key、私钥、Token、数据库连接串 |
| 身份证件 | 身份证号、护照号、银行卡号、社保号 |
| 他人隐私 | 客户名单、同事评价、未公开的他人信息 |
| 商业机密 | 未公开合同条款、内部财务数据 |
| 精确位置 | 家庭住址、实时位置（城市级别可以） |

`brain add` 不做自动脱敏——这是刻意的：**判断什么该记，是用户的权力**。
但入口文件里写死了"不写敏感信息"这条规则，模型会主动拒绝记录这类内容。

## 3. 三种存储后端，按隐私要求选

| 方案 | 隐私等级 | 适用 |
| --- | --- | --- |
| GitHub 私有仓库 | 中（信任 GitHub） | 大多数个人使用，最方便 |
| 自建 Gitea / 公司 GitLab | 较高 | 数据不出自己的服务器 |
| 无远端 + 本地同步盘 | 高（不经过第三方 git 服务） | 最敏感的记忆；代价是失去版本历史兜底 |

本地同步盘写法：

```bash
# 记忆库放在同步目录里，去掉远端
brain init --dir "D:/OneDrive/ai-brain-data" --device win-office
git -C "D:/OneDrive/ai-brain-data" remote remove origin 2>/dev/null

# 换电脑时：把同步盘目录路径指过去即可
#   brain init --dir "D:/OneDrive/ai-brain-data" --device macbook
# 注意：OneDrive 同步期间不要同时写入，可能产生 conflicted copy 文件
```

## 4. 加密（可选）

整库加密，适合放公开或半公开的远端：

```bash
# 仓库内
git-crypt init
echo "memory/** filter=git-crypt diff=git-crypt" >> .gitattributes
git-crypt add-gpg-user <你的GPG指纹>
```

单条目加密更细粒度，但会让 LLM 读不到明文（必须解密后才能用），
因此只适合"保存但不常读"的条目，例如账号提示、私密日记。

## 5. 多用户机器

- `~/.ai-brain/data` 权限设为仅本人可读（Windows 上用「属性 → 安全 → 移除继承 → 只留自己」）。
- 共用电脑时不要配置 `git credential.helper store`，用 SSH key + passphrase。
- `brain doctor` 会显示仓库路径与远端，便于确认没有指向共享目录。

## 6. 可审计性

这是本方案相对"App 内置记忆"的核心优势：

```bash
git -C ~/.ai-brain/data log --oneline            # 谁在什么时候写了什么
git -C ~/.ai-brain/data show <commit> -- memory/ # 具体内容
git -C ~/.ai-brain/data log -p memory/preference # 某条偏好的演变史
```

模型不能偷偷改历史——每次写入都是一条 commit，来源记在 `source` 字段（`工具@设备`）。

## 7. 撤销与清理

```bash
# 删一条记忆
rm ~/.ai-brain/data/memory/fact/xxx.md && brain sync -m "remove: xxx"

# 彻底从历史里抹掉（误提交了敏感信息时）
git -C ~/.ai-brain/data filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch memory/fact/xxx.md' --prune-empty -- --all
git -C ~/.ai-brain/data push --force --all
# 之后立刻轮换已泄露的凭据——历史被重写不代表别人没 clone 过
```
