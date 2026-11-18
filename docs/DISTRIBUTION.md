# pip、Homebrew 与 apt 分发

当前工作区版本为 **1.3.0，未发布**，本轮功能与修复统一纳入这个稳定版本里程碑。日常开发只执行普通 commit；只有维护者明确授权后才能创建 `v1.3.0` tag 或发布到任何渠道。公司网络与最新源码的 Ubuntu 验收仍待完成。本地 CLI 显示 1.3.0 不表示 PyPI 已发布；已发布的 1.2.3 及其官方提交材料保持原样。

三个渠道只安装管理命令。包安装、升级、卸载不会初始化本机服务、捕获配置、调整系统代理或改 shell 文件。需要本机代理时，以普通用户显式运行 `domino-install`；已有离线部署包时也可使用 `domino init --bundle /path/to/bundle.tar.gz`。仅管理远端设备则无需初始化本机服务。

**PyPI、Homebrew 和签名 APT 源均已发布 1.2.3。** 可从 [PyPI 安装 domino-proxy](https://pypi.org/project/domino-proxy/)，可执行命令保持 `domino`。不要安装 PyPI 上的 `domino`：该名字属于另一个项目。发布在本机执行，凭据保存在钥匙串与仓库外；下文提供安装、签名验证和维护命令。

| 渠道 | 发行名称 | 管理命令 | 平台 |
| --- | --- | --- | --- |
| pip / pipx | `domino-proxy` | `domino`、`domino-install` | macOS、Ubuntu；Python 3.9+ |
| Homebrew 自建 tap | `domino` | 同上 | 首先验收 macOS；配方使用 Python 3.13 |
| apt / 本地 deb | `domino-proxy` | 同上 | Ubuntu 22.04 / 24.04，amd64 / arm64 |

每台机器选择一个安装渠道，并由同一包管理器负责后续升级和卸载。目前 macOS / Ubuntu 均可使用 pip（venv）或 pipx；pipx 为 CLI 单独隔离依赖（[PyPA 说明](https://packaging.python.org/en/latest/guides/installing-stand-alone-command-line-tools/)）。Homebrew / apt 使用下文的公开安装入口。开发环境继续使用 `.venv`，不与系统安装混用。

| 渠道 | 安装位置 / 入口 | 升级 | 卸载 |
| --- | --- | --- | --- |
| pipx | 独立 venv，用户 PATH 中的 `domino` 链接 | `pipx upgrade domino-proxy` | `pipx uninstall domino-proxy` |
| pip（venv） | 选定 venv 的 `bin/domino` | `venv/bin/python -m pip install --upgrade domino-proxy` | `venv/bin/python -m pip uninstall domino-proxy` |
| Homebrew | Cellar 中的 CLI，通过 brew prefix 链接 | `brew upgrade KJaebye/tap/domino` | `brew uninstall KJaebye/tap/domino` |
| apt | `/usr/bin/domino`，代码在 `/usr/lib/domino/cli` | `sudo apt install --only-upgrade domino-proxy` | `sudo apt remove domino-proxy` |

上表的三个渠道均可使用；本机与隔离安装验收的实际范围见下文。`domino update` 更新代理配置，不升级 CLI；内核、配置库与 CLI 包的版本分别管理。

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

## 一个本机流程发布三个渠道

发布统一在开发机执行，不要求 GitHub Actions 有可用额度，也不把生产凭据放入 GitHub Secrets。下列 1.2.3 命令保留为已发布版本的维护示例，不是当前 1.3.0 的发布授权。当前版本只做普通 commit，等待维护者明确批准 tag 与发布。

```bash
# 只读演练，不读取生产签名私钥或上传文件
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels all --dry-run

# 正式同步三个渠道
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels all

# 只恢复某个渠道，另外两个不重复上传
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels apt
```

运行前本机应有 `gh`、Git / OpenSSH、GPG、Ruby，以及开发虚拟环境中的 build、twine、keyring。GitHub 操作沿用本机已有 `gh` / SSH 登录，不复制个人 GitHub 凭据到公开仓库。初次初始化的项目凭据位置见下表；正常发布不会创建仓库、密钥或提升软件版本。

```text
固定标签提交 → 复用 / 构建并验证软件产物 → 核验 / 发布 GitHub Release
                                         ├─ PyPI：Twine → 校验文件并临时安装
                                         ├─ Homebrew：本机 gh 提交 tap → 校验配方及 runtime
                                         └─ APT：本机 GPG 签名 → 推送公开软件源 → 校验签名、索引和包
                                                       ↓
                                         本机 release-status.json
```

已有版本直接复用 GitHub Release 原始 wheel、sdist、runtime 和校验清单，并核对其标签提交；不会因为修改发布流程而重建或覆盖软件。新版本须先有与源码版本一致的标签。软件产物只构建一次，失败后不替换同版本的不同内容。

输出在新的 `dist/local-release-<版本>-<运行编号>/`。`release-status.json` 记录各渠道 `verified / failed / blocked`；三个渠道都通过时才记为 `complete=true`。补发单渠道使用 `request_complete` 表示该请求成功，不推断其他渠道状态。只读演练记为 `checked`。

### 凭据存储：只留本机

| 内容 | 位置与使用方式 |
| --- | --- |
| 项目范围的 PyPI token | macOS 钥匙串：服务 `https://upload.pypi.org/legacy/`、账户 `__token__`；仅在确有缺失包时读取，临时交给 Twine 进程 |
| Homebrew / APT 公开仓库写入凭据 | 沿用 `gh` 已有的 macOS 钥匙串登录；通过 GitHub Git API 提交公开文件，不额外生成部署私钥，也不导出个人 token |
| APT GPG 私钥及撤销证书 | 仓库外 `~/.local/share/domino-release/gnupg/`，目录权限 0700；私钥本身有口令保护 |
| APT 私钥解锁口令 | macOS 钥匙串：服务 `domino-release/apt`、账户 `signing-passphrase`；仅签名时通过 stdin 交给 GPG |
| 指纹、目标仓库和钥匙串条目名称 | `~/.local/share/domino-release/state.json`，权限 0600，只含公开配置，不含私钥或 token |
| GitHub 端 | 只保存公开产物、公钥、指纹、签名；不保存生产私钥、token 或解锁口令 |

项目凭据目录 `~/.local/share/domino-release/` 权限为 0700，独立于 Domino 运行目录，普通软件卸载不会删除它。`--credentials-dir` 可指定另一个仓库外的受限目录。工具拒绝从仓库内或权限过宽的目录读取凭据，也不读取仓库内的 token 文件或 `.pypirc`，不为它们新增 `.gitignore` 规则。

首次配置 PyPI token 时使用隐藏输入，不把 token 写入命令或聊天：

```bash
.venv/bin/python -m keyring set https://upload.pypi.org/legacy/ __token__
```

前期 Actions 方案创建的独立 Homebrew 部署密钥已撤销，私钥条目和 GitHub Secret 副本均已移除。本机 gh 登录的凭据仍由系统钥匙串管理。备份 GPG 目录与钥匙串时使用加密备份，撤销证书按私钥同等保护。

### 发布目标与签名

| 渠道 | 公开目标 |
| --- | --- |
| PyPI | `domino-proxy`；Twine 直传，不使用 Actions OIDC 发布 |
| Homebrew | `KJaebye/homebrew-tap` 的 `main`，配方固定 runtime URL 和 SHA-256 |
| APT | `KJaebye/domino-apt` 的 `main`，通过 `raw.githubusercontent.com` 提供静态文件，不需要 Pages 构建或部署任务 |

APT 签名主公钥指纹：`8704BE99B201383E16246ED9099855D35D066EE8`。公钥和指纹用于验签，可以公开；私钥和口令不能公开。`domino.sources` 内嵌公钥，信任只作用于此源，不用 `apt-key` 或 `trusted=yes`。

APT 保留旧 pool 包和按摘要寻址的索引（By-Hash），避免客户端缓存不同步造成校验失败。推送前只允许公开 APT 文件进入仓库，拒绝私钥路径、符号链接和私钥正文。索引与签名可以更新，已经发布的同版本 `.deb` 不替换。

网络请求有限重试。渠道失败后可以重新运行同一版本，或用 `--channels` 只补发失败渠道；已存在且摘要一致的文件跳过。版本冲突、降级、签名不匹配直接失败。原始软件变更仍需新的软件版本，发布工具修复则继续分发原始产物。

### 可选的隔离安装验收

`.github/workflows/release.yml` 只执行单元测试和公开包安装检查，权限为只读，不引用任何生产 Secret，也不执行发布。Actions 无额度时，本机发布仍然可以完成。

```bash
gh workflow run release.yml --repo KJaebye/domino --ref main -f version=1.2.3
```

本机发布默认核验公开 Homebrew 配方、已验证的 runtime、APT 公钥指纹、签名、索引和包摘要，并在临时 venv 安装 PyPI 包；不安装或替换用户现有的 Homebrew / APT CLI。真实 `brew install` / `apt install` 使用隔离 runner，其结果以实际运行记录为准，不把摘要校验称作所有平台安装通过。

### 用户安装命令

```bash
# macOS
brew install KJaebye/tap/domino

# Ubuntu 22.04+，amd64 / arm64
curl -fsSL https://raw.githubusercontent.com/KJaebye/domino-apt/main/domino.sources \
  | sudo tee /etc/apt/sources.list.d/domino.sources >/dev/null
sudo apt update
sudo apt install domino-proxy
```

包名是 `domino-proxy`，执行命令是 `domino`。所有渠道仅安装 CLI；需要本机代理时以普通用户运行 `domino catch` 或 `domino-install`。

本地验证发布工具：

```bash
.venv/bin/python -m unittest tests.test_release_workflow tests.test_channels tests.test_distribution tests.test_release tests.test_repository -q
```

## 服务、升级与卸载边界

包管理器维护 CLI。初始化仍保存用户级运行文件，但不替换 `~/.local/bin/domino`，包括 pipx 的符号链接；失败回滚同样保留该入口。源安装脚本和部署至另一台设备继续使用自包含的用户级 CLI。

从旧源安装切换渠道前，先用 `type -a domino` 找到当前入口。旧 `~/.local/bin/domino` 可能优先于 brew / apt：先停止服务、备份配置，并显式处理旧入口或调整 PATH，再验证 `command -v domino` 与 `domino --version`。初始化不自动清理旧入口。

CLI 包升级不等于内核升级，不重启服务、不改节点与系统代理。仅卸载 CLI 包会保留运行内核、配置库和服务文件；pip 不提供运行时清理钩子。要完整清理，先运行 `domino uninstall`，再使用原包管理器卸载 CLI，例如 `domino uninstall && pip uninstall domino-proxy`。前一步会确认删除配置和备份，并清理终端接入记录；详见 [卸载指南](USAGE.md#卸载与清理)。

项目仓库已公开；新增渠道仍需核验可匿名下载、版本固定的 runtime 地址，以及公开 tap 与签名 apt HTTPS 托管。三个渠道应交付同一源码版本，先构建并校验，再分别上传 wheel、runtime 与 deb / apt 索引；不要在发布步骤改包内容或把生产私钥交给构建脚本。

源安装的 shell 加载器使用 `/usr/bin/env python3`，避免引用随后被删除的安装临时 venv。移除 pip 环境或升级 brew Python 后，运行文件中的纯 Python shell helper 仍可由系统可用的 Python 3.9+ 执行。
