# Domino

捕获本机代理，一键部署到另一台电脑，让翻墙像 domino 一样简单。

Domino 读取兼容的 Clash/Mihomo 配置，通过 SSH 把节点、规则和必要资源部署为独立服务。目标设备在源电脑关机后仍可使用，也能继续部署下一台。

发行包名是 **domino-proxy**，命令是 **domino**。PyPI 上的 `domino` 属于其他项目。

需要 Python 3.9+。本机服务支持 macOS 与使用 systemd 的 Ubuntu；远端部署需要 SSH、Python、curl，以及普通用户的 sudo 权限。

## 安装与使用

```bash
python3 -m venv ~/.venvs/domino
~/.venvs/domino/bin/python -m pip install domino-proxy
~/.venvs/domino/bin/domino --help
```

包安装只提供 CLI，不启动服务、不更改系统或终端代理。需要本机代理时，以普通用户显式初始化：

```bash
~/.venvs/domino/bin/domino-install
~/.venvs/domino/bin/domino catch
~/.venvs/domino/bin/domino list
~/.venvs/domino/bin/domino switch '配置名'
~/.venvs/domino/bin/domino start
```

仅管理远端时不必初始化本机服务：

```bash
~/.venvs/domino/bin/domino user@192.168.1.10
~/.venvs/domino/bin/domino user@192.168.1.10 status
~/.venvs/domino/bin/domino ui
```

`ui` 提供交互式配置管理、节点选择与检测。`scan` 扫描可导入配置，`test` 并行检测配置的节点连通情况，`traffic` 显示动态流量面板。

## 升级

在同一 venv 中执行 `python -m pip install --upgrade domino-proxy`。包升级更新 CLI，运行内核与服务由用户单独管理。卸载 CLI 前如需结束本机代理，先运行 `domino stop`；包卸载保留用户配置与服务文件。

[项目首页](https://github.com/KJaebye/domino) · [完整使用指南](https://github.com/KJaebye/domino/blob/main/docs/USAGE.md) · [macOS / Ubuntu 支持](https://github.com/KJaebye/domino/blob/main/docs/PLATFORMS.md) · [分发与迁移](https://github.com/KJaebye/domino/blob/main/docs/DISTRIBUTION.md) · [问题反馈](https://github.com/KJaebye/domino/issues)

Domino 使用独立的 Mihomo 可执行文件；公共 Python 包不包含 Mihomo 内核或用户代理配置。安装核心服务时会按架构获取内核。第三方许可与声明见仓库 NOTICE 和随包文档。
