# macOS DIRECT 内网连接失败排查（2026-11-18 更新）

**已在真实公司网络验证修复路径：由可被 macOS 识别且获得本地网络授权的原生应用启动器启动原来的 Mihomo，HTTPS 恢复为 200；内核字节无需修改。** 原裸内核 LaunchAgent 仍报 `no route to host`，补 UUID 的裸内核也失败。故障位于 macOS 对后台负责程序的身份识别与本地网络授权环节，不能归因于 DIRECT 规则、DNS 或 UUID 单一因素。

修复已写入工作区源码。当前 Mac 已安装本地源码快照，正式 `17897` 服务已迁移为原生启动器；用户已单独允许「Domino」访问本地网络。**2026-11-22 已在公司对正式应用完成 DIRECT 与重启技术验收；用户已确认重启后 GitLab 与 data-eval 的浏览器页面均正常，Mac 公司现场验收完成，Ubuntu 真机仍单独待验收。** 此次使用正式应用身份，不能与此前测试应用的结果混淆。家庭网络为什么没有触发同样现象，尚未单独解释。所有变更保持未发布。

## 2026-11-22 正式应用公司现场技术验收

使用已安装的 1.3.0 开发构建 `4354eab5fa6b`，管理 CLI、运行时快照与源码一致；目标均经公司 `en0` 路由。正常校验证书，不使用 `--insecure`，不跟随登录跳转，不读取浏览器登录凭据。

| 目标 | 重启前系统 / Domino | 重启后系统 / Domino，各三轮 |
| --- | --- | --- |
| GitLab | 302 / 302 | 均为 302 / 302 |
| data-eval | 200 / 200 | 均为 200 / 200 |

正式服务成功重启一次，公网代理重启前后均为 HTTPS 200。通过保持 TLS 连接并按客户端端口读取 Mihomo 连接元数据，确认重启前后两个目标实际命中 `IPCIDR / 10.42.30.0/24 / DIRECT`。两条公司规则均已加载；IP-CIDR 在域名后缀规则之前，因此本次不能声称命中了 `DomainSuffix`。

重启后的代理监听进程是正式原生启动器的 Mihomo 子进程。应用签名、UUID 和启动器未变，原内核 SHA-256 仍为 `a55a9073f9b7b1fa596a82c034d2dae3407ec34732102b6e42c5513ce3033f34`；配置、终端策略、加载脚本、配置库、LaunchAgent 文件、手动节点选择和系统代理设置均未变化。

另行启用真实 LAN 专项回归：使用正式 `Domino.app` 身份和原内核的独立副本，系统直连、普通子进程与临时 LaunchAgent 对同一目标均通过（1 项）。临时任务及内核副本已清理，未注册新的测试应用，正式服务 PID 不受该专项回归影响。

本机证据在 `dist/company-acceptance-20261122-200504/`，包括重启前后诊断、实际规则、独立回归和文件摘要对照。用户随后回复“两个都正常”，确认正式服务重启后 GitLab 与 data-eval 的浏览器页面均正常，Mac 公司现场验收完成；未据此扩大声称已验证登录后的业务操作。此次未重新运行全量回归、未安装或发布新版本。

## 当前收敛状态与回公司验证

- 正式应用：`~/.local/share/domino/Domino.app`，标识 `io.github.kjaebye.domino`，图标为用户提供的青绿色 DOM 标志。图标资源随 wheel 与独立运行包交付；已通过系统图标接口检查实际显示效果。
- 发现旧测试应用与首次正式启动器的 Mach-O UUID 同为 `AD337E98-2E82-30FE-A5B5-AC9E098EF182`。因此之前正式应用未单独列出、请求却成功，不能作为独立授权的证明。现将应用标识编入主程序，使不同标识获得不同 UUID，同标识重建保持稳定。正式应用当前 UUID 为 `DDC0C77D-C4F5-3519-BBBF-BF26E5452B3E`；用户已为这一身份授权。是否确实复用了旧权限属于推断。
- 修复重启时序：`launchctl bootout` 返回后，旧任务可能仍未完全退出；现在先等待卸载完成，再启动新任务，避免对正在退出的任务执行 `kickstart`。相关回归和真实服务重启均通过。
- 内核 SHA-256 仍为 `a55a9073f9b7b1fa596a82c034d2dae3407ec34732102b6e42c5513ce3033f34`；图标迁移前后配置 hash 和系统代理归属未变化。迁移备份：`20261118-135313-3f4bcf3e`。
- 当前公网检查与重启结果：`dist/macos-local-test/stabilization.json`；安装图标与签名检查：`applied-icon-update.json`；本轮最终回归和安装包检查见同目录收敛报告。
- Ubuntu 先前已完成 749 项回归，0 失败、0 错误、4 项 macOS 专属跳过；公司规则已应用并验证三次 200。此后增加了本轮 macOS 身份、图标和重启修复，Ubuntu 报告仍对应此前快照，不视为最新源码已在 Ubuntu 重跑。
- 不发布 PyPI、APT 或 Homebrew，不再变更正式内核或规则。Debian/Homebrew 收录工作保持暂停。

后续已连接公司网络时，可按以下命令复查：

```sh
cd /Users/kyhuang/ws/domino
domino doctor --url https://data-eval.seene-infra.com/ --json
domino doctor --url https://gitlab.seene-infra.com/ --json
```

预期 data-eval 的 `native.http_status` 和 `configured_proxy.http_status` 均为 200，且 `responsible_app.agent_uses_launcher` 为 true。GitLab 可能返回正常登录重定向 302。结合连接元数据确认命中公司 `DIRECT` 规则，以实际匹配类型为准；然后在浏览器确认页面和登录功能。执行 `domino restart` 后再次检查 data-eval，以验证授权持续生效。若原生请求失败，应先恢复公司网络，不能据此归因于 Domino。

如需恢复图标迁移前的服务：`domino rollback --backup 20261118-135313-3f4bcf3e`。该备份仍是迁移前原生启动器；更早的裸核心备份请按备份记录选择。

## 11 月 18 日公司网络复测

本机恢复 `10.42.30.149/24`，目标仍为 `10.42.30.223:443`，路由为 en0。原生 HTTPS 返回 200，原 Domino 服务 PID 19598 / 17897 的代理请求仍失败。所有实验正常校验证书，未替换已安装核心、修改系统代理或重置隐私权限。

报告：`dist/corporate-direct-20261118-095634/results.json`。同一最小配置、同一独立端口，按正序和逆序各运行一轮：

| 核心 | 普通子进程（两轮） | 临时 LaunchAgent（两轮） |
| --- | --- | --- |
| 原已安装核心，无 UUID | HTTPS 200 | HTTP 000，`no route to host` |
| 同源码重建，无 UUID | HTTPS 200 | HTTP 000，`no route to host` |
| 同源码重建，有 UUID | HTTPS 200 | HTTP 000，`no route to host` |
| `dist/macos-uuid/mihomo`，有 UUID | HTTPS 200 | HTTP 000，`no route to host` |

普通子进程 8/8 成功，LaunchAgent 0/8 成功。带 UUID 核心也保持 `Identifier=a.out`；系统日志显示 `Failed to find a.out using neagent` 和缓存 0 个 UUID。因此“文件存在 UUID”与“系统能找到负责程序并缓存其 UUID”是两回事。

补充实验（同目录 `network-probes.json`）：系统自带 `/usr/bin/curl` 在普通子进程和 LaunchAgent 中均为 HTTPS 200；独立 Swift `NWConnection` 探针连接相同 IP/端口，普通子进程 ready，LaunchAgent 明确得到 `Local network prohibited` / `NWPath.UnsatisfiedReason.localNetworkDenied`。此探针具有独立身份，不能将它的权限状态直接当作 Mihomo 的状态，但它验证了此环境中后台进程确实可能受该策略阻止。

仅对测试副本重新进行 ad-hoc 签名，分别保留 `a.out` 和改用独立标识符，两者的 LaunchAgent 仍失败；独立标识符也出现 `Failed to find ... using neagent`。报告：`dist/corporate-direct-20261118-100112/results.json`。不能把临时重签名作为已验证修复。

完整 app bundle、`NSLocalNetworkUsageDescription`、LaunchServices 注册和 LaunchAgent `AssociatedBundleIdentifiers` 使 nehelper 能为测试程序缓存 1 个 UUID。首次请求仍失败；用户在系统界面允许「Domino LAN Test」后，候选内核连续 3 次 HTTPS 200，重启后又 3 次 200。

进一步用保持存活的原生启动器作为 app 主程序，通过 `fork` / `execv` 启动**原来缺 UUID 的内核**，3 次请求均为 200。使用正式源码构建启动器后，再次得到重启前 3 次、重启后 3 次 HTTPS 200；原核心 SHA-256 始终保持 `a55a9073f9b7b1fa596a82c034d2dae3407ec34732102b6e42c5513ce3033f34`。这证明需要正确识别的是负责程序身份，不必通过修改后端内核来实现。

最后复制完整原配置至私有临时目录，保留 rule 模式、规则、provider 和选择，调整独立监听端口及控制端口、关闭 TUN 并开启 info 日志。访问目标连续 3 次 HTTPS 200，三条日志均明确显示 `match DomainSuffix(seene-infra.com) using DIRECT`。配置副本在测试后自动删除。初次测试因 JSON 默认转义 emoji 为代理对导致 YAML 解析失败；使用 `ensure_ascii=False` 后通过，该启动前错误不算网络失败。

以上报告位于 `dist/macos-lan-bundle-probe/`：`authorized-results.json`、`launcher-original-core-results.json`、`source-launcher-results.json`、`full-config-results.json` 和 `summary.json`。

## GitLab 可访问而 data-eval 失败的对照

2026-11-18 12:38，公司 DNS 为 `10.42.30.215`；`gitlab.seene-infra.com` 解析到同一个 `10.42.30.215`，`data-eval.seene-infra.com` 解析到 `10.42.30.223`。两个目标均经 en0 直达。本机正常证书校验的 HTTPS 对照如下：

| 请求路径 | GitLab | data-eval |
| --- | --- | --- |
| 绕过代理 | 302 | 200 |
| 当前正式 Domino 17897 | 302 | curl 35，HTTP 000 |
| 原核心、独立最小 direct 配置、普通子进程 | 302，日志 DIRECT | 200，日志 DIRECT |
| 相同原核心与配置、独立 LaunchAgent | 302，日志 DIRECT | `no route to host` |

报告：`dist/macos-company-two-host-comparison.json`、`dist/corporate-two-host-20261118-123835/results.json`。隔离实例已退出，没有调整正式服务、规则、DNS 或权限。

[Apple TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy) 明确说明：本地 DNS 服务器地址上的流量不要求本地网络访问权限。GitLab 地址恰好等于当前 DNS 地址，符合这一例外；这为两个同网段 HTTPS 目标在裸核心 LaunchAgent 中表现不同提供了有力解释。该结论是根据实测地址、启动方式对照和系统文档作出的推断，没有通过修改 DNS 来验证例外的因果性。强制 direct 仍出现相同差异，排除了两者只是规则选择不同的解释。

上述双域名对照时，正式服务尚未迁移，因此仍可复现原问题；最新安装状态见本文开头。

## 源码修复

- `domino_macos_app.py` 管理负责应用的标识、LaunchServices 注册及启动参数；`domino_macos_app_build.py` 构建原生启动器并执行本机安装/迁移。
- 应用位于运行目录的 `Domino.app`，标识为 `io.github.kjaebye.domino`，包含用途说明、非零 Mach-O UUID 和本机 ad-hoc 签名。上游 Mihomo 保留在原 `mihomo` 路径，既不重签也不修改。
- LaunchAgent 设置 `AssociatedBundleIdentifiers`，启动原生父进程；父进程保持存活、透传参数与退出状态、转发 SIGTERM/SIGINT/SIGHUP，并等待回收后端子进程。单纯 `exec` 替换主进程不符合此设计。
- 安装前完成构建和签名检查；现有快照包含应用。安装失败或回滚时重新注册恢复后的应用；卸载先停止进程，再撤销应用注册。兼容旧版直接启动内核的服务。
- 需要 Xcode Command Line Tools；缺失时提示 `xcode-select --install` 并在停止旧服务前失败。不会自动安装开发工具、修改系统隐私授权或使用 root 绕过本地网络控制。
- 本机编译和安装逻辑不放入 SSH 日常管理载荷，避免新增原生源码导致单参数长度超过系统边界；相关 Python 模块仍随 wheel 和独立 CLI 包交付。
- `doctor` 区分后端内核 UUID 与当前负责应用 UUID；不会因为后端缺 UUID 就断言原生启动器无效。

已用于当前环境的迁移工具：

```sh
.venv/bin/python scripts/repair_macos_network.py --apply
```

工具先备份，再替换自有 LaunchAgent 的启动方式；不改内核、规则、系统代理或 shell 策略。迁移后需允许 **Domino**，它与已允许的测试程序有不同标识。应配合包含本修复的 CLI 使用，以便新版卸载能够识别新的启动参数；旧 CLI 的启停仍使用相同服务名，但其卸载所有权校验不认识原生启动器。

需要撤回迁移时，使用工具输出的备份名，通过本源码的管理入口回滚：

```sh
PYTHONPATH=src .venv/bin/python src/install_domino.py rollback --backup <迁移前备份名>
```

长期公开分发仍应采用 Apple-issued 签名来可靠维护身份；当前本机构建的 ad-hoc 方案已在这台 Mac 验证，包括重新构建启动器后沿用授权，但未覆盖所有 macOS 版本、工具链升级或其他用户账户。此改动针对 macOS 的 Local Network 隐私机制，未修改 Ubuntu 的 systemd 启动方式。

公司 LAN 回归已通过，可显式指定已经由用户允许、已注册且保留在本机的测试应用：

```sh
PYTHONPATH=src DOMINO_TEST_CORE="$HOME/.local/share/domino/mihomo" \
DOMINO_TEST_LAN_URL=https://data-eval.seene-infra.com/ \
DOMINO_TEST_LAN_APP="$PWD/dist/macos-lan-bundle-probe/Domino LAN Test.app" \
.venv/bin/python -m unittest tests.test_macos_direct_integration -v
```

默认测试不申请系统隐私授权，也不把缺少公司网络的环境当成成功验证。

此前隔离验证：定向 154 项通过；带原核心、真实公司目标和已授权测试 app 的全量 `scripts/verify.py --require-core` 共 749 项，0 失败、0 错误，仅跳过 Linux GNOME 专用检查。报告保存在 `dist/macos-lan-bundle-probe/verification.json` 和 `verification.log`。临时 LaunchAgent、原生父进程和后端子进程均已退出；测试 app 保留注册供复现。当时原 PID 19598 仍监听 17897，核心 hash 未变，正式服务尚未迁移；最新状态见本文开头。

## 原版本实际调用链（以下保留排查历史）

- pip 入口 `domino_install.package_cli` → `domino_cli.main` → `manage`。
- `manage` 启动 `install_domino.py start`；后者调用 `service_action` → `domino_macos.service_action`。
- macOS `start` 查询 `gui/<uid>/local.domino.mihomo`；未加载则 `launchctl enable`、`bootstrap`，已加载则 `kickstart`。
- 安装时生成 `~/Library/LaunchAgents/local.domino.mihomo.plist`，直接执行 `~/.local/share/domino/mihomo -d <app>/data -f <app>/data/config.json`。
- LaunchAgent 设置 `RunAtLoad=True`、`KeepAlive=True`、`ThrottleInterval=3`、`Umask=077`，工作目录为 `<app>/data`，标准输出和错误写入 `~/Library/Logs/domino/mihomo.log`。
- 控制接口 `/version` 就绪后才调用 `system_proxy(..., 'on')`，开启 HTTP/HTTPS/SOCKS 系统代理；停止时先恢复仍由 Domino 接管的系统代理，然后 `bootout`。
- CLI 的 Python 子进程负责管理命令。macOS 核心本身由 launchd 启动；修改 CLI 的 `start_new_session` 不会改变这条核心启动链。
- `start` 不替换或更新核心。`prepare_source` 从 release 元数据选择核心，校验压缩包 SHA-256 后解压，macOS 安装使用 `shutil.copy2`；没有为核心补 UUID 或重新签名的逻辑。`init latest` 还可能复用匹配 manifest 且通过 hash 校验的缓存核心。

## 本机证据

macOS 26.5.2 (25F84)，Mihomo v1.19.34 darwin arm64 / Go 1.26.11。

核心 SHA-256：`a55a9073f9b7b1fa596a82c034d2dae3407ec34732102b6e42c5513ce3033f34`。

现有服务 PID 19598 / PPID 1，`launchctl print` 确认是 Domino LaunchAgent；监听 `127.0.0.1:17897`。系统代理 HTTP/HTTPS/SOCKS 均已开启并指向该端口。

目标 `https://data-eval.seene-infra.com/` → `10.42.30.223:443`，路由 `en0`。原生 HTTPS（正常校验证书）返回 200，现有 Domino 代理 curl exit 35，核心记录 `DIRECT ... no route to host`。

在独立空闲端口上使用同一个已安装二进制、同一个最小配置（direct 模式、关闭 TUN/DNS 服务），按顺序测试并清理每个实例。**系统代理全程保持开启**，没有停止现有 Domino 核心、改动系统代理、规则、接口绑定或隐私设置。

| 启动方式 | 结果 |
| --- | --- |
| Python Popen，父进程存活，普通会话 | 最终 HTTPS 200 |
| Python Popen，父进程存活，新会话 | 最终 HTTPS 200 |
| Python Popen，父进程退出，新会话，DEVNULL，最小 PATH 环境 | PID 21620 / PPID 1；最终 HTTPS 200，正常校验证书 |
| 独立临时 LaunchAgent，默认 ProcessType | curl exit 35；核心 DIRECT `no route to host` |
| 独立临时 LaunchAgent，ProcessType=Interactive | 同样失败 |

这排除了“系统代理开启必然失败”“脱离终端/PPID=1 必然失败”和“设置 Interactive 即可解决”等解释。交接资料还提供了完整原配置在 Terminal 成功的对照；此次隔离实验使用最小配置，未在现有 17897 端口上替换实例。

`otool -l ~/.local/share/domino/mihomo` 不含 `LC_UUID`。同一时间段的系统 `nehelper` 日志反复出现：

```text
Local network allowed by preference for mihomo (a.out), but received prompt. Clearing cached UUIDs and restarting session.
+[NEProcessInfo copyUUIDsForExecutable:]_block_invoke: failed to get UUIDs for /Users/kyhuang/.local/share/domino/mihomo
```

所以系统设置里显示 mihomo 允许访问本地网络，与本次失败并不矛盾。

Apple [TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy) 说明 Terminal/SSH 工具及其子进程自动获准访问本地网络，LaunchAgent 不享有 daemon 的豁免，并说明无 UUID 可导致本地网络权限异常。[TN3178](https://developer.apple.com/documentation/technotes/tn3178-checking-for-and-resolving-build-uuid-problems) 也要求 Mach-O 映像具有独立的 build UUID。

上游 [v1.19.34 Makefile](https://github.com/MetaCubeX/mihomo/blob/v1.19.34/Makefile) 使用 `-w -s -buildid=`。Go [linker 实现记录](https://go.googlesource.com/go/+/6a4feb56448aea1a0fe3485122d48fe7111958b1) 说明 Mach-O 默认从 Go build ID 派生 UUID。清空 build ID 是构建缺陷线索；11 月 18 日公司复测已证明仅保留 build ID 和 UUID 不足以恢复连接。

## 新增只读诊断

源码中运行（当前 pip 安装的 CLI 尚未更新）：

```sh
PYTHONPATH=src python3 src/domino_cli.py doctor \
  --url https://data-eval.seene-infra.com/ --json
```

安装包含本改动的版本后可直接 `domino doctor --url https://内网地址/ --json`。仅诊断自签证书时显式加 `--insecure`。

报告包括：核心版本/hash/UUID、LaunchAgent PID/PPID、系统代理归属、监听状态、DNS 地址/路由接口，以及原生和当前配置代理的最终 HTTPS 结果。UUID 检查不可用与确认缺失分别返回 `null` 和 `[]`。不会输出配置、订阅、curl 错误正文或响应内容；URL 禁止携带凭据、查询参数和 fragment。当前代理测试沿用已有规则，需结合 `domino logs` 确认 DIRECT，不能将代理成功一概当作 DIRECT 成功。

## 验证与下一步修复

```sh
PYTHONPATH=src python3 -m unittest tests.test_doctor tests.test_macos \
  tests.test_command_syntax tests.test_completion tests.test_macos_direct_integration
python3 scripts/verify.py
```

新增 macOS LAN 集成回归需要显式提供测试核心和同子网 HTTP(S) 地址。它先验证原生和普通子进程，再验证临时 LaunchAgent，使用随机服务名、临时目录和空闲端口，最终清理自己的服务；不修改现有代理。公司网络下原核心和目前仅补 UUID 的候选均会在最后一步失败；家庭网络下均成功。最终修复必须在公司网络通过：

```sh
PYTHONPATH=src DOMINO_TEST_CORE="$HOME/.local/share/domino/mihomo" \
DOMINO_TEST_LAN_URL=https://data-eval.seene-infra.com/ \
python3 -m unittest tests.test_macos_direct_integration
```

后续修复需要让 macOS 识别负责程序的稳定身份，并正常记录与应用本地网络授权。有效唯一 UUID 是构建要求之一，不能独立解决当前故障。若从上游源码构建，应保留 Go build ID，避免 `-buildid=`，核对 `otool -l` 输出；长期分发还需考虑 Apple-issued 签名。任何候选必须在同样的 LaunchAgent 环境下通过真实公司目标回归；不能用随机重新签名代替验证。

临时使用 Terminal 启动同一核心已有成功证据。切换前先保存 `scutil --proxy`，执行 `domino stop` 并确认 17897 无监听，再前台执行该核心；此时通过显式 `curl --proxy` 测试。需要浏览器时可在另一个终端执行 `domino proxy on`，退出前台核心前执行 `domino proxy off` 恢复设置。恢复原服务需先退出前台核心，再 `domino start`。这些切换操作本次未执行。

本改动增加诊断、回归和独立构建工具，没有部署、替换或重签已安装的核心；原后台 DIRECT 故障尚未证实消除。撤回诊断代码不会改变任何系统代理、权限或核心文件。后续替换核心前应保留原二进制和 plist，停止 Domino 后替换，通过回归再恢复系统代理；失败时停止新核心并还原原文件。

### 本次测试结果

- 定向验证 80 项通过（包括诊断、macOS 生命周期、CLI/补全和 SSH 内存加载）。
- 使用仓库虚拟环境 `.venv/bin/python scripts/verify.py`：共 738 项，0 失败、4 项跳过。系统 `python3` 缺少 prompt-toolkit，首次验证失败；拆分诊断模块也修复了此次改动触发的 SSH 内嵌长度边界问题。
- 单独启用真实 LAN 回归：原生及普通子进程 HTTPS 均成功，LaunchAgent curl exit 35，断言失败，确认现有核心故障仍存在。这是未修复核心的已知失败，默认测试不会依赖公司网络。
- 最终复核：原 Domino PID 19598 仍独占监听 17897，系统代理仍指向该端口；临时测试实例均已退出。

## 离开公司网络后的模拟与构建

用户确认已离开公司网络，本机 `en0` 变为 `192.168.1.4`。公司目标的原生 HTTPS 也超时，因此此时不能用它判断核心是否修复。

已用相同 Go 1.26.11、相同 Mihomo v1.19.34 源码构建两份对照产物，分别保留 Go build ID（显式 `-B gobuildid`）与清空 build ID（`-buildid=`）。前者具有 `LC_UUID`，后者不含 `LC_UUID`，两者均未替换已安装核心。

在本机局域网地址搭建临时 HTTPS 服务时，两份核心通过临时 LaunchAgent 均返回 200。这说明访问本机自身地址没有复现此前对另一台内网设备的权限故障，不能据此认定无 UUID 没有影响，也不能认定修复成功。

新增离线模拟 `tests/test_macos_direct_simulation.py`：

- 临时生成 TLS 证书，以 `--cacert` 正常校验；验证原生、普通子进程、LaunchAgent 的完整 HTTPS 响应正文与 HTTP 200。
- 使用 `IP-CIDR,...,DIRECT` 加 `MATCH,REJECT`，确保测试依赖 DIRECT 规则。
- 通过保留一个不监听的目标端口模拟远端 TCP 失败，验证代理请求不能因为 CONNECT 被接受而报告 HTTPS 成功。
- 全部使用临时目录、随机服务名、空闲端口，不访问公司网络或修改系统代理。

```sh
PYTHONPATH=src DOMINO_TEST_CORE="$PWD/dist/macos-uuid/mihomo" \
.venv/bin/python -m unittest tests.test_macos_direct_simulation
```

两份对照核心分别执行上述离线模拟，均为 2 项通过。这是连接流程与测试工具的验证，不是 macOS 真实局域网权限的验证。

构建工具 `scripts/build_macos_core.py` 从用户指定的可信源码构建，保留 Go build ID，检查非零 Mach-O UUID 和签名完整性，拒绝覆盖已有输出，不安装核心、不重新签名。

```sh
python3 scripts/build_macos_core.py --source /path/to/mihomo-v1.19.34 \
  --version v1.19.34 --go /path/to/go --output dist/macos-uuid/mihomo
```

已准备的候选核心：`dist/macos-uuid/mihomo`。构建来源、工具链、源码压缩包 hash、二进制 hash、UUID 记录在 `dist/macos-uuid/build.json`，同目录附上上游许可证。它标记为 `v1.19.34-domino-uuid`，与官方预编译产物明确区分。

离线模拟进一步显式检查了 curl 的 `http_connect`：正常 HTTPS 为目标 HTTP 200 / CONNECT 200；远端 TCP 失败为目标 HTTP 000 / CONNECT 200，防止误判隧道握手结果。使用最终候选核心的模拟与 doctor 共 6 项测试通过。包含真实核心的全量验证 `.venv/bin/python scripts/verify.py --require-core` 共 740 项，0 失败、2 项跳过。

用户另提供一台同局域网 Mac（`192.168.1.3`）作为真实 LAN 测试目标，待启动固定响应服务。LAN 回归已支持 HTTP 或 HTTPS；HTTP 足以测试 TCP 建连阶段的本地网络权限，TLS 行为由独立的 HTTPS 模拟覆盖。测试命令示例：

```sh
PYTHONPATH=src DOMINO_TEST_CORE="$PWD/dist/macos-uuid/mihomo" \
DOMINO_TEST_LAN_URL=http://192.168.1.3:18080/ \
.venv/bin/python -m unittest tests.test_macos_direct_integration
```

## 真实家庭局域网对照：新证据修正结论

用户已在另一台 Mac 的 `192.168.1.3:18080` 启动测试服务。本机原生 curl 和 nc 能建立 TCP 连接，但 HTTP 请求未收到响应而超时。

在保留系统代理和现有核心的情况下，按顺序用独立端口/临时 LaunchAgent 测试，并用 `lsof -a -p <core-pid> -iTCP@192.168.1.3:18080` 检查核心自身的远端连接：

| 核心 | 普通子进程 TCP ESTABLISHED | 临时 LaunchAgent TCP ESTABLISHED |
| --- | --- | --- |
| 原已安装核心（无 UUID） | 是 | 是 |
| 同版本重建核心（无 UUID） | 是 | 单次未观测到；核心日志 i/o timeout |
| 同版本重建核心（有 UUID） | 是 | 是 |

各组 HTTP 请求均超时；原核心 LaunchAgent 日志显示 `using DIRECT`，没有公司网络下的 `no route to host`。本轮 nehelper 日志未出现原来的 UUID 错误。测试服务当前未能正常响应，单次超时不能归因于本地网络权限。

这组结果说明：缺失 UUID 并不在所有网络环境中必然导致故障；此前不能将它写成已经证实的单一根因。需要服务正常响应后重复对照，并在公司网络再次比较相同源码的两份核心，才可确认 UUID 的因果作用。已请用户把临时服务切换为多线程并明确响应长度的版本。

用户重启为多线程服务后，原生请求仍然已连接但没有 HTTP 响应。额外用原始 Python socket 发出完整 HTTP/1.0 GET，`netstat` 显示 ESTABLISHED、Send-Q 为 0，接收仍超时。本机 Application Firewall 为 disabled。已请求用户在远端本机运行 `curl http://127.0.0.1:18080/` 并查看监听进程，以先确认测试服务自身可用；不能把这个原生请求也失败的场景算成 Domino 回归失败。

用户在远端本机验证 `127.0.0.1:18080` 返回 HTTP/1.0 200、Content-Length 19 和固定文本，`python3.9` PID 98399 监听 `*:18080`。因此服务至少在回环地址正常。本机工具进程跨机器请求仍超时。下一步需对比当前 Mac 的普通 Terminal 请求（排除工具进程上下文差异），以及远端通过自己的 LAN 地址访问和远端防火墙只读状态；尚不能把无响应归因于服务实现。

进一步对照：用户从当前 Mac 的普通 Terminal 发起请求也超时，排除了仅由工具进程上下文造成无响应的解释。远端访问自己的 `192.168.1.3:18080` 也超时，但回环地址成功；远端 Application Firewall 为 enabled，block-all 为 disabled。当前测试障碍已缩小到远端非回环访问路径，防火墙中测试 Python 的入站规则需要进一步核查（尚未修改防火墙）。

## 家庭真实 LAN 最终结果：四份核心全部通过

远端防火墙列表中已有允许 `/usr/bin/python3` 的规则，但最初运行的 `python3.9` 服务实际解释器路径未确认。未修改任何防火墙规则；用户改用明确的 `/usr/bin/python3 -m http.server`、绑定 `0.0.0.0:18080`，只提供临时目录里的测试文件后，跨机器原生请求立即返回固定文本和 HTTP 200。先前测试服务的非回环访问障碍与解释器/入站规则匹配有关，未进一步确认原解释器的具体阻断规则。

在服务正常后，将原已安装核心、同源码清空 build ID 的核心、同源码保留 UUID 的核心、最终候选核心，按正序和反序各验证一次。每次回归均依次检查原生 HTTP、普通子进程 DIRECT、临时 LaunchAgent DIRECT：

| 核心 | 正序 | 反序 |
| --- | --- | --- |
| 原已安装核心，无 UUID | 全部 HTTP 200 | 全部 HTTP 200 |
| 同版本重建，无 UUID | 全部 HTTP 200 | 全部 HTTP 200 |
| 同版本重建，有 UUID | 全部 HTTP 200 | 全部 HTTP 200 |
| 最终候选，有 UUID | 全部 HTTP 200 | 全部 HTTP 200 |

另外直接通过当前运行的 `127.0.0.1:17897` 请求该目标，也返回固定文本和 HTTP 200；原服务 PID 19598 保持运行。未更换已安装核心、未修改系统代理、分流或隐私设置。逐次结果在 `dist/macos-uuid/lan-regression-results.json`。

最终结论：家庭网络未复现公司故障，缺 UUID 不是在所有 LAN 环境下都导致失败的条件。公司故障中的 nehelper UUID 错误仍需解释，但现有证据不足以将它认定为单一根因，也不足以将带 UUID 的构建部署为已验证修复。候选核心保留为后续受控实验产物。

下次回到公司网络时，先确认原生目标请求成功，再使用相同测试框架比较原核心、同源码无 UUID 核心和有 UUID 核心；同时保留各自核心日志、nehelper 日志、路由和系统代理状态。若仅有 UUID 核心成功，才建立这条构建差异与故障的因果证据；若全部失败或全部成功，应据当时网络/权限状态继续排查，避免改动无关 DNS 或规则。

最终全量验证（候选真实核心 + 家庭 LAN 目标）：

```sh
DOMINO_TEST_CORE="$PWD/dist/macos-uuid/mihomo" \
DOMINO_TEST_LAN_URL=http://192.168.1.3:18080/ \
.venv/bin/python scripts/verify.py --require-core
```

结果：共 740 项测试，0 失败、1 项跳过，耗时 93.855 秒。`git diff --check` 通过。复核仅原 Domino 核心 PID 19598 运行并监听 17897，临时实例均已清理。远端临时服务由用户启动，测试已结束，可在该 SSH 窗口按 Ctrl+C 关闭。
