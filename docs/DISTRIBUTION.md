# pip、Homebrew 与 apt 分发

三个渠道只安装管理命令。包安装、升级、卸载不会初始化本机服务、捕获配置、调整系统代理或改 shell 文件。需要本机代理时，以普通用户显式运行 `domino-install`；已有离线部署包时也可使用 `domino init --bundle /path/to/bundle.tar.gz`。仅管理远端设备则无需初始化本机服务。

**PyPI 已发布，Homebrew / apt 仍在准备中。** 可从 [PyPI 安装 domino-proxy](https://pypi.org/project/domino-proxy/)，可执行命令保持 `domino`。不要安装 PyPI 上的 `domino`：该名字属于另一个项目。Homebrew tap 和 apt 公共地址尚未发布；已补齐渠道准备工具，下文说明维护者如何生成和验收，发布前不能直接使用计划中的地址安装。

| 渠道 | 发行名称 | 管理命令 | 平台 |
| --- | --- | --- | --- |
| pip / pipx | `domino-proxy` | `domino`、`domino-install` | macOS、Ubuntu；Python 3.9+ |
| Homebrew 自建 tap | `domino` | 同上 | 首先验收 macOS；配方使用 Python 3.13 |
| apt / 本地 deb | `domino-proxy` | 同上 | Ubuntu 22.04 / 24.04，amd64 / arm64 |

每台机器选择一个安装渠道，并由同一包管理器负责后续升级和卸载。目前 macOS / Ubuntu 均可使用 pip（venv）或 pipx；pipx 为 CLI 单独隔离依赖（[PyPA 说明](https://packaging.python.org/en/latest/guides/installing-stand-alone-command-line-tools/)）。Homebrew / apt 目前供本地验收。开发环境继续使用 `.venv`，不与系统安装混用。

| 渠道 | 安装位置 / 入口 | 升级 | 卸载 |
| --- | --- | --- | --- |
| pipx | 独立 venv，用户 PATH 中的 `domino` 链接 | `pipx upgrade domino-proxy` | `pipx uninstall domino-proxy` |
| pip（venv） | 选定 venv 的 `bin/domino` | `venv/bin/python -m pip install --upgrade domino-proxy` | `venv/bin/python -m pip uninstall domino-proxy` |
| Homebrew | Cellar 中的 CLI，通过 brew prefix 链接 | `brew upgrade KJaebye/tap/domino` | `brew uninstall KJaebye/tap/domino` |
| apt | `/usr/bin/domino`，代码在 `/usr/lib/domino/cli` | `sudo apt install --only-upgrade domino-proxy` | `sudo apt remove domino-proxy` |

上表中的 pip / pipx 命令可直接使用；Homebrew / apt 需等待公开渠道上线，目前使用本地 tap 或 deb 验收。`domino update` 更新代理配置，不升级 CLI；内核、配置库与 CLI 包的版本分别管理。

Tab 补全：Homebrew 配方使用 `zsh_completion` / `bash_completion` 安装标准文件，deb 分别安装到 `/usr/share/zsh/vendor-completions/_domino` 和 `/usr/share/bash-completion/completions/domino`，不写用户 rc。pip / 独立 CLI 可运行 `eval "$(domino completion zsh)"` 或 bash 对应命令；永久接入由用户将该行加入 rc。详见[使用指南](USAGE.md#tab-补全)。

## 构建与本地验收

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python -m unittest tests.test_channels tests.test_distribution tests.test_release -q
.venv/bin/python scripts/build_release.py
.venv/bin/python scripts/verify_artifacts.py
.venv/bin/python scripts/verify_pip.py
.venv/bin/python -m build --sdist --outdir dist/pypi
.venv/bin/python -m twine check dist/release/*.whl dist/pypi/*.tar.gz
.venv/bin/python scripts/build_distribution.py
```

同版本不重复构建。已有发行产物时，构建下一版或用同一源码的全新 `--output` 路径进行独立验收，不能覆盖既有包。源码包通过 `MANIFEST.in` 纳入构建脚本与工作流。

主发行仍平铺在 `dist/release/`；补充分发材料在 `dist/distribution-0.17.0/`：

```text
domino-proxy_0.17.0-1_all.deb
domino.rb.in
distribution.json
apt/
  pool/main/d/domino-proxy/domino-proxy_0.17.0-1_all.deb
  dists/stable/Release
  dists/stable/main/binary-amd64/Packages[.gz]
  dists/stable/main/binary-arm64/Packages[.gz]
```

`distribution.json` 记录每个文件的 SHA-256、来源 release.json 摘要、是否签名。默认 apt 材料是**未签名预览**，不能直接作为可信软件源。`.deb` 包含 CLI、纯 Python 依赖与第三方声明，不包含内核、订阅或用户配置；`Architecture: all` 的包同时进入 amd64 / arm64 索引，内核在显式初始化时按本机架构另行获取。

`Distribution smoke tests` 是手动 CI：从固定提交构建真实 0.17.5 基线和当前版本，实际执行 pip、apt 与 Homebrew 的安装 → 升级 → 查询 → 卸载。Ubuntu 使用临时 GPG 密钥验证签名 apt 源；macOS 使用本地 runtime 和临时 tap。合成 HOME 中放置配置、运行文件、服务文件、shell 文件和旧 launcher，检查内容、权限及符号链接未被查询或包卸载改动；apt 另检查以 root 查询不会产生未受包管理的 `__pycache__`，卸载后包目录和命令入口清理干净。基线 deb 使用当前打包器重新封装，避免旧打包器漏目录导致无法安装；旧版 CLI 源码与版本不改。CI 密钥仅用于该次测试，不作为生产签名密钥。以具体 Actions 运行结果为准，工作流文件本身不表示验收通过。

## pip / pipx

推荐使用 venv 安装，包名为 `domino-proxy`，避免依赖全局 `pip` 命令或向系统 Python 写入：

Ubuntu 先安装环境依赖（macOS 跳过）：

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip curl
```

再创建并激活 venv：

```bash
python3 -m venv ~/.venvs/domino
source ~/.venvs/domino/bin/activate
python -m pip install --upgrade domino-proxy
domino --version
```

pip 安装 CLI 及其 Python 依赖，发行包**不包含 Mihomo 内核**。首次在本机使用代理时，以普通用户运行：

```bash
domino-install
```

安装器会联网下载对应系统和架构的 Mihomo 并配置后台服务，可复用符合条件且校验通过的缓存。仅管理远端时不必运行此命令；已有本机服务时，日常升级 CLI 也不必再次初始化。重复初始化会保留已有配置并重启服务。

`python -m pip install` 会下载包及 UI/YAML 依赖，除已准备离线 wheelhouse 外需要网络。不使用 `sudo pip`、`--break-system-packages`。

若激活时提示 `activate: No such file or directory`，说明 venv 尚未成功创建，需先完成 `python3 -m venv ~/.venvs/domino`。激活成功后再执行 `python -m pip`；仅改为系统的 `python3 -m pip` 仍可能触发 Ubuntu 的 `externally-managed-environment` 保护。

每次新开终端，先运行 `source ~/.venvs/domino/bin/activate`；也可以直接使用 `~/.venvs/domino/bin/domino`。若希望无需激活环境即可使用命令，可在安装好 pipx 后运行：

```bash
pipx install domino-proxy
pipx ensurepath
```

`pipx ensurepath` 后重新打开终端。离线或验收本地包时，可将 pip 安装命令中的包名替换为实际 wheel 文件路径。首次使用可继续按 [快速开始](../README.md#快速开始) 准备配置或部署远端。

不要把旧 `domino` 发行包与新包装在同一个环境，两个发行包提供同名命令。旧开发环境先确认 `python -m pip show domino` 指向本项目，再卸载旧包、安装新包；不能误删同名的其他项目。也可以新建独立环境。

## 一个 workflow 发布三个渠道

唯一发布入口是 `.github/workflows/publish-pypi.yml`，Actions 显示名为 **Publish · PyPI / Homebrew / APT**。沿用文件名及 `pypi` environment，保留现有 Trusted Publisher 绑定。原先只构建产物的 `release.yml` 已合并进这个入口；`Verify` 和 `Distribution smoke tests` 继续作为独立测试入口，不执行公共发布。

发布工具从 `main` 运行，软件内容固定到输入版本对应的标签提交。已发布的版本直接下载并核对 GitHub Release 原始 wheel、sdist、runtime 和 SHA-256 清单，不重新构建；没有 Release 的新标签先执行源码回归，再构建一次、验证并发布。工具更新不提升软件版本，也不移动软件标签。

对当前 1.2.3 进行只读演练：

```bash
gh workflow run publish-pypi.yml --repo KJaebye/domino --ref main \
  -f version=1.2.3 -f channels=all -f dry_run=true
```

正式同步发布：

```bash
gh workflow run publish-pypi.yml --repo KJaebye/domino --ref main \
  -f version=1.2.3 -f channels=all
```

只补发 APT：

```bash
gh workflow run publish-pypi.yml --repo KJaebye/domino --ref main \
  -f version=1.2.3 -f channels=apt
```

`channels` 支持 `all`、`pypi`、`brew`、`apt`。只读演练不上传、不导入生产签名密钥，也不表示真实安装验收通过。真实运行顺序：

```text
固定标签提交 → 复用 / 构建并验证原始产物 → GitHub Release
                                            ├─ PyPI：仅上传缺失文件 → 隔离安装并核验
                                            ├─ Homebrew：更新 tap → 公开安装与 brew test
                                            └─ APT：保留旧 pool、签名、Pages → 公开 apt 安装核验
                                                        ↓
                                           汇总每个渠道的真实结果
```

每个渠道独立运行，一个失败不阻止另外两个完成。`release-inputs` artifact 固定本次产物，`release-status` artifact 和 Actions Summary 记录 `verified / failed / blocked`。只有三个渠道都核验成功时 `complete=true`；单渠道补发使用 `request_complete` 表示该请求成功，其他渠道不推断为成功。只读演练记为 `checked`，不记作发布完成。

### 首次上线所需配置

首次上线使用以下配置；发布脚本本身不会创建仓库、签名密钥或设置凭据：

| 配置 | 用途 |
| --- | --- |
| 公共 `KJaebye/homebrew-tap`，有初始 `main` 提交 | 保存 `Formula/domino.rb`；工作流只修改本项目配方和缺失的 README |
| `release` environment 的 `RELEASE_TAP_SSH_KEY` secret | 仅授予 tap 仓库写权限的专用 SSH deploy key；也支持仅限 tap 的 `RELEASE_TAP_TOKEN` 作为替代，不复用个人的全局凭据 |
| 本仓库 Settings → Pages → GitHub Actions | 工作流托管 APT 到 `https://kjaebye.github.io/domino/apt/`，不再需要独立 APT 仓库 |
| 仓库 variable `APT_GPG_FINGERPRINT` | 生产签名密钥的完整主公钥指纹 |
| `github-pages` environment 的 `APT_GPG_PRIVATE_KEY` secret | ASCII armored 专用 APT 私钥；只在临时 GPG HOME 中导入，完成即销毁 |
| 同 environment 的 `APT_GPG_PASSPHRASE` secret（如有） | 通过 stdin 解锁密钥，不写命令参数或文件 |
| PyPI Trusted Publisher | owner `KJaebye`、repo `domino`、workflow `publish-pypi.yml`、environment `pypi`；environment 的分支策略须允许 `main` |

可选仓库 variables：`RELEASE_TAP_REPOSITORY`、`RELEASE_APT_URL`。默认指向上表地址；URL 必须是 HTTPS。APT 内容由本 workflow 负责部署；若本仓库已有其他 Pages 网站，需要先安排网站内容的合并，不能直接覆盖已有站点。

PyPI 通过 OIDC 发布，不读取本机 token 文件。此前 Actions 出现过支付 / 额度限制导致任务未启动，当前是否已恢复应以新一次演练结果为准。新文件只有进入远端 `main` 后才能通过 Actions 调度。

### 重试与问题处理

- 版本相同且文件摘要匹配：复用已发布文件；缺少某个 PyPI 文件时仅上传该文件。摘要冲突或已被 yank 的 PyPI 文件直接失败，不静默忽略。
- GitHub 上传中断：保留 draft；对原运行执行 `gh run rerun RUN_ID --failed`，复用原 artifact，补齐缺失文件。全新运行遇到未完成 draft 会要求先检查该 draft，避免重建出另一套相同版本产物。
- Homebrew / APT 更新中断：重跑失败 job 或用 `channels` 补发。网络请求有限重试；所有渠道拒绝降级，旧 APT pool 包保留。
- 修改软件内容才能解决的问题：走新的软件版本；仅修复发布脚本的问题可以继续分发原版本的固定产物。改变生产签名指纹需要单独安排密钥轮换。
- 同一仓库的生产发布串行执行，不取消正在发布的运行。GitHub 默认仅保留一个 pending 运行，不依赖它提供任意长度的发布队列或版本排序。

Agent 使用同一组命令调度、查看结果和分析失败：

```bash
gh run list --repo KJaebye/domino --workflow publish-pypi.yml
gh run view RUN_ID --repo KJaebye/domino --log-failed
gh run download RUN_ID --repo KJaebye/domino --name release-status
gh run rerun RUN_ID --repo KJaebye/domino --failed
```

参考 [PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)、[GitHub Pages 部署](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)和 [Actions 并发控制](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)。

### 发布后用户安装命令

以下为计划入口，公开渠道完成发布验收前不可视为可用。

```bash
# macOS
brew install KJaebye/tap/domino

# Ubuntu 22.04+，amd64 / arm64
curl -fsSL https://kjaebye.github.io/domino/apt/domino.sources \
  | sudo tee /etc/apt/sources.list.d/domino.sources >/dev/null
sudo apt update
sudo apt install domino-proxy
```

包名是 `domino-proxy`，执行命令是 `domino`。Homebrew 配方使用固定版本的自包含 runtime，APT 使用系统 Python 3.9+ 和包内纯 Python 依赖；没有引入新的打包框架。发布 job 当前实际安装验收分别使用 macOS ARM64 和 Ubuntu 24.04 amd64；其他平台验收仍看 `Distribution smoke tests` 的实际结果，不以索引存在代替安装通过。

本地分发工具相关验证：

```bash
.venv/bin/python -m unittest tests.test_release_workflow tests.test_channels tests.test_distribution tests.test_release -q
```

## 服务、升级与卸载边界

包管理器维护 CLI。初始化仍保存用户级运行文件，但不替换 `~/.local/bin/domino`，包括 pipx 的符号链接；失败回滚同样保留该入口。源安装脚本和部署至另一台设备继续使用自包含的用户级 CLI。

从旧源安装切换渠道前，先用 `type -a domino` 找到当前入口。旧 `~/.local/bin/domino` 可能优先于 brew / apt：先停止服务、备份配置，并显式处理旧入口或调整 PATH，再验证 `command -v domino` 与 `domino --version`。初始化不自动清理旧入口。

CLI 包升级不等于内核升级，不重启服务、不改节点与系统代理。仅卸载 CLI 包会保留运行内核、配置库和服务文件；pip 不提供运行时清理钩子。要完整清理，先运行 `domino uninstall`，再使用原包管理器卸载 CLI，例如 `domino uninstall && pip uninstall domino-proxy`。前一步会确认删除配置和备份，并清理终端接入记录；详见 [卸载指南](USAGE.md#卸载与清理)。

项目仓库已公开；新增渠道仍需核验可匿名下载、版本固定的 runtime 地址，以及公开 tap 与签名 apt HTTPS 托管。三个渠道应交付同一源码版本，先构建并校验，再分别上传 wheel、runtime 与 deb / apt 索引；不要在发布步骤改包内容或把生产私钥交给构建脚本。

源安装的 shell 加载器使用 `/usr/bin/env python3`，避免引用随后被删除的安装临时 venv。移除 pip 环境或升级 brew Python 后，运行文件中的纯 Python shell helper 仍可由系统可用的 Python 3.9+ 执行。
