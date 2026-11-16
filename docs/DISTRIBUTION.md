# pip、Homebrew 与 apt 分发

三个渠道只安装管理命令。包安装、升级、卸载不会初始化本机服务、捕获配置、调整系统代理或改 shell 文件。需要本机代理时，以普通用户显式运行 `domino-install`；已有离线部署包时也可使用 `domino init --bundle /path/to/bundle.tar.gz`。仅管理远端设备则无需初始化本机服务。

**当前为发布准备阶段。** PyPI、Homebrew tap 和 apt 公共地址尚未发布；下文标有占位符的命令不能直接作为公开安装入口。不要安装 PyPI 上的 `domino`：该名字属于另一个项目。本项目准备使用发行包名 `domino-proxy`，可执行命令保持 `domino`。名字尚未预留，实际发布前需再次检查。

| 渠道 | 发行名称 | 管理命令 | 平台 |
| --- | --- | --- | --- |
| pip / pipx | `domino-proxy` | `domino`、`domino-install` | macOS、Ubuntu；Python 3.9+ |
| Homebrew 自建 tap | `domino` | 同上 | 首先验收 macOS；配方使用 Python 3.13 |
| apt / 本地 deb | `domino-proxy` | 同上 | Ubuntu 22.04 / 24.04，amd64 / arm64 |

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

`Distribution smoke tests` 是手动 CI：Ubuntu 使用临时 GPG 密钥构建并验证签名 apt 源，实际安装/卸载；macOS 使用本地 runtime 和临时 tap 安装/卸载。均检查查询命令不改临时 HOME。CI 密钥仅用于该次测试，不作为生产签名密钥。工作流已准备不代表远端验收已执行。

## pip / pipx

可先安装本地 wheel，包名已从旧开发版 `domino` 改为 `domino-proxy`：

```bash
python3 -m venv ~/.venvs/domino
~/.venvs/domino/bin/python -m pip install ./dist/release/domino_proxy-0.17.0-py3-none-any.whl
~/.venvs/domino/bin/domino --version
# 仅需要本机服务时运行：
~/.venvs/domino/bin/domino-install
```

`pip install` 会解析 UI/YAML 依赖，因此除已准备离线 wheelhouse 外需要网络。Ubuntu 系统 Python 可能限制全局 pip 写入，优先 venv 或 pipx，不使用 `sudo pip`、`--break-system-packages`。

公开发布后计划使用：

```bash
pipx install domino-proxy
pipx upgrade domino-proxy
pipx uninstall domino-proxy
```

不要把旧 `domino` 发行包与新包装在同一个环境，两个发行包提供同名命令。旧开发环境先确认 `python -m pip show domino` 指向本项目，再卸载旧包、安装新包；不能误删同名的其他项目。也可以新建独立环境。

`.github/workflows/publish-pypi.yml` 仅手动触发，只接受与源码版本精确匹配的 `v0.x.y` 标签，并要求仓库有非空 LICENSE。真正上传还需要：

1. 核对已选定的 `GPL-3.0-only`、LICENSE 与第三方声明已随发行包交付。
2. 在 PyPI 账号创建 `domino-proxy` 的待发布项目 / Trusted Publisher：owner `KJaebye`、repository `domino`、workflow `publish-pypi.yml`、environment `pypi`。
3. 在 GitHub 设置 `pypi` environment 的发布审批与标签限制；Trusted Publisher 的配置必须一致。
4. 完成平台验收后，在对应版本标签上手动运行 `Publish to PyPI`。

工作流使用短期 OIDC 凭据，不在仓库保存 PyPI token。参考 [PyPA 官方发布指南](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)。工作流文件的存在不会自动发布；普通 push 不触发上传。

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

后续 `sudo apt upgrade domino-proxy`，移除用 `sudo apt remove domino-proxy`。不用 `apt-key`、`trusted=yes` 或允许未认证软件包。参考 [Debian 维护脚本与包管理规则](https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html)。

## 服务、升级与卸载边界

包管理器维护 CLI。初始化仍保存用户级运行文件，但不替换 `~/.local/bin/domino`，包括 pipx 的符号链接；失败回滚同样保留该入口。源安装脚本和部署至另一台设备继续使用自包含的用户级 CLI。

从旧源安装切换渠道前，先用 `type -a domino` 找到当前入口。旧 `~/.local/bin/domino` 可能优先于 brew / apt：先停止服务、备份配置，并显式处理旧入口或调整 PATH，再验证 `command -v domino` 与 `domino --version`。初始化不自动清理旧入口。

CLI 包升级不等于内核升级，不重启服务、不改节点与系统代理。卸载 CLI 前如需结束本机代理，先 `domino stop`；卸载包保留配置库、运行内核与服务文件，不作为运行环境卸载器。跨渠道迁移和完整运行环境清理由用户显式处理。

源安装的 shell 加载器使用 `/usr/bin/env python3`，避免引用随后被删除的安装临时 venv。移除 pip 环境或升级 brew Python 后，运行文件中的纯 Python shell helper 仍可由系统可用的 Python 3.9+ 执行。
