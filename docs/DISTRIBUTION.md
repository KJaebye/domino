# pip、Homebrew 与 apt 分发

三个渠道只安装管理命令。包安装、升级、卸载不会初始化本机服务、捕获配置、调整系统代理或改 shell 文件。需要本机代理时，以普通用户显式运行 `domino-install`；已有离线部署包时也可使用 `domino init --bundle /path/to/bundle.tar.gz`。仅管理远端设备则无需初始化本机服务。

**PyPI 已发布，Homebrew / apt 仍在准备中。** 可从 [PyPI 安装 domino-proxy](https://pypi.org/project/domino-proxy/)，可执行命令保持 `domino`。不要安装 PyPI 上的 `domino`：该名字属于另一个项目。Homebrew tap 和 apt 公共地址尚未发布，下文标有占位符的命令不能直接作为公开安装入口。

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
.venv/bin/python -m unittest tests.test_distribution tests.test_release -q
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

`python -m pip install` 会下载包及 UI/YAML 依赖，除已准备离线 wheelhouse 外需要网络。Ubuntu 缺少 venv 时，先运行 `sudo apt-get update && sudo apt-get install -y python3-venv python3-pip curl`；不使用 `sudo pip`、`--break-system-packages`。

每次新开终端，先运行 `source ~/.venvs/domino/bin/activate`；也可以直接使用 `~/.venvs/domino/bin/domino`。若希望无需激活环境即可使用命令，可在安装好 pipx 后运行：

```bash
pipx install domino-proxy
pipx ensurepath
```

`pipx ensurepath` 后重新打开终端。离线或验收本地包时，可将 pip 安装命令中的包名替换为实际 wheel 文件路径。首次使用可继续按 [快速开始](../README.md#快速开始) 准备配置或部署远端。

不要把旧 `domino` 发行包与新包装在同一个环境，两个发行包提供同名命令。旧开发环境先确认 `python -m pip show domino` 指向本项目，再卸载旧包、安装新包；不能误删同名的其他项目。也可以新建独立环境。

### 维护者发布流程

0.17.8 已通过 Trusted Publisher 发布。后续版本继续使用 `.github/workflows/publish-pypi.yml` 手动发布；工作流只接受与源码版本精确匹配的 `v0.x.y` 标签，并要求仓库有非空 LICENSE。发布前核对：

1. 核对已选定的 `GPL-3.0-only`、LICENSE 与第三方声明已随发行包交付。
2. PyPI 项目 `domino-proxy` 的 Trusted Publisher 为 owner `KJaebye`、repository `domino`、workflow `publish-pypi.yml`、environment `pypi`。
3. 核对 GitHub `pypi` environment 与 Trusted Publisher 的配置一致；发布审批与标签限制由维护者另行配置。
4. 完成平台验收后，在对应版本标签上手动运行 `Publish to PyPI`。

工作流使用短期 OIDC 凭据，不在仓库保存 PyPI token。参考 [PyPA 官方发布指南](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)。工作流文件的存在不会自动发布；普通 push 不触发上传。

日常 push、PR 和标签推送也不自动执行完整平台测试。发版前按需在 Actions 中手动运行 `Release artifacts`（先完整验证再构建）或 `Verify`；发布时进入 **Actions → Publish to PyPI → Run workflow**，选择对应版本的 `v0.x.y` 标签。保留仓库的 Actions 功能及现有 Trusted Publisher 绑定即可。

## Homebrew

`build_release.py` 生成 `domino.rb.in`，包含 runtime 的固定版本及 SHA-256。省略 `post_install`，安装不执行初始化；`caveats` 提示普通用户运行 `domino-install`。

发布者先上传原样 runtime 至稳定 HTTPS 地址，再将配方中的 `https://REPLACE-WITH-PUBLIC-ARTIFACT-HOST` 替换为该目录，保存为自建 tap 的 `Formula/domino.rb`。也可在首次构建时指定：

```bash
.venv/bin/python scripts/build_release.py \
  --base-url https://YOUR-ARTIFACT-HOST/releases/v0.17.0
```

配置公共地址不会自动上传。不要重新打包 runtime 后仍使用原配方的摘要。tap 仓库建议命名 `KJaebye/homebrew-tap`；配方已声明 `GPL-3.0-only`，仓库创建、推送与公共下载地址仍须正式发布时落实。

公共 tap 发布后，计划的用户命令为：

```bash
brew install KJaebye/tap/domino
brew upgrade KJaebye/tap/domino
brew uninstall KJaebye/tap/domino
```

发布前还需对公开 URL 执行真实 `brew install` / `brew test` 并检查 `brew audit`；目前的本地配方语法检查不能替代公开 tap 验收。本轮没有申请 Homebrew core 收录。

## Ubuntu apt

本地安装已生成的 deb：

```bash
sudo apt install ./dist/distribution-0.17.0/domino-proxy_0.17.0-1_all.deb
domino --version
# 如需本机服务，以当前普通用户运行，不加 sudo：
domino-install
```

Debian 元数据默认使用项目 owner 的 GitHub noreply 身份；维护者可通过 `--maintainer 'Name <public-email@example.org>'` 替换为正式公开联系地址。包不提供会调整用户文件的维护脚本，也不声明系统级自动服务。

公开 apt 源需要一个已有、由维护者安全保存的 GPG 签名密钥，脚本不创建或上传密钥：

```bash
.venv/bin/python scripts/build_distribution.py \
  --output /path/to/new-signed-distribution \
  --maintainer 'Name <public-email@example.org>' \
  --sign-key FULL_EXISTING_GPG_KEY_FINGERPRINT
```

输出增加 `InRelease`、`Release.gpg` 和 `domino-archive-keyring.gpg`（只有公钥）。生成后用 `gpg --verify .../apt/dists/stable/InRelease` 验证，再将整个 `apt/` 原样托管到稳定 HTTPS 地址。签名依赖当前 gpg-agent 的解锁状态；失败不会留下看似完成的输出目录。更新仓库时保留旧 pool 包，先传新包和索引，再发布 Release / 签名；脚本每次生成的是独立仓库快照，上传时合并旧 pool，不能覆盖掉仍在使用的旧包。托管与签名私钥备份由发布者维护。

未来公开源安装示例，**YOUR-APT-HOST 与 FINGERPRINT 均为占位符**：

```bash
curl -fsSL https://YOUR-APT-HOST/domino/domino-archive-keyring.gpg -o /tmp/domino-archive-keyring.gpg
gpg --show-keys --with-fingerprint /tmp/domino-archive-keyring.gpg
# 从另一可信渠道核对 FINGERPRINT，再安装公钥：
sudo install -m 644 /tmp/domino-archive-keyring.gpg /usr/share/keyrings/domino-archive-keyring.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/domino-archive-keyring.gpg] https://YOUR-APT-HOST/domino stable main' \
  | sudo tee /etc/apt/sources.list.d/domino.list
sudo apt update
sudo apt install domino-proxy
```

后续先 `sudo apt update`，再 `sudo apt install --only-upgrade domino-proxy`；移除用 `sudo apt remove domino-proxy`。不用 `apt-key`、`trusted=yes` 或允许未认证软件包。参考 [Debian 维护脚本与包管理规则](https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html)。

## 服务、升级与卸载边界

包管理器维护 CLI。初始化仍保存用户级运行文件，但不替换 `~/.local/bin/domino`，包括 pipx 的符号链接；失败回滚同样保留该入口。源安装脚本和部署至另一台设备继续使用自包含的用户级 CLI。

从旧源安装切换渠道前，先用 `type -a domino` 找到当前入口。旧 `~/.local/bin/domino` 可能优先于 brew / apt：先停止服务、备份配置，并显式处理旧入口或调整 PATH，再验证 `command -v domino` 与 `domino --version`。初始化不自动清理旧入口。

CLI 包升级不等于内核升级，不重启服务、不改节点与系统代理。仅卸载 CLI 包会保留运行内核、配置库和服务文件；pip 不提供运行时清理钩子。要完整清理，先运行 `domino uninstall`，再使用原包管理器卸载 CLI，例如 `domino uninstall && pip uninstall domino-proxy`。前一步会确认删除配置和备份，并清理终端接入记录；详见 [卸载指南](USAGE.md#卸载与清理)。

仓库目前是私有仓库；仅给配方填入 GitHub Release 地址不能保证用户可下载。正式发布还需要可匿名下载、版本固定的 runtime 地址，以及公开 tap / PyPI Trusted Publisher / 签名 apt HTTPS 托管。三个渠道应交付同一源码版本，先构建并校验，再分别上传 wheel、runtime 与 deb / apt 索引；不要在发布步骤改包内容或把生产私钥交给构建脚本。

源安装的 shell 加载器使用 `/usr/bin/env python3`，避免引用随后被删除的安装临时 venv。移除 pip 环境或升级 brew Python 后，运行文件中的纯 Python shell helper 仍可由系统可用的 Python 3.9+ 执行。
