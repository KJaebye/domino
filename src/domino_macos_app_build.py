# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Local macOS compiler step; excluded from embedded remote management payloads."""
from domino_i18n import tr as _t
from contextlib import contextmanager
from pathlib import Path
import plistlib
import json
import platform
import socket
import shutil
import time
import re
import subprocess
import tempfile
from importlib import resources
from domino_macos_app import APP_NAME, EXECUTABLE, BUNDLE_ID

# The parent must remain alive: exec would replace its responsible code identity.
# No shell or proxy logic belongs here. Forward shutdown and reap exactly our child.
LAUNCHER_SOURCE = r'''/* SPDX-License-Identifier: GPL-3.0-only */
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>
#ifndef DOMINO_APPLICATION_ID
#define DOMINO_APPLICATION_ID "io.github.kjaebye.domino"
#endif
/* Distinct apps must not share the UUID of an otherwise identical launcher. */
__attribute__((used)) static const char domino_application_identity[] = DOMINO_APPLICATION_ID;
static volatile sig_atomic_t child_pid;
static void forward_signal(int number) {
    if (child_pid > 0) kill(child_pid, number);
}
int main(int argc, char **argv) {
    if (argc < 2 || argv[1][0] != '/') {
        fputs("Domino: absolute core path required\n", stderr); return 64;
    }
    sigset_t signals, previous;
    sigemptyset(&signals);
    sigaddset(&signals, SIGTERM); sigaddset(&signals, SIGINT); sigaddset(&signals, SIGHUP);
    if (sigprocmask(SIG_BLOCK, &signals, &previous) != 0) return 71;
    pid_t pid = fork();
    if (pid < 0) { perror("Domino fork"); return 71; }
    if (pid == 0) {
        sigprocmask(SIG_SETMASK, &previous, NULL);
        execv(argv[1], argv + 1);
        perror("Domino exec"); _exit(71);
    }
    child_pid = pid;
    struct sigaction action = {0}; action.sa_handler = forward_signal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL); sigaction(SIGHUP, &action, NULL);
    sigprocmask(SIG_SETMASK, &previous, NULL);
    int status;
    while (waitpid(pid, &status, 0) < 0) { if (errno != EINTR) return 71; }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
'''


@contextmanager
def prepared(ctx):
    # Check without launching the Command Line Tools installer implicitly.
    try:
        developer = subprocess.run(['/usr/bin/xcode-select', '-p'], capture_output=True, timeout=10)
        if developer.returncode:
            raise OSError('Command Line Tools unavailable')
    except (OSError, subprocess.SubprocessError):
        raise ctx.InstallError(_t('macOS 原生启动器需要 Xcode Command Line Tools；请运行 xcode-select --install 后重试，现有服务未修改。')) from None
    with tempfile.TemporaryDirectory(prefix='domino-native-app-') as directory:
        root = Path(directory)
        app = root / APP_NAME
        binary = app / EXECUTABLE
        binary.parent.mkdir(parents=True)
        source = root / 'launcher.c'
        source.write_text(LAUNCHER_SOURCE)
        icon = app / 'Contents/Resources/Domino.icns'
        icon.parent.mkdir()
        icon.write_bytes(resources.files('domino_assets').joinpath('Domino.icns').read_bytes())
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleExecutable': 'Domino', 'CFBundleIdentifier': BUNDLE_ID,
            'CFBundleName': 'Domino', 'CFBundleDisplayName': 'Domino',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
            'CFBundleIconFile': 'Domino.icns',
            'LSUIElement': True, 'DominoManaged': 1,
            'NSLocalNetworkUsageDescription':
                'Domino connects directly to local devices and services when a DIRECT rule matches.'}))
        try:
            subprocess.run(['/usr/bin/xcrun', 'clang', '-Os', '-Wall', '-Wextra', '-Werror',
                            '-DDOMINO_APPLICATION_ID=' + json.dumps(BUNDLE_ID),
                            '-mmacosx-version-min=11.0', str(source), '-o', str(binary)],
                           capture_output=True, check=True, timeout=60)
            load = subprocess.check_output(['/usr/bin/otool', '-l', str(binary)], text=True, timeout=10)
            uuids = re.findall(r'\buuid ([0-9A-Fa-f-]{36})', load)
            if not uuids or any(int(value.replace('-', ''), 16) == 0 for value in uuids):
                raise ValueError('Missing launcher UUID')
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier', BUNDLE_ID, str(app)],
                           capture_output=True, check=True, timeout=15)
            subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)],
                           capture_output=True, check=True, timeout=15)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ctx.InstallError(_t('macOS 原生启动器构建或签名校验失败，现有服务未修改。')) from None
        yield app


def setup_network_app(ctx):
    """Migrate an owned runtime in place; preserve core, data and proxy settings."""
    import domino_macos_app as native
    from domino_macos import owned, paths, state, snapshot, stop, start, restore
    owned(ctx)
    plist, _ = paths(ctx.HOME)
    if not plist.is_file() or not (ctx.APP / 'mihomo').is_file():
        raise ctx.InstallError(_t('尚未安装当前用户的 Domino 运行环境。'))
    value = plistlib.loads(plist.read_bytes())
    legacy = [str(ctx.APP / 'mihomo'), '-d', str(ctx.APP / 'data'), '-f', str(ctx.APP / 'data/config.json')]
    if value.get('ProgramArguments') not in [legacy, native.command(ctx.APP)]:
        raise ctx.InstallError(_t('LaunchAgent 启动参数与当前 Domino 不一致，未修改。'))
    with native.prepared(ctx) as app:
        active, _ = state(ctx.HOME)
        backup = snapshot(ctx, 'network-app', preserve_cli=True)
        try:
            stop(ctx.HOME)
            target = native.app_path(ctx.APP)
            if target.exists():
                native.register(ctx, ctx.APP, remove=True)
                shutil.rmtree(target)
            shutil.copytree(app, target)
            value['ProgramArguments'] = native.command(ctx.APP)
            value['AssociatedBundleIdentifiers'] = [native.BUNDLE_ID]
            ctx.write_private(plist, plistlib.dumps(value))
            native.register(ctx, ctx.APP)
            if active:
                start(ctx.HOME)
                for attempt in range(20):
                    try:
                        ctx.controller(ctx.APP / 'data', '/version', timeout=1)
                        break
                    except (OSError, ctx.InstallError):
                        if attempt == 19:
                            raise ctx.InstallError(_t('原生启动器启动后控制接口未就绪。')) from None
                        time.sleep(.25)
        except BaseException as failure:
            try:
                restore(ctx, backup)
            except BaseException:
                raise ctx.InstallError(_t('迁移失败且恢复未完成；备份：') + str(backup),
                                       code='RECOVERY_INCOMPLETE', effect='unknown') from None
            if isinstance(failure, KeyboardInterrupt):
                failure.domino_effect = 'rolled_back'
                raise
            raise ctx.InstallError(_t('迁移未完成，已恢复原状态；备份：') + str(backup),
                                   code='APPLY_ROLLED_BACK', effect='rolled_back') from None
        finally:
            vars(ctx).pop('_domino_registry_backup', None)
    print(_t('已为 Domino 注册原生启动器；内核、配置和系统代理设置保持原样。'))
    print(_t('请允许 Domino 的本地网络访问，然后使用 domino doctor 验证实际内网连接。'))
    print(_t('迁移前备份：') + backup.name)
    return backup



def install(ctx, bundle):
    from domino_macos import LABEL, owned, state, paths, snapshot, stop, start, restore, configure_environment
    owned(ctx)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
    if manifest.get('platform', 'linux') != 'darwin' or manifest.get('arch') != arch:
        raise ctx.InstallError(_t('安装包与本机 macOS 架构不一致。'))
    if manifest.get('schema') != 1:
        raise ctx.InstallError(_t('安装包格式不受支持。'))
    config = json.loads((bundle / 'data/config.json').read_text())
    ports = [manifest['proxy_port'], manifest['api_port']]
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or ports[0] == ports[1]:
        raise ctx.InstallError(_t('代理端口和控制端口无效。'))
    if config.get('mixed-port') != ports[0] or config.get('external-controller') != f'127.0.0.1:{ports[1]}' or config.get('allow-lan') or config.get('tun', {}).get('enable'):
        raise ctx.InstallError(_t('安装包的监听或 TUN 设置不符合预期。'))
    import domino_subscriptions
    domino_subscriptions.validate_install_registration(ctx, bundle)
    preserve_cli = bool(manifest.get('package_managed_cli')) or ctx.is_package_cli(ctx.HOME / '.local/bin/domino')
    if not preserve_cli and not ctx.owned_cli(ctx.HOME / '.local/bin/domino'):
        raise ctx.InstallError(_t('~/.local/bin/domino 已被其他程序使用。'))
    for name in ['.zshrc', '.bashrc', '.config/domino/proxy.env']:
        path = ctx.HOME / name
        if path.is_symlink():
            raise ctx.InstallError(_t('受管理的环境文件不能是符号链接。'))
        if path.exists() and name != '.config/domino/proxy.env':
            ctx.managed_block(path.read_text(), '')
    old_ports = set()
    if state(ctx.HOME)[0] and (ctx.APP / 'data/config.json').is_file():
        old = json.loads((ctx.APP / 'data/config.json').read_text())
        old_ports = {old['mixed-port'], int(old['external-controller'].rsplit(':', 1)[1])}
    for number in ports:
        if number not in old_ports:
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', number)) == 0:
                    raise ctx.InstallError(_t('端口 {0} 已被占用，请使用 --proxy-port / --api-port 选择空闲端口。', number))
    ctx.prepare_custom_rules(bundle / 'data')
    ctx.run([str(bundle / 'mihomo'), '-t', '-d', str(bundle / 'data'), '-f', str(bundle / 'data/config.json')],
            capture_output=True, text=True, timeout=60)
    pending = manifest.get('awaiting_subscription') and not (config.get('proxies') or config.get('proxy-providers'))
    shell_state = ctx.prepare_shell_policy(ctx.APP, ctx.HOME, system='darwin', shell_env=manifest['shell_env'], pending=pending)
    import domino_macos_app as native
    with native.prepared(ctx) as app:
        return _apply_install(ctx, bundle, manifest, ports, pending, shell_state, preserve_cli, app)


def _apply_install(ctx, bundle, manifest, ports, pending, shell_state, preserve_cli, native_app):
    from domino_macos import LABEL, owned, state, paths, snapshot, stop, start, restore, configure_environment
    import domino_macos_app as native
    import domino_subscriptions
    backup = snapshot(ctx, preserve_cli=True) if preserve_cli else snapshot(ctx)
    try:
        stop(ctx.HOME)
        if ctx.APP.exists():
            native.register(ctx, ctx.APP, remove=True)
            shutil.rmtree(ctx.APP)
        ctx.APP.mkdir(mode=0o700, parents=True)
        shutil.copy2(bundle / 'mihomo', ctx.APP / 'mihomo')
        (ctx.APP / 'mihomo').chmod(0o755)
        shutil.copytree(native_app, native.app_path(ctx.APP))
        shutil.copytree(bundle / 'data', ctx.APP / 'data')
        (ctx.APP / 'data/config.json').chmod(0o600)
        ctx.write_private(ctx.APP / 'manifest.json', json.dumps(manifest))
        ctx.install_cli(bundle, preserve_cli=preserve_cli)
        legacy_port = ctx.install_shell_policy(ctx.APP, shell_state)
        plist, logs = paths(ctx.HOME)
        logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = {'Label': LABEL, 'DominoManaged': 1,
                 'ProgramArguments': native.command(ctx.APP),
                 'AssociatedBundleIdentifiers': [native.BUNDLE_ID],
                 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 3,
                 'WorkingDirectory': str(ctx.APP / 'data'), 'Umask': 0o077,
                 'StandardOutPath': str(logs / 'mihomo.log'), 'StandardErrorPath': str(logs / 'mihomo.log')}
        ctx.write_private(plist, plistlib.dumps(value))
        native.register(ctx, ctx.APP)
        start(ctx.HOME)
        for attempt in range(20):
            try:
                ctx.controller(ctx.APP / 'data', '/version')
                break
            except (OSError,ctx.InstallError):
                if attempt == 19:
                    raise ctx.InstallError(_t('Domino 控制接口未就绪，请查看日志。'))
                time.sleep(.5)
        selections = json.loads((bundle / 'selections.json').read_text())
        for name, selected in selections.items():
            import urllib.parse
            ctx.controller(ctx.APP / 'data', '/proxies/' + urllib.parse.quote(name, safe=''), {'name': selected})
        health = None if pending else ctx.probe(ports[0], manifest['test_url'])
        if manifest['shell_env']:
            configure_environment(ctx, legacy_port=legacy_port)
        domino_subscriptions.register_installed(ctx, bundle)
    except BaseException as failure:
        try:
            restore(ctx, backup)
        except BaseException:
            raise ctx.InstallError(_t('安装失败且恢复未完成；备份：') + str(backup),code='RECOVERY_INCOMPLETE',effect='unknown') from None
        if isinstance(failure, KeyboardInterrupt):
            failure.domino_effect = 'rolled_back'
            raise
        raise ctx.InstallError(_t('安装未完成，已恢复原状态；备份：')+str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        vars(ctx).pop('_domino_registry_backup', None)
    print(_t('Domino 已独立运行；代理端口 {0}，控制端口 {1}；登录当前用户时自动启动。', ports[0], ports[1]))
    if health is None:
        print(_t('基础环境已就绪，待添加订阅：domino configs add "名称"；domino configs switch "名称"。'))
    else:
        print(_t('代理出网通过；出口地区：') + (health['exit_country'] or _t('未返回')))
    if manifest['shell_env']:
        print(_t('终端代理策略：') + (_t('已开启') if shell_state[0]['enabled'] else _t('已关闭')) + _t('；与系统代理独立，使用 domino shell on/off/status 管理。'))
        print(_t('已有终端请加载一次：. "$HOME/.config/domino/proxy.env"；Bash 登录配置需已加载 .bashrc。'))
        print(_t('其他已接入终端下次提示符同步；运行中的 VS Code 不会更新环境。'))
    print(_t('部署前备份：') + backup.name)
    print(_t('首次访问局域网时，请允许 Domino 的本地网络访问；也可在系统设置 → 隐私与安全性 → 本地网络中开启。'))
