# Agent 提交与人工审批

Domino 主仓库使用独立 GitHub App `kjaebye-domino-agent` 提交分支和 PR，
PR 作者显示为 `kjaebye-domino-agent[bot]`。`KJaebye` 使用个人账号审批。
main 保持至少 1 人审批且无绕过名单；Agent 不使用个人账号代替用户审批。

App 仅安装到 `KJaebye/domino`，权限为 Contents 和 Pull requests 读写及
Metadata 只读。没有管理仓库、Secrets 或修改 Actions workflow 文件的权限。
修改 workflow 文件需要另行配置所需权限，不能静默退回个人身份推送。

本机准备：

```sh
.venv/bin/python -m pip install -r scripts/requirements-github-agent.txt
.venv/bin/python scripts/github_agent.py status
```

认证元数据保存在仓库外的 `~/.local/share/domino-agent/state.json`，目录 0700、
文件 0600，包含 `repository`、`app_id`、`client_id`、`installation_id` 和 `slug`。
App 私钥存入 macOS 钥匙串：service 为 `domino-agent/github-app`，username 为
App ID。私钥不提交到 GitHub，不存入 Actions Secrets。新机器需重新安全配置；
丢失私钥时从 GitHub App 设置生成替代密钥，验证后撤销旧密钥。

每次命令从钥匙串读取私钥，签发限定 Domino 的短期 installation token，命令结束
后撤销 token。Token 不写到磁盘或 Git remote，不改变个人 `gh` 登录。

日常提交：

```sh
git switch -c fix/example
# 修改代码，运行相关检查，使用明确文件列表 git add 后提交
.venv/bin/python scripts/github_agent.py push
.venv/bin/python scripts/github_agent.py pr \
  --title 'Describe the change' --body-file /path/to/pr-body.md
```

工具不提供审批或合并命令。PR 创建后交给用户查看并审批，审批前不得合并或绕过规则。
Git 提交作者署名与 PR 创建者是不同概念；是否允许用户审批取决于 PR 的实际创建身份。
此流程不依赖 GitHub Actions 额度，不改变 PyPI、Homebrew、APT 的发布凭据。
