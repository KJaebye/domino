# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""English catalog keyed by explicit source messages; user data is never translated."""
ENGLISH = {'语言偏好保存在本机；请使用 domino language zh 或 domino language en。': 'Language preferences are local; use domino language zh or domino language en.','该操作尚未接入机器协议。': 'This operation is not available through the machine protocol.',
 '机器接口参数无效。': 'Invalid machine interface arguments.',
 '目标没有返回有效的机器协议结果。': 'The target did not return a valid machine protocol result.',
 '目标结果版本或结构无效。': 'Invalid target result version or structure.',
 '安装包需为权限 600 的普通文件。': 'The package must be a regular file with mode 600.',
 '安装包摘要不一致。': 'Package checksum mismatch.',
 '目标暂存响应无效。': 'Invalid target staging response.',
 '目标暂存路径无效。': 'Invalid target staging path.',
 'JSON 日志请求需为有界读取。': 'JSON log requests require a bounded read.',
 '机器请求仅支持单次流量采样，不支持 --watch 或 --full。': 'Machine requests support a single traffic sample; --watch and --full are not '
                                        'supported.',
 '目标结果无法解析。': 'Unable to parse the target result.',
 '不支持的协议版本。': 'Unsupported protocol version.',
 '修订标识格式无效。': 'Invalid revision identifier.',
 '请求去重键长度需为 1–200 个字符。': 'The deduplication key must contain 1–200 characters.',
 '本机请求不能附加 SSH 认证选项。': 'Local requests cannot include SSH authentication options.',
 '未支持的操作。': 'Unsupported operation.',
 '目标结果与请求不一致。': 'The target result does not match the request.',
 '目标退出码与结果不一致。': 'The target exit code does not match the result.',
 '请求超时。': 'Request timed out.',
 '无法读取输入或执行目标请求。': 'Unable to read the input or execute the target request.',
 '请求已中断。': 'Request interrupted.',
 '机器接口发生内部错误。': 'Internal machine interface error.',
 '输入内容过大。': 'Input is too large.',
 '输入必须是 JSON 对象。': 'Input must be a JSON object.',
 '目标地址或用户格式无效。': 'Invalid target address or username.',
 '输入文件权限应为 600 或更严格。': 'Input file permissions must be 600 or more restrictive.',
 'SSH 连接未建立，请检查网络和认证配置。': 'SSH connection not established; check the network and authentication settings.',
 '机器请求格式无效。': 'Invalid machine request.',
 '目标执行出现内部错误。': 'Internal error on the target.',
 '捕获本机代理，并一键部署到指定 IP 的设备上，让翻墙像 domino 一样简单。': 'Capture a local proxy and deploy independent proxy access to another '
                                              'computer over SSH.',
 '命令': 'Command',
 'Clash Verge 配置索引存在无效或不安全的项目，已跳过；其他来源不受影响。': 'Skipped invalid or unsafe Clash Verge profile entries; other sources '
                                              'are unaffected.',
 '代理地址解析': 'Proxy address resolution',
 '目标地址解析': 'Target address resolution',
 '代理入口连接': 'Proxy connection',
 'HTTPS 隧道建立': 'HTTPS tunnel setup',
 'HTTPS / TLS 握手': 'HTTPS / TLS handshake',
 'HTTPS 响应': 'HTTPS response',
 '出网请求': 'Outbound request',
 '出网请求失败（curl {0}）。': 'Outbound request failed (curl {0}).',
 '请结合客户端日志检查当前节点、分流规则及目标网站。': 'Check the current node, routing rules and destination in the client logs.',
 '位置参数': 'Positional arguments',
 '选项': 'Options',
 '显示帮助并退出': 'Show this help message and exit',
 '该文件不是兼容的 Clash/Mihomo 节点配置。': 'This file is not a compatible Clash/Mihomo node configuration.',
 '客户端当前启用（索引）': 'Selected in the client index',
 '来源': 'Source',
 '可用': 'Available',
 '入口出网': 'Proxy connectivity',
 '代理入口': 'Proxy endpoint',
 '配置状态': 'Profile status',
 '独立部署需要兼容的节点配置；本机代理端口、系统隧道/TUN 在线不代表配置可迁移。': 'Independent deployment requires compatible node settings; an active '
                                              'local proxy or system TUN does not prove the profile is portable.',
 '请检查本机代理的认证设置；控制接口密钥与代理认证不是同一项。': 'Check local proxy authentication; controller secrets and proxy credentials are '
                                   'separate.',
 '地区未返回': 'Region unavailable',
 ' · {0} 个节点集': ' · {0} node providers',
 '（保留目标新版）': '(kept the newer target version)',
 '添加命名订阅，默认隐藏输入地址；可用 --url 提供完整配置订阅地址。': 'Save a named subscription; the URL is hidden by default, or provide --url.',
 '切换本机当前配置；在线订阅首次使用时自动下载。': 'Switch the local active profile; subscriptions are downloaded on first use.',
 '更新指定订阅；名称为 all 时更新全部在线订阅。': 'Update a subscription; use all to update every subscription.',
 '修改配置名称，保留配置内容和订阅地址。': 'Rename a profile while preserving its content and subscription URL.',
 '删除非当前配置；当前使用的配置需先切换后再删除。': 'Remove an inactive profile; switch away from the active profile first.',
 '设置或修改订阅地址，默认隐藏输入；本地快照设置地址后可在线更新。': 'Set or change a subscription URL using hidden input; a snapshot can then be '
                                     'updated online.',
 '查看当前系统代理，省略动作时默认执行此操作。': 'Show the system proxy; this is the default when no action is specified.',
 '将系统代理指向 Domino，并保存此前的设置。': 'Point the system proxy to Domino and save the previous settings.',
 '恢复开启 Domino 系统代理前保存的设置。': 'Restore the settings saved before enabling the Domino system proxy.',
 '安装 Domino 内核、配置和后台服务；未提供节点配置时先准备基础环境，随后用 configs add/switch 配置订阅。': 'Install the Domino core, profile and background '
                                                                      'service. Without a node profile, prepare the '
                                                                      'base installation first, then use configs '
                                                                      'add/switch.',
 '本机管理失败（退出码 {0}）。': 'Local management failed (exit code {0}).',
 '缓存目录不能是符号链接。': 'The cache directory must not be a symlink.',
 '代理端口必须在 1024–65535 之间。': 'Proxy port must be between 1024 and 65535.',
 'SSH 端口必须在 1–65535 之间。': 'SSH port must be between 1 and 65535.',
 '目标格式应为 IP、SSH 别名或 user@IP。': 'Target must be an IP address, SSH alias or user@IP.',
 'SSH 用户名无效。': 'Invalid SSH username.',
 '下载地址必须使用 HTTPS。': 'Downloads require HTTPS.',
 '指定的源配置文件不存在。': 'The specified source profile does not exist.',
 '源文件不是包含节点的 Clash/Mihomo 配置。': 'The source file is not a Clash/Mihomo profile containing nodes.',
 '直接使用订阅时不读取本机客户端控制接口，请移除 --controller 和 --controller-socket。': 'Direct subscription imports do not read a local '
                                                                'client controller; remove --controller and '
                                                                '--controller-socket.',
 '完整配置订阅': 'Full profile subscription',
 'Domino 导入源快照只检查文件兼容性，不检查其中保存的旧代理端口。': 'Domino source snapshots are checked for file compatibility; their old saved '
                                        'proxy ports are not tested.',
 '已保存（非当前）': 'Saved (inactive)',
 '已保存（当前项无法确认）': 'Saved (active state unknown)',
 '当前配置': 'Current profile',
 '导入源快照': 'Source snapshot',
 '导入来源': 'Import source',
 '源快照': 'Source snapshot',
 '配置选择': 'Profile selection',
 '检查未通过': 'Check failed',
 '运行配置': 'Runtime profile',
 '原始配置': 'Original profile',
 '检查范围': 'Check scope',
 '配置检查': 'Profile check',
 '出网检查': 'Connectivity check',
 '代理入口要求身份认证（HTTP 407）。': 'Proxy authentication required (HTTP 407).',
 '源控制接口必须是本机回环地址。': 'The source controller must use a local loopback address.',
 '读取源 Clash 当前节点': 'Read the active Clash node',
 '源 Clash 未处于规则或全局代理模式，请先在源客户端启用代理。': 'The source Clash client is not in rule or global mode; enable its proxy first.',
 '官方 release 元数据格式无效。': 'Invalid official release metadata.',
 '官方 release 元数据不是有效稳定版本。': 'Official release metadata does not identify a valid stable version.',
 '目标系统仅支持 Linux 或 macOS。': 'Only Linux and macOS targets are supported.',
 '官方 release 安装包列表无效。': 'Invalid package list in the official release.',
 '官方 release 缺少匹配架构的安装包或 SHA-256 值。': 'The official release has no matching architecture package or SHA-256 checksum.',
 '安装包来源不符合当前资源源地址。': 'The package origin does not match the configured resource source.',
 '复用已安装 Mihomo {0} 的已校验缓存 / {1}。': 'Reusing verified cached Mihomo {0} / {1}.',
 'Mihomo 版本信息': 'Mihomo version metadata',
 'Mihomo 内核': 'Mihomo core',
 '安装包就绪：{0} / {1}，{2} 个内联节点，{3} 个节点 provider。': 'Package ready: {0} / {1}, {2} inline nodes, {3} node providers.',
 '远端源码压缩校验失败，未执行远端操作。': 'Remote source compression verification failed; nothing was executed remotely.',
 '找不到 VS Code 用户设置，请通过 --vscode-settings 指定路径。': 'VS Code user settings were not found; specify --vscode-settings.',
 ' · {0} 个节点': ' · {0} nodes',
 '部署完成': 'Deployment complete',
 '代理出网': 'Proxy connectivity',
 'CLI 版本': 'CLI version',
 '查看状态': 'Check status',
 '准备': 'Preparing',
 '配置与内核…': 'Profile and core…',
 '远端临时目录不符合预期，停止上传。': 'Unexpected remote temporary directory; upload stopped.',
 '本机：domino list；远端：domino user@host list；部署：domino user@host deploy。': 'Local: domino list; remote: domino user@host '
                                                                        'list; deploy: domino user@host deploy.',
 '源电脑下载使用的代理，例如 http://127.0.0.1:7897；不作为目标机上游': 'Proxy for source-side downloads, for example http://127.0.0.1:7897; '
                                                 'not the target upstream',
 '源 Clash 本机控制接口 URL': 'Local source Clash controller URL',
 '源 Clash Unix 控制 socket': 'Source Clash Unix controller socket',
 '附加本地资源目录；可重复指定，用于 provider、证书和 Geo 数据库': 'Additional local resource directory; repeat for providers, certificates '
                                           'and Geo databases',
 '本机 Mihomo 可执行文件，用于提前校验配置': 'Local Mihomo executable for profile validation',
 '固定内核版本，例如 v1.19.33；默认最新稳定版，本机重复安装优先复用已安装版本的已校验缓存': 'Pin the core version, for example v1.19.33; default to stable, '
                                                     'reusing verified installed-version cache on repeat local '
                                                     'installs',
 '代理端口，默认 {0}': 'Proxy port, default {0}',
 '本机控制接口端口，默认 {0}': 'Local controller port, default {0}',
 '不设置目标终端/VS Code 的代理环境': 'Do not configure proxy environment variables for the target terminal or VS Code',
 '部署后 HTTPS 出网验证地址': 'HTTPS URL for post-deployment connectivity verification',
 '当前生效的 Clash/Mihomo YAML 或 JSON 配置': 'Currently active Clash/Mihomo YAML or JSON profile',
 '返回完整 Clash/Mihomo 配置的 HTTPS 订阅链接': 'HTTPS subscription returning a complete Clash/Mihomo profile',
 '选择并捕获外部代理配置': 'Select and capture an external proxy profile',
 '选择本机 Clash/Mihomo 运行配置或保存配置；catch all 捕获全部。\n捕获成功后自动开启 Domino；已有安装保留当前配置和节点选择。': 'Select a local running or saved '
                                                                                   'Clash/Mihomo profile; catch all '
                                                                                   'captures every compatible '
                                                                                   'profile.\n'
                                                                                   'Start Domino after capture; '
                                                                                   'preserve the active profile and '
                                                                                   'node selections in existing '
                                                                                   'installations.',
 '捕获所有兼容配置，并跳过重复项': 'Capture all compatible profiles, skipping duplicates',
 '明确选择本地 Clash/Mihomo 配置文件': 'Explicitly select a local Clash/Mihomo profile file',
 '接受捕获影响，跳过最终确认；多个来源仍需选择或指定 all': 'Accept capture effects and skip final confirmation; still select a source or '
                                  'specify all',
 '禁止 sudo 密码询问；不代表同意导入': 'Disable sudo password prompts; this does not authorize an import',
 'localhost 管理当前用户的本机；USER@IP 或 SSH 别名管理远端；省略时等同 localhost': 'localhost manages the current local user; USER@IP or an '
                                                             'SSH alias manages a remote target; default localhost',
 '目标 IP、SSH Host 别名或 USER@IP；本机请运行安装程序': 'Target IP, SSH Host alias or USER@IP; use the installer for local setup',
 '将代理部署到指定电脑': 'Deploy a proxy to another computer',
 '选择本机兼容配置部署到指定电脑；未指定来源时，交互终端先显示配置选择菜单。': 'Select a compatible local profile and deploy it; interactive terminals show '
                                          'a source menu when no source is specified.',
 '显示配置路径、完整安装过程和终端接入说明': 'Show profile paths, complete installation output and terminal integration instructions',
 '同时更新本机 VS Code 对该目标的代理设置': 'Also update local VS Code proxy settings for this target',
 'VS Code 用户 settings.json 路径': 'VS Code user settings.json path',
 '停止目标当前用户的 VS Code/Codex 进程以应用环境': "Stop the target user's VS Code/Codex processes to apply the environment",
 '只检查目标和源配置，不修改设备': 'Inspect target and source without changing the device',
 '查看服务、系统代理目标和实际出网状态': 'Show service, system proxy endpoint and outbound connectivity',
 '查看服务、自启动、代理端口及实际出网状态，同时显示系统代理是否开启及其目标。Domino 默认代理地址为 127.0.0.1:{0}，自定义端口时显示实际值。': 'Show service, autostart, proxy '
                                                                                    'port and connectivity, including '
                                                                                    'system proxy status and '
                                                                                    'destination. The default proxy is '
                                                                                    '127.0.0.1:{0}; custom ports are '
                                                                                    'displayed when configured.',
 '扫描外部代理配置和 Domino 管理的代理配置': 'Scan external profiles and Domino-managed proxy profiles',
 '分区展示外部客户端配置和 Domino 管理的配置列表，分别统计数量。\n保存配置只检查兼容性，不借用运行端口证明出网；运行入口并发检查，每个超时 5 秒。\n使用 --source 检查指定来源，不切换或管理来源客户端。': 'Show '
                                                                                                                    'external '
                                                                                                                    'clients '
                                                                                                                    'and '
                                                                                                                    'Domino-managed '
                                                                                                                    'profiles '
                                                                                                                    'separately '
                                                                                                                    'with '
                                                                                                                    'counts.\n'
                                                                                                                    'Saved '
                                                                                                                    'profiles '
                                                                                                                    'are '
                                                                                                                    'checked '
                                                                                                                    'for '
                                                                                                                    'compatibility '
                                                                                                                    'without '
                                                                                                                    'reusing '
                                                                                                                    'old '
                                                                                                                    'proxy '
                                                                                                                    'ports; '
                                                                                                                    'running '
                                                                                                                    'endpoints '
                                                                                                                    'are '
                                                                                                                    'checked '
                                                                                                                    'concurrently '
                                                                                                                    'with '
                                                                                                                    'a '
                                                                                                                    '5-second '
                                                                                                                    'timeout.\n'
                                                                                                                    'Use '
                                                                                                                    '--source '
                                                                                                                    'to '
                                                                                                                    'inspect '
                                                                                                                    'a '
                                                                                                                    'specific '
                                                                                                                    'source '
                                                                                                                    'without '
                                                                                                                    'switching '
                                                                                                                    'or '
                                                                                                                    'managing '
                                                                                                                    'its '
                                                                                                                    'client.',
 '检查指定的本地 Clash/Mihomo 配置文件': 'Inspect a specific local Clash/Mihomo profile',
 '比较 macOS 原生与代理 HTTPS 连通性（不修改设置）': 'Compare native and proxied macOS HTTPS connectivity without changing settings',
 '无凭据和查询参数的内网 HTTPS 地址': 'LAN HTTPS URL without credentials or query parameters',
 '仅诊断时跳过证书校验': 'Skip certificate verification for diagnostics only',
 '查看策略组、当前选择和可用节点': 'Show policy groups, active selections and available nodes',
 '只查看指定策略组的候选节点': 'Show candidates for a specific policy group',
 '交互选择节点，或按名称切换节点': 'Select a node interactively or by name',
 '不带名称打开节点选择菜单；填写名称或关键词，匹配多个时选择候选编号。\n多个手动策略组可选时再选择策略组；仅修改当前配置的节点选择。': 'Open the node picker without a name; use a '
                                                                       'name or keyword to select matching '
                                                                       'candidates.\n'
                                                                       'Choose a policy group when multiple manual '
                                                                       'groups are available; only active-profile '
                                                                       'selections are changed.',
 '示例：domino select；domino select "日本"；domino USER@IP select；domino select "日本" --group "节点选择"；含方括号或空格的节点名必须加引号。': 'Examples: '
                                                                                                                  'domino '
                                                                                                                  'select; '
                                                                                                                  'domino '
                                                                                                                  'select '
                                                                                                                  '"Japan"; '
                                                                                                                  'domino '
                                                                                                                  'USER@IP '
                                                                                                                  'select; '
                                                                                                                  'domino '
                                                                                                                  'select '
                                                                                                                  '"Japan" '
                                                                                                                  '--group '
                                                                                                                  '"Node '
                                                                                                                  'selection". '
                                                                                                                  'Quote '
                                                                                                                  'names '
                                                                                                                  'containing '
                                                                                                                  'brackets '
                                                                                                                  'or '
                                                                                                                  'spaces.',
 '指定手动策略组；省略时按可选范围选择': 'Manual policy group; select from available groups when omitted',
 '兼容写法：指定该组中的完整节点或下层策略组名称': 'Compatibility option: exact node or nested policy group name',
 '开启 Domino，接通系统代理': 'Start Domino and connect the system proxy',
 '关闭 Domino，恢复系统代理': 'Stop Domino and restore the system proxy',
 '重启 Domino 并接通系统代理': 'Restart Domino and connect the system proxy',
 '查看代理服务日志': 'Show proxy service logs',
 '查看或设置代理模式': 'Show or set proxy mode',
 '查看或设置日志级别；日志内容用 logs 查看': 'Show or set log level; use logs for log content',
 '列出全部日志级别，用 ● 标记当前项；填写级别直接设置。日志内容使用 domino logs 查看。': 'List log levels with the current level marked by ●; provide a '
                                                       'level to set it. Use domino logs to view logs.',
 '示例：domino log；domino log debug；domino USER@IP log warning。': 'Examples: domino log; domino log debug; domino USER@IP '
                                                               'log warning.',
 '汇总全部配置的节点连通性，或查看指定配置的节点延迟': "Summarize node connectivity across profiles or inspect a profile's node latency",
 '节点或策略组名称，可用唯一部分名称；省略或 all 按配置汇总': 'Node or policy group name, including a unique substring; omit or use all for a '
                                    'profile summary',
 '测试配置库中指定配置的全部节点，不切换当前配置': 'Test all nodes in a saved profile without switching the active profile',
 '测速节点的完整名称或唯一部分名称；含方括号、空格时请加引号': 'Exact node name or unique substring; quote names containing brackets or spaces',
 '明确按策略组名称匹配，测试组内各项': 'Explicitly match a policy group and test its members',
 '按配置汇总，等同不填写名称': 'Summarize by profile, equivalent to omitting the name',
 'HTTPS 测速地址（默认：https://www.gstatic.com/generate_204）': 'HTTPS latency test URL (default: '
                                                        'https://www.gstatic.com/generate_204)',
 '单项超时，默认 5000 毫秒（5 秒），范围 100–60000': 'Per-item timeout, default 5000 ms (5 seconds), range 100–60000',
 '输出 JSON，供脚本或 Agent 使用': 'Output JSON for scripts or agents',
 '查看连接及其规则/节点，或关闭连接': 'Show connections with their rules/nodes, or close connections',
 '内嵌动态流量面板，--full 使用全屏': 'Inline live traffic dashboard; --full uses the full screen',
 '默认内嵌刷新全部流量信息、趋势图和峰值，保留终端历史；--full 切换为全屏。\nq、Esc 或 Ctrl+C 退出。\nJSON 和重定向默认单次采样；--watch 可持续输出采样。': 'Refresh traffic '
                                                                                                   'metrics, trends '
                                                                                                   'and peaks inline '
                                                                                                   'while keeping '
                                                                                                   'terminal history; '
                                                                                                   '--full uses the '
                                                                                                   'full screen.\n'
                                                                                                   'Exit with q, Esc '
                                                                                                   'or Ctrl+C.\n'
                                                                                                   'JSON and '
                                                                                                   'redirected output '
                                                                                                   'default to one '
                                                                                                   'sample; --watch '
                                                                                                   'enables continuous '
                                                                                                   'sampling.',
 '使用全屏显示；内容和功能与默认内嵌面板一致': 'Use the full screen with the same dashboard information and controls',
 '持续采样；终端默认开启，JSON / 重定向时可显式使用': 'Sample continuously; default in terminals, optional for JSON or redirected output',
 '刷新间隔，默认 1 秒，范围 0.2–60 秒': 'Refresh interval, default 1 second, range 0.2–60 seconds',
 '持续采样次数，0 表示直到退出': 'Number of samples; 0 continues until stopped',
 '分流规则管理': 'Routing rule management',
 '规则示例：DOMAIN-SUFFIX,example.com,DIRECT。新增规则默认置顶，先校验再生效。': 'Example: DOMAIN-SUFFIX,example.com,DIRECT. New rules are '
                                                           'validated, then prepended and applied.',
 'add/remove 后的完整 Mihomo 规则，请用引号包裹': 'Complete Mihomo rule after add/remove; enclose it in quotes',
 '查看自定义规则原文': 'Show custom rules verbatim',
 '节点与规则集合管理': 'Manage node and rule providers',
 '配置管理（在线订阅与快照）': 'Profile management (subscriptions and snapshots)',
 '直接运行 domino list 查看列表；使用下列子命令管理在线订阅与配置快照。': 'Run domino list to view saved profiles; use these subcommands to manage '
                                              'subscriptions and snapshots.',
 '查看 Domino 管理的所有代理配置': 'List all Domino-managed proxy profiles',
 '查看配置列表；可使用 --import-current 保存当前配置快照。': 'List profiles; use --import-current to save the active profile as a '
                                          'snapshot.',
 '添加订阅配置': 'Add a subscription profile',
 '切换本机配置': 'Switch the local profile',
 '更新配置（all 表示全部在线订阅）': 'Update a profile (all updates every online subscription)',
 '重命名配置': 'Rename a profile',
 '删除配置': 'Remove a profile',
 '设置订阅地址': 'Set a subscription URL',
 '系统代理管理': 'System proxy management',
 '查看系统代理（默认）': 'Show system proxy (default)',
 '开启系统代理': 'Enable system proxy',
 '恢复原代理设置': 'Restore previous proxy settings',
 '终端代理管理': 'Terminal proxy management',
 '通过代理环境变量让终端（Terminal）中的程序使用 Domino；on 开启、off 恢复原变量、status 查看端口和环境变量。': 'Use proxy environment variables to route '
                                                                         'terminal programs through Domino; on '
                                                                         'enables, off restores previous variables, '
                                                                         'status shows the port and variables.',
 '已接入终端返回命令行后同步。接入方法：. "$HOME/.config/domino/proxy.env"': 'Integrated terminals synchronize when the prompt returns. '
                                                          'To integrate: . "$HOME/.config/domino/proxy.env"',
 '查看终端代理状态': 'Show terminal proxy status',
 '使用 Domino 代理': 'Use the Domino proxy',
 '打开纯终端交互控制台': 'Open the terminal workspace',
 '输出当前 shell 的代理设置，使用 eval "$(domino env)" 生效': 'Print shell proxy settings; apply with eval "$(domino env)"',
 '输出 zsh / bash 的 Tab 补全脚本': 'Print zsh / bash Tab completion scripts',
 '恢复本机或指定电脑上一次部署前的服务和环境文件': 'Restore service and environment files from the previous deployment on this or another '
                            'computer',
 '指定本工具生成的备份 ID，默认最近一次': 'Backup ID created by Domino; default to the latest backup',
 '卸载运行环境并清理终端接入、配置及备份': 'Uninstall runtime and remove terminal integration, profiles and backups',
 '恢复 Domino 接管的代理，停止并移除服务，删除内核、配置库、备份和默认缓存。仅清理 Domino 的终端标记区块；包管理器安装的 CLI 由原包管理器卸载。': 'Restore proxies managed by '
                                                                                      'Domino, stop and remove its '
                                                                                      'service, and remove core, '
                                                                                      'profile library, backups and '
                                                                                      'default cache. Remove only '
                                                                                      'Domino terminal blocks; '
                                                                                      'uninstall a package-managed CLI '
                                                                                      'through its package manager.',
 '确认删除运行配置、配置库与备份': 'Confirm removal of runtime profiles, profile library and backups',
 '只预览清理范围，不修改任何文件或服务': 'Preview cleanup without changing files or services',
 '导出内核和配置，供目标电脑离线安装': 'Export core and profiles for offline installation on another computer',
 '将 Mihomo 内核、节点与分流规则、相关资源及 Domino 管理程序打包为 .tar.gz。\n在本机生成安装包后，将包复制到另一台 Linux 电脑进行安装。\n适合目标电脑无法下载内核或管理依赖的情况；安装后仍需能连接代理节点。\n安装包包含节点凭据，请交给需要使用该配置的人。': 'Package '
                                                                                                                                                     'the '
                                                                                                                                                     'Mihomo '
                                                                                                                                                     'core, '
                                                                                                                                                     'nodes, '
                                                                                                                                                     'routing '
                                                                                                                                                     'rules, '
                                                                                                                                                     'resources '
                                                                                                                                                     'and '
                                                                                                                                                     'Domino '
                                                                                                                                                     'management '
                                                                                                                                                     'code '
                                                                                                                                                     'as '
                                                                                                                                                     '.tar.gz.\n'
                                                                                                                                                     'Create '
                                                                                                                                                     'the '
                                                                                                                                                     'package '
                                                                                                                                                     'locally, '
                                                                                                                                                     'then '
                                                                                                                                                     'copy '
                                                                                                                                                     'it '
                                                                                                                                                     'to '
                                                                                                                                                     'another '
                                                                                                                                                     'Linux '
                                                                                                                                                     'computer.\n'
                                                                                                                                                     'Useful '
                                                                                                                                                     'when '
                                                                                                                                                     'the '
                                                                                                                                                     'target '
                                                                                                                                                     'cannot '
                                                                                                                                                     'download '
                                                                                                                                                     'the '
                                                                                                                                                     'core '
                                                                                                                                                     'or '
                                                                                                                                                     'dependencies; '
                                                                                                                                                     'it '
                                                                                                                                                     'must '
                                                                                                                                                     'still '
                                                                                                                                                     'be '
                                                                                                                                                     'able '
                                                                                                                                                     'to '
                                                                                                                                                     'reach '
                                                                                                                                                     'proxy '
                                                                                                                                                     'nodes.\n'
                                                                                                                                                     'The '
                                                                                                                                                     'package '
                                                                                                                                                     'contains '
                                                                                                                                                     'node '
                                                                                                                                                     'credentials; '
                                                                                                                                                     'share '
                                                                                                                                                     'it '
                                                                                                                                                     'only '
                                                                                                                                                     'with '
                                                                                                                                                     'its '
                                                                                                                                                     'intended '
                                                                                                                                                     'users.',
 '示例：在本机准备 Linux ARM64 安装包\n  domino export --arch arm64 --output ./domino-linux-arm64.tar.gz\n\n复制到目标电脑后运行安装程序\n  ./install.sh --bundle ./domino-linux-arm64.tar.gz\n\n目标尚未安装 Domino 命令时，首次离线引导步骤见 README。': 'Example: '
                                                                                                                                                                                                              'prepare '
                                                                                                                                                                                                              'a '
                                                                                                                                                                                                              'Linux '
                                                                                                                                                                                                              'ARM64 '
                                                                                                                                                                                                              'package '
                                                                                                                                                                                                              'locally\n'
                                                                                                                                                                                                              '  '
                                                                                                                                                                                                              'domino '
                                                                                                                                                                                                              'export '
                                                                                                                                                                                                              '--arch '
                                                                                                                                                                                                              'arm64 '
                                                                                                                                                                                                              '--output '
                                                                                                                                                                                                              './domino-linux-arm64.tar.gz\n'
                                                                                                                                                                                                              '\n'
                                                                                                                                                                                                              'Copy '
                                                                                                                                                                                                              'it '
                                                                                                                                                                                                              'to '
                                                                                                                                                                                                              'the '
                                                                                                                                                                                                              'target '
                                                                                                                                                                                                              'and '
                                                                                                                                                                                                              'run '
                                                                                                                                                                                                              'the '
                                                                                                                                                                                                              'installer\n'
                                                                                                                                                                                                              '  '
                                                                                                                                                                                                              './install.sh '
                                                                                                                                                                                                              '--bundle '
                                                                                                                                                                                                              './domino-linux-arm64.tar.gz\n'
                                                                                                                                                                                                              '\n'
                                                                                                                                                                                                              'See '
                                                                                                                                                                                                              'README '
                                                                                                                                                                                                              'for '
                                                                                                                                                                                                              'initial '
                                                                                                                                                                                                              'offline '
                                                                                                                                                                                                              'bootstrap '
                                                                                                                                                                                                              'when '
                                                                                                                                                                                                              'Domino '
                                                                                                                                                                                                              'is '
                                                                                                                                                                                                              'not '
                                                                                                                                                                                                              'installed.',
 '目标 Linux 电脑的架构：ARM64 选 arm64，x86_64 选 amd64': 'Linux target architecture: arm64 for ARM64, amd64 for x86_64',
 '安装包输出路径（包含节点凭据，权限 600）': 'Output package path (contains node credentials; mode 600)',
 '在本机 macOS/Linux 安装独立代理和管理命令': 'Install an independent proxy and management commands on local macOS/Linux',
 '使用 Domino export 生成的离线安装包': 'Use an offline package generated by Domino export',
 '为 --subscription 保存名称；省略时沿用已有名称或使用订阅主机名': 'Name for --subscription; default to an existing name or the subscription '
                                            'hostname',
 '禁止 sudo 密码询问': 'Disable sudo password prompts',
 '安装支持 macOS 和使用 systemd 的 Linux。': 'Installation supports macOS and systemd-based Linux.',
 '请以具有 sudo 权限的普通用户安装，不要直接使用 root。': 'Install as a regular user with sudo privileges, not directly as root.',
 '常用入口': 'Common commands',
 '节点与检测': 'Nodes and checks',
 '服务与代理': 'Service and proxy',
 '命令概览': 'Command overview',
 '  本机省略 USER@IP；远端将目标放在命令前。': '  Omit USER@IP locally; place the target before the command for remote management.',
 '未发现兼容配置，请用 --source 指定配置，或用 --subscription 提供完整配置订阅。': 'No compatible profile found; specify --source or provide a '
                                                         'full profile subscription with --subscription.',
 '选择部署配置': 'Select deployment profile',
 '{0} 个本机配置 · 目标 {1}': '{0} local profiles · target {1}',
 '配置编号无效，未部署。': 'Invalid profile number; nothing was deployed.',
 '捕获已取消': 'Capture cancelled',
 '未修改本机 Domino。': 'Local Domino was not changed.',
 '选择方式': 'Selection',
 '选择捕获配置': 'Select a profile to capture',
 '{0} 个外部配置 · 重复项自动跳过': '{0} external profiles · duplicates skipped automatically',
 'catch all 不能与 --source 同时使用。': 'catch all cannot be combined with --source.',
 '捕获需要确认。请在终端运行 domino catch；脚本明确指定 --yes；--batch 不代表同意。': 'Capture requires confirmation. Run domino catch in a '
                                                           'terminal or explicitly pass --yes in scripts; --batch does '
                                                           'not authorize an import.',
 '捕获完成': 'Capture complete',
 '新增/更新 {0} · 跳过 {1} · 失败 {2}': 'Added/updated {0} · skipped {1} · failed {2}',
 '查看配置': 'List profiles',
 '切换配置': 'Switch profile',
 'domino switch "配置名"': 'domino switch "profile-name"',
 '捕获需要确认。请在终端运行 domino catch；脚本明确指定 --yes 才会导入，--batch 不代表同意。': 'Capture requires confirmation. Run domino catch in a '
                                                                'terminal; scripts import only with explicit --yes. '
                                                                '--batch is not consent.',
 '捕获本机代理配置': 'Capture local proxy profile',
 '确认后安装或替换当前用户的 Domino 独立服务': "Confirmation installs or replaces the current user's independent Domino service",
 '来源文件': 'Source file',
 '目标电脑': 'Target computer',
 '本机 · 当前用户': 'Local · current user',
 '节点选择': 'Node selection',
 '配置模式': 'Profile mode',
 '监听端口': 'Listening ports',
 '代理 {0} · 控制接口 {1}（仅本机）': 'Proxy {0} · controller {1} (loopback only)',
 '安装影响': 'Installation effects',
 '安装独立内核和后台服务；已有 Domino 配置将被替换、服务将重启，并保留部署前备份。': 'Install an independent core and background service; replace an '
                                                 'existing Domino profile, restart its service and preserve a '
                                                 'pre-deployment backup.',
 '不更新终端代理集成': 'Leave terminal proxy integration unchanged',
 '更新命令 PATH 和终端代理集成；全新安装默认关闭，已有策略按安装器规则保留或迁移': 'Update command PATH and terminal proxy integration; new installations '
                                               'default to off, existing policies are preserved or migrated',
 '环境影响': 'Environment effects',
 '来源客户端': 'Source client',
 '保持运行，不修改其配置或节点选择；初始化后自动开启 Domino 并接通系统代理，不开启 TUN。': 'Keep the source client running with its profile and selections '
                                                      'intact; start Domino and connect its system proxy after '
                                                      'initialization, without enabling TUN.',
 '配置登记': 'Profile registration',
 '保存独立导入源快照并设为 Domino 当前配置；已有在线订阅保留，不自动导入其他发现项。': 'Save an independent source snapshot as the active Domino profile; '
                                                  'preserve existing subscriptions without automatically importing '
                                                  'other discovered profiles.',
 '初始化完成': 'Initialization complete',
 '独立代理已就绪': 'Independent proxy ready',
 '下一步': 'Next step',
 '捕获完成后自动开启 Domino 并接通系统代理': 'Start Domino and connect the system proxy after capture',
 '--bundle 不能与 --source 或 --subscription 同时使用。': '--bundle cannot be combined with --source or --subscription.',
 '--name 需与 --subscription 配合使用。': '--name requires --subscription.',
 '代理端口和控制端口不能相同。': 'Proxy and controller ports must differ.',
 'Domino 已安装。重新打开终端后：domino add "名称"；domino switch "名称"。': 'Domino installed. Open a new terminal, then run domino add '
                                                           '"name" and domino switch "name".',
 '本机独立代理已配置。管理命令：domino status；domino nodes': 'Local independent proxy configured. Manage with domino status or domino '
                                              'nodes.',
 '没有找到匹配的{0}；请运行 domino nodes 查看名称。': 'No matching {0}; run domino nodes to see available names.',
 '匹配到多个{0}，请使用完整名称（含方括号或空格时加引号）：': 'Multiple matching {0}; use an exact name and quote brackets or spaces:',
 '编号 / 名称（回车取消）：': 'Number / name (Enter to cancel):',
 '非交互选择需要节点名；使用 domino [USER@IP] select "节点名" --group "策略组名"。': 'Non-interactive selection requires a node name: '
                                                                'domino [USER@IP] select "node" --group "group".',
 '没有可手动选择的策略组；自动策略组不能直接切换节点。': 'No manually selectable policy group; automatic groups cannot be switched directly.',
 '手动策略组': 'Manual policy group',
 '选择策略组': 'Select policy group',
 '选择节点': 'Select node',
 '--full 需要交互终端，不能用于 JSON、重定向或捕获输出。': '--full requires an interactive terminal and cannot be used with JSON, '
                                      'redirection or captured output.',
 '交互控制台需要终端，请在终端运行 domino ui；脚本请使用各子命令及 --json。': 'The workspace requires a terminal. Run domino ui interactively; use '
                                                  'subcommands and --json in scripts.',
 '下载': 'Download',
 '{0}失败（退出码 {1}）。': '{0} failed (exit code {1}).',
 '{0}超时。': '{0} timed out.',
 '端口必须是整数。': 'Port must be an integer.',
 'SSH 端口必须是整数。': 'SSH port must be an integer.',
 '--user 与目标中的用户名不一致。': '--user does not match the target username.',
 '暂不支持目标架构 {0}；支持 ARM64 和 x86_64。': 'Unsupported architecture {0}; ARM64 and x86_64 are supported.',
 '读取 YAML 需要 PyYAML（python3 -m pip install PyYAML），或提供 JSON 配置。': 'Reading YAML requires PyYAML (python3 -m pip '
                                                                  'install PyYAML); alternatively provide JSON.',
 '读取 Clash 配置': 'Read Clash profile',
 'Clash YAML 配置解析失败；配置内容未输出。': 'Unable to parse the Clash YAML profile; its content was not printed.',
 'Clash Verge 配置索引有重复标识或文件，当前启用项无法可靠确认。': 'The Clash Verge index contains duplicate IDs or files; the active profile '
                                          'cannot be identified reliably.',
 '保存配置不对应独立运行入口，未检查出网；不包含客户端合并或脚本处理。': 'A saved profile has no independent running endpoint; outbound connectivity was '
                                       'not checked. Client merges and scripts are excluded.',
 '没有找到可独立部署的 Domino 或 Clash/Mihomo 配置。请用 --source 指定兼容配置，或用 --subscription 提供完整配置订阅；仅有本机代理端口或专用隧道客户端无法独立迁移。': 'No '
                                                                                                              'independently '
                                                                                                              'deployable '
                                                                                                              'Domino '
                                                                                                              'or '
                                                                                                              'Clash/Mihomo '
                                                                                                              'profile '
                                                                                                              'found. '
                                                                                                              'Specify '
                                                                                                              '--source '
                                                                                                              'or '
                                                                                                              '--subscription; '
                                                                                                              'a local '
                                                                                                              'proxy '
                                                                                                              'port or '
                                                                                                              'dedicated '
                                                                                                              'tunnel '
                                                                                                              'client '
                                                                                                              'alone '
                                                                                                              'is not '
                                                                                                              'portable.',
 '未能完成代理出网检查，请检查客户端状态和日志。': 'Proxy connectivity check could not complete; inspect client status and logs.',
 '配置库无法读取，请检查 Domino 配置目录；外部来源扫描不受影响。': 'Unable to read the Domino profile library; check its directory. External '
                                        'scanning is unaffected.',
 ' 为客户端索引关联）': ' indicates a client-index association)',
 '导入时间': 'Imported',
 '未检查（保存配置）': 'Not checked (saved profile)',
 '未检查': 'Not checked',
 '未关联运行入口': 'No running endpoint linked',
 '未配置': 'Not configured',
 '兼容': 'Compatible',
 '不可用': 'Unavailable',
 '配置文件': 'Profile file',
 '原始状态': 'Original status',
 '按客户端索引关联；出网结果属于运行入口，未核验内核加载内容与文件一致。': 'Linked through the client index; connectivity belongs to the running '
                                        'endpoint, without verifying that the core loaded this exact file.',
 '失败阶段': 'Failure stage',
 '排查建议': 'Suggested checks',
 '外部配置 {0} 个 · ': 'External profiles: {0} · ',
 '配置扫描': 'Profile scan',
 '外部配置': 'External profiles',
 '{0} 个配置': '{0} profiles',
 'Domino 管理': 'Managed by Domino',
 '部署来源': 'Deployment source',
 'Domino 配置': 'Domino profile',
 'Clash/Mihomo 配置': 'Clash/Mihomo profile',
 '仅有本机代理入口': 'Local proxy endpoint only',
 '未发现': 'Not found',
 '配置来源': 'Profile source',
 '\n  此处检查可迁移的配置和对应代理入口；运行及系统代理状态请用 domino status 查看。': '\n'
                                                        '  This checks portable profiles and their proxy endpoints; '
                                                        'use domino status for service and system proxy status.',
 '代理入口拒绝建立 HTTPS 隧道（HTTP {0}）。': 'The proxy refused the HTTPS tunnel (HTTP {0}).',
 '确认原客户端已启动，并检查代理端口和监听地址是否与配置一致。': 'Confirm the source client is running and its proxy port and listening address '
                                   'match the profile.',
 '无法启动出网检查所需的 curl。': 'Unable to start curl for the connectivity check.',
 '提示：导入保存配置，保留文件内默认节点；不读取客户端运行选择或执行合并/脚本。': 'Note: importing a saved profile preserves its default nodes; running '
                                            'selections, merges and scripts are not read.',
 '提示：未连接源 Clash 控制接口，将保留配置中的默认节点。': "Note: source Clash controller not connected; keeping the profile's default nodes.",
 '源 Clash 控制接口返回无效数据。': 'The source Clash controller returned invalid data.',
 '源节点依赖本机回环代理，无法独立迁移。请提供可由目标机直接连接的节点配置。': 'A source node depends on a loopback proxy and is not portable; provide '
                                          'nodes reachable directly from the target.',
 '下载官方 Mihomo {0} / {1}…': 'Downloading official Mihomo {0} / {1}…',
 '官方二进制 SHA-256 校验失败。': 'Official binary SHA-256 verification failed.',
 '本机配置校验': 'Local profile validation',
 '远端操作': 'Remote operation',
 '目标必须是使用 systemd 的 Linux 设备。': 'The target must be a systemd-based Linux device.',
 '目标需要 Python 3.9 或更高版本。': 'The target requires Python 3.9 or later.',
 '请使用普通 SSH 用户（需有 sudo 权限），不要直接以 root 部署。': 'Use a regular SSH user with sudo privileges; do not deploy directly as '
                                            'root.',
 'VS Code 设置包含 JSONC 注释或无效 JSON，未覆盖；请手动设置该主机代理。': 'VS Code settings contain JSONC comments or invalid JSON and were '
                                                  "not overwritten; configure this host's proxy manually.",
 '现有 VS Code 代理设置类型不支持自动合并。': 'Existing VS Code proxy settings cannot be merged automatically.',
 '系统代理': 'System proxy',
 '终端代理': 'Terminal proxy',
 '本地 VS Code 主机代理已更新。': 'Local VS Code host proxy updated.',
 '参数不符合命令定义，请通过 capabilities 查看参数。': 'Arguments do not match the command definition; see capabilities.',
 '子命令': 'Subcommands',
 'SSH 用户名；省略时使用 SSH 配置': 'SSH username; default to SSH configuration',
 'SSH 端口；省略时使用 SSH 配置，通常为 22': 'SSH port; default to SSH configuration, usually 22',
 'SSH 私钥路径，密码不会保存': 'SSH private key path; passwords are not saved',
 '节点名称或关键词；省略时交互选择': 'Node name or keyword; omit for interactive selection',
 '测试 HTTPS 请求延迟，结果单位为毫秒（ms），不测下载带宽。\n不带名称检测所有配置，汇总可用和超时/不可用节点数；填写完整配置名查看节点明细。\n完整名称优先；部分名称唯一时直接使用，匹配多个时列出候选。': 'Test '
                                                                                                               'HTTPS '
                                                                                                               'request '
                                                                                                               'latency '
                                                                                                               'in '
                                                                                                               'milliseconds, '
                                                                                                               'not '
                                                                                                               'download '
                                                                                                               'bandwidth.\n'
                                                                                                               'Omit '
                                                                                                               'the '
                                                                                                               'name '
                                                                                                               'to '
                                                                                                               'summarize '
                                                                                                               'all '
                                                                                                               'profiles; '
                                                                                                               'use an '
                                                                                                               'exact '
                                                                                                               'profile '
                                                                                                               'name '
                                                                                                               'for '
                                                                                                               'node '
                                                                                                               'details.\n'
                                                                                                               'Exact '
                                                                                                               'names '
                                                                                                               'take '
                                                                                                               'precedence; '
                                                                                                               'unique '
                                                                                                               'substrings '
                                                                                                               'select '
                                                                                                               'directly, '
                                                                                                               'otherwise '
                                                                                                               'candidates '
                                                                                                               'are '
                                                                                                               'shown.',
 '汇总所有配置的节点总数、可用数和超时/不可用数；填写配置名查看逐节点延迟。\n本机省略目标；远端使用 domino USER@IP test NAME。': 'Summarize total, available and '
                                                                                 'timed-out/unavailable nodes across '
                                                                                 'all profiles; provide a profile name '
                                                                                 'for per-node latency.\n'
                                                                                 'Omit the local target; remotely use '
                                                                                 'domino USER@IP test NAME.',
 '示例：\n  domino test                          汇总本机所有配置\n  domino test 自动选择                 测组内各项，可省略名称前的符号\n  domino test 美国TRI002                测唯一匹配的节点\n  domino test "[HY2]美国TRI002"          使用完整名称；方括号、空格需加引号\n  domino test 自动选择 --timeout 10000  单项最多等待 10 秒\n  domino user@192.0.2.10 test   汇总远端所有配置\n  domino user@192.0.2.10 test 自动选择  测远端指定组\n\n--url 和 --timeout 后必须填写值；使用默认值时省略整个选项。\nSSH 别名示例：domino my-server test；支持 --user、--ssh-port、--identity、--batch。\n未找到名称时，可运行 domino nodes 查看节点和策略组。': 'Examples:\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test                              '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Summarize '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'local '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'profiles\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Auto                         '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'a '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'matching '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'group\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'US-TRI002                     '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'a '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'uniquely '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'matching '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'node\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '"[HY2]US-TRI002"               '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Quote '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'brackets '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'or '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'spaces\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Auto '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--timeout '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '10000          '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Wait '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'up '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'to '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '10 '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'seconds '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'per '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'item\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'user@192.0.2.10 '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test               '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Summarize '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'remote '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'profiles\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '  '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'user@192.0.2.10 '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Auto          '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Test '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'a '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'remote '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'group\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--url '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'and '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--timeout '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'require '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'values; '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'omit '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'the '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'entire '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'option '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'to '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'use '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'its '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'default.\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'SSH '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'alias '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'example: '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'my-server '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'test; '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'supports '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--user, '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--ssh-port, '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--identity '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'and '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    '--batch.\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'Run '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'domino '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'nodes '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'to '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'see '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'node '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'and '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'policy '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'group '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    'names.',
 '常用示例：\n  domino test                         汇总本机所有配置\n  domino test feiniao                 测配置 feiniao 的全部节点\n  domino user@192.0.2.10 test      汇总远端所有配置\n  domino test --timeout 10000         超时设为 10 秒\n\n高级用法：domino test --help-all': 'Common '
                                                                                                                                                                                                                                                'examples:\n'
                                                                                                                                                                                                                                                '  '
                                                                                                                                                                                                                                                'domino '
                                                                                                                                                                                                                                                'test                              '
                                                                                                                                                                                                                                                'Summarize '
                                                                                                                                                                                                                                                'local '
                                                                                                                                                                                                                                                'profiles\n'
                                                                                                                                                                                                                                                '  '
                                                                                                                                                                                                                                                'domino '
                                                                                                                                                                                                                                                'test '
                                                                                                                                                                                                                                                'feiniao                       '
                                                                                                                                                                                                                                                'Test '
                                                                                                                                                                                                                                                'every '
                                                                                                                                                                                                                                                'node '
                                                                                                                                                                                                                                                'in '
                                                                                                                                                                                                                                                'feiniao\n'
                                                                                                                                                                                                                                                '  '
                                                                                                                                                                                                                                                'domino '
                                                                                                                                                                                                                                                'user@192.0.2.10 '
                                                                                                                                                                                                                                                'test               '
                                                                                                                                                                                                                                                'Summarize '
                                                                                                                                                                                                                                                'remote '
                                                                                                                                                                                                                                                'profiles\n'
                                                                                                                                                                                                                                                '  '
                                                                                                                                                                                                                                                'domino '
                                                                                                                                                                                                                                                'test '
                                                                                                                                                                                                                                                '--timeout '
                                                                                                                                                                                                                                                '10000               '
                                                                                                                                                                                                                                                'Use '
                                                                                                                                                                                                                                                'a '
                                                                                                                                                                                                                                                '10-second '
                                                                                                                                                                                                                                                'timeout\n'
                                                                                                                                                                                                                                                '\n'
                                                                                                                                                                                                                                                'Advanced '
                                                                                                                                                                                                                                                'usage: '
                                                                                                                                                                                                                                                'domino '
                                                                                                                                                                                                                                                'test '
                                                                                                                                                                                                                                                '--help-all',
 '兼容写法（通常无需使用）': 'Compatibility option (usually unnecessary)',
 '添加自定义规则': 'Add a custom rule',
 '删除自定义规则': 'Remove a custom rule',
 'macOS 网络服务名称，默认使用当前出站网络服务': 'macOS network service name; default to the active outbound network service',
 '本机缺少依赖：': 'Missing local dependencies: ',
 '离线包缺少必要文件，请使用 Domino export 重新生成。': 'Offline package is incomplete; regenerate it with Domino export.',
 ' 查看命令参数': ' for command options',
 '部署已取消': 'Deployment cancelled',
 '未修改目标设备。': 'Target device unchanged.',
 '输入编号或 all；回车取消。': 'Enter a number or all; Enter cancels.',
 '输入配置编号；回车取消。': 'Enter a profile number; Enter cancels.',
 'catch 不能捕获 Domino 或 robot-clash 自有配置。': "catch cannot capture Domino or robot-clash's own profiles.",
 '未发现兼容配置，请用 domino catch --source PATH 指定，或用 domino add 添加订阅。': 'No compatible profile found; use domino catch '
                                                                 '--source PATH or add a subscription with domino add.',
 '捕获配置到 Domino': 'Capture profiles into Domino',
 '{0} 个来源 · 重复项跳过': '{0} sources · duplicates skipped',
 '运行影响': 'Runtime effects',
 '保存到配置库，保留当前配置和节点选择；完成后自动启动 Domino 并接通系统代理。终端代理策略保持不变。': 'Save to the library while preserving the active profile and '
                                                          'node selections; start Domino and connect the system proxy '
                                                          'afterwards. Terminal proxy policy is unchanged.',
 'catch 用于捕获外部配置，不能将 Domino 或 robot-clash 自有配置作为来源。': 'catch imports external profiles; Domino and robot-clash '
                                                      'profiles cannot be sources.',
 '未发现可捕获的外部 Clash/Mihomo 配置。请用 domino catch --source PATH 指定兼容配置，或用 domino add 添加订阅；仅有本地代理端口无法独立复制。': 'No external '
                                                                                                      'Clash/Mihomo '
                                                                                                      'profile '
                                                                                                      'available for '
                                                                                                      'capture. '
                                                                                                      'Specify domino '
                                                                                                      'catch --source '
                                                                                                      'PATH or add a '
                                                                                                      'subscription; a '
                                                                                                      'local proxy '
                                                                                                      'port alone '
                                                                                                      'cannot be '
                                                                                                      'copied '
                                                                                                      'independently.',
 '选择配置': 'Select profile',
 '配置编号（回车取消）：': 'Profile number (Enter to cancel):',
 '来源配置或控制接口数据结构无效，未导入；请检查 Clash/Mihomo 配置。': 'Invalid source profile or controller data; nothing was imported. Check '
                                             'the Clash/Mihomo profile.',
 '捕获范围': 'Capture scope',
 '已读取 {0} 个手动选择': 'Read {0} manual selections',
 '使用配置默认节点（未读取到手动选择）': 'Use profile defaults (no manual selections read)',
 '旧版迁移': 'Legacy migration',
 '检测到 robot-clash；现有安装流程会迁移旧版服务和文件。': 'robot-clash detected; installation will migrate the legacy service and files.',
 '本机安装': 'Local installation',
 '非交互模式添加订阅或修改地址时需要 --url。': 'Non-interactive subscription creation or URL changes require --url.',
 '--lines 必须在 1–10000 之间。': '--lines must be between 1 and 10000.',
 '输入编号或名称；关键词可继续筛选；回车取消。': 'Enter a number or name; type to filter; Enter cancels.',
 '节点': 'Node',
 '策略组': 'Policy group',
 '无法读取可选节点列表，请先运行 domino nodes 检查。': 'Unable to read selectable nodes; run domino nodes first.',
 '选择匹配节点': 'Select matching node',
 '节点或下层策略组': 'Node or nested policy group',
 '本机管理': 'Local management',
 '--restart-vscode 需要 --vscode，且不能使用 --no-shell-env。': '--restart-vscode requires --vscode and cannot be used with '
                                                       '--no-shell-env.',
 '部署、安装或回滚需要在终端运行，以便安全输入认证密码。': 'Deployment, installation and rollback require a terminal for secure authentication '
                                'prompts.',
 '服务器返回错误': 'Server returned an error',
 '下载失败（HTTP {0}：{1}；curl 退出码 {2}）。': 'Download failed (HTTP {0}: {1}; curl exit code {2}).',
 '下载失败（退出码 {0}）。': 'Download failed (exit code {0}).',
 '目标必须是合法 IP、主机名或 SSH Host 别名。': 'Target must be a valid IP address, hostname or SSH Host alias.',
 'Clash Verge 配置索引无法读取或解析；其他来源不受影响。': 'Unable to read or parse the Clash Verge index; other sources are unaffected.',
 'Clash Verge · 运行配置': 'Clash Verge · runtime profile',
 '配置无法读取或解析。': 'Unable to read or parse the profile.',
 '源快照不可用': 'Source snapshot unavailable',
 '未记录（旧版运行配置）': 'Not recorded (legacy runtime profile)',
 ' · 默认导入来源': ' · default import source',
 'Domino 配置库无法读取': 'Unable to read the Domino profile library',
 'Domino 管理 {0} 个': 'Domino-managed: {0}',
 '配置': 'Profiles',
 '未发现外部配置。': 'No external profiles found.',
 '配置库无法读取': 'Profile library unreadable',
 '扫描提示': 'Scan notes',
 '● 找到兼容节点配置': '● Compatible node profile found',
 '○ 未找到可独立部署的节点配置': '○ No independently deployable node profile found',
 '未检查（导入源快照）': 'Not checked (source snapshot)',
 '无法连接配置中的代理端口，请求尚未进入代理。': 'Unable to connect to the configured proxy port; the request has not reached the proxy.',
 '检查相关 DNS 设置和域名解析；当前错误不能直接说明节点是否可用。': 'Check DNS settings and resolution; this error alone does not establish node '
                                       'availability.',
 '出网检查返回的诊断信息无效。': 'Connectivity check returned invalid diagnostic data.',
 '存在无法迁移的 provider 类型；未部署任何内容。': 'Unsupported provider type; nothing was deployed.',
 '当前订阅关联记录无效，未重新安装。': 'Invalid active subscription association; nothing was reinstalled.',
 'SSH 认证': 'SSH authentication',
 '远端命令过长，请缩短参数；机器请求请用 --input 通过标准输入传入。': 'Remote command too long; shorten arguments or use --input to send machine '
                                          'requests through stdin.',
 '无法解析目标信息；请检查目标 Python 3 或 shell 启动脚本输出。': 'Unable to parse target information; check Python 3 and shell startup '
                                            'output on the target.',
 '目标缺少依赖：': 'Missing target dependencies: ',
 '已接通': 'Connected',
 '无 GNOME 桌面会话': 'No GNOME desktop session',
 '已开启': 'Enabled',
 '提示：远端临时目录未清理，请稍后检查。': 'Note: the remote temporary directory was not removed; check it later.',
 '禁止 SSH 和 sudo 密码询问': 'Disable SSH and sudo password prompts',
 '启动 Domino 服务，等待内核就绪后开启 HTTP、HTTPS、SOCKS 系统代理，并指向 Domino 代理地址（默认 127.0.0.1:{0}，自定义时使用实际端口）。': 'Start Domino, wait for '
                                                                                               'the core, then enable '
                                                                                               'HTTP, HTTPS and SOCKS '
                                                                                               'system proxies '
                                                                                               'pointing to Domino '
                                                                                               '(default '
                                                                                               '127.0.0.1:{0}, or the '
                                                                                               'configured port).',
 '先恢复仍由 Domino 接管的系统代理设置，再停止服务；保留其他程序之后的修改。': 'Restore system proxies still managed by Domino, then stop its service; '
                                              'preserve changes made by other programs.',
 '重启 Domino 服务，并重新开启系统代理，指向 Domino 代理地址（默认 127.0.0.1:{0}，自定义时使用实际端口）。': 'Restart Domino and reconnect system proxies '
                                                                        'to its endpoint (default 127.0.0.1:{0}, or '
                                                                        'the configured port).',
 ' 系统代理支持 macOS 和 Ubuntu GNOME 桌面；无桌面服务器提供代理入口，终端代理通过 domino shell 独立管理。': ' System proxies support macOS and Ubuntu '
                                                                           'GNOME; headless servers expose a proxy '
                                                                           'endpoint, with terminal policy managed '
                                                                           'separately through domino shell.',
 '配置名称': 'Profile name',
 '新的配置名称': 'New profile name',
 '完整配置 HTTPS 订阅地址；省略时隐藏输入': 'Full-profile HTTPS subscription URL; use hidden input when omitted',
 '离线包包含不安全的路径或文件类型，未安装。': 'Offline package contains unsafe paths or file types; installation cancelled.',
 '无法读取节点信息。': 'Unable to read node information.',
 '将代理部署到指定电脑（等同 domino USER@IP deploy）': 'Deploy proxy access to another computer (same as domino USER@IP deploy)',
 '打开交互控制台': 'Open interactive workspace',
 '查看当前配置的节点和策略组': 'Show active-profile nodes and policy groups',
 '选择节点；可输入名称或关键词': 'Select a node by name or keyword',
 '检测全部配置；指定配置查看各节点结果': 'Test all profiles; specify a profile for per-node results',
 '开启 Domino，接通系统代理（默认端口 {0}）': 'Start Domino and connect system proxies (default port {0})',
 '关闭 Domino，恢复系统代理设置': 'Stop Domino and restore system proxy settings',
 '查看服务、系统代理和出网状态': 'Show service, system proxy and connectivity',
 '卸载运行环境，清理配置和终端接入': 'Uninstall runtime, profiles and terminal integration',
 '终端使用 Domino 代理': 'Use Domino in the terminal',
 '恢复终端原代理设置': 'Restore previous terminal proxy settings',
 '查看内嵌动态流量面板': 'Show inline live traffic dashboard',
 '  选择配置    编号（回车取消）：': '  Select profile    Number (Enter to cancel):',
 '（当前保存项）': '(current saved item)',
 '（已保存）': '(saved)',
 '保存配置': 'Saved profile',
 '使用文件内默认节点': "Use the file's default nodes",
 '全部配置': 'All profiles',
 '配置已保存，但自动开启 Domino 失败：': 'Profile saved, but Domino could not start automatically: ',
 '发现多个配置，请使用 --source 或 catch all 明确选择；--yes 不会自动选择来源。': 'Multiple profiles found; select with --source or catch all. '
                                                         '--yes does not select a source.',
 '编号 / all（回车取消）：': 'Number / all (Enter to cancel):',
 'v2rayN 仅导入节点快照，不迁移其分流、DNS 或客户端设置。': 'v2rayN imports node snapshots only, excluding routing, DNS and client settings.',
 '已捕获': 'Captured',
 '已跳过': 'Skipped',
 '发现多个外部配置，请使用 --source 明确选择；--yes 不会自动选择来源。': 'Multiple external profiles found; choose with --source. --yes does not '
                                               'select a source.',
 '来源编号无效，未导入。': 'Invalid source number; nothing was imported.',
 '日志级别只能指定一次；使用 domino log debug 等命令。': 'Specify the log level once, for example domino log debug.',
 '当前选择': 'Current selection',
 '节点选择已取消': 'Node selection cancelled',
 '未修改节点选择。': 'Node selections unchanged.',
 '该节点属于多个手动策略组，请用 --group 指定：': 'This node belongs to multiple manual groups; specify --group: ',
 '捕获配置需要前台交互确认。': 'Capture requires foreground interactive confirmation.',
 '{0} 操作失败（退出码 {1}）。': '{0} failed (exit code {1}).',
 '内核版本必须是 latest 或 vX.Y.Z。': 'Core version must be latest or vX.Y.Z.',
 '出网检查地址必须是无嵌入凭据的 HTTPS URL。': 'Connectivity test URL must use HTTPS without embedded credentials.',
 '非交互捕获请同时使用 --yes --batch；--batch 仅禁止密码询问。': 'Non-interactive capture requires --yes --batch; --batch only disables '
                                              'password prompts.',
 'localhost 直接管理当前用户的本机，不能附加 SSH 参数；需切换用户时请使用 USER@localhost 通过 SSH 管理。': 'localhost manages the current local user '
                                                                          'without SSH options; use USER@localhost '
                                                                          'over SSH to manage another user.',
 '失败：': 'Error: ',
 '\n已取消。': '\nCancelled.',
 '类型': 'Type',
 '缓存': 'Cache',
 '更新时间': 'Updated',
 '配置库': 'Profile library',
 '尚未登记配置；可用 domino catch 捕获或 domino add 添加。': 'No profiles registered; use domino catch or domino add.',
 '代理地址解析失败。': 'Unable to resolve the proxy address.',
 '目标网站地址解析失败。': 'Unable to resolve the destination address.',
 '请确认系统已安装可用的 curl。': 'Ensure curl is installed and available.',
 'provider 配置资源': 'Provider resources',
 'provider 缓存文件缺失；请检查引用路径或使用 --resource-dir 指定资源目录。': 'Provider cache file missing; check its path or supply a '
                                                      'resource directory with --resource-dir.',
 '设备代理已部署成功，但本地 VS Code 设置未完成；无需重新安装设备服务。': 'Device proxy deployment succeeded, but local VS Code settings were not '
                                            'completed; do not reinstall the device service.',
 '目标地址无效；远端格式为 domino USER@IP COMMAND。': 'Invalid target; remote syntax is domino USER@IP COMMAND.',
 '未知{0}动作：{1}。可用动作：status、on、off；关闭请用 domino {2} off；查询远程主机请用 domino HOST {3} status。': 'Unknown {0} action: {1}. '
                                                                                        'Available: status, on, off; '
                                                                                        'disable with domino {2} off, '
                                                                                        'or query a remote host with '
                                                                                        'domino HOST {3} status.',
 '；all 表示全部在线订阅': '; all selects every online subscription',
 '查看完整帮助；': 'Show complete help; ',
 '捕获失败': 'Capture failed',
 '来源配置数据结构无效，未导入。': 'Invalid source profile structure; nothing was imported.',
 '确认导入': 'Confirm import',
 '节点只能指定一次；用 domino [USER@IP] select "节点名"，或 --group 与 --node。': 'Specify the node once: domino [USER@IP] select '
                                                                 '"node", or use --group and --node.',
 '测速对象只能指定一次；远端格式为 domino USER@IP test NAME。': 'Specify one latency test target; remote syntax: domino USER@IP test '
                                               'NAME.',
 '策略组 ': 'Policy group ',
 '{0} 个候选节点': '{0} candidate nodes',
 '{0} 个手动策略组': '{0} manual policy groups',
 '未选择': 'Not selected',
 '编号': 'No.',
 '节点 / 策略': 'Node / policy',
 '状态': 'Status',
 '选择': 'Select',
 '--full 需要前台交互终端。': '--full requires a foreground interactive terminal.',
 '离线安装包已导出：': 'Offline package exported: ',
 '订阅凭据无效或缺失': 'Subscription credentials are missing or invalid',
 '服务器拒绝访问': 'Access denied by server',
 '订阅地址不存在': 'Subscription URL not found',
 '请求过于频繁': 'Too many requests',
 '请重试或查看客户端日志，当前结果不能直接认定为端口不可达或节点超时。': 'Retry or check client logs; this result alone does not establish an '
                                       'unreachable port or node timeout.',
 '检查系统时间、证书信任链及是否存在 HTTPS 拦截；不要仅据此认定节点离线。': 'Check system time, trusted certificates and HTTPS interception; do not '
                                            'infer node availability from this error alone.',
 '请检查 curl 版本或重试出网检查。': 'Check the curl version or retry the connectivity test.',
 '已关闭；开启：': 'Disabled; enable with: ',
 '部署已执行，但无法核实最终结果；请运行 domino ': 'Deployment ran, but its final result could not be verified; run domino ',
 '目标只能指定一次。': 'Specify the target only once.',
 '目标只能放在命令前：domino USER@IP COMMAND。': 'Place the target before the command: domino USER@IP COMMAND.',
 ' · 当前配置': ' · current profile',
 '配置编号无效，未捕获。': 'Invalid profile number; nothing was captured.',
 '确认捕获': 'Confirm capture',
 '；请检查配置、依赖资源或内核校验。': '; check the profile, resources and core validation.',
 '可选策略组': 'Available policy groups',
 '在线订阅': 'Subscription',
 '配置快照': 'Snapshot',
 '已缓存': 'Cached',
 '未缓存': 'Not cached',
 '尚未更新': 'Not updated yet',
 '出网请求超时；未能获取足够信息判断失败发生在哪个连接阶段（请求时限 {0} 秒）。': 'Outbound request timed out without enough information to identify the '
                                              'connection stage (limit {0} seconds).',
 '检查客户端是否运行、监听地址是否正确，以及本机防火墙设置。': 'Check whether the client is running, its listening address, and the local firewall.',
 'TLS 证书校验失败。': 'TLS certificate verification failed.',
 '节点连接失败或超时也可能表现为此错误；请结合客户端日志判断，不能直接归因为证书问题。': 'Node connection failures and timeouts can produce this error; inspect '
                                               'client logs before attributing it to certificates.',
 '系统代理动作与 --set 不一致，请使用 domino proxy on 或 domino proxy off。': 'System proxy action conflicts with --set; use domino '
                                                              'proxy on or domino proxy off.',
 '在 {0} 秒内未能连接代理入口。': 'Unable to connect to the proxy within {0} seconds.',
 '可能是上游节点连接或转发超时，需结合客户端日志确认具体原因。': 'The upstream node connection or forwarding may have timed out; inspect client '
                                   'logs.',
 'HTTPS / TLS 握手失败或连接被中断（curl 35）。': 'HTTPS / TLS handshake failed or the connection was interrupted (curl 35).',
 '已收到 HTTP 错误响应；检查测试网站是否拒绝请求或服务异常。': 'An HTTP error response was received; check the test site or its access policy.',
 '● 当前': '● Current',
 '正在检测': 'Testing',
 '加载配置': 'Loading profile',
 '代理端口已连接，但在 {0} 秒内未完成 HTTPS 隧道建立。': 'Connected to the proxy, but HTTPS tunnel setup did not complete within {0} '
                                     'seconds.',
 '隧道被接受不代表节点已连通；请检查当前节点、上游链路和客户端日志。': 'An accepted tunnel does not prove upstream connectivity; check the node, '
                                      'upstream connection and client logs.',
 '检查目标网站响应及上游链路，当前结果不属于本机端口不可达。': 'Check destination response time and the upstream connection; the local port was '
                                  'reachable.',
 '代理端口已连接，但 ': 'Connected to the proxy, but ',
 '目标网站返回 HTTP {0}。': 'Destination returned HTTP {0}.',
 '请求过程中连接被关闭、重置或未返回有效响应（curl {0}）。': 'Connection closed or reset, or no valid response received (curl {0}).',
 '可能涉及节点、上游链路或目标网站；需要客户端日志进一步定位。': 'The node, upstream connection or destination may be involved; inspect client logs.',
 '用法：domino [USER@IP] rules，或 domino [USER@IP] rules add/remove "完整规则"。': 'Usage: domino [USER@IP] rules, or domino '
                                                                          '[USER@IP] rules add/remove "complete-rule".',
 '独立 systemd 代理服务': 'Independent systemd proxy service',
 '当前节点和规则配置': 'Current nodes and routing rules',
 '代理已接受 HTTPS 隧道，但 TLS 握手在 {0} 秒内未完成。': 'Proxy accepted the HTTPS tunnel, but TLS handshake did not complete within '
                                        '{0} seconds.',
 'TLS 握手已完成，但 HTTPS 响应在 {0} 秒内未完成。': 'TLS handshake completed, but no HTTPS response arrived within {0} seconds.',
 ' "完整规则"；查询请单独使用 --match 或 --custom。': ' "complete-rule"; use --match or --custom separately for queries.',
 '当前用户代理环境': "Current user's proxy environment",
 '用法：domino [USER@IP] rules ': 'Usage: domino [USER@IP] rules ',
 'import json,re,shlex,subprocess,sys\nsetup=json.loads(sys.argv[1]);source="".join(sys.argv[2:]).encode()\nuploaded=subprocess.run(setup[\'upload\'],input=source,capture_output=True)\nif uploaded.returncode:\n sys.stderr.buffer.write(uploaded.stderr);raise SystemExit(uploaded.returncode)\npaths=[line[len(\'DOMINO_SOURCE=\'):] for line in uploaded.stdout.decode().splitlines() if line.startswith(\'DOMINO_SOURCE=\')]\npath=paths[0] if len(paths)==1 else \'\'\nif not re.fullmatch(r\'/tmp/domino-command-[A-Za-z0-9_-]+\\.py\',path):\n raise SystemExit(\'无法确认远端临时程序路径。\')\ntry:\n command=\'python3 \'+shlex.quote(path)+\' \'+shlex.join(setup[\'arguments\'])\n result=subprocess.run([*setup[\'prefix\'],command])\nfinally:\n try: subprocess.run([*setup[\'cleanup\'],\'rm -f -- \'+shlex.quote(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)\n except subprocess.TimeoutExpired: pass\nraise SystemExit(result.returncode)\n': 'import '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'json,re,shlex,subprocess,sys\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'setup=json.loads(sys.argv[1]);source="".join(sys.argv[2:]).encode()\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "uploaded=subprocess.run(setup['upload'],input=source,capture_output=True)\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'if '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'uploaded.returncode:\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'sys.stderr.buffer.write(uploaded.stderr);raise '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'SystemExit(uploaded.returncode)\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "paths=[line[len('DOMINO_SOURCE='):] "
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'for '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'line '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'in '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'uploaded.stdout.decode().splitlines() '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'if '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "line.startswith('DOMINO_SOURCE=')]\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'path=paths[0] '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'if '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'len(paths)==1 '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'else '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "''\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'if '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'not '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "re.fullmatch(r'/tmp/domino-command-[A-Za-z0-9_-]+\\.py',path):\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'raise '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "SystemExit('Unable "
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'to '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'verify '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'the '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'remote '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'temporary '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'program '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "path.')\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'try:\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "command='python3 "
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "'+shlex.quote(path)+' "
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "'+shlex.join(setup['arguments'])\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "result=subprocess.run([*setup['prefix'],command])\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'finally:\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'try: '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "subprocess.run([*setup['cleanup'],'rm "
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                '-f '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                '-- '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                "'+shlex.quote(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)\n"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                ' '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'except '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'subprocess.TimeoutExpired: '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'pass\n'
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'raise '
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                'SystemExit(result.returncode)\n',
 '缺少 Domino 许可证，无法生成 CLI 同步包。': 'Domino license missing; unable to generate the CLI synchronization package.',
 '  接通      系统代理…': '  Connecting    System proxy…',
 'Domino CLI 版本格式无效。': 'Invalid Domino CLI version.',
 '无法确认 Domino CLI 源码版本。': 'Unable to identify the Domino CLI source version.',
 '目标 CLI 应用资源清单无效。': 'Invalid target CLI application resource list.',
 '目标 CLI 源码清单或文件类型无效。': 'Invalid target CLI source list or file type.',
 '目标 CLI 应用资源不能是符号链接。': 'Target CLI application resources must not be symlinks.',
 'CLI 同步包源码清单无效。': 'Invalid CLI synchronization package source list.',
 'CLI 同步包版本与源码不一致。': 'CLI package version does not match its source.',
 '目标 domino 入口不属于可识别的 Domino，未修改。': 'The target domino entry point is not a recognized Domino installation; left '
                                    'unchanged.',
 '目标 CLI 由系统包或未知环境管理；请先通过原包管理器升级，未覆盖入口。': 'The target CLI belongs to a system package or unknown environment; upgrade '
                                          'through its package manager. The entry point was not overwritten.',
 '目标 CLI 模块位于原虚拟环境之外，未修改。': 'Target CLI modules are outside its virtual environment; left unchanged.',
 '上传的 CLI 版本与发起端不一致，未部署。': 'Uploaded CLI version differs from the sender; deployment cancelled.',
 '目标新版 CLI 准备失败，未部署。': 'Unable to prepare the newer target CLI; deployment cancelled.',
 '  安装      服务与出网检查…': '  Installing    Service and connectivity check…',
 '  同步      CLI 版本检查…': '  Synchronizing    CLI version check…',
 '未知版本': 'Unknown version',
 '运行环境已部署，但目标命令仍为 {0}，预期 {1}。': 'Runtime deployed, but the target command still reports {0}; expected {1}.',
 '目标 CLI 已核验：{0}（{1}）': 'Target CLI verified: {0} ({1})',
 '失败（退出码 {0}）。': ' failed (exit code {0}).',
 '读取目标 CLI': 'Read target CLI',
 '系统代理读回状态未确认接通。': 'System proxy readback did not confirm a connected state.',
 '无法读取系统代理状态。': 'Unable to read system proxy status.',
 '目标 domino 入口无效，未修改。': 'Invalid target domino entry point; left unchanged.',
 '目标机已有较新 CLI {0}，保留新版兼容本次部署。': 'Target already has newer CLI {0}; keeping it for this deployment.',
 '检查目标虚拟环境 pip': 'Check pip in the target virtual environment',
 '目标运行环境部署': 'Deploy target runtime',
 '同步目标 CLI：{0} → {1}（原虚拟环境，离线更新）': 'Synchronize target CLI: {0} → {1} (offline update in its existing virtual '
                                   'environment)',
 '目标 CLI 更新': 'Target CLI update',
 '同步已取消，请检查目标运行环境与 CLI 版本。': 'Synchronization cancelled; inspect the target runtime and CLI version.',
 '失败或超时。': ' failed or timed out.',
 '接通目标系统代理': 'Connect target system proxy',
 '服务已部署，但系统代理未接通：': 'Service deployed, but system proxy not connected: ',
 '已有另一个 CLI 同步操作，请稍后重试。': 'Another CLI synchronization is running; retry later.',
 '准备新版目标 CLI': 'Prepare newer target CLI',
 '目标 CLI 版本核验': 'Verify target CLI version',
 '失败：部署或 CLI 同步未完成：': 'Error: deployment or CLI synchronization incomplete: ',
 'v2rayN 配置无法读取或格式不受支持；未输出配置内容。': 'Unable to read the v2rayN configuration or unsupported format; its content was not '
                                  'printed.',
 '节点快照': 'Node snapshot',
 '转换全部支持的节点为 Mihomo 快照；不迁移 v2rayN 分流、DNS、链式代理或客户端设置，不检查保存端口。': 'Convert supported nodes to a Mihomo snapshot; exclude '
                                                               'v2rayN routing, DNS, chained proxies and client '
                                                               'settings. Saved ports are not tested.',
 'v2rayN 含自定义配置、链式代理或暂不支持的协议；请导出完整 Clash/Mihomo 配置后导入。': 'v2rayN contains custom profiles, chained proxies or '
                                                         'unsupported protocols; export a complete Clash/Mihomo '
                                                         'profile first.',
 'v2rayN 含暂不支持的证书、加密或前置代理设置；未生成不完整配置。': 'v2rayN contains unsupported certificate, encryption or upstream proxy '
                                        'settings; no incomplete profile was generated.',
 'v2rayN 含暂不支持的协议扩展；未生成不完整配置。': 'v2rayN contains unsupported protocol extensions; no incomplete profile was generated.',
 'v2rayN TLS 设置暂不支持转换。': 'v2rayN TLS settings cannot currently be converted.',
 'v2rayN 此协议的 TLS 设置暂不支持转换。': 'TLS settings for this v2rayN protocol cannot currently be converted.',
 'v2rayN 传输暂仅支持 TCP、WebSocket 和 gRPC；未生成不完整配置。': 'v2rayN conversion supports TCP, WebSocket and gRPC only; no '
                                                 'incomplete profile was generated.',
 'ClashX 保存配置；未核验客户端当前加载项，不检查保存端口。': "Saved ClashX profile; the client's active profile was not verified and saved "
                                     'ports were not tested.',
 'v2rayN 数据库正在变化，请稍后重试。': 'The v2rayN database is changing; retry later.',
 'v2rayN Reality 配置不完整或协议暂不支持。': 'Incomplete v2rayN Reality settings or unsupported protocol.',
 'v2rayN 此协议的传输方式暂不支持转换。': 'This v2rayN protocol transport cannot currently be converted.',
 'v2rayN TCP 伪装暂不支持转换。': 'v2rayN TCP camouflage cannot currently be converted.',
 'v2rayN 未保存节点、节点超过 5000 个或配置格式不受支持。': 'v2rayN has no saved nodes, exceeds 5000 nodes or uses an unsupported format.',
 'v2rayN 的 VLESS encryption 暂不支持转换。': 'v2rayN VLESS encryption cannot currently be converted.',
 'v2rayN WebSocket early-data 暂不支持转换。': 'v2rayN WebSocket early-data cannot currently be converted.',
 'v2rayN gRPC 扩展暂不支持转换。': 'v2rayN gRPC extensions cannot currently be converted.',
 '输出 Tab 补全脚本；source 后在当前 shell 生效。': 'Print Tab completion scripts; source them to enable completion in this shell.',
 '代理探测沿用当前分流规则；成功不代表命中 DIRECT，CONNECT 200 不计为 HTTPS 成功。': 'The proxy probe follows current routing rules; success does '
                                                          'not prove DIRECT routing. CONNECT 200 alone is not HTTPS '
                                                          'success.',
 '诊断地址必须是无凭据、查询参数和 fragment 的 HTTPS URL。': 'Diagnostic URL must use HTTPS without credentials, query parameters or a '
                                           'fragment.',
 '代理端口无效。': 'Invalid proxy port.',
 '核心缺少 LC_UUID，且未确认使用具有 UUID 的原生应用启动器；请检查负责程序的身份和本地网络授权。仅补核心 UUID 不足以保证修复。': 'The core has no LC_UUID and a '
                                                                             'UUID-bearing native launcher has not '
                                                                             'been confirmed. Check responsible '
                                                                             'application identity and Local Network '
                                                                             'permission; adding a core UUID alone '
                                                                             'does not ensure a fix.',
 '系统直连成功、代理请求失败；请结合 domino logs 确认是否命中 DIRECT，再比较 Terminal 与 LaunchAgent。': 'Native connectivity succeeded while proxy '
                                                                            'connectivity failed. Confirm DIRECT '
                                                                            'routing in domino logs, then compare '
                                                                            'Terminal and LaunchAgent execution.',
 '桌面代理恢复记录不能为符号链接。': 'Desktop proxy recovery records must not be symlinks.',
 '桌面代理恢复未完成，已保留恢复记录。': 'Desktop proxy recovery incomplete; recovery record retained.',
 'GNOME 系统代理按当前用户管理，不使用 --service 网络服务名称。': 'GNOME system proxies are managed per user; --service network service '
                                            'names do not apply.',
 '仍有桌面代理指向 Domino；请修改该设置后重试 domino stop，服务未停止。': 'A desktop proxy still points to Domino. Change it before retrying '
                                                 'domino stop; the service was not stopped.',
 'GNOME 用户桌面': 'GNOME user desktop',
 '没有可用的 GNOME 桌面会话。': 'No usable GNOME desktop session.',
 '桌面缺少 GNOME 系统代理设置。': 'GNOME system proxy settings are unavailable.',
 '桌面代理设置读取或写入失败。': 'Unable to read or write desktop proxy settings.',
 '桌面代理设置读回不一致。': 'Desktop proxy readback mismatch.',
 '桌面代理恢复记录无效，未修改设置。': 'Invalid desktop proxy recovery record; settings unchanged.',
 '桌面代理恢复未完成，恢复记录已保留；请重试 domino stop。': 'Desktop proxy recovery incomplete; record retained. Retry domino stop.',
 '桌面代理有待完成的恢复，请先运行 domino stop。': 'Desktop proxy recovery is pending; run domino stop first.',
 'Domino 代理端口无效。': 'Invalid Domino proxy port.',
 '请先用 domino add / domino switch 配好订阅，再运行 domino start。': 'Configure a subscription with domino add / domino switch '
                                                          'before running domino start.',
 'Domino 服务尚未运行，请执行 domino start。': 'Domino is not running; run domino start.',
 '当前桌面使用 PAC 或认证代理，请先处理后再开启 Domino。': 'The desktop uses PAC or authenticated proxies; resolve these settings before '
                                      'enabling Domino.',
 '桌面': 'Desktop',
 '无法访问当前用户的桌面代理设置。': "Unable to access the current user's desktop proxy settings.",
 '桌面代理设置不允许当前用户修改。': 'The current user cannot modify desktop proxy settings.',
 '桌面会话不可用，无法恢复系统代理；服务未停止。': 'Desktop session unavailable; system proxy could not be restored and the service was not '
                            'stopped.',
 '桌面代理读回不一致。': 'Desktop proxy readback mismatch.',
 '桌面代理未应用，已恢复本次操作前的设置。': 'Desktop proxy changes were not applied; previous settings restored.',
 '● 已指向 Domino': '● Connected to Domino',
 '● 未接通桌面系统代理': '● Desktop system proxy not connected',
 '未开启': 'Disabled',
 '服务已启动，但控制接口未就绪，系统代理未接通。': 'Service started, but the controller is not ready and system proxies are not connected.',
 '桌面代理设置失败且恢复未完成，恢复记录已保留。': 'Desktop proxy setup and recovery failed; recovery record retained.',
 '无法读取服务日志，请检查当前用户的日志权限。': "Unable to read service logs; check the current user's log permissions.",
 '● 使用 PAC / 自动代理配置': '● Using PAC / automatic proxy configuration',
 '网络服务': 'Network service',
 '恢复记录': 'Recovery record',
 '已解除 Domino 系统代理；已关闭或由其他程序管理的设置保持不变': 'Domino system proxy released; disabled settings and settings managed by other '
                                       'programs are preserved',
 'launchctl 操作失败；请确认当前用户已登录 macOS 图形会话。': 'launchctl failed; confirm the current user is logged into a macOS GUI '
                                          'session.',
 'Domino 安装路径不能是符号链接。': 'Domino installation paths must not be symlinks.',
 '不是 macOS Domino 备份，未恢复。': 'This is not a macOS Domino backup; restore cancelled.',
 '日志行数必须在 1–10000 之间。': 'Log line count must be between 1 and 10000.',
 '尚未安装本机 Domino 运行环境，请先运行安装程序。': 'Local Domino runtime is not installed; run the installer first.',
 '已恢复：': 'Restored: ',
 '无法读取或修改系统代理；请检查网络服务名称和管理员权限。': 'Unable to read or modify system proxies; check the network service name and '
                                 'administrator privileges.',
 '无法确定当前网络服务，请用 --service 指定；可用：': 'Unable to identify the active network service; specify --service. Available: ',
 '● 未指向 Domino': '● Not connected to Domino',
 '可用 domino proxy off 恢复仍由 Domino 管理的项目': 'Use domino proxy off to restore settings still managed by Domino',
 '操作': 'Action',
 '另一网络服务已有代理备份，请先使用 domino proxy off 恢复。': 'Another network service has a proxy backup; restore it with domino proxy '
                                           'off first.',
 '已开启 Domino 系统代理': 'Domino system proxy enabled',
 '同名 LaunchAgent 不属于 Domino，未覆盖。': 'A same-named LaunchAgent is not owned by Domino; it was not overwritten.',
 'Domino LaunchAgent 未能停止。': 'Unable to stop the Domino LaunchAgent.',
 '等待 Domino LaunchAgent 退出超时；请检查服务状态后重试。': 'Timed out waiting for the Domino LaunchAgent to exit; inspect its status '
                                           'before retrying.',
 '受管理的文件不能是符号链接。': 'Managed files must not be symlinks.',
 '恢复未完成；备份：': 'Recovery incomplete; backup: ',
 '暂无日志。': 'No logs available.',
 '运行状态': 'Runtime status',
 '● 已关闭': '● Stopped',
 '服务': 'Service',
 '已停止': 'Stopped',
 '已解除 Domino 接管（恢复原设置，保留其他程序的修改）': "Domino proxy settings released (previous settings restored; other programs' "
                                   'changes preserved)',
 '  开启 Domino：domino start': '  Start Domino: domino start',
 '运行中': 'Running',
 '已开启（HTTP / HTTPS / SOCKS）': 'Enabled (HTTP / HTTPS / SOCKS)',
 '代理目标': 'Proxy endpoint',
 '回滚未完成，已恢复操作前状态。': 'Rollback incomplete; the pre-operation state was restored.',
 '历史记录已失效，现有设置保持不变': 'Recovery record expired; existing settings preserved',
 '无': 'None',
 '请先启动 Domino，再开启系统代理。': 'Start Domino before enabling the system proxy.',
 '当前网络使用需要认证的系统代理，无法完整备份其密码；请先手动处理该代理。': 'This network uses an authenticated system proxy whose password cannot be '
                                         'fully backed up; resolve it manually first.',
 '当前网络启用了 PAC/自动发现，请先手动关闭或选择其他网络服务。': 'PAC/auto-discovery is enabled; disable it manually or select another network '
                                      'service first.',
 '系统代理有未完成的恢复，请先使用 domino proxy off 处理。': 'System proxy recovery is pending; run domino proxy off first.',
 '仍有生效代理指向 Domino，恢复记录已保留。': 'An active proxy still points to Domino; recovery record retained.',
 '● 已重启 · 系统代理已接通': '● Restarted · system proxy connected',
 '● 已开启 · 系统代理已接通': '● Started · system proxy connected',
 '系统代理修改需要预先授权 sudo；机器接口不会询问密码。': 'System proxy changes require pre-authorized sudo; the machine interface will not '
                                  'prompt for a password.',
 '网络服务不存在；可用：': 'Network service not found; available: ',
 '系统代理恢复读回不一致，恢复记录已保留。': 'System proxy recovery readback mismatch; recovery record retained.',
 '  ·  需要认证': '  ·  Authentication required',
 '系统代理设置读回不一致，正在恢复原设置。': 'System proxy readback mismatch; restoring previous settings.',
 '系统代理未应用，已恢复本次操作前设置。': 'System proxy changes were not applied; previous settings restored.',
 '服务已启动，但系统代理未接通；请运行 domino status 检查。': 'Service started, but system proxies are not connected; run domino status.',
 '服务已启动，但系统代理未接通：': 'Service started, but system proxies are not connected: ',
 '回滚和自动恢复未完成；当前状态备份：': 'Rollback and automatic recovery incomplete; current state backup: ',
 '系统代理回滚读回不一致。': 'System proxy rollback readback mismatch.',
 '系统代理修改失败且恢复未完成，恢复记录已保留。': 'System proxy setup and recovery failed; recovery record retained.',
 '控制接口未就绪，请用 domino logs 查看日志。': 'Controller not ready; inspect domino logs.',
 'Domino 应用身份不匹配，未修改注册。': 'Domino application identity mismatch; registration unchanged.',
 '无法注册 Domino 本地网络应用身份。': 'Unable to register the Domino Local Network application identity.',
 '已为 Domino 注册原生启动器；内核、配置和系统代理设置保持原样。': 'Domino native launcher registered; core, profile and system proxy settings '
                                        'preserved.',
 '请允许 Domino 的本地网络访问，然后使用 domino doctor 验证实际内网连接。': "Allow Domino's Local Network access, then use domino doctor to "
                                                    'check actual LAN connectivity.',
 'Domino 已独立运行；代理端口 {0}，控制端口 {1}；登录当前用户时自动启动。': 'Domino is running independently; proxy port {0}, controller port {1}; '
                                                'starts when this user logs in.',
 '首次访问局域网时，请允许 Domino 的本地网络访问；也可在系统设置 → 隐私与安全性 → 本地网络中开启。': "Allow Domino's Local Network access on first LAN use, or "
                                                            'enable it in System Settings → Privacy & Security → Local '
                                                            'Network.',
 '尚未安装当前用户的 Domino 运行环境。': "The current user's Domino runtime is not installed.",
 'LaunchAgent 启动参数与当前 Domino 不一致，未修改。': 'LaunchAgent arguments do not match this Domino installation; left unchanged.',
 '迁移前备份：': 'Pre-migration backup: ',
 '安装包与本机 macOS 架构不一致。': 'Package does not match the local macOS architecture.',
 '安装包格式不受支持。': 'Unsupported package format.',
 '代理端口和控制端口无效。': 'Invalid proxy or controller port.',
 '安装包的监听或 TUN 设置不符合预期。': 'Unexpected listening or TUN settings in the package.',
 '~/.local/bin/domino 已被其他程序使用。': '~/.local/bin/domino is used by another program.',
 '基础环境已就绪，待添加订阅：domino configs add "名称"；domino configs switch "名称"。': 'Base runtime ready. Add a subscription: domino '
                                                                      'configs add "name"; domino configs switch '
                                                                      '"name".',
 '已有终端请加载一次：. "$HOME/.config/domino/proxy.env"；Bash 登录配置需已加载 .bashrc。': 'Existing terminals: load . '
                                                                        '"$HOME/.config/domino/proxy.env" once; Bash '
                                                                        'login settings must already load .bashrc.',
 '其他已接入终端下次提示符同步；运行中的 VS Code 不会更新环境。': 'Other integrated terminals synchronize at their next prompt; running VS Code '
                                        'processes keep their existing environment.',
 '部署前备份：': 'Pre-deployment backup: ',
 'macOS 原生启动器需要 Xcode Command Line Tools；请运行 xcode-select --install 后重试，现有服务未修改。': 'The macOS native launcher requires '
                                                                                   'Xcode Command Line Tools; run '
                                                                                   'xcode-select --install and retry. '
                                                                                   'Existing service unchanged.',
 '受管理的环境文件不能是符号链接。': 'Managed environment files must not be symlinks.',
 '代理出网通过；出口地区：': 'Proxy connectivity verified; exit region: ',
 '；与系统代理独立，使用 domino shell on/off/status 管理。': '; independent of the system proxy; manage with domino shell '
                                               'on/off/status.',
 'macOS 原生启动器构建或签名校验失败，现有服务未修改。': 'macOS native launcher build or signature verification failed; existing service '
                                  'unchanged.',
 '安装未完成，已恢复原状态；备份：': 'Installation incomplete; original state restored. Backup: ',
 '未返回': 'Not returned',
 '终端代理策略：': 'Terminal proxy policy: ',
 '迁移未完成，已恢复原状态；备份：': 'Migration incomplete; original state restored. Backup: ',
 '端口 {0} 已被占用，请使用 --proxy-port / --api-port 选择空闲端口。': 'Port {0} is occupied; select free ports with --proxy-port / '
                                                      '--api-port.',
 '已关闭': 'Disabled',
 'Domino 控制接口未就绪，请查看日志。': 'Domino controller not ready; inspect the logs.',
 '安装失败且恢复未完成；备份：': 'Installation and recovery failed; backup: ',
 '迁移失败且恢复未完成；备份：': 'Migration and recovery failed; backup: ',
 '原生启动器启动后控制接口未就绪。': 'Controller not ready after starting the native launcher.',
 '资源源必须是 HTTPS 目录地址。': 'Resource source must be an HTTPS directory URL.',
 '资源源必须是无凭据的 HTTPS 目录地址。': 'Resource source must be an HTTPS directory URL without credentials.',
 'Geo 资源索引': 'Geo resource index',
 'Geo 资源索引格式无效。': 'Invalid Geo resource index.',
 'Geo 资源': 'Geo resources',
 'Geo 资源缺少 SHA-256。': 'Geo resource has no SHA-256 checksum.',
 'Geo 资源 SHA-256 校验失败。': 'Geo resource SHA-256 verification failed.',
 '资源下载配置格式无效。': 'Invalid resource download configuration.',
 '参数类型不符合接口定义。': 'Argument type does not match the interface definition.',
 '参数取值不符合接口定义。': 'Argument value does not match the interface definition.',
 '参数超出允许范围。': 'Argument outside the permitted range.',
 '参数不能为空。': 'Argument must not be empty.',
 '参数格式不符合接口定义。': 'Argument format does not match the interface definition.',
 '未支持的写操作。': 'Unsupported write operation.',
 '需要唯一的资源选择条件。': 'A unique resource selection is required.',
 '需要参数对象。': 'Arguments must be an object.',
 '缺少必填参数。': 'Required argument missing.',
 '包含未支持的参数。': 'Unsupported argument included.',
 '只能选择一种配置来源。': 'Select only one profile source.',
 '代理和控制端口不能相同。': 'Proxy and controller ports must differ.',
 '只能指定一种测速对象。': 'Specify only one latency test target.',
 '未找到订阅。': 'Subscription not found.',
 '导出文件已存在，请使用新的输出路径。': 'Export file already exists; choose a new output path.',
 '关闭连接后读回结果尚未一致。': 'Connection close readback has not converged.',
 '配置已变化，请重新读取状态。': 'The profile changed; read the current state again.',
 '只支持 Domino 自有服务。': 'Only Domino-owned services are supported.',
 '预览不接受请求去重键。': 'Preview does not accept a request deduplication key.',
 '目标平台不支持该操作。': 'Operation unsupported on the target platform.',
 '目标尚未安装 Domino 运行环境。': 'Domino runtime is not installed on the target.',
 '只读操作不接受写操作控制参数。': 'Read-only operations do not accept write-control arguments.',
 '目标请求超时。': 'Target request timed out.',
 '无法读取目标服务或配置。': 'Unable to read target service or profile.',
 '目标返回的数据不符合接口定义。': 'Target data does not match the interface definition.',
 '安装包平台与目标不符。': 'Package platform does not match the target.',
 '安装包架构与目标不符。': 'Package architecture does not match the target.',
 '安装包端口与配置不一致。': 'Package ports do not match the profile.',
 '导出路径已被占用。': 'Export path is already occupied.',
 '部分订阅更新未完成。': 'Some subscription updates did not complete.',
 '无法确认操作记录已落盘。': 'Unable to confirm the operation record was saved.',
 '终端代理端口无效；请检查安装配置。': 'Invalid terminal proxy port; check the installation settings.',
 '请先切换订阅，再删除当前订阅。': 'Switch away before removing the active subscription.',
 '本地快照没有在线订阅地址。': 'The local snapshot has no online subscription URL.',
 '需要手动策略组及其中有效的节点。': 'A manual policy group and a valid member node are required.',
 '操作已取消并恢复。': 'Operation cancelled and state restored.',
 '写操作未获得已确认结果，请查询操作记录。': 'Write operation has no confirmed result; query the operation record.',
 '未找到连接。': 'Connection not found.',
 '需要可更新的 HTTP 或文件集合。': 'An updatable HTTP or file provider is required.',
 '前一项结果未确认，尚未尝试。': 'Not attempted because the previous result is unconfirmed.',
 '订阅更新未完成。': 'Subscription update incomplete.',
 '未设置': 'Not set',
 '空值': 'Empty value',
 'Domino 已接管终端代理': 'Domino manages the terminal proxy',
 ' · 保留手动设置': ' · manual settings preserved',
 ' · 跳过只读变量': ' · read-only variables skipped',
 '已设置（值已隐藏）': 'Set (value hidden)',
 'Domino 已接管部分变量': 'Domino manages some variables',
 '使用原有代理设置': 'Using previous proxy settings',
 '导入源快照无效或资源不完整。': 'Invalid source snapshot or incomplete resources.',
 '本地资源引用路径无效。': 'Invalid local resource reference.',
 '本地资源引用包含符号链接，未读取。': 'Local resource reference includes a symlink; it was not read.',
 '文件；请检查配置引用，或使用 --resource-dir 指定资源目录。': ' file; check profile references or supply --resource-dir.',
 '证书/私钥': 'Certificate/private key',
 '。请先让来源客户端完成 Geo 数据更新，或配置 Domino 的 Geo 资源源后重试；未更改当前配置。': '. Update Geo data in the source client, or configure a '
                                                          'Domino Geo resource source and retry; the active profile is '
                                                          'unchanged.',
 '未知来源': 'Unknown source',
 '旧版运行配置快照': 'Legacy runtime snapshot',
 'Clash Verge 运行配置': 'Clash Verge runtime profile',
 '缺少': 'Missing',
 '捕获缺少 Geo 数据库：': 'Capture is missing Geo databases: ',
 ' 配置快照': ' profile snapshot',
 'Clash Verge 保存配置': 'Saved Clash Verge profile',
 '未命名配置': 'Unnamed profile',
 'provider 缓存': 'Provider cache',
 '操作 ID 无效。': 'Invalid operation ID.',
 '操作记录不能是符号链接。': 'Operation records must not be symlinks.',
 '未找到操作记录。': 'Operation record not found.',
 '请求记录路径不安全。': 'Unsafe request record path.',
 '该请求去重键已用于不同的操作参数。': 'This deduplication key was already used with different arguments.',
 '该操作尚无已确认结果，请按操作 ID 查询后再处理。': 'This operation has no confirmed result; query its operation ID before continuing.',
 '请求去重键无效。': 'Invalid request deduplication key.',
 '操作 ID 已存在。': 'Operation ID already exists.',
 '操作记录路径不安全。': 'Unsafe operation record path.',
 '操作记录格式无效。': 'Invalid operation record format.',
 ' 已超额': ' Exceeded',
 ' · 缓存': ' · cached',
 '配置登记或备份数据无效。': 'Invalid profile registration or backup data.',
 '本地快照没有可用订阅地址；请在“修改地址”中填写 HTTPS 订阅地址后更新配置。': 'The snapshot has no usable subscription URL; enter an HTTPS URL with '
                                              'Set URL, then update the profile.',
 '未知总量': 'Unknown total',
 '{0} 个配置 · 在线订阅 / 快照': '{0} profiles · subscriptions / snapshots',
 '\n  套餐数据来自订阅服务；domino list --refresh-usage 仅刷新流量，不切换或重载配置。': '\n'
                                                               '  Quota data comes from subscription providers; domino '
                                                               'list --refresh-usage refreshes quota only, without '
                                                               'switching or reloading profiles.',
 '配置名称需为 1–100 个字符，不能含控制字符或首尾空白。': 'Profile names must contain 1–100 characters without control characters or '
                                   'leading/trailing whitespace.',
 '未找到配置：': 'Profile not found: ',
 '完整配置订阅地址（隐藏输入）：': 'Full profile subscription URL (hidden input):',
 '订阅地址必须是无嵌入用户名和密码的 HTTPS URL。': 'Subscription URL must use HTTPS without embedded username or password.',
 '尚未安装运行环境，请先运行安装程序，再下载或切换订阅。': 'Runtime is not installed; run the installer before downloading or switching '
                                'subscriptions.',
 '订阅尚未下载，请先更新或使用该订阅。': 'Subscription not downloaded; update or use it first.',
 '待添加订阅': 'Add a subscription',
 '独立配置（未绑定订阅）': 'Independent profile (no linked subscription)',
 '套餐流量': 'Plan usage',
 '\n  添加订阅：domino add "名称"': '\n  Add a subscription: domino add "name"',
 '套餐已用 / 总量': 'Plan used / total',
 '--url 需用于 domino add 或 domino set-url。': '--url requires domino add or domino set-url.',
 '--new-name 需与 --rename 配合使用。': '--new-name requires --rename.',
 '获取失败': 'Fetch failed',
 '未关联订阅': 'No linked subscription',
 '未提供': 'Not provided',
 '未获取': 'Not fetched',
 '配置存储路径不能是符号链接。': 'Profile storage paths must not be symlinks.',
 '配置目录格式不受支持。': 'Unsupported profile registry format.',
 '配置名称已存在：': 'Profile name already exists: ',
 '隐藏输入需要交互终端；脚本请使用 --url。': 'Hidden input requires an interactive terminal; use --url in scripts.',
 '未关联订阅的当前配置': 'Current profile without a linked subscription',
 '尚未初始化': 'Not initialized',
 '流量更新': 'Usage updated',
 '缺少配置校验内核，请先安装 Domino 或使用 --core。': 'Profile validation core missing; install Domino or specify --core.',
 '订阅必须返回完整 Clash/Mihomo 配置；不支持节点链接列表或登录页面。': 'A subscription must return a complete Clash/Mihomo profile; node link '
                                             'lists and login pages are unsupported.',
 '尚未下载': 'Not downloaded',
 '本地': 'Local',
 '当前运行配置快照': 'Current runtime snapshot',
 '订阅源配置或依赖无效，未更改运行配置。': 'Invalid subscription profile or dependencies; runtime profile unchanged.',
 '订阅未应用，已恢复原配置；备份：': 'Subscription not applied; original profile restored. Backup: ',
 '不能删除当前正在使用的配置，请先切换到其他配置。': 'Cannot remove the active profile; switch to another profile first.',
 '订阅应用失败且恢复未完成；备份：': 'Subscription apply and recovery failed; backup: ',
 '当前配置快照登记失败且恢复未完成。': 'Current profile snapshot registration and recovery failed.',
 '部分订阅更新失败，保留各自旧配置：': 'Some subscription updates failed; previous profiles retained: ',
 '仅统计 {0}，不包含其他代理或系统总流量': 'Statistics cover only {0}, excluding other proxies and system-wide traffic',
 '当前配置、代理链路和节点': 'Active profile, proxy paths and nodes',
 '按名称或关键词选择节点': 'Select a node by name or keyword',
 '选择配置或捕获全部': 'Select profiles or capture all',
 '规则 / 全局 / 直连模式': 'Rule / global / direct mode',
 '检查服务和真实 HTTPS 出网': 'Check service and real HTTPS connectivity',
 '选择全部配置、单个配置或节点检测': 'Choose all profiles, one profile or a node to test',
 '扫描当前目标的配置和代理入口出网': 'Scan target profiles and proxy connectivity',
 '选择内嵌或全屏动态流量面板': 'Choose inline or full-screen traffic dashboard',
 '查看或选择关闭连接': 'View or choose connections to close',
 '查看、添加或选择删除自定义规则': 'View, add or choose custom rules to remove',
 '选择节点 / 规则集合': 'Choose node / rule providers',
 '查看配置与管理面板': 'View profiles and management panel',
 '添加配置': 'Add profile',
 '更新配置或 all': 'Update a profile or all',
 '修改订阅地址': 'Change subscription URL',
 '立即刷新状态和流量': 'Refresh status and traffic now',
 '最近的内核日志': 'Recent core logs',
 '查看或设置日志级别': 'Show or set log level',
 '终端代理：开启 / 关闭 / 状态': 'Terminal proxy: on / off / status',
 '重启并重新接通系统代理': 'Restart and reconnect the system proxy',
 '预览或卸载运行环境，清理配置与终端接入': 'Preview or uninstall runtime, profiles and terminal integration',
 '命令与快捷键': 'Commands and shortcuts',
 '清空本次操作记录': "Clear this session's event history",
 '退出界面，也可输入 exit 或按 Ctrl+D': 'Exit the workspace; exit or Ctrl+D also works',
 '模式未知': 'Unknown mode',
 '未初始化': 'Not initialized',
 '  ·  {0} 节点 / {1} 组': '  ·  {0} nodes / {1} groups',
 '仅统计 {0}；部分系统代理指向其他代理': 'Statistics cover only {0}; some system proxies point elsewhere',
 '仅统计 {0}；系统使用 PAC / 自动发现': 'Statistics cover only {0}; the system uses PAC / auto-discovery',
 '仅统计 {0}；系统代理未开启，应用需单独设置代理': 'Statistics cover only {0}; system proxy is disabled, so applications need explicit '
                              'proxy settings',
 '交互界面需要 prompt-toolkit；请安装项目依赖，或更新带 UI 组件的 Domino 安装包。': 'The workspace requires prompt-toolkit; install project '
                                                          'dependencies or update Domino with UI components.',
 '↑ {0}  ↓ {1}  ·  {2} 连接': '↑ {0}  ↓ {1}  ·  {2} connections',
 '接口在线': 'Controller online',
 '接口离线': 'Controller offline',
 '仅统计 {0}；系统代理仍指向其他代理': 'Statistics cover only {0}; system proxies still point elsewhere',
 '未知命令，输入 /help 查看可用操作。': 'Unknown command; enter /help for available actions.',
 '用法：/shell status，/shell on，/shell off。': 'Usage: /shell status, /shell on, /shell off.',
 '  ·  {0} 节点': '  ·  {0} nodes',
 '控制接口不可用，正在重试…': 'Controller unavailable; retrying…',
 'Esc / /traffic 关闭面板 · 底部每 2 秒刷新': 'Esc / /traffic closes the panel · refreshes every 2 seconds',
 '选择捕获的外部配置': 'Select an external profile to capture',
 '读取配置': 'Read profiles',
 '检测配置节点 · 选择配置': 'Test profile nodes · select a profile',
 '直接输入命令并回车进入选择面板，↑↓ 选择、Enter 确认；也可输入参数作为快捷操作。': 'Enter a command to open its picker, use ↑↓ to navigate and Enter to '
                                                 'confirm; arguments are also accepted as shortcuts.',
 '/shell 只管理终端代理策略；UI 不修改父 shell，退出后由已加载的 shell 集成同步。': '/shell manages terminal proxy policy only; the workspace does '
                                                        'not change its parent shell. Existing shell integration '
                                                        'synchronizes after exit.',
 '面板中输入筛选，↑↓ 导航，Enter 确认，Ctrl+T 测速。Ctrl+C 中断命令或清空输入。': 'Type to filter; ↑↓ navigates, Enter confirms, Ctrl+T tests '
                                                       'latency. Ctrl+C interrupts a command or clears input.',
 '活跃连接 {0} 条；显示前 20 条。': '{0} active connections; showing the first 20.',
 '选择关闭的连接': 'Choose a connection to close',
 '选择删除的自定义规则': 'Choose a custom rule to remove',
 '订阅集合 · Enter 更新 HTTP / file 集合': 'Subscription providers · Enter updates HTTP / file providers',
 '未选择配置': 'No profile selected',
 '已退出 Domino 界面；代理服务继续运行。': 'Domino workspace closed; the proxy service keeps running.',
 '规则': 'Rule',
 '全局': 'Global',
 '直连': 'Direct',
 '连接中…': 'Connecting…',
 ' / {0} 组': ' / {0} groups',
 '已有任务进行中；Ctrl+C 可中断。': 'A task is running; Ctrl+C interrupts it.',
 '读取策略组': 'Read policy groups',
 '当前配置  ': 'Current profile  ',
 '当前选择按规则分流，不代表所有请求都使用同一节点。': 'Current selections follow routing rules; requests may use different nodes.',
 '读取可选节点': 'Read selectable nodes',
 '没有匹配的节点；使用 /nodes 查看名称。': 'No matching node; use /nodes to see names.',
 '● 已开启': '● Enabled',
 '系统代理已开启 → Domino 127.0.0.1:{0}': 'System proxy enabled → Domino 127.0.0.1:{0}',
 '策略组 · ': 'Policy groups · ',
 '没有发现兼容外部配置；可使用 /catch --source "配置路径"。': 'No compatible external profiles found; use /catch --source "profile-path".',
 '全部配置 · 汇总可用/不可用节点': 'All profiles · summarize available/unavailable nodes',
 '选择节点所在策略组': "Select the node's policy group",
 '动态面板已打开；底部每 2 秒刷新；Esc 或 /traffic 关闭。': 'Live dashboard opened; refreshes every 2 seconds. Esc or /traffic closes it.',
 '动态流量面板已关闭。': 'Live traffic dashboard closed.',
 '设置尚在提交，请等操作完成后退出。': 'Settings are being committed; wait for completion before exiting.',
 '没有活跃连接。': 'No active connections.',
 '没有自定义规则。': 'No custom rules.',
 '没有可用集合。': 'No providers available.',
 '刷新配置': 'Refresh profiles',
 '测试节点延迟': 'Test node latency',
 '  不可用': '  Unavailable',
 '/ 命令': '/ Command',
 '未关联配置库的配置': 'Profile not linked to the library',
 '当前代理  ': 'Current proxy  ',
 '请填写唯一的手动策略组名称。': 'Enter a unique manual policy group name.',
 '切换节点': 'Switch node',
 '未关联配置库': 'No linked profile',
 '无桌面系统代理；终端使用 /shell on/off/status。': 'No desktop system proxy; use /shell on/off/status in the terminal.',
 '测试策略组延迟': 'Test policy group latency',
 '自动策略': 'Automatic policy',
 '{0} → {1}': '{0} → {1}',
 ' · 自动策略': ' · automatic policy',
 '捕获外部配置': 'Capture external profiles',
 '当前配置 · 选择策略组检测': 'Active profile · select a group to test',
 '当前配置 · 选择单个节点检测': 'Active profile · select a node to test',
 '检测全部配置': 'Test all profiles',
 '执行 /start 开启 Domino 并接通系统代理。': 'Run /start to start Domino and connect the system proxy.',
 '运行选择无法读取，本次不标记当前节点。': 'Runtime selections are unavailable; current nodes will not be marked.',
 '{0} 节点 · {1} 可用 · {2} 超时/不可用': '{0} nodes · {1} available · {2} timed out/unavailable',
 '关闭连接': 'Close connection',
 '这是内置节点快照；请用 /list 管理和更新完整订阅。': 'This is an internal node snapshot; use /list to manage and update full '
                                 'subscriptions.',
 '更新集合': 'Update provider',
 '{0}  [{1}]  {2} 项': '{0}  [{1}]  {2} entries',
 '切换': 'Switch',
 '添加': 'Add',
 '捕获': 'Capture',
 '保存快照': 'Save snapshot',
 '全部更新': 'Update all',
 ' 个配置 · 当前：': ' profiles · current: ',
 '请输入有效的 HTTPS 订阅地址。': 'Enter a valid HTTPS subscription URL.',
 '服务已停止': 'Service stopped',
 '  配置库为空，可在下方添加配置。': '  The profile library is empty; add a profile below.',
 '  没有匹配项；继续输入或按 Esc 返回。': '  No matches; keep typing or press Esc to return.',
 '↑↓ / 点击选择 · Enter 确认 · Esc 取消': '↑↓ / click to select · Enter confirms · Esc cancels',
 'Tab 操作 · Enter 确认 · Esc 返回': 'Tab for actions · Enter confirms · Esc returns',
 ' · Ctrl+T 测速': ' · Ctrl+T tests latency',
 '系统代理混用': 'Mixed system proxies',
 '系统代理 PAC': 'System proxy uses PAC',
 '系统代理未开启': 'System proxy disabled',
 '系统代理未知': 'System proxy unknown',
 '无桌面系统代理': 'No desktop system proxy',
 '无法刷新控制接口；/refresh 重试，/logs 查看日志。': 'Unable to refresh the controller; retry with /refresh or inspect /logs.',
 '已中断命令；可用 /status 查看实际状态。': 'Command interrupted; use /status to check actual state.',
 '已取消操作；未继续提交。': 'Operation cancelled; no further changes submitted.',
 '操作超时，请重试或使用 /logs 检查。': 'Operation timed out; retry or inspect /logs.',
 '没有可手动选择的策略组。': 'No manually selectable policy groups.',
 '服务已停止，Domino 系统代理接管已解除。': 'Service stopped; Domino system proxy settings released.',
 '系统代理尚未接通；/status 查看详情。': 'System proxy not connected; use /status for details.',
 '该组由策略自动选择；请在上层 Selector 策略组中切换。': 'This group selects automatically; switch through a parent Selector group.',
 '检测配置节点': 'Test profile nodes',
 '未启用 · 当前使用 ': 'Inactive · currently using ',
 '  · 当前选中': '  · currently selected',
 ' 不需要额外参数。': ' does not accept extra arguments.',
 '已请求刷新状态和流量。': 'Status and traffic refresh requested.',
 '重命名': 'Rename',
 '修改地址': 'Set URL',
 '检测': 'Test',
 '删除': 'Remove',
 '更新配置': 'Update profile',
 '  操作对象：': '  Target profile: ',
 '配置管理 · ': 'Profile management · ',
 'HTTPS 订阅地址（隐藏输入）': 'HTTPS subscription URL (hidden input)',
 '更新全部在线订阅': 'Update all online subscriptions',
 '状态刷新失败 · /refresh 重试': 'Status refresh failed · retry /refresh',
 'Enter 提交 · Esc 取消输入': 'Enter submits · Esc cancels input',
 '↑↓ 选配置 · Tab 操作栏 · ←→ 选操作 · Enter 执行 · Esc 返回': '↑↓ selects profile · Tab switches toolbar · ←→ selects action · '
                                                  'Enter runs · Esc returns',
 '系统代理指向其他代理 :': 'System proxies point elsewhere: ',
 '捕获流程已结束，使用 /list 查看配置。': 'Capture finished; use /list to view profiles.',
 '操作失败。': 'Operation failed.',
 '● 当前配置  ': '● Current profile  ',
 '测试配置  ': 'Test profile  ',
 '  超时 / 不可用': '  Timed out / unavailable',
 ' 节点  ': ' Nodes  ',
 '正在应用设置，完成后即可继续；此阶段不强行中断。': 'Applying settings; wait for completion. This phase is not forcibly interrupted.',
 '再次按 Ctrl+C 退出，代理服务会继续运行。': 'Press Ctrl+C again to exit; the proxy service will keep running.',
 '输入筛选': 'Type to filter',
 '完成。': 'Done.',
 '配置列表刷新失败；按 F5 重试。': 'Unable to refresh profiles; press F5 to retry.',
 '新配置名称': 'New profile name',
 '快照名称': 'Snapshot name',
 '配置管理': 'Profile management',
 '状态待刷新': 'Awaiting status refresh',
 '操作已完成，但状态刷新失败；使用 /refresh 重试。': 'Operation completed, but status refresh failed; retry /refresh.',
 '用法：/select，/select "节点名或关键词"，可附加 --group "策略组"。': 'Usage: /select, /select "node or keyword", optionally --group '
                                                    '"group".',
 '读取外部配置': 'Read external profiles',
 '配置已更新：': 'Profile updated: ',
 '选择一个外部配置': 'Select an external profile',
 '全部配置 · 重复项自动跳过': 'All profiles · duplicates skipped automatically',
 '切换模式': 'Switch mode',
 '选择运行模式': 'Select proxy mode',
 '用法：/mode，或 /mode rule|global|direct。': 'Usage: /mode, or /mode rule|global|direct.',
 '扫描配置与代理出网': 'Scan profiles and proxy connectivity',
 '添加订阅': 'Add subscription',
 '规则模式  按分流规则选择出口': 'Rule mode    Select outbound by routing rules',
 '全局模式  使用 GLOBAL 当前选择': 'Global mode  Use the current GLOBAL selection',
 '直连模式  直接连接目标': 'Direct mode  Connect directly to destinations',
 '扫描配置': 'Scan profiles',
 '用法：/scan，或 /scan --source "配置路径"。': 'Usage: /scan, or /scan --source "profile-path".',
 '订阅管理': 'Subscription management',
 '扫描指定配置': 'Scan a specific profile',
 '扫描全部外部配置与 Domino 配置': 'Scan all external and Domino profiles',
 '指定配置文件路径': 'Specify profile file path',
 '配置文件路径：': 'Profile path:',
 '动态流量面板': 'Live traffic dashboard',
 '流量监控': 'Traffic monitor',
 '用法：/traffic 选择面板，/traffic --inline，/traffic --full。': 'Usage: /traffic to choose a dashboard, /traffic --inline, '
                                                        '/traffic --full.',
 ' "配置名称"，地址将隐藏输入；也可附加 --url "HTTPS 地址"。': ' "profile-name" to enter a hidden URL, or add --url "HTTPS-URL".',
 '新配置名称：': 'New profile name:',
 '测试延迟': 'Test latency',
 '连接管理': 'Connection management',
 '用法：/': 'Usage: /',
 '；/update all 更新全部在线订阅。': '; /update all updates every online subscription.',
 '用法：/test 汇总所有配置，或 /test "配置名" 查看节点明细。': 'Usage: /test to summarize profiles, or /test "profile-name" for node '
                                          'details.',
 '打开独立全屏面板 · q 返回': 'Open full-screen dashboard · q returns',
 '读取连接': 'Read connections',
 '分流规则': 'Routing rules',
 '读取集合': 'Read providers',
 ' "旧名称" "新名称"': ' "old-name" "new-name"',
 ' "配置名称"': ' "profile-name"',
 '关闭内嵌面板': 'Close inline dashboard',
 '打开内嵌动态面板': 'Open inline live dashboard',
 '查看活跃连接': 'Show active connections',
 '选择关闭一个连接': 'Choose a connection to close',
 '关闭全部活跃连接': 'Close all active connections',
 '新增规则': 'Add rule',
 '选择集合类型': 'Select provider type',
 '用法：/providers 或 /providers rule。': 'Usage: /providers or /providers rule.',
 '用法：/connections，/connections --close ID，/connections --all。': 'Usage: /connections, /connections --close ID, '
                                                                '/connections --all.',
 '查看运行规则': 'Show runtime rules',
 '查看自定义规则': 'Show custom rules',
 '搜索运行规则': 'Search runtime rules',
 '选择删除自定义规则': 'Choose a custom rule to remove',
 '完整规则（如 DOMAIN-SUFFIX,example.com,DIRECT）：': 'Complete rule (for example DOMAIN-SUFFIX,example.com,DIRECT):',
 '读取自定义规则': 'Read custom rules',
 '日志级别': 'Log level',
 '搜索规则': 'Search rules',
 '节点集合 · proxy': 'Node providers · proxy',
 '规则集合 · rule': 'Rule providers · rule',
 '日志级别可选 debug、info、warning、error、silent。': 'Log levels: debug, info, warning, error, silent.',
 '搜索关键词：': 'Search keyword:',
 '读取规则': 'Read rules',
 '终端代理策略': 'Terminal proxy policy',
 '查看内核日志': 'Show core logs',
 '调试  debug': 'Debug    debug',
 '信息  info': 'Info     info',
 '警告  warning': 'Warning  warning',
 '错误  error': 'Error    error',
 '静默  silent': 'Silent   silent',
 'on · 在终端中使用 Domino 代理': 'on · Use Domino in the terminal',
 'off · 恢复原代理设置': 'off · Restore previous proxy settings',
 'status · 查看端口和环境变量': 'status · Show port and environment variables',
 '开启 Domino 系统代理': 'Enable Domino system proxy',
 '恢复此前的系统代理设置': 'Restore previous system proxy settings',
 '系统代理状态': 'System proxy status',
 '用法：/proxy，/proxy on，/proxy off，/proxy status。': 'Usage: /proxy, /proxy on, /proxy off, /proxy status.',
 '卸载 Domino': 'Uninstall Domino',
 ' "完整规则"。例如 /rules add "DOMAIN-SUFFIX,example.com,DIRECT"。': ' "complete-rule". Example: /rules add '
                                                              '"DOMAIN-SUFFIX,example.com,DIRECT".',
 '卸载预览': 'Uninstall preview',
 '执行 ': 'Run ',
 '用法：/rules ': 'Usage: /rules ',
 '预览清理范围（不修改）': 'Preview cleanup without changes',
 '卸载运行环境并删除配置、备份（需确认）': 'Uninstall runtime, profiles and backups (confirmation required)',
 '使用 /uninstall 选择预览或卸载。': 'Use /uninstall to choose preview or removal.',
 'Mihomo、运行配置、配置库、部署备份、默认缓存和日志': 'Mihomo, runtime profiles, profile library, deployment backups, default cache and '
                                 'logs',
 '保留': 'Preserve',
 '项目源码、外部客户端及包管理器安装的 CLI': 'Project source, external clients and package-managed CLI',
 '● 运行环境已移除': '● Runtime removed',
 '终端接入': 'Terminal integration',
 '已清理 Domino 管理区块；请重新打开终端或重新 SSH 登录': 'Domino-managed blocks removed; open a new terminal or reconnect SSH',
 '包管理器入口保留；pip 安装的 CLI 可继续运行 pip uninstall domino-proxy': 'Package-managed entry point preserved; for pip '
                                                          'installations, use pip uninstall domino-proxy',
 'Domino 终端标记不完整，未修改启动文件。': 'Incomplete Domino terminal markers; startup file unchanged.',
 '卸载仅支持 macOS 和 Linux。': 'Uninstallation supports macOS and Linux only.',
 '预览（未修改）': 'Preview (no changes)',
 '移除当前用户的运行环境': "Remove the current user's runtime",
 '目录': 'Directory',
 '清理接入': 'Remove integration',
 'Domino 日志目录类型异常，未卸载。': 'Unexpected Domino log directory type; uninstall cancelled.',
 '同名服务是符号链接，未卸载。': 'A same-named service is a symlink; uninstall cancelled.',
 '卸载会删除配置和备份；请在终端确认，或明确添加 --yes。': 'Uninstall deletes profiles and backups; confirm in a terminal or explicitly pass '
                                   '--yes.',
 '已取消卸载，未修改。': 'Uninstall cancelled; nothing changed.',
 '卸载路径包含符号链接，未修改：': 'Uninstall path includes a symlink; left unchanged: ',
 'Domino 终端标记嵌套，未修改启动文件。': 'Nested Domino terminal markers; startup file unchanged.',
 '卸载目录类型异常：': 'Unexpected uninstall directory type: ',
 'LaunchAgent 不属于当前用户的 Domino，未卸载。': "LaunchAgent is not owned by the current user's Domino; uninstall cancelled.",
 '同名服务不属于当前用户的 Domino，未卸载。': "A same-named service is not owned by this user's Domino; uninstall cancelled.",
 '命令入口在卸载期间发生变化，未删除。': 'Command entry point changed during uninstall; it was not removed.',
 '同名服务内容异常，未卸载。': 'Unexpected same-named service content; uninstall cancelled.',
 '服务文件未移除，保留运行文件；请重试卸载。': 'Service file was not removed; runtime files retained. Retry uninstall.',
 '终端文件在卸载期间发生变化，未覆盖：': 'Terminal file changed during uninstall; it was not overwritten: ',
 '确认卸载并删除这些数据？[y/N] ': 'Uninstall and delete this data? [y/N] ',
 '远端步骤': 'Target step',
 '没有本版本工具生成的可恢复备份。': 'No recoverable backup was created by this version of Domino.',
 '未启用自启动': 'Autostart disabled',
 '内核': 'Core',
 '{0}  ·  {1} 策略组  ·  {2} 节点': '{0}  ·  {1} policy groups  ·  {2} nodes',
 '● 已切换': '● Switched',
 '当前节点': 'Current node',
 '\n  新连接将使用该选择；已有长连接可能需要重新连接。': '\n  New connections use this selection; existing connections may need to reconnect.',
 '规则模式': 'Rule mode',
 '全局模式': 'Global mode',
 '直连模式': 'Direct mode',
 '调试': 'Debug',
 '信息': 'Info',
 '警告': 'Warning',
 '错误': 'Error',
 '静默': 'Silent',
 '没有找到指定{0}；请运行 domino nodes 查看名称。': 'Specified {0} not found; run domino nodes to see names.',
 '尚未安装运行环境，请先运行安装程序。': 'Runtime is not installed; run the installer first.',
 '代理已部署，但旧 VS Code 进程未退出；未强制终止：': 'Proxy deployed, but old VS Code processes are still running; they were not forcibly '
                                  'terminated: ',
 '同名服务不是本工具管理的，停止以免覆盖。': 'A same-named service is not managed by Domino; stopped to avoid overwriting it.',
 '安装目录是符号链接，停止。': 'Installation directory is a symlink; stopped.',
 '控制接口地址不是预期的回环地址。': 'Controller address is not the expected loopback endpoint.',
 '出网检查 URL 无效。': 'Invalid connectivity test URL.',
 '备份格式无效，未恢复。': 'Invalid backup format; restore cancelled.',
 '用户或目录名称不适合自动生成 systemd 服务。': 'Username or directory name is unsuitable for automatic systemd service generation.',
 '请用普通 SSH 用户部署，脚本只为系统服务步骤调用 sudo。': 'Deploy as a regular SSH user; the installer invokes sudo only for system service '
                                     'steps.',
 '安装包版本不受支持。': 'Unsupported package version.',
 '安装包架构与目标设备不一致。': 'Package architecture does not match the target device.',
 '安装包端口配置无效。': 'Invalid package port settings.',
 '安装包配置与安全监听端口不一致。': 'Package profile does not match the safe listening ports.',
 '~/.local/bin/domino 已被其他程序使用，未覆盖。': '~/.local/bin/domino belongs to another program; it was not overwritten.',
 '服务已运行并启用开机自启；代理端口：': 'Service running with boot autostart enabled; proxy port: ',
 '基础环境已就绪，待添加订阅：domino add "名称"；domino switch "名称"。': 'Base runtime ready. Add a subscription: domino add "name"; '
                                                      'domino switch "name".',
 '其他已接入终端下次提示符同步；运行中的 VS Code / Server 不会更新环境。': 'Other integrated terminals synchronize at their next prompt; running '
                                                 'VS Code / Server processes keep their existing environment.',
 '目标机管理和继续部署：~/.local/bin/domino status；~/.local/bin/domino USER@IP': 'Manage or deploy onward from the target: '
                                                                      '~/.local/bin/domino status; ~/.local/bin/domino '
                                                                      'USER@IP',
 '备份不存在或来自不支持自动恢复的旧版本。': 'Backup missing or created by an older version without automatic recovery support.',
 '请使用部署时的普通 SSH 用户回滚。': 'Roll back as the regular SSH user who deployed the service.',
 '已恢复部署前状态：': 'Pre-deployment state restored: ',
 '回滚前状态也已保存：': 'Pre-rollback state also saved: ',
 '○ 尚未安装运行环境': '○ Runtime not installed',
 '未知': 'Unknown',
 '未检测': 'Not checked',
 '登录时自启': 'Start at login',
 '开机自启': 'Start at boot',
 '无法确认': 'Unknown',
 '策略无法读取': 'Unable to read policy',
 '代理地址': 'Proxy address',
 '上游依赖': 'Upstream dependency',
 '  下一步：domino add "名称"；domino switch "名称"。': '  Next: domino add "name"; domino switch "name".',
 '待添加并切换订阅。': 'Add and switch to a subscription.',
 '目标尚未安装本工具管理的代理。': 'No Domino-managed proxy is installed on the target.',
 '当前代理': 'Current proxy',
 '无法确定（未发现可用策略组）': 'Unknown (no usable policy group)',
 '  按规则分流；以上为手动策略组（无手动组时为自动策略组）的当前选择。': '  Routing follows rules; these are current manual group selections, or '
                                        'automatic groups when no manual group exists.',
 '\n  * 表示被策略组当前选中，不代表所有请求都走该节点。': "\n  * marks a group's current selection; requests may use different nodes.",
 '\n  查看组内节点：domino nodes --group "策略组名称"': '\n  List group members: domino nodes --group "group-name"',
 '策略组不存在，请先用 nodes 查看。': 'Policy group not found; run nodes first.',
 '该组由自动策略选择；请切换上层可手动选择的策略组。': 'This group selects automatically; switch through a manually selectable parent group.',
 '指定节点不在该策略组中，未更改任何选择。': 'The specified node is not in this group; selections unchanged.',
 '● 当前已选择，无需切换': '● Already selected; no change needed',
 '切换请求已发送，但读回的选择尚未一致；请用 nodes 核实。': 'Selection request sent, but readback has not converged; verify with nodes.',
 '本机尚未安装 Domino 代理。': 'Local Domino proxy is not installed.',
 '管理服务': 'Manage service',
 '尚未安装 Domino 运行环境，请先运行安装程序。': 'Domino runtime is not installed; run the installer first.',
 '代理模式': 'Proxy mode',
 '值': 'Value',
 '保存': 'Persistence',
 '已写入配置，重启后保留': 'Saved to the profile and retained after restart',
 ' · 节点 {0} · 可用 {1} · 不可用 {2}': ' · nodes {0} · available {1} · unavailable {2}',
 '缺少 Mihomo 内核，无法测试配置。': 'Mihomo core missing; unable to test profiles.',
 '测速超时必须在 100–60000 毫秒之间。': 'Latency timeout must be between 100 and 60000 milliseconds.',
 '测速 URL 必须是无内嵌凭据的 HTTPS 地址。': 'Latency URL must use HTTPS without embedded credentials.',
 '配置出网检测': 'Profile connectivity tests',
 '{0} 个配置 · 逐节点 HTTPS 检测': '{0} profiles · per-node HTTPS checks',
 '配置、节点和策略组只能选择一种测速对象。': 'Select only one test target: profile, node or policy group.',
 '节点或策略组': 'Node or policy group',
 '节点测速': 'Node latency',
 '\n  ● 表示当前配置或策略组当前选中的节点；实际请求按代理模式和规则分流。': '\n'
                                            '  ● marks the active profile or selected node; requests follow proxy mode '
                                            'and routing rules.',
 '连接': 'Connections',
 '{0} 个活跃连接': '{0} active connections',
 '流量刷新间隔必须为 0.2–60 秒；次数不能为负。': 'Traffic interval must be between 0.2 and 60 seconds; sample count cannot be negative.',
 'Domino · 流量监控': 'Domino · Traffic monitor',
 '仅统计经过 Domino 的流量 · 每 {0:g} 秒刷新 · {1}': 'Domino traffic only · refresh every {0:g} seconds · {1}',
 '上传': 'Upload',
 'q / Esc / Ctrl+C 退出 · 累计值自内核启动计数': 'q / Esc / Ctrl+C exits · totals since core startup',
 '流量': 'Traffic',
 '仅统计经过 Domino 的流量': 'Only traffic through Domino is counted',
 '自定义规则路径不能是符号链接。': 'Custom rule paths must not be symlinks.',
 '自定义规则文件格式无效。': 'Invalid custom rules file.',
 '基础规则必须为字符串列表。': 'Base rules must be a list of strings.',
 '请提供单行 Mihomo 规则，例如 DOMAIN-SUFFIX,example.com,DIRECT。': 'Provide a single-line Mihomo rule, for example '
                                                         'DOMAIN-SUFFIX,example.com,DIRECT.',
 '未找到该自定义规则；使用 domino rules --custom 查看原文。': 'Custom rule not found; use domino rules --custom to see the original '
                                             'text.',
 '尚未安装内核，请先运行安装程序。': 'Core is not installed; run the installer first.',
 '规则显示数量必须在 1–100000 之间。': 'Displayed rule count must be between 1 and 100000.',
 '终端代理动作必须是 on 或 off。': 'Terminal proxy action must be on or off.',
 '控制接口暂不可用；可使用 /start 或 /logs 检查。': 'Controller temporarily unavailable; use /start or /logs.',
 '保存命名订阅；不切换当前配置': 'Save a named subscription without switching the active profile',
 '更新订阅；当前订阅校验成功后自动应用': 'Update a subscription; validate before applying an active subscription',
 '切换订阅；首次使用时自动下载': 'Switch subscriptions; download automatically on first use',
 '删除非当前订阅': 'Remove an inactive subscription',
 '重命名，配合 --new-name': 'Rename with --new-name',
 '修改地址，配合 --url': 'Change URL with --url',
 '保存当前配置为本地快照': 'Save the active profile as a local snapshot',
 '仅刷新订阅套餐流量；不更新或切换运行配置': 'Refresh plan usage only; do not update or switch the runtime profile',
 '代理环境标记不完整，停止修改启动文件。': 'Incomplete proxy environment markers; startup file changes stopped.',
 '控制接口拒绝请求。': 'Controller rejected the request.',
 '受管理的环境文件是符号链接，未覆盖。': 'Managed environment file is a symlink; it was not overwritten.',
 '安装目录是符号链接，停止恢复。': 'Installation directory is a symlink; restore stopped.',
 '恢复未完成；保留的完整备份：': 'Recovery incomplete; complete backup retained at: ',
 '受管理的环境文件是符号链接，停止。': 'Managed environment file is a symlink; stopped.',
 '代理出网校验通过；出口地区：': 'Proxy connectivity verified; exit region: ',
 '备份 ID 无效。': 'Invalid backup ID.',
 '  下一步：运行安装程序。': '  Next: run the installer.',
 '  ·  出口 ': '  ·  Exit ',
 '策略已开启': 'Policy enabled',
 '策略已关闭': 'Policy disabled',
 '  ·  domino shell status 查看当前终端': '  ·  domino shell status shows the current terminal',
 '版本未知': 'Unknown version',
 '需要源电脑保持在线': 'Source computer must remain online',
 '  启动服务：domino start': '  Start service: domino start',
 '无法读取 Mihomo 节点，请先运行 status 检查服务。': 'Unable to read Mihomo nodes; check the service with status first.',
 '（直连）': '(direct)',
 '（拒绝连接）': '(rejected)',
 '（节点信息不可用）': '(node information unavailable)',
 '（按连接分配）': '(per-connection selection)',
 '（尚未选定节点）': '(no node selected yet)',
 '没有找到该策略组，请先运行 nodes 查看名称。': 'Policy group not found; run nodes to see names.',
 '节点名称': 'Node name',
 '协议': 'Protocol',
 '当前选中该节点的策略组': 'Groups currently selecting this node',
 '暂无数据。': 'No data available.',
 '设置读回不一致。': 'Settings readback mismatch.',
 '设置保存失败，已恢复原设置。': 'Unable to save settings; previous settings restored.',
 '模式': 'Mode',
 '级别': 'Level',
 '当前模式': 'Current mode',
 '当前级别': 'Current level',
 '匹配到多个{0}，请使用完整名称。候选：': 'Multiple matching {0}; use an exact name. Candidates: ',
 ' · 配置 {0}/{1}': ' · profile {0}/{1}',
 '查看明细': 'View details',
 'domino test "配置名"；可用表示该节点本次 HTTPS 请求成功。': 'domino test "profile-name"; available means this node\'s HTTPS request '
                                            'succeeded in this test.',
 '配置库为空': 'Profile library empty',
 '请先用 domino catch 捕获配置，或用 domino add 添加订阅。': 'Capture a profile with domino catch or add a subscription with domino '
                                              'add.',
 '{0} 节点  ·  {1} 可用  ·  {2} 超时/不可用': '{0} nodes  ·  {1} available  ·  {2} timed out/unavailable',
 '延迟': 'Latency',
 '使用状态': 'Usage status',
 '  暂无活跃连接。': '  No active connections.',
 '↑ 上传  ': '↑ Upload  ',
 '↓ 下载  ': '↓ Download  ',
 '活跃连接  {0}    内核内存  ': 'Active connections  {0}    Core memory  ',
 '终端缺少全屏支持；可用 domino traffic --json 读取单次采样。': 'Full-screen terminal support missing; use domino traffic --json for one '
                                              'sample.',
 '全屏流量监控需要交互终端；可用 domino traffic --json 读取单次采样。': 'Full-screen traffic monitoring requires an interactive terminal; '
                                                  'use domino traffic --json for one sample.',
 '无法打开流量监控终端；可用 domino traffic --json 读取单次采样。': 'Unable to open the traffic terminal; use domino traffic --json for '
                                                'one sample.',
 '终端显示组件不可用，请更新 Domino 安装包；全屏显示可使用 domino traffic --full。': 'Terminal display components unavailable; update Domino or '
                                                            'use domino traffic --full.',
 '该自定义规则已存在。': 'This custom rule already exists.',
 '自定义规则': 'Custom rules',
 '● 规则已存在，无需重复添加': '● Rule already exists; no duplicate added',
 '已持久保存，后续新连接使用当前配置': 'Saved persistently; new connections use the current profile',
 '备份': 'Backup',
 '{0} 条  ·  从上到下匹配': '{0} rules  ·  matched from top to bottom',
 '{0} 条匹配  ·  显示 {1} 条': '{0} matching rules  ·  showing {1}',
 '没有找到指定 provider。': 'Specified provider not found.',
 '该集合是内置节点快照，没有独立订阅更新地址；请使用 configs add/switch 管理完整配置订阅。': 'This provider is an internal node snapshot without its own '
                                                           'update URL; use configs add/switch to manage complete '
                                                           'subscriptions.',
 '节点集合': 'Node providers',
 '规则集合': 'Rule providers',
 '{0} 个集合': '{0} providers',
 '在线': 'Online',
 '本地文件': 'Local file',
 '内置': 'Built-in',
 '内嵌': 'Inline',
 '  暂无集合。': '  No providers available.',
 '终端代理策略读取或写入失败；请检查安装与策略文件。': 'Unable to read or write terminal proxy policy; check the installation and policy file.',
 '作用': 'Purpose',
 '让终端（Terminal）中支持代理环境变量的程序使用代理': 'Use a proxy in terminal programs that support proxy environment variables',
 '代理端口': 'Proxy port',
 '开启目标': 'Enabled endpoint',
 '以下为开启 Domino 终端代理时设置的变量': 'Variables set when enabling the Domino terminal proxy',
 '生效': 'Synchronization',
 '已接入终端返回命令行后同步；on/off 后用 domino shell status 查看': 'Integrated terminals synchronize at their next prompt; check with '
                                                   'domino shell status after on/off',
 '已取消。': 'Cancelled.',
 '需要预先授权 sudo；机器接口不会询问密码。': 'Pre-authorized sudo required; the machine interface will not prompt for a password.',
 '代理环境标记顺序无效。': 'Invalid proxy environment marker order.',
 'VS Code/Codex 旧进程已退出，PID：': 'Old VS Code/Codex processes exited; PIDs: ',
 '控制接口请求超时。': 'Controller request timed out.',
 '无法连接控制接口。': 'Unable to connect to the controller.',
 '目标端口 {0} 已被其他服务占用，未修改。': 'Target port {0} is occupied by another service; nothing changed.',
 '部署未完成，正在恢复服务、节点配置和环境文件…': 'Deployment incomplete; restoring service, node profile and environment files…',
 '部署未完成，已恢复原状态；备份：': 'Deployment incomplete; original state restored. Backup: ',
 '● 服务已运行 · 待添加订阅': '● Service running · add a subscription',
 '● 服务已停止 · 待添加订阅': '● Service stopped · add a subscription',
 '● 服务已停止': '● Service stopped',
 '使用 PAC 自动配置': 'Using PAC autoconfiguration',
 '无 GNOME 桌面会话；终端可用 domino shell on': 'No GNOME desktop session; use domino shell on in the terminal',
 '  排查连接：domino logs；domino nodes': '  Troubleshoot: domino logs; domino nodes',
 '代理控制接口或独立出网检查失败': 'Proxy controller or independent connectivity check failed',
 '组内当前选择': 'Current group selection',
 '● 已重启': '● Restarted',
 '无 GNOME 桌面会话；代理入口已就绪': 'No GNOME desktop session; proxy endpoint ready',
 '使用 domino shell on/off/status 独立管理': 'Manage separately with domino shell on/off/status',
 '已解除 Domino 接管；无桌面时不修改系统代理': 'Domino proxy settings released; no system proxy changes on a headless target',
 '未缓存，请先更新或捕获配置。': 'Not cached; update or capture the profile first.',
 '节点总数': 'Total nodes',
 '超时/不可用': 'Timed out/unavailable',
 '检测状态': 'Test status',
 '没有可测速的节点；请运行 domino nodes 查看配置。': 'No testable nodes; run domino nodes to inspect profiles.',
 '读取失败，本次不标记正在使用的节点': 'Unable to read active selections; current nodes will not be marked',
 '● 已关闭全部连接': '● All connections closed',
 '● 已关闭指定连接': '● Selected connection closed',
 '连接 ID': 'Connection ID',
 '正在连接控制接口…': 'Connecting to controller…',
 '    累计下载  ': '    Total downloaded  ',
 '  ·  {0} 连接': '  ·  {0} connections',
 '规则校验失败，请检查语法、出口名称及引用的资源；原配置未修改。': 'Rule validation failed; check syntax, outbound names and referenced resources. '
                                    'Original profile unchanged.',
 '● 已删除': '● Removed',
 '● 已新增并置顶': '● Added at the top',
 '生效条件': 'Activation',
 '切换规则模式：domino mode --set rule': 'Switch to rule mode: domino mode --set rule',
 '  暂无自定义规则。': '  No custom rules.',
 '  没有匹配的规则。': '  No matching rules.',
 '名称': 'Name',
 '数量': 'Count',
 '请先安装 Domino，再设置终端代理。': 'Install Domino before configuring the terminal proxy.',
 '● 策略已开启': '● Policy enabled',
 '● 策略已关闭': '● Policy disabled',
 '恢复原代理设置，保留手动修改': 'Restore previous proxy settings, preserving manual changes',
 '当前环境': 'Current environment',
 '本次命令继承的已导出变量（同步前）；地址不含账号密码': 'Exported variables inherited by this command, before synchronization; credentials '
                               'omitted',
 '未检测到完整集成；安装后加载 ~/.config/domino/proxy.env': 'Full integration not detected; load ~/.config/domino/proxy.env after '
                                              'installation',
 '目标已有另一个修改操作在执行，请稍后重试。': 'Another target modification is running; retry later.',
 '● 服务运行中 · 系统代理未接通': '● Service running · system proxy not connected',
 '已开启，指向 Domino': 'Enabled, pointing to Domino',
 '指向其他代理': 'Points to another proxy',
 '部分指向其他代理': 'Some proxies point elsewhere',
 '  接通系统代理：domino start': '  Connect system proxy: domino start',
 '（循环引用）': '(circular reference)',
 '（手动）': '(manual)',
 '（自动）': '(automatic)',
 '设置保存失败且恢复未完成。': 'Saving settings and recovery failed.',
 '配置测速临时内核启动失败；请检查缓存配置和依赖资源。': 'Temporary core could not start for profile testing; check the cached profile and '
                               'resources.',
 '配置测速临时内核启动超时。': 'Temporary core startup timed out during profile testing.',
 '● 当前使用中': '● Active',
 '当前使用状态无法确认': 'Active state unknown',
 '正在采样速率…': 'Sampling traffic rate…',
 '实时监控中': 'Live monitoring',
 '累计上传  ': 'Total uploaded  ',
 '近期趋势 · 峰值 ': 'Recent trend · peak ',
 '规则未应用，已恢复原配置；备份：': 'Rules not applied; original profile restored. Backup: ',
 '匹配内容': 'Match',
 '出口': 'Outbound',
 '  ·  已更新 ': '  ·  Updated ',
 '服务控制接口未就绪。': 'Service controller not ready.',
 '自动恢复未完成。保留的完整备份：': 'Automatic recovery incomplete. Complete backup retained at: ',
 '回滚和自动恢复未完成。当前状态备份：': 'Rollback and automatic recovery incomplete. Current state backup: ',
 '● 代理出网正常': '● Proxy connectivity verified',
 '● 服务运行中 · 连通检查未通过': '● Service running · connectivity check failed',
 '  订阅 ': '  Subscription ',
 '配置加载或测速失败，请检查缓存和内核；当前配置未改变。': 'Profile load or latency check failed; inspect the cache and core. Active profile '
                                'unchanged.',
 '已检测': 'Tested',
 '配置 ': 'Profile ',
 '当前选中': 'Currently selected',
 '规则应用失败且恢复未完成；备份：': 'Rule apply and recovery failed; backup: ',
 'doctor 当前仅支持 macOS。': 'doctor currently supports macOS only.',
 '  ·  累计 ↑': '  ·  Total ↑',
 '目标订阅组件版本过旧，请先更新该设备的 Domino，以保留自定义规则。': 'Target subscription components are too old; update Domino on that device to '
                                         'preserve custom rules.',
 '目标管理程序缺少订阅组件，请先更新该设备的 Domino。': 'Target management code lacks subscription components; update Domino on that device '
                                  'first.',
 '仅本次命令使用的语言：zh 或 en': 'Language for this command only: zh or en',
 '查看或保存界面语言': 'Show or save the interface language',
 'zh 为中文，en 为英文；保存后对后续命令生效': 'zh for Chinese, en for English; saved for future commands',
 '界面语言：{0}': 'Interface language: {0}',
 '切换中英文界面': 'Switch between Chinese and English',
 '界面语言': 'Interface language',
 '用法：/language，或 /language zh / en。': 'Usage: /language, or /language zh / en.',
 'Tab 补全': 'Tab completion',
 '内网访问': 'LAN access',
 '后台服务': 'Background service',
 '基础环境已安装 · 待添加订阅': 'Base environment installed; add a subscription',
 '安装结果': 'Installation result',
 '实际出网': 'Connectivity',
 '已交付': 'Installed',
 '已应用': 'Applied',
 '已有终端': 'Existing terminals',
 '已检测通过': 'Verified',
 '应用接入': 'Application access',
 '恢复备份': 'Recovery backup',
 '新开的 {0} 终端自动加载': 'New {0} terminals load completion automatically',
 '服务运行不代表浏览器或终端已使用代理；domino status 查看': 'A running service does not mean browsers or terminals use the proxy; check domino status',
 '本次未设置终端接入': 'Terminal integration skipped for this installation',
 '补全文件缺失，请重新安装': 'Completion file missing; reinstall Domino',
 '运行中 · 开机自启': 'Running; starts at boot',
 '运行中 · 登录当前用户时自启': 'Running; starts at user login',
 '运行环境已安装': 'Runtime installed',
 '重新打开一次即可；不需要每次手动加载': 'Reopen once; no manual loading is needed for each session',
 '首次访问局域网时，请在系统弹窗允许 Domino': 'Allow Domino in the system prompt when first accessing the LAN',
 '● 服务运行中 · 出网尚未检测': 'Service running; connectivity not checked',
 '检测未通过': 'Check failed',
 'HTTPS 检测': 'HTTPS check',
 '内网检测': 'LAN check',
 '未检测；按目标地址使用 domino doctor --url URL': 'Not checked; use domino doctor --url URL for a target',
 '  下一步：domino status 执行出网检查。': '  Next: run domino status to check connectivity.',
 '接口在线 · 出网未检测': 'API online; connectivity not checked',
 '配置操作已完成；配置应用不代表出网通过，使用 domino status 检查。': 'Profile operation completed; applying a profile does not verify connectivity. Check with domino status.',
 'Domino 请求': 'Domino request',
 '仅检查，不修改网络设置': 'Read-only; network settings stay unchanged',
 '内核解析': 'Core resolution',
 '失败阶段：{0}': 'Failure stage: {0}',
 '尚未安装本机运行环境；系统直连已单独检查，代理路径未检测。': 'Local runtime is not installed; the native path was checked separately and the proxy path was not checked.',
 '已收到 HTTPS 响应；HTTP 错误应检查目标服务或访问权限，不应直接判断为 DNS 或代理断网。': 'An HTTPS response was received. Check the target service or access permissions for HTTP errors; this alone does not indicate DNS or proxy failure.',
 '无凭据和查询参数的 HTTPS 地址；省略时检查默认公网地址': 'HTTPS URL without credentials or query parameters; defaults to a public connectivity target',
 '未能检查': 'Could not check',
 '未返回地址': 'No address returned',
 '检查时间': 'Checked at',
 '比较系统直连与代理 HTTPS，检查 DNS 和路由（不修改设置）': 'Compare native and proxy HTTPS, DNS and routing without changing settings',
 '用法：/doctor，或 /doctor https://example.com/。': 'Usage: /doctor or /doctor https://example.com/.',
 '目标地址': 'Target URL',
 '系统 hosts 包含目标，但内核未启用系统 hosts；请更新运行配置后重试。': 'System hosts contains the target, but the core does not have system hosts enabled; update the runtime configuration and retry.',
 '系统直连': 'Native path',
 '系统直连成功、代理请求失败；请结合 domino logs 确认是否命中 DIRECT，再检查 DNS、VPN 路由和程序权限。': 'The native path succeeded while the proxy failed. Check domino logs for DIRECT routing, then inspect DNS, VPN routes and application permissions.',
 '系统能解析目标，内核没有返回地址；请检查内核 DNS 与 VPN 的分流 DNS。': 'The system resolved the target but the core returned no address; check core DNS and VPN split DNS.',
 '系统解析': 'System resolution',
 '路由说明': 'Routing note',
 '连接诊断': 'Connection diagnosis',
 '诊断系统直连与代理，支持指定 HTTPS 地址': 'Diagnose native and proxy connectivity, optionally for a specific HTTPS URL',
 '内部 DNS 查询': 'Internal DNS query',
 '无 DNS 记录；系统 hosts 提供映射': 'No DNS record; system hosts supplies the mapping'}
