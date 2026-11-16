# Domino Agent 接口 · 协议 1

从 `domino --output json capabilities` 发现操作、参数 JSON Schema、结果 Schema、平台和安装条件。`available` 表示平台与安装条件支持；运行时连接、资源和权限在执行时复核。API 不要求 TTY，不弹出订阅输入或密码询问。先写全局机器参数，再写命令；普通终端命令和旧 `--json` 保持兼容。

```bash
domino --output json --protocol-version 1 --non-interactive status
domino --output json user@192.0.2.10 nodes
domino --output json scan
```

`scan` 对应 `source.list`，返回 `data.sources`，汇总已发现的配置文件，包含 `config`、来源标签 `name`、`default`、`compatible_config_found` 和 `proxy`；无法读取或不兼容的配置带 `config_error`。每项的 `exit_checked` 表示是否检测了配置对应的代理入口，`healthy` 表示实际 HTTPS 出网是否成功，检测失败带 `check_error`。入口最多四个并发检测，每个入口超时 5 秒，相同入口只检查一次；无代理入口时 `exit_checked` 和 `healthy` 均为 `false`。列表查询成功仍返回退出码 0，逐项健康状态由字段表达；`compatible_config_found` 不保证来源正在运行或目标能成功部署。`scan --source '/path/to/config.yaml'` 对应 `source.inspect`，检查指定的单一来源；直接调用 `source.inspect` 时仍可省略 `path` 检查默认来源。来源发现、检查和导入保持只读；管理操作只针对目标上的 Domino 自有运行时。

macOS Clash Verge 的本地 `profiles.yaml` 中 `remote` / `local` 保存配置也加入列表，但不改变自动部署的默认来源；普通 `catch` 菜单和 `catch all` 可捕获保存配置。保存配置增加 `source_kind: "profile"`、`profile_id`、`profile_name`、`client_current` 和 `check_note`。`client_current` 是客户端索引的选择，不代表运行；为 `null` 时表示存在索引歧义，不能可靠确认。它与 `default`（默认导入来源）独立。JSON 中生成运行配置仍作为独立记录保留，可能包含客户端合并／脚本处理结果。保存配置不关联监听端口：`proxy: null`、`exit_checked: false`、`healthy: false`，`check_note` 解释未检查范围，不是出网失败；不能借用活动端口给未启用配置背书。指定已索引保存配置的 `source.inspect` 使用相同字段和隔离规则，不回退环境代理进行探测。机器查询成功仍返回退出码 0；普通单来源 `scan --source`（含旧 `--json`）沿用未确认健康时退出码 3，不能只凭这个退出码把未检查当作连通失败。索引读取或项目校验失败时，列表可包含通用 `warnings` 数组，不输出原始条目、订阅 URL 或解析正文；无警告时省略该字段。

配置库存在时，`source.list` 还返回 `managed_configs`，含 `active`、`current_source` 和 `configs`。配置项为配置库公开列表投影（名称、类型、节点数、缓存与当前标记、更新时间、可选订阅主机），不包含原始订阅地址或节点内容；不读取或校验保存缓存、不启动内核。无法读取配置库时返回空 `configs` 和安全 `error`，外部来源继续扫描。终端先显示外部来源，再集中显示 Domino 的全部登记配置表；终端不再展开 Domino 运行来源详情或部署提示，摘要数量按实际展示的外部配置分组与配置库列表分别计算；`sources` 保留原始独立记录和默认来源顺序。

Domino 运行来源可带 `current_config` 和 `import_source`。后者只公开 `status`（`known` / `unknown` / `invalid`）、私有源快照的 `snapshot_path`、`capture_kind`、安全显示名 `label`、`captured_at`、可选 `profile_name` / `association` 和解析内容／可携带快照摘要 `import_content_sha256` / `snapshot_sha256`；摘要不是原始文件字节校验和。`association: "index"` 只表示捕获时客户端索引的关联，不证明内核加载内容。`unknown` 为缺少旧版记录，`invalid` 为记录不可用，两者均不触发自动迁移或写入；源状态不替代运行入口健康。源快照不作为额外运行入口加入列表；显式检查 Domino 源快照时可返回 `source_kind: "import-snapshot"`，`proxy: null`、`exit_checked: false`、`healthy: false`，不会探测旧端口或回退环境代理。来源读取只投影白名单，不返回原配置或私有元数据全文。

显式 `--source` 导入保存配置保留原始文件和默认节点，不查询其中的控制接口（即使指定 controller 也不借用运行选择），不执行 merge/script；provider 等相对资源沿用文件原目录解析。辅助 merge/script 索引项不列为独立部署来源。扫描保持只读，运行来源的端口检查不证明某份配置实际已加载。

终端和 UI 的 `/scan` 共用分组键值行展示。若能唯一识别兼容的当前保存配置和 Clash Verge 生成运行配置，人类列表将其合并为该配置名下的一组，同时显示“运行配置”和“原始配置”路径；入口健康及诊断只属于运行配置，按索引关联不证明内核加载内容与文件一致。当前项不明确、保存文件缺失／不兼容或运行配置不存在时不合并。此分组及路径缩写、换行只作用于人类可读输出；JSON 的独立记录、完整路径与字段保持不变，保存配置的 `proxy`、`exit_checked`、`healthy` 不因展示合并而改变，因此机器记录数可能多于人类展示组数。UI 扫描使用当前目标的执行环境。

出网失败增加 `check_code`（如 `PROBE_PORT_UNREACHABLE`、`PROBE_TUNNEL_TIMEOUT`、`PROBE_TLS_FAILED`）、`check_stage`（`proxy_dns` / `dns` / `proxy` / `tunnel` / `tls` / `http` / `request`）和 `check_hint`。`check_error` 提供具体原因；`check_details` 提供可获取的 `curl_exit_code`、`http_status`、`connect_status`、`proxy_connected`、`tls_established`、`elapsed_ms`、`timeout_seconds` 和 `test_host`，不包含原始响应正文或 stderr。缺少阶段诊断时使用总体超时分类，不推断节点超时。`source.inspect` 使用相同诊断字段。

机器模式 stdout 只输出一个 JSON 文档。应用版本与协议版本独立；新增兼容字段不改变协议版本。调用者应忽略未知响应字段，使用 `error.code` 和退出码分支，不解析中文消息。

## 系统代理与独立终端代理策略

`service.start` / `service.restart` 在 macOS 与 Ubuntu GNOME 桌面等待控制接口就绪后接通系统代理，`service.stop` 先恢复仍由 Domino 接管的系统代理，再停止服务；Ubuntu Server / 无 GNOME 会话时只管理服务并返回无桌面系统代理状态。启动服务成功但系统代理接通失败时返回错误及 `effect: "unknown"`，需要查询状态，不报告整体成功。服务启停的预览包含系统代理变化，即使服务原本已运行或停止也会考虑代理状态。终端策略不随服务启停改变。

`status.get` 与普通 `status --json` 返回 `system_proxy: {"routing": "domino|off|other|mixed|pac|unknown|unsupported", "ports": [...]}`。`healthy` 仍表示 Domino 代理入口的实际出网检查结果，不等同于系统代理已接通；系统是否使用 Domino 需同时检查 `system_proxy.routing`。Ubuntu GNOME 的 `system_proxy` 还包含 `backend: "gnome"`、`supported`；无桌面会话返回 `routing: "unsupported"`、`supported: false`。`proxy.*` 在 Linux 也保留兼容，不写入 shell 环境；Linux 不接受 macOS 专用的 `service` 参数。恢复记录保存在 `~/.config/domino/linux-system-proxy.json`。原 `proxy.*` 协议名称不变。

`proxy.status`、`proxy.on`、`proxy.off`（普通 CLI 为 `domino proxy status/on/off`）只管理系统代理，不写入终端变量。`shell.status`、`shell.on`、`shell.off`（`domino shell status/on/off`）独立读取或修改目标用户的持久化终端策略，不切换系统代理，不代表服务或实际代理出网正常。

```bash
domino --output json call shell.status
domino --output json --request-id 'shell-on-001' call shell.on
domino --output json user@192.0.2.10 call shell.off
# 普通入口也支持机器协议
domino --output json shell status
```

三项 `shell.*` 操作的 `data` 都包含 `enabled`、`scope: "user-policy"`、`policy_only: true`、`current_shell_applied: false` 和 `integration_available`。`enabled` 是持久化策略，`integration_available` 仅说明检测到受管理加载器标记及已安装的 helper 文件；两者都不证明任何父 shell 已加载或应用。`effect: "applied"` / `changed` 也只描述目标策略的落地与变更，不确认父进程环境。机器操作不能修改调用方 shell，远端操作更不会把目标代理应用到本地终端。`status` 中的终端策略摘要同样不是当前环境或连通性验证；实际出网另看 `data.healthy`。

全新 macOS / Linux 安装默认为 `off`；已有策略在重装、升级、部署时保留。尚无策略时，只有完整匹配已识别旧版 Linux 导出模板的环境迁移为 `on`，旧版 macOS 迁移为 `off`。`--no-shell-env` 保留此前设置，跳过本次 shell 环境修改，不清除旧环境或重置策略。策略保存在 `~/.local/share/domino/shell-policy.json`；相关 `domino_shell` 模块随部署包与 wheel 分发。

加载器 `~/.config/domino/proxy.env` 通过 `.bashrc`、`.zshrc` 的受管理区块接入，Linux 还接入 `.vscode-server/server-env-setup`。Bash 登录配置须已加载 `.bashrc`，安装程序不修改登录文件；已有交互终端需先执行 `. "$HOME/.config/domino/proxy.env"` 一次。加载后的本机包装函数在 `domino shell on/off` 后同步当前 shell，其他已接入终端在下一次提示符同步。UI 的 `/shell`、`/shell status/on/off` 只管理当前目标策略；UI 子进程不会修改父 shell，退出后由提示符同步。

同步逐变量保存开启前的存在状态、值和 export 属性；重复 `on` 保留原基线，`off` 只恢复仍由 Domino 管理的变量。手动赋值、unset 或 export 属性变化会使对应变量脱离管理；自动启动不覆盖已有、未归 Domino 管理的变量，显式本机 `shell on` 可重新接管并保存新基线。相同值且属性不变的手动赋值无法检测。嵌套 shell 继承管理元数据，不把 Domino 值当成原始基线，也不恢复未继承的父 shell 非 export 变量。旧环境基线未知时，只清理或接管精确匹配已识别旧模板的值并给出警告；自定义 `proxy.env` 原文保存到 `~/.local/share/domino/shell-env.previous`，受管理区块外的用户代码保留。

`eval "$(domino env)"` 和 `eval "$(domino env --unset)"` 保持显式临时行为，两者均设置 `DOMINO_SHELL_MODE=manual` 暂停当前 shell 同步，不改变策略。`--unset` 清除变量，不恢复基线；也可自行 `export DOMINO_SHELL_MODE=manual` 暂停。已接入的本机 `domino shell on/off` 恢复自动同步。已运行 IDE / Server 等进程仍保留原环境，需按需彻底退出后重启；再次运行 `code .` 可能复用已有进程。

## 私有参数与操作调用

`call OPERATION [TARGET]` 是 Agent 的统一入口，完整参数由 `--input -` 或权限 600 的文件提供。普通命令也可搭配私有输入。`deployment.apply` 的 `bundle` 是调用电脑上的私有文件，会自动上传到目标暂存目录；`service.install` 的 `bundle` 则是执行端已经存在的文件。

```bash
# URL 来自调用方的私有输入，避免放入 argv 和 shell 历史。
domino --output json --input - call configs.add
# stdin: {"name":"机场A","url":"https://用户提供的完整配置订阅"}

domino --output json --input /private/rename.json call configs.rename
# rename.json: {"id":"订阅列表中的32位ID","new_name":"备用"}

domino --output json --input /private/install.json user@192.0.2.10 call service.install
# install.json: {"bundle":"/目标机私有目录/domino.tar.gz","bundle_sha256":"64位SHA-256"}
```

文件导入／`catch` 成功后会将本次导入登记为本地快照并设为当前，保留同名在线订阅；不自动将其他扫描来源加入配置库，不从外部客户端索引借用订阅 URL。登记与安装健康检查处于同一回滚范围，源快照、运行配置、当前 marker 和目标配置库一致提交。捕获配置直接使用来源配置名，自动登记遇到重名时追加六位随机字母数字后缀（如 `xlink-xqEiJS`）；来源关联依据留在元数据中，不放入名称。同一来源再次捕获保留已有名称，不自动重命名旧条目。订阅缓存版本保存转换前解析源（资源路径已迁移）与派生基础配置；应用仍沿用本机设置和自定义规则层。配置切换和当前订阅更新不执行出网检查，配置校验、加载及提交成功即生效；实际出网另用 `status` / `source.list` 检查，不能将切换成功当作 `healthy: true`。校验、加载或提交失败仍回滚。旧版本缺来源时不伪造原始订阅身份，`configs --import-current` 是显式运行配置快照。

`configs.list` 返回订阅稳定 ID；重命名不改变 ID。订阅选择使用 `id` 或 `name` 二选一。URL 不出现在订阅列表、正常错误或操作记录中。操作记录保存在执行端 `~/.local/state/domino/operations/`，目录权限 700、文件权限 600，安装替换程序目录时保留。

## 导出与跨设备部署

```bash
domino --output json --input /private/export.json call bundle.export
# export.json: {"source":"/path/to/config.yaml","arch":"arm64","output":"/private/domino.tar.gz"}
# 也可使用 subscription 地址；省略来源时自动发现兼容配置。

domino --output json --request-id "deploy-001" --input /private/deploy.json \
  call deployment.apply user@192.0.2.10
# deploy.json: {"bundle":"/private/domino.tar.gz","bundle_sha256":"导出返回的摘要"}
```

导出默认面向 Linux，可用 `system: "darwin"` 指定 macOS 归档。输出不能覆盖已有文件；文件权限为 600。`deployment.apply` 验证调用端摘要，上传私有暂存文件，再由目标以同一协议预检、备份、安装和验证，最后清理暂存。来源订阅/配置只用于构建，目标获得自己的控制密钥。重试时使用原安装包和请求键，避免重新构建出不同内容。目标侧 `service.install` 适合已有离线包的场景。

## 安全重试与预检

- `--dry-run` 校验参数、当前资源和可校验的配置，返回变更摘要，不执行配置或服务变更。规则/安装包预检会在临时目录运行内核校验；它不是权限或未来网络可用性的保证。预览不接受 `--request-id`。
- `--if-revision REVISION` 防止覆盖预检后已经变化的配置。修订号覆盖 Domino 管理配置、当前配置关联与导入源配置/元数据、订阅、规则、终端代理策略、手动运行时选择，以及本机可读的系统代理设置；不包含父 shell 的变量与基线，也不是整个操作系统的快照。
- `--request-id KEY` 是一次语义请求的去重键。同目标、操作和参数重复执行，返回原操作结果和 `replayed: true`；同一键用于不同参数返回冲突。安装包按内容摘要去重，暂存路径变化不触发重新安装。
- 不确定的旧操作不会被自动重做。连接中断后可按操作 ID 或已知请求键查询目标记录；需要目标恢复可达。

```bash
domino --output json --dry-run --input /private/change.json call mode.set
domino --output json --if-revision '预检返回的revision' --request-id 'mode-change-001' \
  --input /private/change.json call mode.set

domino --output json --input - call operations.get
# stdin: {"request_id":"mode-change-001"}，或 {"id":"operation_id"}
domino --output json call operations.list
```

修订检查、去重及写入在同一目标锁内执行。去重不替代检查结果：`effect: unknown` 表示无法确认落地状态，`changed: null`，必须查询/核实，不能据此自动重新提交。请求键用于长期关联，调用方应生成唯一键并保留。

## 结果与退出码

```json
{
  "schema_version": 1,
  "ok": true,
  "operation": "mode.set",
  "target": "localhost",
  "client": "domino",
  "operation_id": "32位操作ID",
  "revision": "64位配置修订号",
  "changed": true,
  "effect": "applied",
  "replayed": false,
  "data": {"mode": "rule", "persisted": true},
  "error": null
}
```

协议 1 的 `client` 字段固定为 `"domino"`，仅标识受管理运行时，不是可选择的客户端参数。

显式 `configs.update` 支持从已捕获的 Clash Verge 来源记录恢复订阅地址：只匹配原客户端索引中捕获时的 profile ID 和原文件关联，成功下载校验后保持配置 ID / 名称并转为在线订阅，地址保存在私有登记中。找不到地址时返回 `SUBSCRIPTION_URL_REQUIRED`，原快照不变；这与 `catch` 阶段不自动借用订阅地址的行为不同。`configs.update_all` 仍只处理已登记地址的条目。

`effect` 为 `none`、`applied`、`rolled_back` 或 `unknown`。`changed` 表示该操作确认造成状态变化；重复返回的结果保留原操作信息。服务重启、关闭连接和 provider 刷新可能成功，但配置修订号不变。

| 退出码 | 分类 |
| --- | --- |
| 0 | 查询/操作成功；健康状况另见 `data.healthy` |
| 1 | 内部错误或无效目标数据 |
| 2 | 参数、输入或协议版本错误 |
| 3 | 缺少安装、资源或平台不支持 |
| 4 | 认证或权限不足，如 sudo 未预授权 |
| 5 | SSH/控制接口/下载不可达；SSH 无法仅凭退出码可靠区分网络和认证失败 |
| 6 | 锁、修订号、请求键冲突，或旧操作尚未确认 |
| 7 | 超时或取消，需结合 `effect` |
| 8 | 应用失败，需结合恢复状态 |
| 9 | 批量操作部分失败 |

错误包含 `code`、`message`、`retryable`，可带结构化 `details`。`configs.update_all` 在 `data.results` 逐项报告成功、失败及尚未尝试项；遇到恢复未确认即停止后续写入。

## 支持范围

当前提供有界 JSON 请求：状态/来源、节点/测速、模式/日志级别、连接/流量采样、规则/provider、订阅、系统代理、独立终端代理策略、服务与安装包和操作记录。具体参数与平台限制以当前 `capabilities` 为准。状态与管理操作仅针对 Domino 自有运行时；外部 Clash/Mihomo 仅作为只读配置和当前节点选择的导入来源，不开放运行时写操作。

导出构建与上传编排分别使用 `bundle.export`、`deployment.apply`；恢复历史部署使用 `service.rollback`。普通 `domino USER@IP deploy` 保持一条命令完成部署。日志用有界 `logs.read` 返回脱敏消息，流量用 `traffic.sample`；UI 与无限日志/流量输出不属于普通 JSON 请求。NDJSON 持续事件流尚未开放。

`delay.test` 支持 `config` 指定目标配置库中的完整名称，与 `name` / `node` / `group` 互斥。普通入口为 `domino test --config 名称`；`name` 与已登记配置名完整相同时优先按配置测试。通过缓存配置运行隔离临时内核，返回原有逐节点 `name`、`delay_ms`、`ok` 数组，不切换当前配置，不更新订阅或缓存。

裸 `domino --output json test` 调用 `delay.summary`，返回按配置的数组：`name`、`active`、`total`、`available`、`unavailable`、`status`。`status` 为 `tested` / `uncached` / `error`；未完成节点检测时计数为 `null`，附安全的 `message`，加载错误可带 `error_code`。单配置仍使用 `delay.test`，逐节点结果不变。

普通终端 `domino select` 支持交互菜单，`domino select "节点名"` 支持唯一名称匹配；机器入口继续要求显式 `--group` 和 `--node`，映射到原有 `nodes.select` 参数，不进入交互菜单或隐式选择策略组。

日志级别的人类命令为 `domino log [LEVEL]`，旧 `log-level` 人类命令及 TUI 别名均已移除，远端使用 `domino USER@IP log LEVEL`，机器操作名仍为 `log-level.get` / `log-level.set`；JSON 仍使用 `log-level` 键。`logs.read` 继续读取实际日志内容。

交互终端的 `domino traffic` 默认内嵌完整动态面板，内容与 `--full` 相同，`--full` 仅切换为全屏显示；`--full` 不用于 JSON、捕获或机器请求；机器协议 `traffic.sample` 和普通 `traffic --json` 仍为单次有界采样，不打开终端面板。普通 CLI `traffic --json --watch --count N` 保持原逐行 JSON 输出，与机器请求的单一结果信封不同。

UI 通过私有的 `--ui-result` 请求单次测速结果与当前选择信息，并单独消费 stderr 检测进度；该私有数据不是公开 Agent 操作，普通 `test --json` 仍返回原数组。`/catch` 的私有只读 `catch-options` 查询仅提供当前目标的兼容来源名称和路径，选择后调用同版 CLI 完成确认和捕获，不新增机器写操作；UI 不修改父 shell 环境。
