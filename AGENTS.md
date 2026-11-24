# Domino 开发与交付约定

本文件统一维护仓库开发约定。工程操作细节见 [交付指南](docs/DELIVERY.md)、[分发指南](docs/DISTRIBUTION.md) 和 [GitHub 身份与审批](docs/GITHUB_AGENT.md)。[Agent 接口文档](docs/AGENT.md) 描述软件的 JSON 协议，不是另一份开发约定。

## 当前里程碑与授权

- 已公开发布的版本是 1.2.3；之后的功能与修复统一累计到 1.3.0。`src/domino_cli.py` 的 `VERSION` 与 `pyproject.toml` 的版本保持一致。2026-11-24 按用户本轮正式发布意向准备 `release/v1.3.0`，该发布分支将 `BUILD_CHANNEL` 设为 `release`，不把既有 development 产物当作正式包。
- 用户已授权日常开发执行普通 commit，并要求推进 1.3.0 正式发布准备。先完成发布分支、全量检查和 PR；main 保持人工审批要求，审批前不合并或创建正式标签。生产发布须使用审核通过的固定源码与原始包，并满足本机凭据和维护者确认要求；发布候选、版本号或检查通过均不能描述为已公开发布。
- 2026-11-22 已完成本机正式 Domino 的公司现场技术验收：内网 DIRECT、正常证书校验、正式服务重启及独立 LaunchAgent 回归通过；用户已确认重启后 GitLab 与 data-eval 两个浏览器页面均正常，Mac 公司现场验收完成。最新源码的 Ubuntu 真机验收仍按用户要求留待之后，不反复要求恢复连接，也不将隔离 Linux 或 VPN 验证当作真机、公司现场验收。
- 保留已发布的 1.2.3 原始产物及 Debian 提交材料。Homebrew/Debian 官方收录与现有渠道维护是不同工作，不因普通开发自动继续提交或发布。
- 用户已授权按 PM 复审结果精简默认输出：聚焦动作结果与必要状态，路径、环境变量与操作说明通过 `--verbose` 查看；保留异常、恢复信息和现有 JSON 协议。

## 版本、构建与验证

- 软件版本使用三段 `X.Y.Z`，与 Mihomo 内核版本分别管理。1.3.0 发布后，按兼容修复、兼容功能、破坏性变更分别递增补丁、次、主版本；不改写历史版本或编造发布记录。
- 代码交付记录实际变更与验证范围。纯说明性文档改动不升软件版本、不重建软件包；仅维护分发流程时复用指定正式版本的原始产物，不为工具变更重建已发布的软件。
- 小功能和局部修复运行受影响的聚焦检查及必要的产物冒烟。较大重构、正式发布前或用户明确要求时运行完整回归；不因每批修改重复执行全量测试，不为低影响文档整理增加实现镜像测试。
- 需要交付软件产物时，在适当验证后运行 `.venv/bin/python scripts/build_release.py`。当前 1.3.0 开发构建使用全新 `--output` 目录区分源码快照，保留先前产物，不覆盖同名已构建文件；这不代表创建新正式版本。
- 默认正式产物沿用 `dist/release/` 平铺及历史归档规则，详见交付指南；不默认改成版本子目录。`dist/`、虚拟环境、用户配置、凭据和本机验证报告不提交 Git。
- 校验本轮产物的 SHA256SUMS、wheel METADATA 和源码清单，在临时 HOME、源码目录外执行 wheel/runtime 冒烟；区分源码回归、产物检查、安装验收与公共发布，旧报告不作为新改动的通过证明。
- 交付说明本轮源码/产物版本、路径、实际检查结果、跳过项及安装版是否同步；不宣称未实测的平台已通过。
- `--version` 保持纯版本号；`status` 区分管理 CLI 开发版本、构建指纹、运行时快照与内核版本，构建不一致时明确提示。

## 命令与显示

- 本机使用 `domino CMD`，远端使用 `domino USER@IP CMD`，支持 IP 与 SSH 别名；新文档和调用使用目标前置。
- 配置管理使用顶层 `list/add/switch/update/remove/rename/set-url`，旧 `configs` 组仅保留隐藏兼容；TUI 使用对应斜杠命令。
- `select NAME` 表示当前配置的节点；交互多匹配进入候选菜单，非交互要求唯一匹配。`test NAME` 表示测速对象，不将名称推断为远端目标。
- 日志级别使用 `log [LEVEL]`，日志内容使用 `logs`。旧 `log-level` 人类命令已移除，不作为 CLI/TUI 别名或 SSH 目标；`delay` 仅保留隐藏兼容。机器协议的 `configs.*`、`delay.*` 操作名保持稳定。
- 交互终端的 `traffic` 默认内嵌动态面板并保留历史，内容与 `traffic --full` 一致，后者使用全屏；JSON/重定向默认单次采样。
- 人类命令结果前后各留一行，标题、内容区与提示之间各留一行，不出现连续两行空白；字段值按终端显示宽度对齐，换行延续同一值列。JSON、环境脚本、补全协议和动态面板保持各自原格式。
- 中英文界面遵循相同语义和布局；用户配置名、节点名、规则及机器字段不翻译。保留成功、未检测、失败、部分完成和恢复不完整的区别，不用重复教程替代实际结果。

## 平台与真实环境

- 默认终端接入：macOS 使用 Zsh（`.zshrc`），Ubuntu/Linux 使用 Bash（`.bashrc`）。不安装 Zsh 或更改登录 shell；保留另一种 shell 的既有集成与用户设置，两种补全脚本均继续提供。
- macOS 与 Ubuntu GNOME 日常服务开关使用 `start/stop/status`：start/restart 等内核就绪后接通系统代理，stop 先恢复仍由 Domino 接管的系统代理再停服。`proxy` 仅保留隐藏兼容；终端 `shell` 策略独立，不随系统代理开关自动改变。
- Ubuntu/Linux 使用 systemd；无 GNOME 会话时明确显示不支持桌面系统代理，不更改全局环境或终端策略。macOS 本地网络权限与应用身份的验证结果不得外推为 Linux 结论。
- `catch` 成功后按用户要求自动启动并接通系统代理；已有安装保留当前配置和节点选择，不自动切换新捕获项。普通包安装和 CLI 更新不因此自动改变系统代理。
- 源码修改、构建、安装版同步、服务重启与对外发布分别核对用户已有授权，不将源码修改扩大为真实环境变更，也不重复询问已经授权的步骤；更新 CLI 不顺带重启服务或 VS Code。
- 使用临时 HOME、合成配置、独立测试内核和受控服务验证；不为测试自动捕获、切换真实配置/节点、下载真实订阅或迁移现有安装。
- 远端部署不降级较新的目标 CLI。pipx/用户 venv 通过随包 wheel 离线同步并保留入口链接，完成后核验实际命令版本；系统包或未知环境不强制覆盖。只读管理不因版本差异自动升级。
- 远端部署显示完成前读回核验系统代理接通状态；无 GNOME 桌面如实报告不支持，终端策略保持独立。

## 凭据、Git 与 PR

- 根目录 `pypi-token` 是本机凭据，禁止读取、暂存、提交或上传。暂存使用明确文件列表，不使用会带入其他文件的批量操作。
- 不输出完整订阅 URL、节点凭据、控制密钥、原始私有配置或索引正文；构建不包含用户配置。公共 CLI runtime 与包含内核/节点凭据的私有部署 bundle 分开处理。
- commit、tag、推送与发布记录必须对应真实操作。普通 commit 的既有授权不延伸为推送、创建远端、合并、tag 或发布授权；已明确授权的外部步骤按原授权范围执行。
- 主仓库推送和创建 PR 使用本机已登录且具有仓库权限的 GitHub 账号；通过 `gh auth status` 核验身份，按用户授权执行 `git push` 或 `gh pr create --title ... --body-file ...`。不要求机器人身份、GitHub App 配置或 App 私钥。
- main 至少需要 1 人审批，用户 KJaebye 负责审批；Agent 不使用用户凭据代为审批，不提前合并，不修改保护规则或设置绕过名单。
- GitHub 凭据使用本机凭据管理器；不把私钥或 token 写入代码、日志、Git remote 或 GitHub Secrets。旧 GitHub App 工具仅保留兼容，不是日常操作前置条件。

## 分发与源码布局

- 经明确发布授权后，统一从本机 `.venv/bin/python scripts/release_channels.py publish --version X.Y.Z --channels all` 执行；`--dry-run` 仅演练，`--channels pypi/brew/apt` 可补发指定渠道，不依赖 GitHub Actions 额度。
- PyPI 使用 Twine 和维护者指定目录中的 Token TXT；Homebrew 沿用本机已有 gh 登录；APT 使用同目录 `gnupg/` 中的私钥及 `domino-apt-signing-passphrase.txt` 签名。分发凭据与主仓库认证分别管理，不上传私钥或解锁口令。
- 维护者明确要求 Domino 发布凭据统一放在 OneDrive `oetree/domino/tokens`，默认 `~/OneDrive/oetree/domino/tokens`；不用苹果钥匙串保存或读取 PyPI Token、APT 签名口令或备份解密密码。`domino-apt-backup-password.txt` 专用于解密 `domino-apt-recovery-*.tar.gpg`，与签名口令不同。所有凭据留在仓库外，目录 0700、文件 0600；修改此流程时保留 TXT 读取方式，不擅自恢复钥匙串存储。
- 维护已有版本先复用原始公开产物并核对摘要，仅恢复失败渠道；内容冲突或降级即停止，不移动软件标签、不覆盖已发布文件。`release-status.json` 的单渠道完成不代表全部渠道通过，公开摘要校验与真实安装验收分别记录。
- `.github/workflows/release.yml` 等工作流仅提供可选测试/隔离验收，不发布软件、不读取生产私钥。
- Python 实现放在 `src/`，维护工具放在 `scripts/`，根目录不新增实现模块。开发使用虚拟环境 editable 安装及 `.venv/bin/python ./domino COMMAND`；独立 runtime/部署包维持 `cli/` 模块布局，不将仓库的 `src/` 路径带到目标设备。
