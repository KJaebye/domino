# GitHub 提交与人工审批

主仓库推送分支和创建 PR 使用本机已登录、具有仓库权限的 GitHub 账号，不要求机器人身份或 GitHub App 配置。2026-11-24 按用户要求取消原先必须由专用 App 推送和创建 PR 的限制。

日常操作：

```sh
gh auth status
git switch -c fix/example
# 修改代码、运行相关检查，使用明确文件列表暂存并提交
git push -u origin HEAD
gh pr create --base main --title 'Describe the change' --body-file /path/to/pr-body.md
```

推送、创建 PR、合并和公开发布分别遵循用户授权；允许推送不代表允许创建 PR 或发布。main 保持至少 1 人审批且无绕过名单。Agent 不代替用户审批，不提前合并，不修改保护规则来规避审批。

GitHub 不允许 PR 作者审批自己的 PR。使用个人账号创建的 PR 应由另一位有权限的审核者审批；不为满足审批要求伪造其他身份或绕过规则。

凭据保存在本机凭据管理器，不写入代码、日志、Git remote 或 GitHub Secrets。旧 `scripts/github_agent.py` 及其依赖文件保留供已有 App 环境显式使用，不再是开发或推送的前置条件；本次不撤销远端 App 或其他电脑的凭据。

此变更不改变 PyPI、Homebrew、APT 的发布凭据，不创建 release tag 或公开发行。
