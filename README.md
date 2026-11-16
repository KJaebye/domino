<p align="center">
  <a href="assets/domino-logo.png" title="查看静态 Logo">
    <img src="assets/domino-logo.gif" alt="DOMINO 像素字母从左到右像多米诺骨牌一样依次倒下，再重新立起" width="420">
  </a>
</p>

# Domino

**捕获本机代理，一键部署到另一台电脑，让翻墙像 domino 一样简单。**

[安装](#1-安装) · [快速开始](#快速开始) · [交互管理](#在一个界面里管理配置) · [常用命令](#常用命令) · [完整指南](docs/USAGE.md)

你已经在一台电脑上配好了代理，新服务器却还要重新找订阅、装内核、搬规则、选节点。Domino 把这些步骤收进一条命令：

```bash
domino user@192.168.1.10
```

它读取兼容的 Clash/Mihomo 配置，通过 SSH 在目标设备安装独立的 Mihomo 服务。节点、规则和必要资源一起交付；部署后，源电脑可以关机，目标电脑仍可独立使用，也能继续部署下一台。

## 快速开始

支持 **macOS / Ubuntu**，需要 **Python 3.9+**。

### 1. 安装

```bash
python3 -m venv ~/.venvs/domino
source ~/.venvs/domino/bin/activate
python -m pip install --upgrade domino-proxy
domino --version
```

pip 安装 CLI 和 Python 依赖，**不包含 Mihomo 内核**。首次在本机使用代理时，再运行：

```bash
domino-install
```

安装器会联网下载对应系统和架构的 Mihomo，并配置后台服务。仅管理远端时可跳过这一步。

新开终端后先执行 `source ~/.venvs/domino/bin/activate`，再使用 `domino`。[详细安装说明](docs/DISTRIBUTION.md)

### 2. 准备配置

已有 Clash Verge 或其他兼容配置时：

```bash
domino catch                 # 选择外部配置，捕获到配置库
domino list                  # 查看配置名称
domino switch '配置名'       # 启用其中一份
domino start                 # 开启 Domino，并接通系统代理
```

也可以用 `domino catch all` 一次捕获全部配置，重复内容自动跳过。已有 Domino 时，捕获只保存到配置库，保留当前配置、节点和代理状态。

没有外部配置时，用完整的 Clash/Mihomo HTTPS 订阅添加：

```bash
domino add '主力'            # 隐藏输入订阅地址
domino switch '主力'
domino start
```

### 3. 部署到另一台电脑

目标需要 **Linux、systemd、Python 3.9+、curl、tar**，以及可通过 SSH 登录并使用 sudo 的普通用户。

```bash
domino user@192.168.1.10            # 等同于 domino user@192.168.1.10 deploy
domino user@192.168.1.10 status     # 查看服务与实际代理出网
domino user@192.168.1.10 ui         # 交互管理这台电脑
```

SSH 别名同样可用：`domino my-server deploy`。仅部署远端时，安装 PyPI 管理命令即可，无需先安装本机代理服务；更多选项见 [安装与部署](docs/USAGE.md#开始使用)。

## 在一个界面里管理配置

```bash
domino ui
```

输入 `/list`，配置列表和操作栏同时显示。当前配置用 `●` 标记，选中一份即可切换、更新、重命名、删除、修改订阅地址或检测节点；也能直接添加、捕获配置，或保存当前配置快照。

名称与订阅地址在页内输入，地址隐藏且不进入输入历史。“更新配置”会下载所选配置的最新内容，成功后显示结果并更新列表；操作完成后继续留在管理页。

**鼠标点击**或 **↑↓ 选配置 → Tab 进入操作栏 → ←→ 选动作 → Enter 执行**；Esc 返回，F5 刷新。

其他入口也可以直接回车后选择：

| 输入 | 可以做什么 |
| --- | --- |
| `/select` | 选择策略组与节点，输入关键词筛选 |
| `/test` | 检测全部配置、某个配置或单个节点，实时显示进度 |
| `/traffic` | 打开内嵌动态流量面板，或切换全屏监控 |
| `/mode` | 选择规则、全局或直连模式 |
| `/shell` | 选择终端代理 `on / off / status` |
| `/status` | 查看运行状态、系统代理和实际出网 |

输入 `/` 查看全部命令。退出 UI 后，代理服务继续运行。

## 常用命令

```text
domino [USER@IP] COMMAND [ARGS] [options]
```

本机省略目标；远端把 `USER@IP` 或 SSH 别名放在命令前，例如 `domino my-server test`。

| 用途 | 命令 |
| --- | --- |
| 扫描外部配置与 Domino 配置库 | `domino scan` |
| 捕获一个 / 全部配置 | `domino catch` / `domino catch all` |
| 列出 / 添加 / 切换配置 | `domino list` / `domino add '名称'` / `domino switch '名称'` |
| 更新一个 / 全部在线订阅 | `domino update '名称'` / `domino update all` |
| 重命名 / 删除配置 | `domino rename '旧名' '新名'` / `domino remove '名称'` |
| 当前配置与代理节点 | `domino nodes` |
| 交互选择 / 按关键词选择节点 | `domino select` / `domino select '日本'` |
| 全部配置连通汇总 / 某个配置的节点明细 | `domino test` / `domino test '配置名'` |
| 启动 / 停止 / 检查状态 | `domino start` / `domino stop` / `domino status` |
| 终端使用代理 / 恢复原设置 / 查看状态 | `domino shell on` / `off` / `status` |
| 动态流量 / 全屏流量 | `domino traffic` / `domino traffic --full` |
| 日志级别 / 内核日志 | `domino log` / `domino logs` |

完整参数用 `domino -h` 或 `domino COMMAND -h` 查看。节点名含空格或方括号时加引号；在 UI 中可直接筛选选择。

## 卸载

卸载本机运行环境，并移除 pip 安装的管理命令：

```bash
source ~/.venvs/domino/bin/activate
domino uninstall && python -m pip uninstall domino-proxy
```

卸载远端使用 `domino USER@IP uninstall`；可先加 `--dry-run` 预览。卸载会确认删除内核、配置库和部署备份，并清理 `.bashrc` / `.zshrc` 中 Domino 的接入记录。完成后重新打开终端或重新 SSH 登录。更多说明见 [卸载指南](docs/USAGE.md#卸载与清理)。

## 它如何工作

**发现配置 → 打包配置与依赖 → SSH 交付 → 启动独立服务 → 验证出网。**

外部客户端是只读来源。Domino 为目标准备自己的控制密钥、配置和服务，把 provider 缓存、证书及需要的 Geo 文件一起带走；部署失败时恢复部署前状态。

没有网络下载条件时，也可以先 [导出离线安装包](docs/USAGE.md#无法下载内核时使用离线包)。已部署的 Linux 电脑可使用同一套命令继续部署下一台。

## 支持范围

| 场景 | 当前支持 |
| --- | --- |
| 本机安装与管理 | macOS、使用 systemd 的 Linux；ARM64 / x86_64 |
| 通过 SSH 部署 | 使用 systemd 的 Linux；ARM64 / x86_64 |
| 配置来源 | Clash/Mihomo YAML 或 JSON、完整配置 HTTPS 订阅；自动发现 Clash Verge 保存配置 |
| 系统代理 | macOS、Ubuntu GNOME 桌面；`start / stop` 联动接通与恢复 |
| 无桌面 Linux | 运行独立服务，终端应用通过 `shell` 或本地代理地址使用 |

默认代理地址是 `http://127.0.0.1:17897`，控制端口是 `19091`。终端代理由 `domino shell` 独立管理；已接入的终端在返回命令行后同步。

Domino 需要有效的节点配置，不提供订阅，也不能仅凭一个代理端口复制专用客户端的登录状态。默认只监听本机回环地址，不开启 TUN 或接管默认路由。导出的配置包包含节点凭据，请妥善保管。

## 文档与开发

| 文档 | 内容 |
| --- | --- |
| [使用指南](docs/USAGE.md) | 捕获与去重、资源路径、配置管理、离线部署、代理开关、排查与恢复 |
| [Agent 接口](docs/AGENT.md) | JSON 协议、能力发现、结构化操作与错误码 |
| [架构与路线](docs/ARCHITECTURE.md) | 项目边界、组件划分与后续规划 |
| [开发与交付](docs/DELIVERY.md) | 聚焦测试、版本管理、构建和资源分发 |
| [版本记录](CHANGELOG.md) | 已完成的功能与修复 |
| [平台支持](docs/PLATFORMS.md) | macOS、Ubuntu Desktop / Server 的依赖与验证边界 |
| [参与开发](CONTRIBUTING.md) | 开发环境、测试和提交约定 |
| [安全反馈](SECURITY.md) | 私密报告入口与脱敏要求 |

开发环境可用 `python3 -m venv .venv`，再运行 `.venv/bin/python -m pip install -e .`。测试按改动范围运行；完整交付流程见开发文档。

欢迎通过 [Issues](https://github.com/KJaebye/domino/issues) 反馈可复现的问题。请隐去订阅地址、控制密钥和节点凭据。

## 许可证

Domino 的原创代码与文档采用 **[GNU GPLv3，仅第 3 版](LICENSE)**（`GPL-3.0-only`）。允许使用、修改和商用；分发原版或衍生作品时须遵守相应的源码提供、许可证保留等条款。

Mihomo 与其他第三方组件保留各自的许可证，见 [第三方声明](NOTICE)。
