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

### Clash Verge 配置发现

`domino scan` 扫描当前用户，`domino USER@IP scan` 扫描远端登录用户；不会将发起端的配置算入目标机。外部配置捕获或添加到 Domino 后，才计入「Domino 管理」。不要使用 `sudo domino scan` 扫描普通用户的配置。

扫描和捕获支持以下标准目录中的 `clash-verge.yaml` 与 `profiles.yaml` 索引关联的保存配置：

- Clash Verge Rev：macOS 的 `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev`；Ubuntu 的 `${XDG_DATA_HOME:-~/.local/share}/io.github.clash-verge-rev.clash-verge-rev`。
- 旧版 Clash Verge：`~/.config/clash-verge`，可通过绝对路径的 `XDG_CONFIG_HOME` 指定配置根目录。
- Clash / Mihomo：`~/.config/clash/config.yaml`、`~/.config/mihomo/config.yaml`，也支持 `.yml` 后缀和 `XDG_CONFIG_HOME`。

目录约定参考客户端源码：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.4/src-tauri/src/utils/dirs.rs)、[旧版 Clash Verge](https://github.com/zzzgydi/clash-verge/blob/main/src-tauri/src/utils/dirs.rs)。自定义或便携目录可使用 `domino [USER@IP] scan --source '配置文件路径'` 显式检查。

### ClashX 与 v2rayN

ClashX 扫描 `~/.config/clash/` 下的多份 `.yaml` / `.yml` 配置，也覆盖 `XDG_CONFIG_HOME` 的 Clash 目录。该目录也被其他 Clash 客户端使用，因此来源标为「ClashX / Clash」。除默认 `config.yaml` / `config.yml` 外，保存项不假定为当前加载配置，也不检查保存端口。参见 [ClashX 目录实现](https://github.com/MetaCubeX/ClashX.Meta/blob/master/ClashX/Macro/Paths.swift)。

v2rayN 扫描常见数据目录下的 `guiConfigs/guiNDB.db`：macOS 的 `~/Library/Application Support/v2rayN`、Ubuntu 的 `~/.local/share/v2rayN`，以及 `~/.config/v2rayN`、`~/v2rayN`、常见 app 与 `/opt/v2rayN` 安装目录；支持相应 XDG 根目录。旧版只有 `guiNConfig.json` 时读取其中的节点列表，新版设置文件不重复计数。便携或自定义目录可显式指定：

```bash
domino scan --source '/path/to/v2rayN/guiConfigs/guiNDB.db'
domino catch --source '/path/to/v2rayN/guiConfigs/guiNDB.db'
```

整份节点库导入为**一个节点快照配置**，优先排列可识别的当前节点。支持常见 VMess、VLESS / Reality、Shadowsocks、SOCKS、HTTP、Trojan、Hysteria2、TUIC、AnyTLS 节点，以及 TCP、WebSocket、gRPC。**不迁移 v2rayN 分流、DNS、订阅更新或客户端设置**。含自定义配置、链式代理、XHTTP / KCP 等不支持项目时，扫描显示原因，整份来源不导入，不静默丢弃节点。数据库和 WAL 先复制到私有临时目录再读取，不改动原文件或检查保存端口。再次 `catch` 可获取本地节点变化；在线更新仍需兼容的完整 Clash/Mihomo 订阅地址。

格式依据：[v2rayN 路径实现](https://github.com/2dust/v2rayN/blob/master/v2rayN/ServiceLib/Common/Utils.cs)、[数据库实现](https://github.com/2dust/v2rayN/blob/master/v2rayN/ServiceLib/Helper/SqliteHelper.cs)、[节点字段](https://github.com/2dust/v2rayN/blob/master/v2rayN/ServiceLib/Models/Entities/ProfileItem.cs)。CLI、本机 / SSH 和 UI 使用同一适配器。

### 系统依赖

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
