# Domino

捕获本机代理，一键部署到另一台电脑，让翻墙像 domino 一样简单。

Domino 读取兼容的 Clash/Mihomo 配置，通过 SSH 把节点、规则和必要资源部署为独立服务。目标设备在源电脑关机后仍可使用，也能继续部署下一台。

发行包名是 **domino-proxy**，命令是 **domino**。PyPI 上的 `domino` 属于其他项目。

需要 Python 3.9+。本机服务支持 macOS 与使用 systemd 的 Ubuntu；远端部署需要 SSH、Python、curl，以及普通用户的 sudo 权限。

## 安装与使用

首次在本机使用代理，以普通用户运行：

```bash
pip install domino-proxy && domino-install
```

这条命令先安装管理工具，成功后下载 Mihomo 内核并安装后台服务。已有配置时会保留配置并重启服务。然后准备代理配置：

```bash
domino catch
domino list
domino switch '配置名'
domino start
```

仅管理远端时，只需安装管理工具，不必初始化本机服务：

```bash
pip install domino-proxy
domino user@192.168.1.10
domino user@192.168.1.10 status
domino ui
```

`ui` 提供交互式配置管理、节点选择与检测。`scan` 扫描可导入配置，`test` 并行检测配置的节点连通情况，`traffic` 显示动态流量面板。

## 升级

使用安装时的 Python 环境执行 `python -m pip install --upgrade domino-proxy`。包升级更新 CLI，运行内核与服务由用户单独管理。卸载 CLI 前如需结束本机代理，先运行 `domino stop`；包卸载保留用户配置与服务文件。

[项目首页](https://github.com/KJaebye/domino) · [完整使用指南](https://github.com/KJaebye/domino/blob/main/docs/USAGE.md) · [macOS / Ubuntu 支持](https://github.com/KJaebye/domino/blob/main/docs/PLATFORMS.md) · [分发与迁移](https://github.com/KJaebye/domino/blob/main/docs/DISTRIBUTION.md) · [问题反馈](https://github.com/KJaebye/domino/issues)

Domino 使用独立的 Mihomo 可执行文件；公共 Python 包不包含 Mihomo 内核或用户代理配置。安装核心服务时会按架构获取内核。第三方许可与声明见仓库 NOTICE 和随包文档。

## 许可证

Domino 的原创代码与文档采用 [GNU GPLv3，仅第 3 版](https://github.com/KJaebye/domino/blob/main/LICENSE)（`GPL-3.0-only`）。第三方组件保留各自许可证，详见 [NOTICE](https://github.com/KJaebye/domino/blob/main/NOTICE)。
