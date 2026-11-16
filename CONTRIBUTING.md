# 参与开发

Domino 面向 macOS 和 Ubuntu，使用 Python 3.9+。修改管理流程时，请同时考虑本机、SSH、CLI、UI 和 Agent 的调用路径。

## 开发环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/domino -h
```

Ubuntu 可先安装 `python3-venv`、`python3-pip`、`curl`、`openssh-client` 和 `zsh`。日常使用不需要安装开发依赖。

`dev` 依赖保留支持 Python 3.9 的终端组件版本，用于构建兼容最低版本的公共 runtime；普通 wheel 安装仍由 pip 为当前 Python 选择合适的依赖。构建器会拒绝不兼容最低 Python 版本的依赖环境。

## 验证改动

小功能运行受影响的测试，例如：

```bash
.venv/bin/python -m unittest tests.test_tui tests.test_linux_proxy
.venv/bin/python scripts/check_repository.py
```

发布前使用临时内核进行完整回归：

```bash
.venv/bin/python scripts/fetch_test_core.py --output .test-resources/mihomo
DOMINO_TEST_CORE="$PWD/.test-resources/mihomo" .venv/bin/python scripts/verify.py --require-core
.venv/bin/python scripts/verify_ssh.py
```

测试使用临时 HOME、合成配置、受控 HTTP 服务和临时内核。请勿通过切换真实配置、下载私人订阅或重启正在使用的服务验证改动。没有 `DOMINO_TEST_CORE` 时，临时内核集成测试会明确跳过；`--require-core` 禁止这种跳过。

## 提交与发布

- 使用 `domino [USER@IP] COMMAND` 语法，配置管理使用顶层命令。
- 保留普通 JSON 和 Agent 协议的兼容性；人类可读输出不要进入机器结果。
- 新增模块同步更新 `CLI_MODULES`、打包配置和 SSH 分发；新增依赖说明其用途。
- 功能与修复记录到 `CHANGELOG.md`，CLI 与包版本保持一致，使用三段 `0.x.y`。
- 不提交用户配置、订阅链接、密钥、私有导出包、内核二进制或本机验证报告。
- PR 说明实际变化、验证结果和未验证的平台。构建不会自动安装或发布。

完整流程见 [开发与交付](docs/DELIVERY.md)，平台差异见 [平台支持](docs/PLATFORMS.md)。
