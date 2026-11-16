# macOS 与 Ubuntu

[返回首页](../README.md) · [使用指南](USAGE.md) · [开发与交付](DELIVERY.md)

## 支持边界

| 能力 | macOS | Ubuntu Desktop / GNOME | Ubuntu Server |
| --- | --- | --- | --- |
| 本机安装、CLI、UI、配置库 | 支持 | 支持 | 支持 |
| 后台服务 | 当前用户 LaunchAgent | systemd | systemd |
| start / stop 系统代理联动 | 当前网络服务 | 当前用户 GNOME 会话 | 明确显示无桌面系统代理 |
| shell on / off / status | Bash / Zsh | Bash / Zsh | Bash / Zsh |
| SSH 远程管理已有 Domino | 支持 | 支持 | 支持 |
| 作为一键 SSH 部署目标 | 尚未开放 | 支持 | 支持 |
| 从当前电脑部署下一台 Linux | 支持 | 支持 | 支持 |

内核支持 ARM64 和 x86_64。默认代理端口 `17897`、控制端口 `19091`；均监听回环地址。macOS 服务随用户登录启动，退出登录后停止；Ubuntu 的 systemd 服务随系统启动。

## 安装依赖

macOS 需要 Python 3.9+（含 pip 和 venv）、curl；跨设备部署还需要 OpenSSH 客户端。使用普通登录用户运行安装脚本，LaunchAgent 不需要 sudo。可通过 python.org 或自己的包管理器安装 Python。

Ubuntu 22.04 / 24.04 / 26.04 的基础依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl openssh-client sudo git tar
git clone https://github.com/KJaebye/domino.git
cd domino
./install.sh
```

安装和服务管理使用具备 sudo 权限的普通用户，不直接使用 root。`--batch` 禁止认证提示，要求已有所需权限。

GNOME 桌面代理通过 GSettings 和当前用户 D-Bus 会话设置 HTTP、HTTPS、SOCKS，恢复时保留其他程序后续修改。没有桌面会话时照常运行服务，终端应用使用 `domino shell on`；不写入 `/etc/environment` 或 APT 代理设置。

## 持续验证

CI 固定使用 Ubuntu 22.04、24.04、26.04 和 macOS 15 的 Intel / Apple Silicon runner，避免 `latest` 标签变动。覆盖 Python 3.9 最低兼容版本以及 Ubuntu 自带的主流 Python 版本；Ubuntu ARM64 也有单独任务。

每个任务检查仓库、运行完整回归与临时 Mihomo 集成、构建 wheel/runtime，并在临时 HOME 与源码目录外执行产物冒烟。Ubuntu 还在临时 HOME、新 D-Bus 会话和独立 dconf 数据库中验证真实 GSettings 的应用与恢复，不修改真实桌面。

这些检查不会替代真实桌面的人工验收。发布前还应在可用的 macOS 和 Ubuntu GNOME 设备确认系统设置面板、开关恢复与登录自启；无桌面 Ubuntu 验证 systemd、自启和 shell。以本轮生成的验证报告及 GitHub Actions 结果为准，不将工作流配置本身视为已通过。

当前本机报告位于 `dist/verification.json`、`dist/artifact-verification.json` 和 `dist/repository-verification.json`，不随源码提交。测试核心必须通过 `DOMINO_TEST_CORE` 显式指定；不会默认读取正在使用的安装。
