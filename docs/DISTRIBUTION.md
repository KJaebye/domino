# pip、Homebrew 与 apt 分发

**1.3.0 已于 2026-11-24 正式发布**，固定源码为 `v1.3.0` 的 `c3963b8`，构建渠道为 release。GitHub Release、PyPI、Homebrew tap、自建签名 APT 和下载中心均已更新并完成摘要/签名校验，PyPI 隔离安装及 Ubuntu 24.04 隔离 APT 更新与下载通过。Mac 公司现场验收保留原记录；最新源码的 Ubuntu 真机服务、桌面代理和自启验收仍待完成。1.2.3 原始产物与历史记录继续保留。

三个渠道只安装管理命令。包安装、升级、卸载不会初始化本机服务、捕获配置、调整系统代理或改 shell 文件。需要本机代理时，以普通用户显式运行 `domino-install`；已有离线部署包时也可使用 `domino init --bundle /path/to/bundle.tar.gz`。仅管理远端设备则无需初始化本机服务。

**PyPI、Homebrew 和签名 APT 源均已发布 1.3.0。** 可从 [PyPI 安装 domino-proxy](https://pypi.org/project/domino-proxy/)，可执行命令保持 `domino`。不要安装 PyPI 上的 `domino`：该名字属于另一个项目。发布在维护者本机执行，凭据以 TXT 和 GPG 文件统一保存在仓库外的 OneDrive `oetree/domino/tokens`；下文提供安装、签名验证和维护命令。

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

不覆盖或重建已发布版本。1.3.0 已正式发布；后续代码变更按[仓库约定](../AGENTS.md)使用新版本号，开发构建使用全新 `--output` 目录区分源码快照。同源码独立验收也可使用全新输出目录，不能覆盖既有包。源码包通过 `MANIFEST.in` 纳入构建脚本与工作流。

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

发布统一在开发机执行，不要求 GitHub Actions 有可用额度，也不把生产凭据放入 GitHub Secrets。下列 1.2.3 命令保留为已发布版本的维护示例。1.3.0 已由维护者在本机确认并完成发布；后续版本继续分别核对源码审批、标签、产物审核与正式发布授权。

```bash
# 只读演练，不读取生产签名私钥或上传文件
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels all --dry-run

# 正式同步三个渠道
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels all

# 只恢复某个渠道，另外两个不重复上传
.venv/bin/python scripts/release_channels.py publish --version 1.2.3 --channels apt
```

运行前本机应有 `gh`、Git / OpenSSH、GPG、Ruby，以及开发虚拟环境中的 build、twine。GitHub 操作沿用本机已有 `gh` / SSH 登录，不复制个人 GitHub 凭据到公开仓库。初次初始化的项目凭据位置见下表；正常发布不会创建仓库、密钥或提升软件版本。

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

### 自托管 CI 候选包与本机审核

自托管构建不持有生产凭据。`scripts/candidate_release.py review` 接收下载后的
`result.json`、`output/` 和固定提交的干净源码副本，核对控制器/容器报告、构建镜像、
完整文件清单、runtime 源码清单、sdist 和 Debian 绑定关系。`--smoke` 在临时 HOME 中
验收 wheel/runtime，不修改本机安装。审核报告仍为 `publication_allowed=false`。

```bash
.venv/bin/python scripts/candidate_release.py doctor
.venv/bin/python scripts/candidate_release.py review \
  --candidate /path/to/private-ci-candidate --source /path/to/clean-pinned-source --smoke
```

`doctor` 只检查公开配置、凭据 TXT 的元数据、目录权限和公有签名指纹，不读取密码、私钥正文或
仓库内 token 文件。缺少凭据不会阻止候选包只读审核。

日常 `development` 构建可以验收，但不能重贴稳定标签发布。只有维护者明确授权
源码稳定化和创建正式标签后，`BUILD_CHANNEL=release`、标签提交完全一致且完整 CI
通过的 `release-candidate` 才能进入发布准备。1.3.0 发布分支已切换 release 标记，
本流程本身不自动修改版本、BUILD_CHANNEL 或创建标签。

稳定候选构建先运行 `candidate_release.py preflight`，拒绝 GitHub 已有 Release/draft、
PyPI 已有同版本、APT/Homebrew 已有同版本或更高版本等情况。它只读取公开渠道。

在获得发布授权后，既有本机发布入口可以导入该候选包：

```bash
# 只有正式标签已经存在、且候选来自相同稳定提交时才可执行；只读准备。
.venv/bin/python scripts/release_channels.py publish --version X.Y.Z \
  --candidate /path/to/private-ci-candidate --channels all --dry-run
```

wheel、runtime、sdist 与 `.deb` 原样导入，不重新构建或重压缩发行包。Debian 原包的
未压缩 control/payload 必须与已校验 runtime 的规范内容、路径、权限和时间戳一致，
不允许添加安装钩子。工具只重新生成 APT 索引和签名，避免 Linux/macOS 的 gzip 差异。
预览及正式签名阶段的 `.deb` 都必须与 CI 原包摘要完全相同，否则在上传前失败。
`plan.json` 保留 run-id、源码 SHA、infra SHA、镜像 ID 和候选报告摘要。
已发布版本仍走原始公开产物复用流程。补发渠道时可以携带同一个候选作为核对材料，
但始终下载并使用官方原始字节；候选与公开文件有任何差异都会拒绝，不能替换既有版本。

跨项目的抓取、审核封存和交互式人工确认入口由 `oetree-infra/scripts/release.py`
管理；本仓库维护具体包格式、分发与签名规则。准备成功、临时签名验收和正式发布分别报告。

### 凭据存储：维护者指定的 TXT 文件

维护者明确选择将 Domino 发布凭据统一存放在 OneDrive `oetree/domino/tokens`，不使用苹果钥匙串保存或读取本流程的 PyPI Token、APT 私钥口令和备份解密密码。默认入口为 `~/OneDrive/oetree/domino/tokens`；其他电脑可用 `--credentials-dir` 指定对应的仓库外目录。

| 文件 | 用途 |
| --- | --- |
| `domino-proxy-pypi-upload.txt` | PyPI 项目上传 Token；仅确有缺失包需要上传时读取 |
| `gnupg/` | 当前 APT 签名私钥、公钥和撤销证书 |
| `domino-apt-signing-passphrase.txt` | 解锁 `gnupg/` 中私钥、签署 APT 索引时使用的口令 |
| `domino-apt-backup-password.txt` | 解密 `domino-apt-recovery-*.tar.gpg` 加密备份包时使用的密码 |
| `domino-apt-recovery-*.tar.gpg` | APT 密钥、签名口令和公开配置的加密备份包 |
| `state.json` | 公开的签名指纹和凭据文件名称，不含密码或 Token |
| `说明.txt` | 各文件用途说明，不含凭据值 |

两份 APT 密码用途不同。文件夹权限为 0700，凭据文件为 0600；读取时拒绝仓库内路径、符号链接、权限过宽、过大或空文件。签名时在短路径临时目录复制 GPG 数据，避免在 OneDrive 中同步 agent socket 和锁文件；操作结束后停止临时 agent 并删除临时副本，不保留隐藏目录中的长期发布凭据。签名口令只通过 stdin 交给 GPG，PyPI Token 只临时交给 Twine 子进程，不进入命令参数、日志或报告。不读取仓库根目录的 `pypi-token` 或 `.pypirc`。

Homebrew 和 APT 公开仓库写入继续使用维护者已有的 `gh` 登录，不改动其账号认证配置。GitHub 端仅保存公开发行包、公钥和签名；CI/VPS 不接收发布凭据。正式发布确认要求保持不变。

### 发布目标与签名

| 渠道 | 公开目标 |
| --- | --- |
| PyPI | `domino-proxy`；Twine 直传，不使用 Actions OIDC 发布 |
| Homebrew | `KJaebye/homebrew-tap` 的 `main`，配方固定 runtime URL 和 SHA-256 |
| APT | `KJaebye/domino-apt` 的 `main`，通过 `raw.githubusercontent.com` 提供静态文件，不需要 Pages 构建或部署任务 |

APT 签名主公钥指纹：`61ADCFADCDBE96102419F2797501FC6C688FCF00`。公钥和指纹用于验签，可以公开；私钥和口令不能公开。`domino.sources` 内嵌公钥，信任只作用于此源，不用 `apt-key` 或 `trusted=yes`。

2026-11-24 因原签名口令不可恢复，经维护者授权更换上述签名身份；软件包字节保持不变。已安装旧 APT 源的用户需要重新执行下方源配置导入命令；新密钥不具备旧密钥的签名背书。新私钥、签名口令 TXT、备份解密密码 TXT 及加密恢复包均按维护者明确要求集中保存在 OneDrive `oetree/domino/tokens`。

APT 保留旧 pool 包和按摘要寻址的索引（By-Hash），避免客户端缓存不同步造成校验失败。推送前只允许公开 APT 文件进入仓库，拒绝私钥路径、符号链接和私钥正文。索引与签名可以更新，已经发布的同版本 `.deb` 不替换。

网络请求有限重试。渠道失败后可以重新运行同一版本，或用 `--channels` 只补发失败渠道；已存在且摘要一致的文件跳过。版本冲突、降级、签名不匹配直接失败。原始软件变更仍需新的软件版本，发布工具修复则继续分发原始产物。

### 分发维护记录

以下是现有渠道维护，不新增软件版本，也不修改历史发行包：

| 日期 | 对象 | 实际维护与验证 |
| --- | --- | --- |
| 2026-11-24 | 1.3.0 正式发布 | 原始 CI 候选从 `c3963b8` 发布至四个渠道，下载中心同步。GitHub 七个资产、PyPI 两个包、Homebrew 配方和 APT 签名/索引/原始 Debian 包均校验通过；草稿中断恢复不替换资产，原失败状态保留，新恢复记录为完整成功。 |
| 2026-11-24 | 现有 1.2.3 签名 APT 源 | 原口令不可恢复，经维护者授权将签名指纹从 `8704BE99B201383E16246ED9099855D35D066EE8` 更换为 `61ADCFADCDBE96102419F2797501FC6C688FCF00`；保留全部原始 `.deb`、Release 正文、Packages 与 By-Hash 字节，只更换公钥、签名、源配置和维护说明。 |
| 2026-11-24 | 发布凭据 | 按维护者要求改用上述 OneDrive 目录中的 TXT 文件，移除本流程原有的苹果钥匙串条目；签名私钥口令和加密备份包密码分别命名，文件读取签名与备份解密回验通过。 |
| 2026-11-24 | 公开托管验收 | 下载域名上的 20 个 APT 公共文件摘要核对通过；隔离 Ubuntu 24.04 客户端使用新公钥完成 `apt update` 并下载原 1.2.3 包，摘要一致。这不是 Ubuntu 真机服务安装、启动或桌面代理验收。 |

原 1.2.3 发布记录、原始包和摘要保留。1.3.0 已经独立完成维护者确认及实际渠道校验，不以此前的密钥更换、工具演练或标签存在代替发布结果。后续维护继续追加记录；机器生成的历史 `release-status.json` 保留原始结果，新尝试写新目录，不手工改成成功。当前公开源中的 `channel.json` 则随真实的签名和公开文件更新。

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
