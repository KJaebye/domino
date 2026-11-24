# Domino 1.3.0 发布说明

本版本已于 2026-11-24 正式发布，固定标签为 [v1.3.0](https://github.com/KJaebye/domino/releases/tag/v1.3.0)，源码提交为 `c3963b8`。GitHub Release、PyPI、Homebrew tap 和自建签名 APT 已更新，发布核验记录见[分发指南](DISTRIBUTION.md)。PyPI 包名继续为 `domino-proxy`，CLI 版本为 `1.3.0`，发行许可证为 GPL-3.0-only。

## 相比 1.2.3

- 默认界面语言改为英文，保留已保存的偏好，使用 `domino language zh` 切换中文。
- macOS 使用独立应用身份启动原 Mihomo 内核，支持本地网络授权和失败恢复；修复服务重启时任务尚未卸载的时序问题。
- macOS Intel 明确选择 amd64-v1 内核包，兼容未提供 v3 指令集的处理器。
- 改善公司内网域名解析：使用目标系统 DNS 与系统 hosts，不更改系统 DNS 或监听 DNS 端口。
- 精简状态、扫描、配置和安装结果，详细路径与诊断放在 `--verbose`；保留未检测、失败、部分成功及恢复不完整的区别。
- 改善扫描来源选择提示，关闭终端策略后显示实际保留的代理地址；统一中英文对齐和输出空白。
- macOS 默认使用 Zsh、Ubuntu/Linux 默认使用 Bash；保留另一种 shell 的既有配置及补全。
- 支持从自托管 CI 审核并导入固定源码对应的原始发行包，复用 `.deb` 字节生成签名 APT 索引；正式发布保留维护者确认。

完整变更见 [CHANGELOG](../CHANGELOG.md)。

## 安装与升级

在原安装环境中，按所用渠道升级：

```sh
pip install --upgrade domino-proxy==1.3.0
brew update && brew upgrade KJaebye/tap/domino
sudo apt update && sudo apt install domino-proxy=1.3.0-1
```

Homebrew 与 APT 需要先配置已有 tap/签名源，见 [分发指南](DISTRIBUTION.md)。普通升级只更新 CLI，不自动切换配置、节点、终端策略或重启服务。

## 验证边界

2026-11-22 已完成 Mac 公司现场 DIRECT、证书校验与重启验收；这不是每个后续源码提交的全量证明。固定发布源码的渠道校验和隔离安装结果见[分发指南](DISTRIBUTION.md)。

自托管 CI 的 Ubuntu x86_64 容器测试不代表 Ubuntu 主机 systemd、GNOME 桌面或 ARM64 的真实安装通过。最新源码的 Ubuntu 真机验收仍待完成，不扩大平台支持声明。
