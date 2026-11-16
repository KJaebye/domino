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

## 目录结构

```text
src/          Python 实现：CLI、UI、平台适配、配置与资源管理
scripts/      构建、发布准备、验证和文档资产生成工具
tests/        单元测试与隔离集成测试
docs/         使用、架构、平台和分发说明
assets/       README 动图与静态 Logo
licenses/     第三方许可证文本
.github/      CI、分发工作流与协作模板
domino        源码运行入口
install.sh    安装入口
pyproject.toml  包元数据、依赖和命令入口
```

根目录不再放实现模块。修改源码后，可直接 `.venv/bin/python ./domino COMMAND`，或在完成 editable 安装后使用 `.venv/bin/domino COMMAND`。原来的 `python domino_cli.py` 改为 `python ./domino`；需要直接运行模块文件时，路径是 `src/domino_cli.py`。

`src/` 保留现有模块名；wheel、独立 runtime 和远端部署包仍沿用稳定的模块与入口布局。新增实现文件放进 `src/`，并同步 `CLI_MODULES` 和 `pyproject.toml` 的模块声明；不要把构建脚本放回根目录。

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

日常 push、PR 和标签推送不自动运行完整 GitHub Actions 矩阵。发版前可在 Actions 中手动运行 `Verify`，或运行会先执行完整验证的 `Release artifacts`；上传 PyPI 使用独立的手动工作流 `Publish to PyPI`。

## 提交与发布

- 使用 `domino [USER@IP] COMMAND` 语法，配置管理使用顶层命令。
- 保留普通 JSON 和 Agent 协议的兼容性；人类可读输出不要进入机器结果。
- 新增模块同步更新 `CLI_MODULES`、打包配置和 SSH 分发；新增依赖说明其用途。
- 功能与修复记录到 `CHANGELOG.md`，CLI 与包版本保持一致，使用三段 `0.x.y`。
- 不提交用户配置、订阅链接、密钥、私有导出包、内核二进制或本机验证报告。
- PR 说明实际变化、验证结果和未验证的平台。构建不会自动安装或发布。

完整流程见 [开发与交付](docs/DELIVERY.md)，平台差异见 [平台支持](docs/PLATFORMS.md)。

## 许可证与贡献

项目采用 GNU GPLv3（仅第 3 版，`GPL-3.0-only`），完整条款见 [LICENSE](LICENSE)。提交用于本项目的贡献应可按该许可证分发；引入第三方代码或资源时保留原声明，并说明来源与许可证。
