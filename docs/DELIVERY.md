# 交付状态与版本管理

仓库开发约定统一维护在 [AGENTS.md](../AGENTS.md)；本页记录交付流程与验收范围。[Agent 接口文档](AGENT.md) 单独描述软件的机器协议。

## 1.3.0 当前里程碑（未发布）

用户要求本轮功能与修复累计在 1.3.0，期间只提交普通 commit。`BUILD_CHANNEL` 保持 `development`；只有明确授权后才能标记 release、创建 tag 或发布，不因构建成功或测试通过自动发布。

已完成安装结果统一、状态语义、macOS/Linux 只读 doctor 与 TUI 入口、套餐新鲜度/到期、构建身份和恢复范围提示。CLI 首页推荐下一步，查询不自动初始化服务或修改启动文件。详细变化见变更记录。

本轮本地验证：Mac 全量 788 项，0 失败、2 项环境跳过；修订后的系统 hosts 出站回归另行通过。隔离 Debian ARM64 全量 786 项，0 失败、33 项平台/可选 shell 等跳过，使用普通用户、Bash 和独立 Mihomo；包括独立 dconf/DBus 的代理应用与恢复。Linux 环境未安装 Zsh。wheel/runtime 和隔离 pip 安装、从 1.2.3 升级及卸载均已验证。测试环境使用 Debian 自带 Python；这是 Linux 补充检查，不作为 Ubuntu 真机安装验收。

仍待完成：最新源码在 Ubuntu 真机上的 systemd、桌面代理、重启自启和 Bash 接入；正式 Mac 应用在公司局域网的内网访问与重启重复验证。公司外 OpenVPN + 既有系统 hosts 的浏览器访问已由用户确认，但不能替代公司现场验收。Ubuntu 当前暂不可连接，用户已要求真机验收留待之后。

本轮详细报告保存在本机 `dist/v1.3.0-usability/`；这些报告不自动随源码分发，也不将模拟或跳过项目记为通过。公共 PyPI、Homebrew、APT 产物保持原样。

## 版本规则

- 用户已指定 `1.0.0` 为正式发布版本，采用三段版本号 `X.Y.Z`；兼容修复递增补丁号，兼容功能递增次版本号，破坏性变更递增主版本号。保留末尾 `.0`，历史 `0.x.y` 版本不改写。
- 当前 1.3.0 里程碑按用户要求累计开发变更，保持 `src/domino_cli.py` / `pyproject.toml` 版本一致，记录实际代码变更；不同开发快照使用全新 `--output` 目录构建，不覆盖旧产物。正式发布后，后续交付按上述语义版本规则编号；纯说明性文档修改不升版本、不重建软件包。
- 历史 `0.13.0` 曾归档未逐次编号的功能与修复；旧 `0.12.0` 产物保留，不编造中间发布记录。本轮遵循上述 1.3.0 累计开发规则。软件版本不等于 Mihomo 内核版本。
- 源码、构建、安装版同步、服务重启和公共发布是独立动作；构建不会修改用户安装。真实安装同步仍需明确授权。

## 工程交付范围

以下为已有能力与验收边界，不表示所有平台或分发渠道均已验证：

| 顺序 | 工程交付 | 验证与剩余工作 |
| --- | --- | --- |
| 1 结果和展示分离 | 共享结果/类型化错误；状态、节点、规则、连接、provider、流量等数据接口不打印终端内容 | 保留原人类输出、旧 JSON 和 UI |
| 2 只读 Agent 协议 | 版本 1 JSON、非交互、能力/参数/结果发现 | 无 TTY、参数失败、未安装和健康失败有独立语义 |
| 3 结构化写操作 | 订阅、规则、节点、模式、系统代理、服务、provider、私有安装包、导出、上传与恢复；预检、修订校验、去重、操作记录与逐项批量结果 | 有界日志读取已开放；持续事件流仍待扩展，见 Agent 文档 |
| 4 本机/SSH 一致性 | 同版应用服务随 SSH 调用传输；结果分帧排除登录横幅 | 临时真实 OpenSSH 验证写入、去重、私有包上传与目标预检；不是指定 Linux 目标的完整服务安装实测 |
| 5 兼容配置导入 | 只读发现、扫描和导入 Clash/Mihomo 配置；支持 Verge 常见有效配置和只读 Unix socket 来源 | 管理操作仅针对 Domino 自有运行时；来源兼容性仍需验证 |
| 6 冷启动分发 | wheel、`domino-install`、带 UI/YAML 依赖的运行包、Homebrew 模板、可配置 HTTPS 内核/Geo 源和摘要校验 | PyPI 已发布 `domino-proxy`；公共 runtime 地址、Homebrew tap 与 apt 源仍待上线，见 [分发指南](DISTRIBUTION.md)；项目许可证为 GPL-3.0-only |
| 7 可靠性交付 | 安装/规则/模式失败恢复、独立操作记录、真实内核相邻复制回归、跨平台 CI 工作流 | 已验证 macOS ARM64；Linux ARM64/x86_64、macOS Intel 的真实安装与恢复矩阵尚未跑完 |

所有测试在临时目录/进程中运行，不替换测试机正在使用的订阅、节点或系统代理。相邻复制回归在删除源配置和停止上一实例后验证下一实例仍能通过本地代理请求；不代表已完成真实机场的跨设备网络验收。

## 构建本地发布产物

```bash
# 频繁开发的小功能只运行改动相关测试，例如：
.venv/bin/python -m unittest discover -s tests -p test_delay_configs.py
# 较大重构、正式发布前或明确要求时，才运行完整回归：
# .venv/bin/python scripts/verify.py
# 当前未发布的 1.3.0 开发快照使用全新输出目录，保留旧构建：
.venv/bin/python scripts/build_release.py --output dist/本次开发快照
# 正式交付目录沿用默认布局；构建本身不代表发布授权：
.venv/bin/python scripts/build_release.py
# 可选：SSH 载荷相关改动再运行受控 SSH 验证
# .venv/bin/python scripts/verify_ssh.py
```

沿用既有存放规则，不把默认目录改成 `dist/release/<版本>/`：

```text
dist/
  domino_proxy-0.17.0-py3-none-any.whl      # 各版本 wheel，旧包保留
  verification.json                  # 最近一次源码回归，不是安装同步证明
  installed-verification.json        # 实际安装验证记录，不因构建而改写
  ssh-verification.json              # SSH 验证记录，未重跑不能冒充当前通过
  release/
    domino_proxy-0.17.0-py3-none-any.whl
    domino-runtime-0.17.0.tar.gz
    domino.rb.in                     # 有 --base-url 时为 domino.rb
    release.json                     # 当前发行清单，published: false
    SHA256SUMS                       # 当前发行产物及清单的摘要
    history/0.12.0/                  # 更新固定名称文件前原样归档的旧发行
    history/0.13/                    # 更正版本名称前的构建，保留原始名称
```

`dist/release/` 中历史版本的 wheel/runtime 原地保留；当前清单只列本次产物，不将旧包混进新清单。已有旧发行须先通过原清单/摘要校验，再将其产物、Formula、清单与 SHA256SUMS 原样归档，随后更新当前固定名称文件；失败尝试恢复旧元数据并移除本次新包。旧版本归档已存在、旧清单损坏、输出为符号链接或同版本包已存在时拒绝构建。默认构建锁用于防止脚本并行交付；进程被强制终止时需人工检查锁、清单和历史归档，不宣称断电原子性。

runtime 含纯 Python UI/YAML 依赖及其许可证，不包含 Mihomo 内核或用户配置。当前未发布的 1.3.0 开发快照及同源码特殊复建可用 `--output` 指定全新目录，此时只生成该目录的独立产物，不更新默认 `dist/` 和 `dist/release/`；指定目录已存在（包括空目录或符号链接）则拒绝。新目录不代表正式版本，源码快照由产物清单标识；已发布版本的后续代码变更必须使用新版本号。

如已有公共地址，应在首次构建时指定 `--base-url https://你的发布域名/releases/0.17.0`，而不是向同一目录连续构建两次。也可为另一种分发形式显式选择新目录。模板地址必须替换为真实地址；生成带地址 Formula 也不会上传或发布。

构建暂存显式源码列表，wheel/runtime 使用同一份项目模块快照。`release.json` 记录 UTC 时间、Python 版本、逐文件源码摘要、构建脚本摘要、产物大小和 SHA-256；SHA256SUMS 同时覆盖产物和清单。构建中源码变化会失败；暂存完成后交付，版本化包使用排他创建，固定名称元数据最后更新，release.json 最后落地。只有当前 release.json 与 SHA256SUMS 及所有列出的产物相符才视为完成。源码摘要不是 Git commit，也不意味着构建字节级可复现。

交付前逐项校验 SHA256SUMS、wheel METADATA Version、模块与源码摘要，在临时 HOME、源码目录外实际运行打包 CLI 的 `--version`、`shell status`、`configs list`，区分源码回归与产物冒烟。可变的 `dist/verification.json` 不自动作为某个包的验证证书；只有本轮真实执行的测试才能报告为通过。构建需要当前环境已安装项目依赖和 setuptools；wheel 构建不从网络解析依赖，也不自动安装依赖。

pip、Homebrew 与 apt 包只安装 CLI，不执行服务初始化钩子。完整本机安装由普通用户显式执行 `domino-install`；发布脚本、签名 apt 源与渠道验收见 [分发指南](DISTRIBUTION.md)。

## 直连资源布局

配置 `DOMINO_RESOURCE_BASE=https://你的域名/domino/`，或：

```json
{"resource_base":"https://你的域名/domino/"}
```

保存至 `~/.config/domino/downloads.json`。支持以下布局：

```text
mihomo/latest.json
mihomo/v1.19.33.json
mihomo/v1.19.33/mihomo-darwin-arm64-v1.19.33.gz
mihomo/v1.19.33/mihomo-darwin-amd64-v1.19.33.gz
mihomo/v1.19.33/mihomo-linux-arm64-v1.19.33.gz
mihomo/v1.19.33/mihomo-linux-amd64-v1-v1.19.33.gz
geo/index.json
geo/Country.mmdb
geo/geoip.dat
geo/geosite.dat
geo/ASN.mmdb
```

内核 JSON 与官方 release 的相关字段兼容：`tag_name`、`prerelease: false`、`assets[]` 中的 `name`、`digest: sha256:...`、当前资源目录下的 `browser_download_url`。Geo 索引为 `{"schema_version":1,"files":{"Country.mmdb":{"sha256":"64位摘要"}}}`，按配置中的规则需要选择下载。Geo 地址字段沿用 [Mihomo 官方配置](https://wiki.metacubex.one/config/general/)。

发布端先取得可信官方 release 元数据、匹配内核归档及 Geo 文件，再离线生成资源目录：

```bash
python3 scripts/build_resources.py --base-url https://你的域名/domino/ \
  --release-json release.json --archive mihomo-darwin-arm64-v1.19.33.gz \
  --archive mihomo-linux-arm64-v1.19.33.gz --geo-dir /path/to/geo
```

该工具核对内核归档与官方摘要，仅复制显式输入的公共文件，不读取用户订阅或节点。资源缺失/摘要错误会明确失败；用户订阅及其私有 provider URL 不在公共分发目录内。离线包依然需要在生成阶段完整取得订阅资源。

## 平台验证

`scripts/verify.py` 输出 `dist/verification.json`，记录系统、架构、Python、测试数和跳过项。`DOMINO_TEST_CORE` 可指定临时校验内核。GitHub Actions 的 `Verify` 保留 macOS / Ubuntu × Python 版本矩阵，仅通过 `workflow_dispatch` 手动运行或作为复用测试 workflow 调用；日常 push、PR 和标签推送不自动触发完整测试。真实执行结果以 CI 为准，未运行的矩阵不能记为通过。

三渠道统一发布在本机运行 `.venv/bin/python scripts/release_channels.py publish --version X.Y.Z --channels all`；先用 `--dry-run` 演练，或用 `--channels` 补发单个渠道。Twine、Homebrew 推送、APT 签名与上传均在本机完成，不要求 Actions 额度，也不把私钥放到 GitHub。已发布版本复用原始产物，不因发布工具改动重建软件或升版本。详情见 [分发说明](DISTRIBUTION.md#一个本机流程发布三个渠道)。`release.yml`、`Verify` / `Distribution smoke tests` 只提供可选测试入口；真实安装通过须有运行记录。

`scripts/verify_ssh.py` 仅监听回环地址，临时生成测试密钥并启动用户级 sshd，使用临时 HOME 执行写操作，结束后停止进程和清理目录；某些系统不允许普通用户启动 sshd 时返回未验证状态，不修改系统 Remote Login。


## GitHub 发布准备

1. 在干净检出中安装 `.[dev]`，运行 `scripts/check_repository.py`，确认公开文件、文档链接、最低 Python 语法和凭据模式检查通过。
2. 按 [平台支持](PLATFORMS.md) 运行完整 CI；本地完整回归显式设置临时 `DOMINO_TEST_CORE`，使用 `scripts/verify.py --require-core`。
3. 同步版本、更新变更记录，运行 `scripts/build_release.py` 和 `scripts/verify_artifacts.py`；再用 `python -m twine check dist/release/*.whl` 检查包元数据。
4. `scripts/release_channels.py publish` 是唯一本机发布入口，固定软件标签和产物后分发 GitHub Release、PyPI、Homebrew 与签名 APT 源，私钥留本机。`release.yml` / `Verify` / `Distribution smoke tests` 仅手动测试，不发布。
5. 人工确认许可证、第三方声明和本轮平台结果，再创建与版本一致的 Git tag / GitHub Release，仅上传公共 CLI 产物。不要上传 `domino export` 生成的私有部署包、用户配置或本机报告目录。

公共 runtime 和 wheel 都包含 README、文档、动图及第三方声明。仓库源码以 `MANIFEST.in` 限定源码分发内容；不包含缓存、虚拟环境、内核或私有配置。Actions 固定提交 SHA，并使用只读仓库权限；依赖更新通过 Dependabot 提议。
