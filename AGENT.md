# Domino 开发与交付约定

## 版本与构建

- 用户要求：每完成一批可交付的代码更新或 debug 修复，管理版本、记录变更、验证并构建，不让不同代码长期共用一个版本。
- 不对每个中间编辑/失败重试反复升版本；未完成或测试失败不能声明交付成功。纯说明性文档改动通常不新增软件版本。
- 用户明确：仅维护分发工具、渠道或发布流程时，不提升 Domino 软件版本；直接复用既有正式版本的原始产物，发布流程单独记录修订与状态。本轮软件版本保持 1.2.3，不重建或覆盖已发布的软件包。
- 用户已指定正式发布 `1.0.0`，版本统一使用三段 `X.Y.Z`；后续兼容修复递增补丁号、兼容功能递增次版本号，破坏性变更递增主版本号并明确记录影响。保留末尾 `.0`；历史 `0.x.y` 产物和记录不改写。
- 同时更新 src/domino_cli.py 的 VERSION、pyproject.toml 的 [project].version、CHANGELOG.md 的日期与实际变更；这是 Domino 版本，不是 Mihomo 内核版本。
- 不倒推编造未记录的历史版本，也不删除旧 dist 产物。已构建同版本后若继续修改代码，下一次交付应升版本，不覆盖旧包。
- 用户处于频繁开发阶段：小功能更新和局部修复只运行受影响的聚焦测试与必要的产物冒烟，不默认执行全量回归。较大重构、正式发布前或用户明确要求时再运行 `.venv/bin/python scripts/verify.py`；不要因每批构建都重复跑全量。
- 每批交付按上述范围验证后运行 `.venv/bin/python scripts/build_release.py`。报告本轮实际执行的检查；旧全量报告不能作为新改动的通过证明。
- 沿用既有 dist 存放规则：`dist/` 保留版本化 wheel 与各类验证报告，完整发行产物平铺在 `dist/release/`，不默认增加版本子目录。更新固定名称清单/Formula 前，将上一份完整发行产物原样归档到 `dist/release/history/<旧版本>/`；旧版 wheel/runtime 不删除、不覆盖。相同版本拒绝重复构建；特殊复建可显式指定全新 `--output`，但不能用它掩盖改了代码却未升版本。
- 交付时校验 SHA256SUMS、wheel METADATA、源码清单，在临时 HOME、源码目录外运行 wheel/runtime CLI 冒烟；报告真实通过和跳过情况，不宣称未测试平台已通过。
- 输出交代源码/产物版本、路径、测试结果、安装版是否同步。源码回归与产物冒烟是不同验证，不把旧 verification.json 冒充当前构建证明。

## 命令语法

- 本机使用 `domino CMD`，远端使用 `domino USER@IP CMD`（支持 IP / SSH 别名），所有新文档和调用都使用目标前置。
- 配置管理使用顶层 `list/add/switch/update/remove/rename/set-url`；旧 configs 组仅保留隐藏兼容。TUI 使用对应斜杠命令。
- `select NAME` 只表示当前配置的节点；交互时多匹配进入候选菜单，非交互仍要求唯一匹配，`test NAME` 只表示本机测速对象，不推断 NAME 为远端。交互终端的 `traffic` 默认内嵌完整动态面板并保留历史，内容和功能与 `traffic --full` 相同，只有后者使用全屏，JSON / 重定向保留单次采样；日志级别使用 `log [LEVEL]`，日志内容使用 `logs`；旧 `log-level` 命令已移除，不保留 CLI/TUI 别名，也不把它误作 SSH 目标；旧 `delay` 仅保留隐藏兼容；协议操作名 `configs.*`、`delay.*` 保持稳定，不随人类命令名称修改。

- macOS 与 Ubuntu GNOME 桌面的日常开关统一使用 `start/stop/status`：start/restart 等待内核就绪后接通系统代理，stop 先恢复系统代理再停服，status 一并展示；原 proxy 命令仅保留隐藏兼容。终端 shell 策略保持独立；Ubuntu / Linux 使用 systemd 管理服务，无 GNOME 会话时明确显示无桌面系统代理，不更改终端策略或全局环境。按用户要求，catch 成功后自动启动并接通系统代理；已有安装保留当前配置和节点选择，不自动切换新捕获项。普通安装和 CLI 更新不因该联动自动改变系统代理。

## 环境与安全边界

- 远端部署按用户要求以较新 CLI 兼容旧部署格式，不降级目标较新版本。pipx / 用户 venv 的旧命令通过随包 wheel 离线同步，保留入口链接，部署完成核验实际命令版本；系统包或未知环境不强制覆盖。远程部署在显示完成前自动接通并读回核验目标系统代理，不能要求用户另跑 start；无 GNOME 桌面时如实显示不支持，终端代理策略保持独立。普通只读管理命令不因版本差异自动升级。

- 构建不等于安装同步，不等于对外发布。修改安装版 CLI、环境加载器、rc 文件、服务配置或真实代理设置，需要用户明确授权；更新 CLI 不顺带重启服务或 VS Code。
- 不自动 catch、切换配置/节点、下载真实订阅或迁移现有安装来验证代码。使用临时 HOME、合成配置和受控服务。
- 不输出订阅完整 URL、节点凭据、控制密钥、原始私有配置或索引正文；构建不能带入用户配置。CLI runtime 包与包含内核/配置的私有部署 bundle 不同。
- 项目按用户授权纳入 Git 管理；commit/tag 必须对应真实操作，不得虚构。初始化、提交、推送、创建远端或对外发布均须用户明确授权，不因完成代码改动就自动执行。dist、虚拟环境、用户配置和凭据不入库；构建清单继续用源码摘要标识输入。

详细流程见 docs/DELIVERY.md；版本记录见 CHANGELOG.md。

## 统一分发

- 唯一发布入口是在本机运行 `.venv/bin/python scripts/release_channels.py publish --version X.Y.Z --channels all`；`--dry-run` 只演练，`--channels pypi/brew/apt` 只恢复一个渠道。发布不依赖 GitHub Actions 的额度。
- PyPI 用 Twine 读取 macOS 钥匙串；Homebrew 使用钥匙串中的专用部署私钥；APT 使用仓库外的 GPG 私钥与钥匙串口令，在本机签名后推送公开静态源。私钥、token 和解锁口令不提交 Git，也不上传 GitHub Secrets；GitHub 仅保存公钥、指纹、签名与公开产物。
- `.github/workflows/release.yml` 仅提供可选的只读测试与隔离安装验收，不发布软件、不读取生产私钥。其余测试 workflow 同样不是发布入口。
- 发布已有版本先复用 GitHub Release 原始文件，核对各渠道摘要。成功文件不重复上传，只恢复失败渠道；内容冲突或降级直接失败。不为工具更新移动软件标签或重建已发布的软件包。
- Agent 查看本机运行目录的 `release-status.json`。`complete=true` 仅表示三个渠道都通过本次核验；补发单渠道只记录 `request_complete`，不推断其他渠道。公开摘要 / 签名校验与真实安装验收分开报告。详细存储位置与命令见 docs/DISTRIBUTION.md。

## 源码布局

- Python 实现放在 `src/`，维护工具放在 `scripts/`，根目录不新增实现模块。开发先在虚拟环境执行 editable 安装；源码入口为 `.venv/bin/python ./domino COMMAND`。独立 runtime / 部署包的 `cli/` 模块布局保持兼容，不把仓库的 `src/` 路径带到目标设备。
