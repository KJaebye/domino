# 多米诺 · Domino

Domino 提供完全命令行的代理安装和管理，仅管理自己安装的 Mihomo 运行时。在本机初始化独立 Mihomo 服务，或将当前生效的 **Clash/Mihomo 节点、分流规则和选中节点**部署到指定 Linux 设备。外部配置和当前节点选择仅作为只读导入来源，不接管外部客户端。部署后目标设备不依赖源电脑在线。

```bash
domino                         # 只显示常用操作，不修改系统
domino catch                   # 捕获本机外部代理配置，确认后交给 Domino 独立运行
domino nvidia@192.168.8.21      # 将翻墙能力复制到指定电脑
```

当前版本自动发现 Mac 的 Clash Verge 配置，以及 Domino 已部署在本机的配置，也支持 `--source` 指定 Clash/Mihomo 配置，或 `--subscription` 提供完整配置订阅。本机 macOS（Apple Silicon / Intel）和使用 systemd 的 Linux（ARM64 / x86_64）通过 `./install.sh` 一次安装管理程序、内核和后台服务。通过 SSH 部署的目标仍支持使用 systemd 的 Linux ARM64 和 x86_64。这里迁移的是兼容的节点配置；不支持直接克隆专用隧道客户端的登录状态或设备证书，不接管目标系统的默认路由。

保留源配置的规则模式或全局模式，以及可获取的当前节点选择。源客户端处于 `direct` 模式时停止迁移，避免将直连误当作已开启的代理。

## 命令格式

裸 `domino` 仅显示捕获、远端部署、状态、节点、控制台和完整帮助等常用入口，不扫描、不安装、不重启服务；全部顶层命令仍通过 `domino -h` 查看。使用 `domino catch` 捕获本机外部配置；直接使用 `domino USER@IP` 部署到指定电脑，无需先执行 catch 或单独预检查。其他管理操作使用下述命令组。部署参数可用 `domino USER@IP -h` 查看。

### 捕获本机代理配置

```bash
domino catch                             # 自动发现外部来源，确认后导入
domino catch --source '/path/config.yaml' # 明确选择配置来源
```

`catch` 自动发现已知 Clash Verge / Clash / Mihomo 配置，排除本机 Domino 和旧版 robot-clash 自有配置。只有一个兼容来源时采用该来源；多个来源时请用户选择，不按文件顺序猜测哪个正在使用。没有发现配置时可用 `--source` 指定；仅有本地代理端口、专用 App 登录或 TUN 在线并不足以独立迁移。`scan` 仍然只读检查，不导入配置。

导入前显示来源文件、目标为本机、端口、配置替换、服务重启及环境影响，默认不执行，只有明确确认后才安装。会保存部署前备份，沿用安装器的失败恢复机制；不会关闭或修改外部客户端，也不会自动开启系统代理或 TUN。终端代理集成及已有策略按当前安装器规则保留或迁移；服务出网成功不代表所有应用已切换至 Domino。

捕获保留文件中的规则/全局模式，并只读查询本机控制接口以尽量保留当前手动节点选择；不是完整的客户端运行态快照。没有控制接口时会提示采用文件默认节点；已发现或指定的控制接口连接失败则停止，不静默降级。与之不同，兼容入口 `domino init --source ...` 仍按静态文件导入，不连接来源控制接口。捕获不会自动关联外部客户端的完整订阅管理记录；成功后会保存 Domino 自有的导入源快照，登记为本地配置快照并设为当前项。已有在线订阅即使同名也不会被覆盖或借用地址，其他发现配置不会自动导入。同一可靠来源再次捕获会更新对应快照，保留用户重命名；无法可靠区分的来源采用保守的内容身份，不仅凭运行文件名覆盖旧项。

脚本可用 `domino catch --source PATH --yes --batch`：`--yes` 明确接受导入/替换影响，`--batch` 仅禁止 sudo 密码询问；两者不能互相替代。`--yes` 不替代多来源选择，非交互多来源必须通过 `--source` 指定。完整捕获选项见 `domino catch -h`；catch 暂不提供机器协议或 TUI `/catch` 操作。

资源操作优先采用 `domino <对象> <动作> [参数] [目标] [选项]`。动作使用位置参数；`--json`、`--batch`、`--service` 等选项控制输出、执行条件或附加配置。本机目标可以省略，查询可以使用对象的默认动作。

```bash
domino configs                          # 默认 list
domino configs list
domino configs add '机场A'
domino configs switch '机场A'
domino configs update all
domino rules add 'DOMAIN-SUFFIX,example.com,DIRECT'
domino proxy                         # 默认 status
domino proxy status
domino proxy on
domino proxy off                      # 恢复开启前保存的系统代理设置
domino shell                          # 默认 status，独立的终端代理策略
domino shell on
domino shell off                      # 已接入终端恢复仍由 Domino 管理的原变量
```

CLI、UI 的 `/对象 动作` 形式及后续 Agent 能力描述使用同一命令树。其他现有命令沿用当前语法，后续按所属功能逐步归组；新增资源操作遵循上述约定。

`domino -h` 只列出顶层命令和命令组。具体操作放在各组的帮助中，例如 `domino configs -h`、`domino rules -h`、`domino proxy -h`；使用 `domino configs add -h` 查看某个操作的参数。子操作使用普通文字，说明列保持对齐。

## 本机命令行控制台

0.6.0 起，本机支持 macOS 用户级服务，并提供纯终端交互菜单和独立子命令。无需依赖 Clash 图形界面保持运行。

```bash
# 一次安装管理程序、内核、基础配置和后台服务，无需提前准备订阅
./install.sh

# 安装后添加订阅，地址默认隐藏输入；切换后即可使用
~/.local/bin/domino configs add '机场A'
~/.local/bin/domino configs switch '机场A'

# 只有需要其他端口时才填写；默认代理端口 17897、控制端口 19091
./install.sh --proxy-port 17898 --api-port 19092
```

安装、跨设备部署和 `export` 默认使用代理端口 `17897`、API 端口 `19091`，无需填写端口参数。没有订阅时会显示“待添加订阅”：后台服务和控制接口已经就绪，基础配置拒绝代理流量，尚不具备代理出网能力。全新 macOS / Linux 安装默认关闭系统代理和终端代理策略；安装 shell 加载器并不代表开启代理，重装和迁移的策略保留规则见下文。配置好订阅后，macOS 系统代理可用 `domino proxy on`，终端代理独立用 `domino shell on`。安装成功后运行 `~/.local/bin/domino ui` 进入持续交互工作台；`~/.local/bin` 已在 PATH 中时可直接使用 `domino ui`。

重复运行安装程序时保留已有配置作为来源，优先复用已安装版本对应的内核压缩包缓存，并按照安装记录中的 SHA-256 重新校验。缓存缺失或校验失败、首次安装、显式指定 `--mihomo-version` 时仍查询官方版本信息。下载错误会区分订阅、provider、GitHub 版本信息和内核安装包。重新安装会重启服务；日常更新订阅使用 `domino configs update "名称"`。

```bash
domino ui
domino ui localhost
```

界面左上角显示三行高的青绿色 DOMINO 文字 Logo，版本、目标、订阅、模式、接口状态、代理端口和节点/策略组数量排列在右侧。窄窗口或高度不足时自动使用两行紧凑标题，长名称会截断，接口状态仍保持可见。中间保留操作记录，初始留白；底部输入区只保留上下细线和 `❯`，状态栏压缩为一行。输入 `/` 查看命令，`/nodes` 打开无边框的搜索式策略组与节点面板，使用方向键和 Enter 选择。退出界面不会停止代理服务。所有管理子命令均支持省略目标或填写 `localhost`；填写 `USER@IP` 则通过 SSH 管理远端。

```text
/nodes                  搜索策略组和节点
/mode                   选择规则 / 全局 / 直连模式
/mode global            直接切换到全局模式
/delay                  测试全部节点延迟
/delay 自动选择         测试指定组；也可填写节点名称
/status                 检查实际 HTTPS 出网
/proxy status           查看系统代理；/proxy on、/proxy off 开启或恢复
/shell status           查看终端代理策略；/shell on、/shell off 切换
/scan                   扫描当前目标的配置及代理入口出网
/connections            查看连接
/traffic                查看累计流量、统计范围和刷新时间
/rules google           搜索规则
/rules add "DOMAIN-SUFFIX,example.com,DIRECT"  新增并置顶规则
/rules --custom         查看自定义规则原文
/configs          查看和管理多个完整配置订阅
/help                   查看命令
exit 或 /exit           退出界面
```

Tab 补全命令，↑↓ 导航或查阅输入历史，Enter 确认，Esc 返回；节点面板中 Ctrl+T 测试高亮节点，输入 `/refresh` 刷新状态，PgUp/PgDn 浏览操作记录，Ctrl+L 清空记录，Ctrl+D 或输入 `exit` 退出（`/exit` 也支持）。Ctrl+D 在输入框有文字或节点筛选面板中也表示退出，不再删除字符；退出 UI 不停止代理服务。只读查询和测速可以用 Ctrl+C 中断；设置正在提交时会等待完成。需要管理员认证的操作会临时释放终端，完成后返回工作台。

状态栏每 2 秒读取控制接口和流量计数，平时只显示实时速率、连接数和命令入口；操作面板打开时显示当前操作的快捷键。累计上传/下载、统计范围和刷新时间可通过 `/traffic` 查看，完整用法通过 `/help` 查看，不会反复发起外网测速。速率按 B/s、KiB/s、MiB/s 自动选择单位，小流量不会一律舍入为 0.0 KiB/s；尚未完成采样时显示 `—`，刷新失败时给出重试提示。macOS 的系统代理若未开启、指向其他端口或使用 PAC，底栏会保留简短提示：经过其他客户端的流量不会计入 Domino。如需切换，可在界面执行 `/proxy on`。“接口在线”不等于代理出网成功；使用 `/status` 进行实际出网验证。操作记录和输入历史仅保留在本次会话中。

新界面使用 prompt-toolkit。通过 pip 安装 Domino 时自动安装依赖；部署包会携带源环境可用的 UI 组件，目标无需另行 pip 下载。使用源码生成完整部署包前，建议先在虚拟环境安装项目依赖。离线包升级管理程序时会保留携带的 UI 组件和许可证。

`domino -h` 只列出顶层命令和命令组。组内操作在对应帮助中查看，例如 `domino configs -h`、`domino rules -h`、`domino proxy -h`；单个操作的参数可继续用 `domino configs add -h` 查看。

| Clash 中的常用功能 | 命令行操作 |
| --- | --- |
| 状态、版本、当前模式、实际出网 | `domino status` |
| 策略组与当前节点 | `domino nodes` |
| 查看组内候选节点 | `domino nodes --group '组名'` |
| 切换节点 | `domino select --group '组名' --node '节点名'` |
| 规则 / 全局 / 直连模式 | `domino mode --set rule` / `global` / `direct` |
| 单节点延迟测试 | `domino delay '节点名'` |
| 全部节点延迟测试 | `domino delay` |
| 指定节点 / 组内各项延迟测试 | `domino delay '节点或策略组名'` |
| 活跃连接、命中规则和实际节点 | `domino connections` |
| 关闭指定连接 / 全部连接 | `domino connections --close '连接ID'` / `domino connections --all` |
| 实时速率、累计流量和连接数 | `domino traffic --watch` |
| 搜索分流规则 | `domino rules --match google` |
| 添加 / 删除自定义规则 | `domino rules add '完整规则'` / `domino rules remove '完整规则'` |
| 查看自定义规则原文 | `domino rules --custom` |
| 查看节点 / 规则集合 | `domino providers` / `domino providers --kind rule` |
| 更新指定 HTTP / file 集合 | `domino providers --update '集合名'` |
| 查看 / 修改日志级别 | `domino log-level` / `domino log-level --set info` |
| 最近日志 / 跟随日志 | `domino logs` / `domino logs --follow` |
| 服务启停 | `domino start` / `domino stop` / `domino restart` |
| macOS 系统代理状态 / 开启 / 恢复原配置 | `domino proxy status` / `domino proxy on` / `domino proxy off` |
| 终端代理策略状态 / 开启 / 恢复原变量 | `domino shell status` / `domino shell on` / `domino shell off` |

状态、节点、模式、连接、流量、规则和 provider 查询支持 `--json`。模式和日志级别在控制接口读回确认后写入本地配置，服务重启后保留。节点选择由 Mihomo 自身的持久化缓存保存。

`domino status` 默认显示中文摘要：优先突出代理出网结果、订阅、模式和出口地区，再列出服务/自启动、代理地址和内核版本；macOS 额外显示系统代理是否指向 Domino；终端代理策略独立简要展示。策略开启只表示用户配置，不证明当前父 shell 已应用，更不证明实际出网成功；终端详情用 `domino shell status` 查看。未添加订阅、服务停止和连通检查失败会显示对应状态及后续操作。终端中使用颜色强调关键状态，重定向输出或设置 `NO_COLOR` 时使用纯文本；脚本和 Agent 使用 `domino status --json` 获取结构化字段。

其他常用查询沿用相同风格：`scan`、`nodes`、`configs`、`proxy`、`shell`、`mode`、`log-level`、`delay`、`connections`、`traffic`、`rules` 和 `providers` 均使用 Domino 标题、中文摘要和清晰的数据区域。节点名称与协议分列，当前订阅和节点选择突出显示，测速汇总可用/失败数量，时间按本机时区显示，流量自动换算 B/KiB/MiB 等单位。空列表和异常状态提供相应说明；各命令的 `--json` 数据格式保持兼容，`traffic --json --watch` 仍逐行输出 JSON。`env` 继续输出可执行 shell 语句，日志继续保留原文。

人类可读输出统一为“标题、摘要、空行、正文”，标题前和输出结束后各留一行空白。`status` 也使用相同标题布局；`proxy on/off/status` 使用同一状态展示，操作完成后读回 HTTP、HTTPS、SOCKS 和恢复记录，避免操作成功被误认为系统代理一定关闭。JSON、shell 环境语句和原始日志不增加装饰或空行。

`domino delay` 默认测试本机全部节点，`domino delay USER@IP` 测远端全部节点（也可直接填写 IP）。`domino delay -h` 只显示常用选项和三个例子：本机全部、远端全部、自定义超时。单项超时默认 5000 毫秒（5 秒），可用 `--timeout 10000` 改为 10 秒；`--json` 供脚本或 Agent 调用。

按名称测速、自定义网址和通用 SSH 参数放在 `domino delay --help-all` 中。`domino delay 自动选择` 测组内各项，`domino delay 美国TRI002` 测指定节点；远端用 `domino delay '名称' USER@IP`，SSH 别名测全部用 `domino delay all my-server`。名称优先完整匹配，也支持唯一的部分名称；多个匹配会列出候选，不执行测速。含方括号、空格的完整名称需加引号，例如 `domino delay "[HY2]美国TRI002"`。`--node`、`--group`、`--all` 兼容选项仍可使用。

延迟测试测量 HTTPS 请求耗时，单位为毫秒，不测下载带宽；测试地址默认 `https://www.gstatic.com/generate_204`。需要时使用 `--url 'https://example.com/'` 设置，选项后必须填写值，超时范围为 100–60000 毫秒。流量统计仅覆盖经过 Domino 的流量，累计值自内核运行开始计数，不代表机场账号剩余流量。`traffic --watch --count 5` 可以采样五次后退出。

HTTP / file provider 可通过更新命令重新读取；由内联节点自动生成的内置集合没有订阅更新地址。完整配置订阅使用下面的 `configs` 管理，更新无需重新安装。

## 自定义分流规则

```bash
domino rules add 'DOMAIN-SUFFIX,example.com,DIRECT'
domino rules add 'DOMAIN-SUFFIX,example.org,🚀 节点选择'
domino rules --custom
domino rules --match example
domino rules remove 'DOMAIN-SUFFIX,example.com,DIRECT'

# 在指定设备上添加；省略目标或写 localhost 都操作本机
domino rules add 'DOMAIN-SUFFIX,example.com,DIRECT' user@192.168.8.21
```

规则采用 [Mihomo 规则语法](https://wiki.metacubex.one/config/rules/)，通常是 `类型,匹配内容,出口`。`DIRECT` 表示直连，`REJECT` 表示拒绝，代理出口需填写当前配置中存在的节点或策略组名称，可用 `domino nodes` 查看。请将整条规则放在引号里，尤其是出口名称含空格时。

自定义规则默认置顶，最新添加的规则最先匹配；重复添加不会产生重复项。规则模式下才按分流规则选择出口，当前为全局或直连模式时命令会提示，可自行执行 `domino mode --set rule`。新增/删除会先由已安装的内核校验，然后重载配置并保留当前模式、端口、控制密钥及仍有效的手动节点选择；应用失败则恢复原文件和运行时选择。后续新连接使用更新后的配置，无需重新安装内核。

自定义规则独立保存于当前用户的 `~/.config/domino/rules.json`。订阅更新、切换和重新初始化时会重新合并，完整配置快照保存基础规则，避免把个人规则写死到订阅里。每台设备独立管理自己的自定义规则；部署有效配置仍会复制其中已经生效的规则。新订阅缺少自定义规则所引用的出口/provider 时，校验会失败并保留原配置，请用 `rules --custom` 检查，必要时先用 `rules remove` 删除对应自定义规则。`remove` 只删除自定义层；订阅中原本存在的同一条规则仍会保留。

UI 内支持 `/rules add "完整规则"`、`/rules remove "完整规则"` 和 `/rules --custom`，原有 `/rules google` 搜索方式继续可用。远端设备若仍安装旧订阅组件，需更新 Domino 后再进行保留自定义规则的订阅切换或更新。

## 配置管理

使用 `domino configs` 统一管理完整 Clash/Mihomo 配置订阅和本地快照，选择其中一个作为本机当前配置；不会自动合并不同机场的节点和规则。`scan` 列出本机发现的导入来源，`configs` 只列出已登记到 Domino 的配置，因此两者数量不必相同。`catch` 或文件导入成功后会登记本次配置快照并设为当前，保留其他在线订阅；不会因为扫描发现了其他配置就自动加入配置库。捕获配置直接使用来源配置名，重名时追加六位随机字母数字后缀，例如 `xlink-xqEiJS`，不把来源说明放入名称。同一来源重复捕获保留已有名称（包括手动重命名）；已有配置不会自动改名。

```bash
domino configs                           # 查看名称、当前项、节点数、更新时间和来源主机
domino configs --import-current '原有配置' # 将现有配置保存为可切回的快照
domino configs add '主力机场'           # 隐藏输入地址，添加后不切换
domino configs add '备用机场'
domino configs switch '主力机场'               # 首次使用自动下载，之后使用已校验缓存
domino configs update '主力机场'               # 当前订阅更新成功后应用
domino configs update '备用机场'               # 非当前订阅只更新缓存
domino configs update all                      # 更新所有有地址的订阅，快照跳过
domino configs rename '备用机场' '备用'
domino configs set-url '备用'            # 隐藏输入新地址，下次更新/使用重新下载
domino configs remove '备用'                   # 当前项不能直接删除
domino configs --json
domino configs user@192.168.8.21         # 查看远端目录
domino configs switch '主力机场' user@192.168.8.21
domino configs update all user@192.168.8.21
domino configs rename '备用机场' '备用' user@192.168.8.21
domino configs remove '备用' user@192.168.8.21
```

`configs update all` 中的 `all` 表示全部订阅；如果某个订阅恰好叫 `all`，可用 `domino configs --update all` 单独更新它。

完整配置订阅的下载使用 Clash/Mihomo 兼容客户端标识 `clash.meta`，用于兼容按客户端类型识别请求的订阅服务。下载失败会报告可获取的 HTTP 状态码，并隐藏订阅密钥；本机管理失败保留后端退出码，避免重复输出失败提示。

### 导入源快照与运行配置

Domino 将两层分开保存：

- `~/.local/share/domino/data/source/config.json` 是**导入源快照**：保存导入时解析到的配置内容，位于 Domino 私有目录，支持的 provider／证书资源一并复制、重定位。不保留原 YAML 注释或格式，不是逐字原始文件，也不依赖外部客户端持续运行。
- `~/.local/share/domino/data/config.json` 是**运行配置**：从源配置生成 Domino 自己的端口、控制接口及其他运行设置，再叠加本机自定义规则；Mihomo 服务读取此文件。

导入源的私有 `metadata.json` 记录来源类别、导入时间及内容摘要；Clash Verge 的当前项关联会注明来自客户端索引，不证明内核实际加载内容。切换节点、模式、日志级别或编辑本机自定义规则不会改写导入源快照。订阅更新将源与派生基础配置保存为同一缓存版本；切换和失败恢复同步维护源、运行文件及当前配置关联，不替换内核运行中的 `cache.db`。

`configs --import-current` 仍是对当前运行配置的显式快照（去除本机自定义规则层），不能用它声称找回未记录的原始订阅。旧安装缺少来源记录时，扫描只显示“未记录”，不会自动迁移或凭内容猜测来自哪个机场；后续明确导入可建立新的来源记录。缺失来源的旧缓存仍可切换，但不沿用上一配置的来源信息。

源快照、资源、离线包和备份可能包含节点凭据或私钥，必须按私有数据保管（目录 700、文件 600），不要公开上传。订阅 URL 只保存在显式在线订阅所需的私有登记数据中，不出现在公开来源摘要、正常日志或机器操作记录中；配置内容中的 provider 等私密字段也不会被扫描输出。

`configs add` 和 `configs set-url` 也接受 `--url 'https://...'`，便于脚本使用；交互使用建议省略，避免地址进入 shell 历史。地址和配置保存于当前用户权限受限的 `~/.config/domino/subscriptions/`，列表只显示来源主机，不显示路径或密钥。每台设备独立保存自己的订阅目录；部署当前配置不会顺带复制全部订阅地址。

更新复用本机已安装的 Mihomo，不下载或升级内核，不修改系统代理或 shell 环境。先下载 provider 等资源并由内核校验；应用时保留代理/控制端口、控制密钥、当前模式和日志级别，同名且仍有效的手动节点选择会保留，各订阅也保存自己的选择。切换和当前订阅更新在配置校验、内核加载及节点选择恢复成功后直接生效，不检查出网，也不会因节点不可用或测试网站不可达而回滚；配置校验、加载或提交失败仍恢复原配置和运行时选择。切换成功只表示配置已应用，实际 HTTPS 出网请另用 `domino status` 检查。切换/应用需要 Domino 服务正在运行，必要时先执行 `domino start`。切换可能使部分连接重新建立。

安装时也可通过 `./install.sh --subscription 'https://...' --name '主力机场'` 直接提供订阅，安装成功后会关联当前配置；省略 `--name` 时沿用已有名称或使用主机名。通常建议安装后通过隐藏输入的 `configs add` 添加地址。旧版本复制进来的配置没有完整订阅地址，可先另存为快照，再手动添加订阅。快照可以切换，但没有地址时不能在线更新。

UI 内输入 `/configs` 进入订阅列表，Enter 选择切换、更新或删除，也可交互添加订阅、设置订阅地址或保存当前配置为快照。还可输入 `/configs add "名称"`、`/configs set-url "名称"`、`/configs switch "名称"`、`/configs update "名称"`、`/configs update all`、`/configs rename "旧名称" "新名称"`、`/configs remove "名称"`，与 CLI 相同。

### 系统代理与终端代理

`domino proxy` 支持 `status`、`on`、`off`，不支持 `stop`（关闭请用 `domino proxy off`）。远程主机名或 SSH 别名请显式写在动作后，如 `domino proxy status my-host`；省略动作时仅接受明确的本机地址、IP 或 `USER@HOST`，避免将拼错的动作当成 SSH 主机。

macOS 安装默认不修改系统网络代理。`domino proxy on` 在当前出站网络服务上设置 HTTP、HTTPS、SOCKS 代理，先保存原设置；重复开启时，仅仍由 Domino 管理的项目沿用原备份，其他项目以本次开启前的实际设置为准。需要时使用 `--service 'Wi-Fi'` 明确指定网络服务，修改可能要求管理员认证。已有 PAC 或认证代理时会提示处理，避免丢失原配置。

`domino proxy off` 按项目恢复仍生效且指向 Domino 的代理，保留之后已关闭或被其他客户端接管的设置；过期恢复记录会在清理完成后移除，不阻止停止服务。状态查询以实际生效配置为准，不因历史记录存在就声称仍可恢复。`domino stop` 在停止服务前执行相同清理；没有备份时只关闭仍指向 Domino 的生效代理。真实授权、写入或读回失败仍会报告错误并保留恢复信息，不会强行停服留下不可用的系统代理。启动服务本身不会自动开启系统代理。

**系统代理与终端代理独立管理。** `domino proxy on/off/status` 只管理系统代理；macOS 上修改/恢复网络服务配置，不设置、清除或同步 `http_proxy`、`https_proxy` 等 shell 变量。`domino shell on/off/status` 管理当前用户持久化的终端代理策略，与系统代理及服务启停无联动。两者都不是全流量接管；应用是否读取系统代理或环境变量取决于程序本身。

全新 macOS / Linux 安装的终端策略均默认为 `off`，与是否提供订阅无关。已有策略在重装、升级和重新部署时保留；尚无策略的旧安装中，只有完整匹配已识别旧版 Linux 固定导出模板的环境才迁移为 `on`，旧版 macOS 迁移为 `off`。`--no-shell-env` 跳过本次 shell 环境修改并保留此前设置，不会撤销旧代理环境或重置策略。

安装程序通过 `~/.bashrc`、`~/.zshrc` 的受管理区块加载 `~/.config/domino/proxy.env`；Linux 还接入 `~/.vscode-server/server-env-setup`。加载器配置命令 PATH、shell 包装函数和提示符同步，不再无条件导出固定代理。Bash 登录终端需由已有登录配置加载 `.bashrc`，安装程序不改 `.bash_profile`、`.bash_login` 或 `.profile`。已经打开的 Bash / Zsh 终端需先加载一次：

```bash
. "$HOME/.config/domino/proxy.env"
domino shell status           # 策略；包装函数另显示当前 shell 的同步摘要
domino shell on               # 开启策略，并在本机已接入的当前 shell 应用
domino shell off              # 关闭策略，并恢复仍由 Domino 管理的原变量
```

包装函数逐个管理 `http_proxy`、`https_proxy`、`all_proxy`、`no_proxy` 及其大写形式。开启前保存变量是否存在、值及是否 export；重复开启保留最初基线，关闭时仅恢复仍属于 Domino 的变量。手动赋值、`unset` 或更改 export 属性后，该变量脱离管理，不会在下次提示符被覆盖；自动启动同步也保护已有、未归 Domino 管理的变量。显式在本机执行 `domino shell on` 可以重新接管它们，并保存此时的基线。无法检测把变量手动赋成完全相同值且属性不变的操作。嵌套 shell 继承管理元数据，避免把 Domino 值误存为原始基线；子 shell 不会凭空恢复父 shell 未 export 的变量。

其他已接入终端在下一次提示符同步策略；没有加载器的终端不会自动改变。普通 CLI 子进程只能确认策略写入，不能修改或断言父 shell 已应用；机器结果始终标明 `policy_only: true`、`current_shell_applied: false`。远端 `domino shell on/off USER@IP` 只操作目标用户策略，不会把远端代理应用到调用方终端。UI 支持 `/shell`、`/shell status`、`/shell on`、`/shell off`，同样只改变当前目标策略，退出 UI 后已接入 shell 在下次提示符同步。

临时显式环境命令继续保留，不等同于持久化策略：

```bash
eval "$(domino env)"          # 当前终端临时使用 Domino，并暂停策略同步
eval "$(domino env --unset)"  # 当前终端清除代理变量，并暂停同步；不恢复原值
export DOMINO_SHELL_MODE=manual  # 也可只暂停当前 shell 的同步
# 在已接入的本机 shell 中执行 domino shell on 或 off，恢复自动同步
```

两个 `env` 命令均设置 `DOMINO_SHELL_MODE=manual`，不修改持久化策略；`--unset` 是清除而不是基线恢复。需要保留/恢复原代理时使用 `shell on/off`。旧环境没有可信的开启前基线，迁移只对精确匹配已识别旧模板的变量值清理或接管，并警告无法恢复未知原值，不据端口相同就清除自定义变量。自定义 `proxy.env` 的原文保存在 `~/.local/share/domino/shell-env.previous`；shell 文件受管理区块之外的用户代码保留。

配置状态不等于连通性，使用 `domino status` 验证实际 HTTPS 出网。已经运行的 IDE、VS Code Server 和其他程序保留原环境；修改父 shell 不会更新它们，必要时保存工作并彻底退出对应父进程后重启。仅再次运行 `code .` 可能复用原进程。macOS 用户服务在退出当前用户后停止；这里不启用需要特权的 TUN，也不接管 DNS 或系统默认路由。
## 使用边界：相邻两台电脑，独立部署

每次操作只处理当前电脑和指定目标，不维护整条链路或拓扑。部署后目标电脑直接连接配置中的代理节点，使用自己的独立服务、控制密钥和本地配置。源电脑可以关机；目标电脑的代理和本地管理命令仍可使用。

| 当前电脑的来源 | 独立部署方式 |
| --- | --- |
| 已有 Clash/Mihomo 兼容配置 | 自动发现或使用 `--source` 指定配置后部署 |
| 由 Domino 部署过的电脑 | 自动读取本机 Domino 配置和当前选择，使用已安装的 Domino 部署下一台 |
| 其他代理客户端 | 需要导出 Mihomo 可用的节点配置，再用 `--source` 部署 |
| 当前电脑没有代理客户端 | 使用 `--subscription` 提供完整配置订阅，或 `--source` 提供兼容配置 |
| 仅有本地代理端口、专用 App 登录或系统隧道/TUN | 可以检查已发现的本地代理，但无法仅凭端口独立复制；需要兼容节点配置 |

Domino 不自动降级为依赖源电脑的 SSH 转发。本机代理出网正常，也不等于拥有可迁移的节点配置。明显依赖源电脑回环地址的节点会被拒绝；目标端还会检查服务、控制接口和实际 HTTPS 出网，失败时恢复部署前状态。

其他人可在目标电脑上将应用代理设置为 `http://127.0.0.1:17897`（或部署时指定的端口）使用。管理配置和节点请使用部署账号；Linux 启停服务需要 sudo，macOS 用户服务无需 sudo。默认只提供目标机本地代理，不开放给局域网内的其他电脑。机场账号有效期、并发限制及目标网络能否访问节点仍由服务提供商和实际网络决定。

## 开始使用

源电脑需要 Python 3.9+、OpenSSH、curl。通过 pip 安装会自动安装 PyYAML；部署包会携带可跨平台运行的纯 Python YAML 解析组件。源码环境也可使用 Mac 自带 Ruby 解析 YAML。目标设备需要 Python 3.9+、curl、tar、systemd，以及具备 sudo 权限的普通 SSH 用户。

基础命令可以直接从源码目录运行；新交互界面需要 UI 组件，使用下方虚拟环境安装方式可一并安装：

```bash
cd /Users/kyhuang/ws/domino
./domino nvidia@192.168.8.21
```

按提示在 Mac 终端输入 SSH 和目标 sudo 密码。密码不会保存。SSH 已有密钥或 Host 配置同样可用，保持正常的主机密钥验证。

也可以安装为独立命令：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[yaml]'
.venv/bin/domino --help
```

0.5.0 起部署时也会在目标机安装 `~/.local/bin/domino`，不要求目标机预先安装 Python 包。可用完整路径执行；如果希望直接输入 `domino`，在当前终端运行 `export PATH="$HOME/.local/bin:$PATH"`。

在一台由 Domino 部署过的电脑上，继续部署另一台：

```bash
# 在当前这台已部署的 Linux 电脑上执行
~/.local/bin/domino status localhost
~/.local/bin/domino user@192.168.8.22
```

旧设备需要从源电脑重新执行一次部署，才会安装新版管理命令。继续部署需要当前电脑具备 OpenSSH 客户端，并能 SSH 登录指定目标；每次部署仍使用操作者自己的 SSH 和目标 sudo 权限。

## 分发与可配置资源源

`./install.sh` 一次完成管理程序、内核、基础配置和后台服务安装。终端策略与加载器所需的 `domino_shell` 模块随部署包和 wheel 一并分发。wheel 另提供 `domino-install` 安装入口；pip/pipx 本身只安装 Python 包，完整安装可使用 `pipx run --spec ./dist/domino-0.13-py3-none-any.whl domino-install --batch`。Linux 需预先授权 sudo。只读扫描、导出和部署已有兼容配置无需先安装本机 Domino 服务。

通过环境变量 `DOMINO_RESOURCE_BASE=https://你的公共资源域名/domino/`，或 `~/.config/domino/downloads.json` 的 `resource_base` 字段指定直连资源源。指定后，内核元数据、二进制与所需 Geo 数据从该源读取并校验 SHA-256，不自动回退 GitHub。未指定时继续使用官方 GitHub 内核源。用户订阅及其 provider 的下载位置由用户配置决定。

本地发布工具、资源布局、Homebrew 模板与验收状态见 [交付说明](docs/DELIVERY.md)，每次交付变更见 [变更记录](CHANGELOG.md)。大版本使用 `0.x`（例如 `0.13`、`0.14`），小更新和 debug 修复使用 `0.x.x`（例如 `0.13.1`）。完成一批代码改动后同步 CLI / wheel 版本、记录变更、测试并构建；沿用旧目录规则：版本化 wheel 存于 `dist/`，完整发行产物平铺于 `dist/release/`；更新固定名称清单/Formula 前，将上一份发行产物归档到 `dist/release/history/<旧版本>/`，不覆盖旧版 wheel/runtime。构建清单记录源码摘要、构建时间和产物校验值，不代表字节级可复现构建。公共云端地址、PyPI/pipx 分发和 Homebrew tap 尚未上线；本地产物不等于已经发布，也不会自动同步安装版或重启服务。

## 产品架构与路线（规划）

产品定位为“代理管理入口 + 独立配置交付工具”。完整安装准备 Domino 自有内核和服务；只安装 Python 管理程序仍可用于导出和部署已有兼容配置。以下内容是后续规划，不代表新增命令已实现。

首先区分管理目标（`localhost` / `USER@IP`）与部署来源（已发现的兼容配置 / 指定配置文件 / 用户订阅）。管理命令始终操作目标上的 Domino 自有内核；外部 Clash/Mihomo 配置只用于只读扫描和导入，通过 `--source` 明确选择文件，不作为管理目标。TUI 和状态输出应始终显示当前目标及配置名。

| 层次 | 职责 |
| --- | --- |
| CLI / TUI / 外部 Agent | 共享同一套应用服务；CLI 提供稳定的机器调用协议，统一状态、结果、错误和任务进度 |
| 控制服务 | 状态、节点、模式、连接、流量、日志及能力检查 |
| 运行时管理 | 仅管理 Domino 自有内核、配置及服务 |
| Profile 服务 | 原始订阅 / 配置、用户覆盖项、合成有效配置和运行时选择分层 |
| 部署服务 | 检查兼容性、构建完整资源包、暂存、备份、启动、验证、提交或回滚 |
| 平台与传输 | macOS LaunchAgent / Linux systemd、系统代理、本机执行 / SSH |
| 资源分发 | 可直连版本索引、内核、校验信息和必要 Geo 数据；不保存用户凭据 |

Domino 不修改外部客户端的运行时、profile、订阅或服务生命周期；来源控制接口仅用于读取导入所需的模式和当前节点选择。完整安装合并管理程序、内核、基础配置和后台服务；订阅更新不重装内核。只安装 CLI 仍可扫描、导出和部署兼容配置。

独立交付要验证配置资源闭包：内核、provider 缓存、Geo 文件、证书、手动节点选择及管理依赖。不能将来源的回环代理、Unix socket、网卡或未解析文件路径带到目标。目标必须有自己的控制密钥，且来源停止后仍能新建代理连接。

| 阶段 | 交付重点 | 验收重点 |
| --- | --- | --- |
| 0.7 交互工作台 | 持续输入、命令补全、搜索面板、异步任务、只读快照 | 不阻塞输入；退出不停止内核；明确 API 在线和真实出网的区别 |
| 0.8 多订阅管理（已实现） | 命名订阅、更新、切换、当前配置快照、CLI/TUI 入口 | 配置更新不重装内核、不重置端口；失败恢复配置和运行时选择 |
| 0.12 Agent CLI（已实现有界请求） | 版本化 JSON、非交互执行、能力发现、稳定错误码、结构化写操作结果 | 外部 Agent 可直接调用并判断结果；现有 CLI / TUI 保持兼容 |
| 冷启动分发（工程已准备，待发布） | pip/pipx/brew、可直连资源、完整离线包 | 新机器无需预装梯子；安装不请求 GitHub |
| 1.0 稳定交付 | 事务记录、升级回滚、兼容性报告、真实平台回归 | 幂等；断连可恢复；来源关闭后目标可用；目标能继续独立部署 |

多人交付初期以部署账号管理、目标本地应用使用为边界；跨账号转交通过导出及新账号重新初始化处理。macOS 用户服务在退出该用户后停止，不能等同 Linux 系统服务的开机常驻。PATH 安装也应与 shell 代理开关分开。

明确不做机场订阅提供、任意专用隧道客户端登录态克隆、默认实时转发、全拓扑或中心控制平台。高级 TUN/DNS 行为后续单独设计；命令行界面不需要聊天模型或自然语言自动执行。

### 外部 Agent 调用接口（协议 1）

```bash
domino --output json capabilities
domino --output json status
domino --output json capabilities nvidia@192.168.8.21
```

机器模式使用统一结果信封、稳定错误码和非交互执行；本机与 SSH 使用同一应用服务。`--json` 的旧结果形状继续保持兼容。

订阅、规则、节点、模式、系统代理、终端代理策略、服务、provider、私有安装包、导出与上传部署的写操作支持预检、修订校验、请求去重与目标侧操作记录；具体支持项以 `capabilities` 为准。订阅地址可从 stdin 或权限 600 的 JSON 文件读取。详细参数、退出码和断连恢复方式见 [Agent 接口](docs/AGENT.md)。

### 只读扫描和导入兼容配置

```bash
domino scan                          # 扫描所有已发现的配置
domino scan --source '/path/to/current-config.yaml'
domino nvidia@192.168.8.21 --source '/path/to/current-config.yaml'
```

`domino scan` 汇总 Domino、旧版 robot-clash、Clash Verge 和标准 Clash/Mihomo 配置路径，同一文件只列一次，显示兼容性、默认来源、代理入口及实际 HTTPS 出网结果。终端使用统一的 Domino 标题、摘要和键值行，每个来源单独分组；配置路径用 `~` 缩写用户目录，长内容按终端宽度缩进换行，JSON 保留完整路径。不可读或不兼容的文件单独标记，不影响其他项。入口最多四个并发检查，每个入口超时 5 秒，相同入口只检查一次；失败显示“检查未通过”，未配置入口显示“未检查”。检测明确使用各配置自己的代理端口，不沿用系统代理；出网可用不代表系统代理已指向该入口。扫描不读取专用客户端的内存或加密订阅，不修改外部客户端。自动发现顺序仍优先 Domino。用 `domino scan --source '/path/to/config.yaml'` 检查某份配置及对应代理入口，用 `domino USER@IP --source '/path/to/config.yaml'` 明确选择部署来源。扫描支持 `--json`；Agent 操作沿用 `source.list`（列表）和 `source.inspect`（指定来源检查）。

Domino 的运行条目还显示当前登记名称、导入来源、运行配置与源快照两个路径及导入时间；缺少旧版来源时明确标为未记录。JSON 为该运行条目附加白名单 `import_source` 元数据，不额外增加一个源快照运行入口。显式 `scan --source` 检查 Domino 源快照时不探测其中保存的旧端口。扫描始终只读，不因发现缺失元数据就创建文件或登记配置。

macOS 的 Clash Verge 扫描还会读取本地 `profiles.yaml` 索引，列出保存的订阅／本地配置，例如 `Clash Verge · xlink` 和 `Clash Verge · feiniao`，并标明“客户端当前启用（索引）”或“已保存（非当前）”。“默认导入来源”与客户端当前项独立；索引当前项不证明服务已启动。若能唯一识别兼容的当前保存配置和生成的 `clash-verge.yaml`，人类可读列表将两者合并为该配置名下的一组，同时保留“运行配置”和“原始配置”两个路径。出网结果只属于运行入口；按索引关联不证明内核已加载相同内容。当前项不明确、原始文件缺失／不兼容或没有运行配置时，仍分开显示。运行文件可能含有客户端合并／脚本处理结果，并不等同原始文件；JSON 和机器接口始终保留独立记录，不合并健康状态。

保存配置本身只检查文件兼容性，不探测其声明的端口，也不借用当前运行入口的出网结果；单独显示时标为“未检查（保存配置）”，这不表示配置出网失败。显式 `scan --source` 指向已索引的保存配置时同样隔离运行检查；普通单来源命令沿用“未确认健康返回退出码 3”的兼容行为，脚本应区分 `exit_checked: false` 和实际检查失败，机器协议查询成功则仍返回 0。其他运行来源继续显示入口检测结果，但端口可用不能证明某份文件已加载。索引损坏或含不安全项目时提示通用警告，其他来源照常显示。

可复制扫描结果中的配置路径，通过 `domino USER@IP --source '配置路径'` 导入任意一份保存配置。导入使用原始文件与文件内默认节点，不连接它声明的控制接口来借用另一份配置的运行选择，也不执行 Clash Verge 的合并或脚本；结果可能与客户端生成的运行配置不同。辅助 merge/script 项不作为独立配置列出。新增保存配置不改变自动部署或 `catch` 的默认来源范围；未启用配置需要显式 `--source`。

UI 输入 `/scan` 执行相同扫描，并在操作记录中按相同样式显示结果；`/scan --source "配置路径"` 检查指定配置。命令结果保留 CLI 的标题、标签和状态配色：标题青色、成功绿色、失败红色、提示黄色，标签和路径使用弱化样式；命令结果遵循 `NO_COLOR`，JSON 保持纯文本。扫描在 UI 当前目标上执行，远端工作台不会改为扫描本机。`/scan` 可通过 `/` 命令面板或 Tab 补全选择，运行期间可用 Ctrl+C 中断。

出网检查失败时，列表会显示“失败阶段、出网检查、排查建议”，区分代理端口不可达、地址解析失败、隧道建立超时、TLS 握手失败或超时、证书校验失败、HTTPS 响应超时和 HTTP 错误。端口不可达表示请求尚未进入本机代理；隧道被接受只说明代理开始处理 HTTPS 请求，不保证上游节点已经连通。节点连接超时也可能表现为 TLS 握手中断，因此不会只凭 TLS 错误或总体请求超时就断言节点故障，进一步原因需要结合客户端日志确认。成功与失败结果独立于配置兼容性。

## 全新设备从零开始

全新设备不需要预先安装 Clash、Mihomo 或代理图形界面，但需要有效的机场订阅或兼容节点配置。本机安装支持 macOS 和使用 systemd 的 Linux；远端部署支持 Linux。macOS 使用当前登录用户的 LaunchAgent；Linux 使用 systemd 和 sudo。两者都需要 Python 3.9+ 和 curl。

### 从另一台电脑快速配置空白目标

在本项目目录执行。当前电脑也可以没有代理客户端，直接提供订阅即可：

```bash
./domino user@192.168.8.21 --subscription 'https://example.com/clash-config?token=YOUR_TOKEN'
```

如果当前电脑已有可用的兼容配置，省略 `--subscription` 即可。目标机安装后独立运行，源电脑可以关机。

### 在空白 macOS / Linux 设备本机配置

把本项目复制到设备后，运行安装脚本。脚本在临时 Python 虚拟环境中安装管理依赖，下载并校验内核，生成配置、安装后台服务和 `~/.local/bin/domino`，完成后清理临时环境。仅查看安装帮助使用 `./install.sh -h`，不会下载资源。

```bash
# 推荐：先装好环境，再通过隐藏输入添加订阅
./install.sh
~/.local/bin/domino configs add '机场A'
~/.local/bin/domino configs switch '机场A'

# 安装时也可显式提供已有配置文件
./install.sh --source /path/to/config.yaml
```

安装程序支持没有节点配置的基础安装，也可通过 `--source` 或 `--subscription` 一次配置好。macOS 使用 `local.domino.mihomo` 用户 LaunchAgent，随当前用户登录自动启动，无需 sudo；Linux 使用 `domino.service`，通过 sudo 设置开机自启。显式提供配置文件时，不会连接原客户端的控制接口或将其本地端口当作已运行的下载代理。

`--subscription` 当前要求 HTTPS 链接返回**完整的 Clash/Mihomo YAML 或 JSON 配置**，不能直接填机场官网、登录链接、单个节点 URI 或仅含 Base64 节点列表的通用订阅。直接部署到目标电脑和 `export` 同样支持该参数。安装时使用 `--subscription` 会保存地址，后续用 `configs update '名称'` 更新；已独立部署的其他设备需在各自订阅目录更新，或重新部署当前有效配置。

这种在线安装要求当前网络能访问订阅地址和 Mihomo 官方下载地址；GitHub 下载受限时可以使用 `--local-proxy` 指定仅用于下载的代理，或采用下面的离线方式。

### 无法下载内核时，使用离线包

`export` 将内核、节点与分流规则、相关资源和 Domino 管理程序打成 `.tar.gz` 安装包。流程是：在能下载资源的电脑上生成包 → 把包复制到目标电脑 → 在目标电脑上安装。目标安装时使用包内文件；安装后仍需能连接配置中的代理节点。

当前 `export` 生成 Linux 安装包，可在 Mac 上为 Linux 目标准备。按目标电脑架构选择参数（ARM64 使用 `arm64`，x86_64 使用 `amd64`）：

```bash
./domino export --arch arm64 --output ./device-proxy.tar.gz
# 没有本机客户端时，也可在 export 后加 --subscription 'https://...'
```

将安装包和 `dist/domino-0.13-py3-none-any.whl` 复制到目标设备。以下命令只用 Python 标准库展开管理程序，不需要先安装 pip 包或联网下载 Python 依赖：

```bash
python3 -m zipfile -e ./domino-0.13-py3-none-any.whl ./domino-bootstrap
python3 ./domino-bootstrap/domino_install.py --bundle ./device-proxy.tar.gz
```

离线安装统一通过安装程序完成。离线包包含内核、节点配置和 provider 缓存；安装后仍会验证真实代理出网，因此目标必须能连接配置中的代理节点。包内含节点凭据，应只交给需要使用该配置的人。

### 安装后立即管理

```bash
~/.local/bin/domino status localhost
~/.local/bin/domino nodes localhost
~/.local/bin/domino logs localhost --lines 100
~/.local/bin/domino restart localhost
```

全新 macOS / Linux 安装的终端策略默认关闭；已有策略和已识别旧环境按前述迁移规则处理。已有终端先加载 `. "$HOME/.config/domino/proxy.env"`，再用 `domino shell on/off` 独立管理终端代理及原变量恢复；macOS 系统代理另用 `domino proxy on/off`。`eval "$(domino env)"` 仍可临时显式使用代理，但会暂停当前 shell 的策略同步。应用也可直接设置 HTTP 代理为 `http://127.0.0.1:17897`。环境变量只会被新启动的子进程继承，已运行的应用不会因修改父 shell 而更新。

## 本机和指定电脑使用同一组管理命令

统一使用 `domino <操作> <目标>`：`localhost` 表示当前用户的本机，`USER@IP` 或 SSH 别名表示远端。两端使用相同的命令和参数，只需更换目标：

| 用途 | 管理本机 | 管理指定电脑 |
| --- | --- | --- |
| 检查指定配置及代理入口出网 | `domino scan --source '/path/to/config.yaml'` | 在目标机执行相同命令 |
| 扫描全部已发现的配置 | `domino scan` | 在目标机执行 `domino scan` |
| 服务、开机自启和实际出网 | `domino status localhost` | `domino status USER@IP` |
| 策略组和当前节点 | `domino nodes localhost` | `domino nodes USER@IP` |
| 切换节点 | `domino select localhost --group '组名' --node '节点名'` | `domino select USER@IP --group '组名' --node '节点名'` |
| 最近的服务日志 | `domino logs localhost --lines 100` | `domino logs USER@IP --lines 100` |
| 实时跟随日志 | `domino logs localhost --follow` | `domino logs USER@IP --follow` |
| 启动代理服务 | `domino start localhost` | `domino start USER@IP` |
| 停止代理服务 | `domino stop localhost` | `domino stop USER@IP` |
| 重启代理服务 | `domino restart localhost` | `domino restart USER@IP` |
| 恢复上次部署前状态 | `domino rollback localhost` | `domino rollback USER@IP` |

`localhost` 直接在本机执行，不需要本机开启 SSH 服务。`127.0.0.1`、`::1` 也表示本机；省略目标的旧写法仍等同于 `localhost`。需要通过 SSH 切换本机用户时使用 `USER@localhost`；SSH 参数不能附加到直接执行的 `localhost` 目标上。`scan` 扫描当前电脑的配置，不需要目标参数。

远端命令共用 SSH 选项：`--user USER` 指定用户名，`--ssh-port PORT` 指定端口，`--identity PATH` 指定私钥，`--batch` 禁止 SSH/sudo 密码询问。未指定时沿用 SSH 配置和默认行为；这些通用参数在 `delay` 的普通帮助中折叠，可通过 `domino delay --help-all` 查看。

启停和日志命令可能提示 sudo 密码；添加 `--batch` 禁止密码询问，要求已有相应权限。`status`、`nodes`、`scan` 支持 `--json`。`scan --source /path/to/config.yaml` 可检查指定配置的兼容性及对应代理入口出网；`compatible_config_found` 表示发现了可进一步校验的配置，实际部署仍需内核和目标出网检查。

`status` 只检查 Domino 自有服务；本机没有安装 Domino 时会报告未安装，不回退到外部配置或代理状态。需要检查兼容配置及代理入口时使用 `scan`。仅有系统隧道/TUN 且未暴露代理端口时，无法自动确定其代理状态或导出节点。远程管理通过 SSH 完成，不要求当前电脑的代理客户端继续运行。

## 常用命令

直接指定目标即可部署，自动完成检查、配置交付和出网验证：

```bash
./domino nvidia@192.168.8.21
./domino nvidia@dvt-1-unilever-poc
./domino 'nvidia@[2001:db8::10]' --ssh-port 2222 --identity ~/.ssh/id_ed25519
```

固定内核版本、指定源配置或端口：

```bash
./domino nvidia@192.168.8.21 --mihomo-version v1.19.33
./domino user@10.0.0.20 --source /path/to/config.yaml --local-proxy http://127.0.0.1:7897
./domino user@10.0.0.20 --proxy-port 17890 --api-port 19091
```

检查运行状态和实际代理出网：

```bash
./domino status nvidia@192.168.8.21
./domino status nvidia@192.168.8.21 --json
```

`healthy` 表示代理实际完成 HTTPS 请求；`active` 和 `enabled` 分别表示服务运行与开机自启状态。`exit_country` 来自验证服务响应，节点名称本身不用于判断出口地区。状态异常返回非零退出码。

已配置 SSH 密钥且目标允许免密码 sudo 时，可以在自动化中使用 `--batch`。该模式同时禁止 SSH 和 sudo 的密码询问，认证失败会直接退出，不会等待输入。

更新源订阅或节点后，再执行相同的目标命令。每次部署前会保存完整备份；部署失败会恢复服务、配置、启动状态和受管理的用户环境文件。

手动恢复上次部署前状态：

```bash
./domino rollback nvidia@192.168.8.21
./domino rollback nvidia@192.168.8.21 --backup 20261111-150000-123456ab
```

手动回滚也会先备份当前状态。旧的一次性脚本生成的备份会保留，但没有事务元数据的旧备份不支持自动回滚；首次用新工具更新设备时，会为现有的正常配置生成可回滚备份。

## 查看和切换节点

在 Mac 上管理目标设备，不需要重装服务，也不需要复制控制密钥：

```bash
./domino nodes nvidia@192.168.8.21
./domino nodes nvidia@192.168.8.21 --group '🚀 节点选择'
```

第一条列出策略组的当前选择及全部节点名称；第二条列出指定组的候选项，`*` 标记当前选择。策略组、节点名称应按实际输出填写。

为一个可手动选择的策略组更换节点：

```bash
./domino select nvidia@192.168.8.21 --group '🚀 节点选择' --node '实际节点名称'
```

切换后会读回控制接口确认结果。自动测速/故障转移组由其策略选择节点，需要手动选节点时请选择其上层的手动选择组。分流规则使用哪个策略组，就会沿该组当前选择的链路出网；更改一个无关策略组不一定改变所关注应用的出口。

节点切换影响新建立的连接，现有长连接可能需要重新连接。目标配置启用了 `store-selected`，选择由 Mihomo 缓存保存；再次向目标部署 会重新同步源电脑的配置和选择。

管理命令通过现有 SSH 读取目标本地控制接口，无需 sudo，兼容最初的一次性安装。它们不要求源电脑的 Clash 仍在运行。支持 `nodes --json` 用于脚本读取。

## 无界面设备的状态查看

### 在本机查看指定电脑

在本机的 Domino 目录中执行，将 `nvidia@192.168.8.21` 换成部署时的用户和 IP，也可以换成 SSH 别名（如 `dvt-1-unilever-poc`）：

```bash
# 综合检查：服务是否运行、是否开机自启、实际代理出网、出口地区
./domino status nvidia@192.168.8.21

# 查看运行模式、各策略组当前选择、可用节点
./domino nodes nvidia@192.168.8.21

# 查看某个策略组的候选节点，* 表示当前选择
./domino nodes nvidia@192.168.8.21 --group '🚀 节点选择'

# 输出 JSON，方便脚本读取
./domino status nvidia@192.168.8.21 --json
./domino nodes nvidia@192.168.8.21 --json

# 通过 SSH 查看 systemd 服务详情和最近日志
ssh nvidia@192.168.8.21 'systemctl status domino.service --no-pager -l'
ssh -t nvidia@192.168.8.21 'sudo journalctl -u domino.service -n 100 --no-pager'
```

这些查询不会重新部署或切换节点。使用安装后的 `domino` 命令时，可省略 `./`。SSH 密码认证可正常询问密码；已有密钥时可给 Domino 查询命令加 `--batch` 禁止交互，无需 sudo。

`status` 输出含义：

| 字段 | 含义 |
| --- | --- |
| `installed` | 目标用户目录中存在部署配置 |
| `service` | Linux 为 `domino.service`；macOS 为 `local.domino.mihomo` |
| `deployment_method` | 新部署为 `independent`，表示目标独立连接节点 |
| `requires_source_online` | 新部署为 `false`，表示不依赖源电脑在线 |
| `active` | Mihomo 服务正在运行 |
| `enabled` | Linux 开机自启 / macOS 当前用户登录自启 |
| `healthy` | 控制接口检查成功，且通过本地代理端口完成了 HTTPS 测试请求 |
| `proxy_port` | 目标机的 HTTP/SOCKS 混合代理端口，默认 `17897` |
| `exit_country` | 测试请求出口的国家或地区代码，例如 `JP`、`US`；未返回时为 `null` |
| `version` / `arch` | Mihomo 内核版本 / 部署架构 |
| `check_error` | 控制接口或代理出网检查失败时的提示 |

`active: True` 只说明进程在运行；需要结合 `healthy` 判断测试请求是否成功。规则模式可能让测试地址走 `DIRECT`，因此出口地区是该次请求的出口，不保证是某个节点的地区，也不代表所有应用都在走代理。当前健康检查以 `healthy` 决定退出码；开机自启状态需单独看 `enabled`。

### 在目标电脑上直接查看

先登录目标机，使用部署时的普通用户执行以下命令。手工排查无需额外安装工具，也不需要图形界面。

0.5.0 起目标机已附带 Domino，优先使用 `~/.local/bin/domino status localhost`、`~/.local/bin/domino nodes localhost`、`~/.local/bin/domino logs localhost`。以下 systemd/Mihomo 命令也可用于手工排查旧部署。

```bash
ssh nvidia@192.168.8.21

# 服务详情 / 运行状态 / 开机自启状态
systemctl status domino.service --no-pager -l
systemctl is-active domino.service
systemctl is-enabled domino.service

# 最近 100 行日志；实时跟随日志时按 Ctrl+C 退出查看
sudo journalctl -u domino.service -n 100 --no-pager
sudo journalctl -u domino.service -f

# 已安装的 Mihomo 二进制版本
"$HOME/.local/share/domino/mihomo" -v
```

验证实际代理出网，自动读取部署端口（包括使用自定义端口的设备）：

```bash
MIHOMO_PROXY_PORT=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".local/share/domino/data/config.json").read_text())["mixed-port"])')
curl --noproxy '' --proxy "http://127.0.0.1:$MIHOMO_PROXY_PORT" \
  --fail --silent --show-error --connect-timeout 8 --max-time 25 \
  https://www.cloudflare.com/cdn-cgi/trace
```

输出中 `ip=` 是该次请求的出口 IP，`loc=` 是出口国家或地区代码。该命令显式使用代理端口，不依赖当前终端是否加载代理环境；具体出站路径仍由 Mihomo 分流规则决定。要检查某个应用访问的网站，可把 URL 换成该网站的 HTTPS 地址。

### 在目标电脑上查看模式和当前节点（Mihomo API）

Mihomo 的运行模式和节点选择通过控制 API 查询。先在目标机当前 Bash/Zsh 终端粘贴以下函数；它自动从部署配置读取控制地址和密钥，不把密钥放进命令行参数，也不需要额外安装 `jq`：

```bash
mihomo_api() {
  python3 - "$@" <<'PY'
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    config = json.loads((Path.home() / '.local/share/domino/data/config.json').read_text())
    address = config['external-controller']
    if not re.fullmatch(r'127\.0\.0\.1:\d+', address):
        raise ValueError('控制地址必须是目标机回环地址')
    route = sys.argv[1] if len(sys.argv) > 1 else '/version'
    if route not in ('/version', '/configs', '/proxies'):
        raise ValueError('支持的查询：/version、/configs、/proxies')
    request = urllib.request.Request(
        'http://' + address + route,
        headers={'Authorization': 'Bearer ' + config.get('secret', '')})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        result = json.load(response)
    if route == '/proxies':
        for name, item in result['proxies'].items():
            if isinstance(item.get('all'), list):
                print(f"{name} [{item.get('type')}] → {item.get('now')}")
    elif route == '/configs':
        print(json.dumps({key: result.get(key) for key in
                          ('mode', 'mixed-port', 'allow-lan', 'log-level')},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
except (OSError, ValueError, KeyError) as error:
    print('查询失败：请检查部署配置、服务状态和控制接口。错误类型：' + type(error).__name__, file=sys.stderr)
    sys.exit(1)
PY
}

# 正在运行的内核版本（也可验证控制接口是否可用）
mihomo_api /version

# 当前运行模式和端口；mode 通常为 rule / global / direct
mihomo_api /configs

# 各策略组的当前选择：策略组 [类型] → 当前节点或下层策略组
mihomo_api /proxies
```

函数仅在当前终端会话中生效。`/proxies` 会列出包括 `GLOBAL` 在内的全部策略组；`GLOBAL` 的选择用于全局模式，规则模式应看规则实际引用的组。自动策略组和负载均衡组的实际出站还取决于策略及具体连接。

API 定义参考 [Mihomo 官方 API 文档](https://wiki.metacubex.one/api/)。这里的代理端口和控制接口都只监听目标机 `127.0.0.1`，本机远程查询通过 SSH 完成。部署默认不开启 TUN；应用需要使用代理环境变量或自行配置代理，服务运行不等于目标机所有流量都经过代理。

## VS Code / Codex（可选）

部署默认不修改 Mac 的 VS Code 设置，也不停止远端程序。未使用 `--no-shell-env` 时，目标新终端和 Linux 新启动的 VS Code Server 通过加载器按该用户策略同步；全新安装默认 `off`，不是无条件导出代理。已有 Server / IDE 进程保留旧环境，其他已接入的交互终端在下次提示符同步。需要更新 Mac 的 VS Code 主机代理并停止旧 Server 时，显式添加：

```bash
./domino nvidia@dvt-1-unilever-poc --vscode --restart-vscode
```

这会断开该目标上当前用户的 VS Code/Codex 会话，不停止其他用户或机器人业务进程。完成后重新连接。目标应与 VS Code 使用的 SSH Host 名称一致。

VS Code 设置文件包含 JSONC 注释时，工具会保留原文件并提示手动设置，不尝试覆盖。可用 `--vscode-settings` 指定其他设置文件。

只部署代理、不修改目标的 shell / VS Code 环境文件：

```bash
./domino user@10.0.0.20 --no-shell-env
```

`--no-shell-env` 不会撤销此前已存在的代理环境；它只表示本次不修改这些文件。

## 导出与源配置

只准备安装包，不连接设备：

```bash
./domino export --arch arm64 --output ~/Downloads/device-proxy.tar.gz
```

默认优先读取本机 Domino 配置，也可发现 Mac Clash Verge 等兼容配置；可只读查询来源的本地控制接口或 socket，保留当前模式和选中的策略组。使用 `--source` 明确指定配置，必要时使用 `--controller http://127.0.0.1:9090` 或 `--controller-socket /path/to/socket` 指定只读来源接口。控制接口认证使用源配置中的 secret，不写入命令行参数。未配置或未发现控制接口时使用配置中默认的节点，并明确提示；已经指定的控制接口连接失败时停止，避免误迁移其他节点。这些来源参数不会使管理命令接管外部客户端。

HTTP/file providers 会连同缓存资源迁移，并改为目标上的相对路径。HTTP providers 保留自身 URL/更新配置，后续是否自动刷新取决于源配置中的 interval 等设置。内联节点是当前配置快照，更新后需要再次部署。缺失 provider 缓存时通过源电脑下载 HTTPS 资源，避免目标首次启动时依赖尚未建立的代理。Provider 的专用 headers/auth 下载方式暂不支持；需要源客户端已有可用缓存。

安装包、配置和 provider 缓存包含节点凭据，仅通过已认证 SSH 传到指定设备。源电脑临时凭据目录自动清理；显式导出的包权限为 `600`，不要提交到代码仓库。二进制缓存不含节点配置，位于 `~/Library/Caches/domino`（Mac）或 `~/.cache/domino`，可用 `DOMINO_CACHE` 覆盖。

## 目标设备上的文件

| 内容 | 路径 |
| --- | --- |
| Linux systemd 服务 | `/etc/systemd/system/domino.service` |
| macOS 用户 LaunchAgent | `~/Library/LaunchAgents/local.domino.mihomo.plist` |
| macOS 内核日志 | `~/Library/Logs/domino/mihomo.log` |
| macOS 系统代理恢复记录 | `~/.config/domino/system-proxy.json` |
| Mihomo、配置、provider 缓存 | `~/.local/share/domino/` |
| 目标机管理入口 | `~/.local/bin/domino` |
| 管理及继续部署所需的程序 | `~/.local/share/domino/cli/` |
| 部署和回滚备份 | `~/.local/share/domino-backups/` |
| 终端代理加载器 | `~/.config/domino/proxy.env` |
| 持久化终端代理策略 | `~/.local/share/domino/shell-policy.json` |
| 迁移前自定义加载器备份 | `~/.local/share/domino/shell-env.previous` |
| 资源源配置 | `~/.config/domino/downloads.json` |
| Agent 操作记录与去重 | `~/.local/state/domino/operations/` |
| shell 加载区块 | `~/.bashrc`、`~/.zshrc`；不修改 Bash 登录文件 |
| Linux VS Code 环境入口 | `~/.vscode-server/server-env-setup` |

服务名和目录名统一使用 `domino`。服务以 SSH 用户身份运行，只监听目标回环地址；不开放 LAN 代理，不启用 TUN，不修改系统 DNS/默认路由。新增环境排除 localhost 和常见私网范围；已运行的进程需要自行重启才会继承环境。

### 已有设备升级命名

0.4.0 起使用 `domino.service` 和上表中的新路径。对已部署的设备重新执行：

```bash
./domino nvidia@192.168.8.21
```

工具会备份原状态、停用并移除本工具管理的旧服务，将当前源配置部署到新目录，完成出网校验。默认同步替换 shell / VS Code 环境中的旧路径和标记；使用 `--no-shell-env` 时保留原环境文件和引用的旧代理环境文件。旧备份保留，升级失败会自动恢复；`rollback` 可恢复升级前的服务名和配置。

升级会短暂中断代理连接，并重新同步源电脑的节点选择。尚未升级时，本机 `status`、`nodes`、`select` 仍能识别旧部署，`status` 的 `service` 字段显示实际服务名。目标机直接执行本页的 `domino.service` 和新目录命令，需要先完成升级。

二进制来自 [Mihomo 官方 Releases](https://github.com/MetaCubeX/mihomo/releases)，校验 GitHub 提供的 SHA-256。x86_64 使用 amd64-v1 兼容版本。systemd 运行方式参考 [Mihomo 官方说明](https://wiki.metacubex.one/startup/service/)。

## 测试与命令入口

```bash
python3 -m unittest discover -s tests -v
```

测试包含目标地址校验、架构选择、凭据隐藏、provider 迁移、重复部署、失败恢复、首次安装失败清理、回滚、环境幂等性和进程选择范围。测试包含模拟目标、临时真实 Mihomo 进程、临时 Clash API 及相邻配置复制验证，不安装或重启当前设备服务。`scripts/verify_ssh.py` 另使用临时用户级 OpenSSH 进程验证真实 SSH 协议，不修改系统 sshd。

命令入口统一使用 `domino`。新设备请使用 `domino USER@IP`；已有设备的命名升级见上文。
