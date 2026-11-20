#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Target-side installer and management runtime. No credential values in output."""
from __future__ import annotations
from domino_i18n import tr as _t

import argparse
from contextlib import ExitStack, contextmanager, nullcontext, redirect_stdout
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import unicodedata

HOME = Path.home()
APP = HOME / '.local/share/domino'
BACKUPS = HOME / '.local/share/domino-backups'
SERVICE = Path('/etc/systemd/system/domino.service')
MARKER = '# Managed by domino'
BEGIN = '# BEGIN domino proxy'
END = '# END domino proxy'
ENV_FILES = ['.bashrc', '.zshrc', '.vscode-server/server-env-setup', '.config/domino/proxy.env']
LEGACY_APP = HOME / '.local/share/robot-clash'
LEGACY_BACKUPS = HOME / '.local/share/robot-clash-backups'
LEGACY_SERVICE = Path('/etc/systemd/system/robot-clash.service')
LEGACY_MARKER = '# Managed by robot_clash.py'
LEGACY_BEGIN = '# BEGIN robot-clash proxy'
LEGACY_END = '# END robot-clash proxy'
LEGACY_ENV_FILES = ENV_FILES[:-1] + ['.config/robot-clash/proxy.env']
DEFAULT_TEST = 'https://www.cloudflare.com/cdn-cgi/trace'
CLI_MARKER = '# Managed by Domino CLI'


try:
    from domino_model import DomainError
except ModuleNotFoundError:
    sys.path.insert(0,str(Path(__file__).parent/'cli' if '__file__' in globals() else APP/'cli'))
    from domino_model import DomainError


class InstallError(DomainError):
    pass


@contextmanager
def legacy_layout():
    """Use the old layout only while backing up or restoring an existing deployment."""
    global APP, BACKUPS, SERVICE, MARKER, BEGIN, END, ENV_FILES
    current = APP, BACKUPS, SERVICE, MARKER, BEGIN, END, ENV_FILES
    APP, BACKUPS, SERVICE = LEGACY_APP, LEGACY_BACKUPS, LEGACY_SERVICE
    MARKER, BEGIN, END, ENV_FILES = LEGACY_MARKER, LEGACY_BEGIN, LEGACY_END, LEGACY_ENV_FILES
    try:
        yield
    finally:
        APP, BACKUPS, SERVICE, MARKER, BEGIN, END, ENV_FILES = current


def current_installation():
    if not (APP / 'data/config.json').is_file() and (LEGACY_APP / 'data/config.json').is_file():
        return LEGACY_APP, LEGACY_SERVICE
    return APP, SERVICE


@contextmanager
def deployment_lock():
    import fcntl
    path = HOME / '.local/share/domino.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    # Also honor an existing old lock so an older client cannot deploy concurrently.
    paths = [path]
    old_lock = HOME / '.local/share/robot-clash.lock'
    if old_lock.exists():
        paths.append(old_lock)
    with ExitStack() as stack:
        for lock_path in paths:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            os.fchmod(fd, 0o600)
            handle = stack.enter_context(os.fdopen(fd, 'a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstallError(_t('目标已有另一个修改操作在执行，请稍后重试。'),code='LOCKED',exit_code=6,retryable=True) from None
        yield


def run(args, *, stage=None, **kwargs):
    stage = stage or _t('远端步骤')
    try:
        return subprocess.run(args, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        if args[:3]==['sudo','-n','-v']:
            raise InstallError(_t('需要预先授权 sudo；机器接口不会询问密码。'),code='AUTH_REQUIRED',exit_code=4) from None
        raise InstallError(_t('{0}失败（退出码 {1}）。', stage, exc.returncode),
                           code='CONFIG_VALIDATION_FAILED' if stage == _t('本机配置校验') else 'OPERATION_FAILED') from None
    except subprocess.TimeoutExpired:
        raise InstallError(_t('{0}超时。', stage),
                           code='CONFIG_VALIDATION_TIMEOUT' if stage == _t('本机配置校验') else 'OPERATION_FAILED') from None


def write_private(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(text.encode() if isinstance(text, str) else text)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def managed_block(old, body):
    for begin, end in dict.fromkeys([(BEGIN, END), (LEGACY_BEGIN, LEGACY_END)]):
        if old.count(begin) != old.count(end) or old.count(begin) > 1:
            raise InstallError(_t('代理环境标记不完整，停止修改启动文件。'))
        if begin in old:
            start = old.index(begin)
            if old.index(end) < start:
                raise InstallError(_t('代理环境标记顺序无效。'))
            finish = old.index(end, start) + len(end)
            old = old[:start] + old[finish:].lstrip('\n')
    header = ''
    if old.startswith('#!'):
        header, _, old = old.partition('\n')
        header += '\n'
    return header + f'{BEGIN}\n{body}\n{END}\n' + old


def vscode_target(argv, home):
    prefix = str(home / '.vscode-server') + '/'
    if not argv or not any(a.startswith(prefix) for a in argv):
        return False
    return (any(a.endswith('/out/server-main.js') or a.endswith('/server/bin/code-server') for a in argv)
            or ('command-shell' in argv and argv[0].startswith(prefix))
            or ('app-server' in argv and argv[0].startswith(prefix + 'extensions/openai.chatgpt-')))


def restart_vscode():
    stopped = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = [a.decode(errors='replace') for a in (entry / 'cmdline').read_bytes().split(b'\0') if a]
            if vscode_target(argv, HOME):
                os.kill(int(entry.name), signal.SIGTERM)
                stopped.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    for _ in range(10):
        remaining = []
        for pid in stopped:
            try:
                argv = [a.decode(errors='replace') for a in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if a]
                if vscode_target(argv, HOME):
                    remaining.append(pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        if not remaining:
            print(_t('VS Code/Codex 旧进程已退出，PID：') + str(stopped))
            return
        time.sleep(0.5)
    raise InstallError(_t('代理已部署，但旧 VS Code 进程未退出；未强制终止：') + str(remaining))


def systemctl(action, service=None):
    if sys.platform == 'darwin':
        import domino_macos
        active, enabled = domino_macos.state(HOME)
        return active if action == 'is-active' else enabled if action == 'is-enabled' else False
    return subprocess.run(['systemctl', action, (service or SERVICE).name], capture_output=True, text=True).returncode == 0


def sudo(*args):
    return run(['sudo', '-n', *args], capture_output=True, text=True)


def owned_service():
    if SERVICE.is_symlink() or (SERVICE.exists() and MARKER not in SERVICE.read_text()):
        raise InstallError(_t('同名服务不是本工具管理的，停止以免覆盖。'))


def owned_installations():
    for legacy in (False, True):
        if legacy:
            with legacy_layout():
                owned_service()
        else:
            owned_service()
    if APP.is_symlink() or LEGACY_APP.is_symlink():
        raise InstallError(_t('安装目录是符号链接，停止。'))


def controller(data, route, payload=None, *, method=None, timeout=3):
    config = json.loads((data / 'config.json').read_text())
    address = config.get('external-controller', '')
    if not re.fullmatch(r'127\.0\.0\.1:\d+', address):
        raise InstallError(_t('控制接口地址不是预期的回环地址。'))
    request = urllib.request.Request(
        'http://' + address + route,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + config['secret'], 'Content-Type': 'application/json'},
        method=method or ('PUT' if payload is not None else 'GET'))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    writing=request.get_method() not in ['GET','HEAD']
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        code,exit_code=('AUTH_REQUIRED',4) if error.code in [401,403] else ('RESOURCE_NOT_FOUND',3) if error.code==404 else ('CONTROLLER_REJECTED',8)
        raise InstallError(_t('控制接口拒绝请求。'),code=code,exit_code=exit_code,details={'http_status':error.code}) from None
    except (TimeoutError,urllib.error.URLError) as error:
        timeout_error=isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError)
        raise InstallError(_t('控制接口请求超时。') if timeout_error else _t('无法连接控制接口。'),
            code='TIMEOUT' if timeout_error else 'CONTROLLER_UNREACHABLE',exit_code=7 if timeout_error else 5,
            retryable=True,effect='unknown' if writing else 'none') from None


def probe(proxy_port, url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise InstallError(_t('出网检查 URL 无效。'))
    result = run(['curl', '--noproxy', '', '--proxy', f'http://127.0.0.1:{proxy_port}',
                  '--fail', '--silent', '--show-error', '--connect-timeout', '8',
                  '--max-time', '25', '--proto', '=https', '--config', '-'],
                 input='url = ' + json.dumps(url) + '\n', capture_output=True, text=True, timeout=30)
    country = next((s[4:] for s in result.stdout.splitlines() if re.fullmatch(r'loc=[A-Z]{2}', s)), None)
    return {'healthy': True, 'exit_country': country}


def _snapshot(kind='deploy', backup=None, *, preserve_cli=False):
    if backup is None:
        BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
        BACKUPS.chmod(0o700)
        backup = BACKUPS / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(mode=0o700)
    state = {'schema': 1, 'kind': kind, 'created_ns': time.time_ns(), 'was_active': systemctl('is-active'),
             'was_enabled': systemctl('is-enabled'), 'had_app': APP.exists(),
             'had_unit': SERVICE.exists(), 'files': {}}
    if APP.exists():
        shutil.copytree(APP, backup / 'app', symlinks=True)
    if SERVICE.exists():
        write_private(backup / 'service', SERVICE.read_bytes())
    for i, name in enumerate(ENV_FILES):
        path = HOME / name
        if path.is_symlink():
            raise InstallError(_t('受管理的环境文件是符号链接，未覆盖。'))
        state['files'][name] = {'exists': path.exists()}
        if path.exists():
            mode = path.stat().st_mode & 0o777
            write_private(backup / f'file-{i}', path.read_bytes(), mode)
            state['files'][name]['mode'] = mode
    cli = HOME / '.local/bin/domino'
    state['cli_file'] = {'exists': cli.exists(), 'preserved': preserve_cli}
    if cli.exists() and not preserve_cli:
        state['cli_file']['mode'] = cli.stat().st_mode & 0o777
        write_private(backup / 'cli-launcher', cli.read_bytes(), state['cli_file']['mode'])
    write_private(backup / 'snapshot.json', json.dumps(state))
    return backup


def snapshot(kind='deploy', *, preserve_cli=False):
    backup = _snapshot(kind, preserve_cli=True) if preserve_cli else _snapshot(kind)
    # Publish only after both installation layouts and the external registry are captured.
    pending = backup / 'snapshot.pending'
    (backup / 'snapshot.json').rename(pending)
    with legacy_layout():
        _snapshot(kind, backup / 'legacy', preserve_cli=True) if preserve_cli else _snapshot(kind, backup / 'legacy')
    import domino_subscriptions
    domino_subscriptions.snapshot_registry(sys.modules[__name__], backup)
    pending.rename(backup / 'snapshot.json')
    return backup


def _restore(backup):
    state = json.loads((backup / 'snapshot.json').read_text())
    if state.get('schema') != 1 or set(state['files']) != set(ENV_FILES):
        raise InstallError(_t('备份格式无效，未恢复。'))
    owned_service()
    # Restore the whole user-level app and environment, including first-install failure.
    if SERVICE.exists():
        sudo('systemctl', 'stop', SERVICE.name)
    if APP.exists():
        if APP.is_symlink():
            raise InstallError(_t('安装目录是符号链接，停止恢复。'))
        shutil.rmtree(APP)
    if state['had_app']:
        shutil.copytree(backup / 'app', APP, symlinks=True)
    for i, name in enumerate(ENV_FILES):
        item = state['files'][name]
        path = HOME / name
        if item['exists']:
            write_private(path, (backup / f'file-{i}').read_bytes(), item['mode'])
        elif path.exists():
            path.unlink()
    cli = HOME / '.local/bin/domino'
    if 'cli_file' in state:
        item = state['cli_file']
        if item.get('preserved'):
            pass
        elif item['exists']:
            write_private(cli, (backup / 'cli-launcher').read_bytes(), item['mode'])
        elif cli.exists():
            cli.unlink()
    elif cli.is_file() and CLI_MARKER in cli.read_text():
        cli.unlink()
    if SERVICE.exists():
        sudo('systemctl', 'disable', SERVICE.name)
    if state['had_unit']:
        sudo('install', '-m', '644', str(backup / 'service'), str(SERVICE))
    else:
        sudo('rm', '-f', str(SERVICE))
    sudo('systemctl', 'daemon-reload')
    if state['had_unit']:
        sudo('systemctl', 'enable' if state['was_enabled'] else 'disable', SERVICE.name)
        if state['was_active']:
            sudo('systemctl', 'start', SERVICE.name)


def restore(backup):
    # Neither recovery domain may prevent the other from being attempted.
    failures = []
    try:
        _restore_installations(backup)
    except BaseException as exc:
        failures.append(exc)
    try:
        import domino_subscriptions
        domino_subscriptions.restore_registry(sys.modules[__name__], backup)
    except BaseException as exc:
        failures.append(exc)
    if failures:
        raise InstallError(_t('恢复未完成；保留的完整备份：') + str(backup),
                           code='RECOVERY_INCOMPLETE', effect='unknown') from None


def _restore_installations(backup):
    owned_installations()
    state = json.loads((backup / 'snapshot.json').read_text())
    expected_files = LEGACY_ENV_FILES if backup.parent == LEGACY_BACKUPS else ENV_FILES
    if state.get('schema') != 1 or set(state['files']) != set(expected_files):
        raise InstallError(_t('备份格式无效，未恢复。'))
    # Stop both names before starting either restored service to release their ports.
    for service in (SERVICE, LEGACY_SERVICE):
        if service.exists():
            sudo('systemctl', 'stop', service.name)
    if backup.parent == LEGACY_BACKUPS:
        # Historical backups use schema 1 and the old environment-file layout.
        if SERVICE.exists():
            sudo('systemctl', 'disable', SERVICE.name)
            sudo('rm', '-f', str(SERVICE))
        if APP.exists():
            shutil.rmtree(APP)
        (HOME / ENV_FILES[-1]).unlink(missing_ok=True)
        with legacy_layout():
            _restore(backup)
    else:
        _restore(backup)
        if (backup / 'legacy/snapshot.json').is_file():
            with legacy_layout():
                _restore(backup / 'legacy')


def unit_text(user, group):
    # Literal systemd substitutions, quotes, and control chars must not be interpreted.
    if any(c in user + group + str(APP) for c in ['\n', '\r', '"', '%', '\\']):
        raise InstallError(_t('用户或目录名称不适合自动生成 systemd 服务。'))
    return f'''{MARKER}
[Unit]
Description=Standalone Mihomo proxy managed by Domino
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={user}
Group={group}
ExecStart="{APP}/mihomo" -d "{APP}/data" -f "{APP}/data/config.json"
Restart=on-failure
RestartSec=3
LimitNOFILE=65536
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
'''


def configure_cli_path(home):
    names = ['.bashrc'] if sys.platform == 'linux' else ['.zshrc']
    for name in names:
        path = home / name
        old = path.read_text() if path.exists() else ''
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        write_private(path, managed_block(old, 'export PATH="$HOME/.local/bin:$PATH"'), mode)


def prepare_shell_policy(app, home, *, system, shell_env=True, pending=False):
    """Read migration state before replacing APP; never execute the old env file."""
    import domino_shell
    path = home / '.config/domino/proxy.env'
    text = path.read_text() if path.is_file() else ''
    if not text and system == 'linux':
        legacy_path = home / '.config/robot-clash/proxy.env'
        text = legacy_path.read_text() if legacy_path.is_file() else ''
    legacy = domino_shell.legacy_environment_port(text, system)
    migrate_enabled = system == 'linux' and legacy is not None and not pending
    if legacy is None and text.startswith('# Managed by Domino shell integration v1\n'):
        marker = re.search(r'^# Legacy proxy port: (\d+)$', text, re.M)
        if marker and 1024 <= int(marker[1]) <= 65535:
            legacy = int(marker[1])
    policy = domino_shell.read_policy(app)
    if not (app / 'shell-policy.json').exists():
        policy = {'version': 1, 'enabled': migrate_enabled} if shell_env else None
    previous = app / 'shell-env.previous'
    customized = text if text and legacy is None and not text.startswith('# Managed by Domino shell integration v1') else None
    saved = customized if customized is not None else previous.read_text() if previous.is_file() else None
    return policy, legacy, saved


def install_shell_policy(app, state):
    policy, legacy, saved = state
    if policy is not None:
        write_private(app / 'shell-policy.json', json.dumps(policy))
    if saved is not None:
        write_private(app / 'shell-env.previous', saved)
    return legacy


def configure_shell_environment(app, home, *, linux=False, legacy_port=None):
    import domino_shell
    write_private(home / '.config/domino/proxy.env', domino_shell.integration(app, ['/usr/bin/env', 'python3'], legacy_port))
    body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
    # Follow the supported platform default without changing the login shell.
    # Existing integration in another shell is preserved for previous users.
    names = ['.bashrc'] if linux else ['.zshrc']
    if linux:
        names.append('.vscode-server/server-env-setup')
    for name in names:
        path = home / name
        old = path.read_text() if path.exists() else ('#!/bin/sh\n' if name.endswith('server-env-setup') else '')
        mode = path.stat().st_mode & 0o777 if path.exists() else (0o700 if name.endswith('server-env-setup') else 0o600)
        write_private(path, managed_block(old, body), mode)


def configure_environment(proxy_port, *, legacy_port=None):
    configure_shell_environment(APP, HOME, linux=True, legacy_port=legacy_port)


def install_cli(bundle, *, preserve_cli=False):
    if not (bundle / 'cli').is_dir():
        return
    shutil.copytree(bundle / 'cli', APP / 'cli')
    if preserve_cli or json.loads((bundle / 'manifest.json').read_text()).get('package_managed_cli'):
        return
    launcher = f'''#!/usr/bin/env python3
{CLI_MARKER}
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path.home() / '.local/share/domino/cli'))
runpy.run_module('domino_cli', run_name='__main__')
'''
    write_private(HOME / '.local/bin/domino', launcher, 0o700)


def is_package_cli(path):
    """Recognize console scripts without executing them or replacing their links."""
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            return False
        text = path.read_text()
    except (OSError, UnicodeError, RuntimeError):
        return False
    if CLI_MARKER in text:
        return False
    for module, entry in [('domino_install', 'package_cli'), ('domino_cli', 'main')]:
        if ('from ' + module + ' import ' + entry in text
                and any(call + '(' + entry + '())' in text for call in ('sys.exit', 'SystemExit'))):
            return True
    return False


def owned_cli(path):
    if is_package_cli(path):
        return True
    if path.is_symlink():
        return False
    if not path.exists():
        return True
    try:
        return path.is_file() and path.stat().st_size <= 64 * 1024 and CLI_MARKER in path.read_text()
    except (OSError, UnicodeError):
        return False


def install(bundle):
    if os.getuid() == 0:
        raise InstallError(_t('请用普通 SSH 用户部署，脚本只为系统服务步骤调用 sudo。'))
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('schema') != 1:
        raise InstallError(_t('安装包版本不受支持。'))
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}.get(platform.machine())
    if arch != manifest.get('arch'):
        raise InstallError(_t('安装包架构与目标设备不一致。'))
    proxy_port, api_port = manifest['proxy_port'], manifest['api_port']
    if any(not isinstance(p, int) or isinstance(p, bool) or not 1024 <= p <= 65535 for p in [proxy_port, api_port]) or proxy_port == api_port:
        raise InstallError(_t('安装包端口配置无效。'))
    config = json.loads((bundle / 'data/config.json').read_text())
    if (config.get('mixed-port') != proxy_port or config.get('external-controller') != f'127.0.0.1:{api_port}'
            or config.get('allow-lan', False) or config.get('tun', {}).get('enable', False)):
        raise InstallError(_t('安装包配置与安全监听端口不一致。'))
    import domino_subscriptions
    domino_subscriptions.validate_install_registration(sys.modules[__name__], bundle)
    for command in ['sudo', 'systemctl', 'curl']:
        if not shutil.which(command):
            raise InstallError(_t('目标缺少依赖：') + command)
    owned_installations()
    cli = HOME / '.local/bin/domino'
    preserve_cli = bool(manifest.get('package_managed_cli')) or is_package_cli(cli)
    if not preserve_cli and not owned_cli(cli):
        raise InstallError(_t('~/.local/bin/domino 已被其他程序使用，未覆盖。'))
    body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
    for name in dict.fromkeys(ENV_FILES + LEGACY_ENV_FILES):
        path = HOME / name
        if path.is_symlink():
            raise InstallError(_t('受管理的环境文件是符号链接，停止。'))
        if path.exists() and name in ENV_FILES[:-1]:
            managed_block(path.read_text(), body)
    old_ports = set()
    for app, service in ((APP, SERVICE), (LEGACY_APP, LEGACY_SERVICE)):
        if systemctl('is-active', service) and (app / 'data/config.json').exists():
            old = json.loads((app / 'data/config.json').read_text())
            old_ports.update({old.get('mixed-port'), int(old['external-controller'].rsplit(':', 1)[1])})
    for number in [proxy_port, api_port]:
        if number in old_ports:
            continue
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', number)) == 0:
                raise InstallError(_t('目标端口 {0} 已被其他服务占用，未修改。', number))
    prepare_custom_rules(bundle / 'data')
    run([str(bundle / 'mihomo'), '-t', '-d', str(bundle / 'data'), '-f', str(bundle / 'data/config.json')],
        capture_output=True, text=True, timeout=60)
    run(['sudo', *(['-n'] if manifest.get('non_interactive') else []), '-v'])
    user = run(['id', '-un'], capture_output=True, text=True).stdout.strip()
    group = run(['id', '-gn'], capture_output=True, text=True).stdout.strip()
    unit = unit_text(user, group)
    pending = manifest.get('awaiting_subscription') and not (config.get('proxies') or config.get('proxy-providers'))
    shell_state = prepare_shell_policy(APP, HOME, system='linux', shell_env=manifest['shell_env'], pending=pending)
    backup = snapshot(preserve_cli=True) if preserve_cli else snapshot()
    try:
        if LEGACY_SERVICE.exists():
            sudo('systemctl', 'stop', LEGACY_SERVICE.name)
            sudo('systemctl', 'disable', LEGACY_SERVICE.name)
            sudo('rm', '-f', str(LEGACY_SERVICE))
        if systemctl('is-active'):
            sudo('systemctl', 'stop', SERVICE.name)
        if APP.exists():
            shutil.rmtree(APP)
        APP.mkdir(parents=True, mode=0o700)
        shutil.copy2(bundle / 'mihomo', APP / 'mihomo')
        (APP / 'mihomo').chmod(0o755)
        shutil.copytree(bundle / 'data', APP / 'data')
        (APP / 'data/config.json').chmod(0o600)
        write_private(APP / 'manifest.json', json.dumps(manifest))
        install_cli(bundle, preserve_cli=preserve_cli)
        legacy_port = install_shell_policy(APP, shell_state)
        unit_path = bundle / 'domino.service'
        write_private(unit_path, unit, 0o644)
        sudo('install', '-m', '644', str(unit_path), str(SERVICE))
        sudo('systemctl', 'daemon-reload')
        sudo('systemctl', 'enable', '--now', SERVICE.name)
        for attempt in range(15):
            try:
                controller(APP / 'data', '/version')
                break
            except (OSError,InstallError):
                if attempt == 14:
                    raise InstallError(_t('服务控制接口未就绪。'))
                time.sleep(1)
        selections = json.loads((bundle / 'selections.json').read_text())
        for name, selected in selections.items():
            controller(APP / 'data', '/proxies/' + urllib.parse.quote(name, safe=''), {'name': selected})
        health = None if pending else probe(proxy_port, manifest['test_url'])
        if manifest['shell_env']:
            configure_environment(proxy_port, legacy_port=legacy_port)
            (HOME / LEGACY_ENV_FILES[-1]).unlink(missing_ok=True)
        if LEGACY_APP.exists():
            shutil.rmtree(LEGACY_APP)
        domino_subscriptions.register_installed(sys.modules[__name__], bundle)
    except BaseException as failure:
        try:
            print(_t('部署未完成，正在恢复服务、节点配置和环境文件…'), file=sys.stderr)
        except OSError:
            pass  # Still restore if the SSH terminal disconnected.
        try:
            restore(backup)
        except BaseException:
            raise InstallError(_t('自动恢复未完成。保留的完整备份：') + str(backup),code='RECOVERY_INCOMPLETE',effect='unknown') from None
        if isinstance(failure,KeyboardInterrupt):
            failure.domino_effect='rolled_back'
            raise
        raise InstallError(_t('部署未完成，已恢复原状态；备份：')+str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        globals().pop('_domino_registry_backup', None)
    if manifest.get('deployment_output'):
        write_private(bundle / 'deployment-result.json', json.dumps({
            'schema': 1, 'exit_country': health.get('exit_country') if health else None,
            'node_count': len(config.get('proxies', [])),
            'provider_count': len(config.get('proxy-providers', {})),
            'shell_enabled': shell_state[0]['enabled'] if shell_state[0] is not None else None,
            'backup': backup.name,
            'proxy_port': proxy_port, 'awaiting_subscription': bool(pending)}))
    print(_t('服务已运行并启用开机自启；代理端口：') + str(proxy_port))
    if health is None:
        print(_t('基础环境已就绪，待添加订阅：domino add "名称"；domino switch "名称"。'))
    else:
        print(_t('代理出网校验通过；出口地区：') + (health['exit_country'] or _t('未返回')))
    if manifest['shell_env']:
        print(_t('终端代理策略：') + (_t('已开启') if shell_state[0]['enabled'] else _t('已关闭')) + _t('；与系统代理独立，使用 domino shell on/off/status 管理。'))
        print(_t('已有终端请加载一次：. "$HOME/.config/domino/proxy.env"；Bash 登录配置需已加载 .bashrc。'))
        print(_t('其他已接入终端下次提示符同步；运行中的 VS Code / Server 不会更新环境。'))
    print(_t('部署前备份：') + backup.name)
    if (APP / 'cli').is_dir():
        print(_t('目标机管理和继续部署：~/.local/bin/domino status；~/.local/bin/domino USER@IP'))


def select_backup(name=None):
    if name:
        if name in ['.', '..'] or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise InstallError(_t('备份 ID 无效。'))
        for directory in (BACKUPS, LEGACY_BACKUPS):
            candidate = directory / name
            if not candidate.is_symlink() and (candidate / 'snapshot.json').is_file():
                return candidate
        raise InstallError(_t('备份不存在或来自不支持自动恢复的旧版本。'))
    candidates = []
    for directory in (BACKUPS, LEGACY_BACKUPS):
        if not directory.exists():
            continue
        for candidate in directory.iterdir():
            if candidate.is_symlink() or not (candidate / 'snapshot.json').is_file():
                continue
            state = json.loads((candidate / 'snapshot.json').read_text())
            if state.get('kind') == 'deploy':
                candidates.append((state.get('created_ns', 0), candidate))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    raise InstallError(_t('没有本版本工具生成的可恢复备份。'))


def rollback(name=None, non_interactive=False):
    if os.getuid() == 0:
        raise InstallError(_t('请使用部署时的普通 SSH 用户回滚。'))
    owned_installations()
    backup = select_backup(name)
    run(['sudo', *(['-n'] if non_interactive else []), '-v'])
    safety = snapshot('rollback-safety')
    try:
        restore(backup)
    except BaseException:
        try:
            restore(safety)
        except BaseException:
            raise InstallError(_t('回滚和自动恢复未完成。当前状态备份：') + safety.name,code='RECOVERY_INCOMPLETE',effect='unknown') from None
        raise InstallError(_t('回滚未完成，已恢复操作前状态。'),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        globals().pop('_domino_registry_backup', None)
    print(_t('已恢复部署前状态：') + backup.name)
    print(_t('回滚前状态也已保存：') + safety.name)


def subscription_name(app):
    try:
        marker = json.loads((app / 'data/subscription.json').read_text())
        registry = json.loads((HOME / '.config/domino/subscriptions/index.json').read_text())
        return next((v['name'] for v in registry['items'] if v['id'] == marker['id']), None)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def subscription_pending(app, config=None):
    manifest_path = app / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    if not manifest.get('awaiting_subscription'):
        return False
    config = config if config is not None else json.loads((app / 'data/config.json').read_text())
    return not (config.get('proxies') or config.get('proxy-providers'))


def human_text(value):
    return ''.join(char for char in str(value if value is not None else '—') if char.isprintable() or ord(char) in (0x200c,0x200d))


def human_style(value, code='1', *, color=None):
    if color is None:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    text = human_text(value)
    return f'\033[{code}m{text}\033[0m' if color and code else text


def human_header_text(title, summary=None, tone='32', *, color=None):
    lines=['',human_style('Domino','1;36',color=color) + '  ·  ' + human_style(title,color=color)]
    if summary: lines.append('  ' + human_style(summary,tone,color=color))
    return '\n'.join([*lines,'',''])


def human_header(title, summary=None, tone='32'):
    print(human_header_text(title,summary,tone),end='')


class _HumanOutput:
    def __init__(self, stream, color=None):
        self.stream,self.started,self.trailing=stream,False,0
        self.color=color

    def __getattr__(self, name):
        return getattr(self.stream,name)

    def isatty(self):
        return self.color if self.color is not None else self.stream.isatty()

    def write(self, value):
        parts=[]
        for char in value:
            if char == '\n':
                if self.trailing < (2 if self.started else 1):
                    parts.append(char)
                    self.trailing += 1
            else:
                if not self.started and self.trailing == 0: parts.append('\n')
                self.started=True
                self.trailing=0
                parts.append(char)
        self.stream.write(''.join(parts))
        return len(value)

    def finish(self):
        if self.started:
            self.stream.write('\n' * max(0,2-self.trailing))
            self.stream.flush()


@contextmanager
def human_output(enabled=True, *, color=None):
    if not enabled:
        yield
        return
    stream=_HumanOutput(sys.stdout,color=color)
    with redirect_stdout(stream):
        try:
            yield
        finally:
            stream.finish()


def human_row(label, value, *, wrap=False, columns=None):
    if wrap:
        text,code = (human_text(value[0]),value[1]) if isinstance(value,tuple) else (human_text(value),None)
        padding = ' ' * max(2,10-human_width(label))
        prefix = '  ' + human_style(label,'2') + padding
        indent = ' ' * (2+human_width(label)+len(padding))
        width = max(1,(columns or shutil.get_terminal_size((100,24)).columns)-len(indent))
        lines=[]
        while human_width(text)>width:
            end=0
            for index in range(1,len(text)+1):
                if human_width(text[:index])>width: break
                end=index
            end=max(1,end)
            boundary=text.rfind('/',0,end)
            if boundary>0: end=boundary+1
            lines.append(text[:end])
            text=text[end:]
        lines.append(text)
        for index,line in enumerate(lines):
            print((prefix if index==0 else indent)+human_style(line,code))
        return
    rendered = human_style(*value) if isinstance(value,tuple) else human_text(value)
    print('  ' + human_style(label,'2') + ' ' * max(2,10-human_width(label)) + rendered)


def human_width(value):
    width = 0
    previous = ''
    for char in human_text(value):
        if ord(char) == 0xfe0f:
            if previous and unicodedata.east_asian_width(previous) not in ['W','F']: width += 1
        elif not unicodedata.category(char).startswith(('M','C')):
            width += 2 if unicodedata.east_asian_width(char) in ['W','F'] else 1
            previous = char
    return width


def human_table(headers, rows):
    cells = [[(human_text(cell[0]),cell[1]) if isinstance(cell,tuple) else (human_text(cell),None) for cell in row] for row in rows]
    widths = [max([human_width(header),*(human_width(row[index][0]) for row in cells)]) for index,header in enumerate(headers)]
    def line(row):
        return '  ' + '  '.join(human_style(value,code) if index == len(row)-1 else
            (human_style(value,code) + ' '*(widths[index]-human_width(value))) for index,(value,code) in enumerate(row))
    print(line([(human_text(header),'2') for header in headers]))
    for row in cells: print(line(row))


def human_size(value, rate=False):
    if value is None: return '—'
    number = max(0,float(value))
    units = ['B','KiB','MiB','GiB','TiB']
    index = 0
    while number >= 1024 and index < len(units)-1:
        number /= 1024
        index += 1
    amount = f'{number:.0f}' if index == 0 and (number >= 1 or number == 0) else f'{number:.2f}' if 0 < number < 1 else f'{number:.1f}'
    return amount + ' ' + units[index] + ('/s' if rate else '')


def human_time(value):
    if not value: return _t('尚未更新')
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp.astimezone().strftime('%Y-%m-%d %H:%M %z') if stamp.year >= 1970 else _t('尚未更新')
    except (ValueError,TypeError,OverflowError):
        return human_text(value)


def status_text(result, system_proxy=None, *, color=False):
    system_proxy = system_proxy if system_proxy is not None else result.get('system_proxy')
    text = human_text
    def styled(value, code):
        return human_style(value,code,color=color)
    if not result.get('installed'):
        summary, tone = _t('○ 尚未安装运行环境'), '33'
    elif result.get('awaiting_subscription'):
        summary, tone = (_t('● 服务已运行 · 待添加订阅'), '33') if result.get('active') else (_t('● 服务已停止 · 待添加订阅'), '31')
    elif not result.get('active'):
        summary, tone = _t('● 服务已停止'), '31'
    elif result.get('healthy') and system_proxy is not None and system_proxy.get('routing') not in ['domino','unsupported']:
        summary, tone = _t('● 服务运行中 · 系统代理未接通'), '33'
    elif result.get('healthy'):
        summary, tone = _t('● 代理出网正常'), '32'
    else:
        summary, tone = _t('● 服务运行中 · 连通检查未通过'), '31'
    lines = human_header_text(_t('运行状态'),summary,tone,color=color).splitlines()
    if not result.get('installed'):
        return '\n'.join([*lines,_t('  下一步：运行安装程序。'),''])
    subscription = result.get('subscription') or (_t('待添加订阅') if result.get('awaiting_subscription') else _t('独立配置（未绑定订阅）'))
    mode = {'rule':_t('规则模式'),'global':_t('全局模式'),'direct':_t('直连模式')}.get(result.get('mode'),_t('模式未知'))
    country = result.get('exit_country') or (_t('未知') if result.get('healthy') else _t('未检测'))
    lines += [_t('  订阅 ') + styled(subscription,'1') + '  ·  ' + mode + _t('  ·  出口 ') + styled(country,'1')]
    def row(label, value):
        lines.append('  ' + styled(label,'2') + ' '*(10-2*len(label)) + value)
    startup = (_t('登录时自启') if result.get('autostart_scope') == 'user-login' else _t('开机自启')) if result.get('enabled') else _t('未启用自启动')
    row(_t('服务'), (_t('运行中') if result.get('active') else _t('已停止')) + '  ·  ' + startup)
    if system_proxy is not None:
        routing = system_proxy.get('routing','unknown')
        ports = '/'.join(text(number) for number in system_proxy.get('ports',[]))
        value = {'domino':_t('已开启，指向 Domino') + (f" 127.0.0.1:{text(result['proxy_port'])}" if result.get('proxy_port') else ''),
                 'off':_t('未开启'), 'other':_t('指向其他代理') + (' :'+ports if ports else ''),
                 'mixed':_t('部分指向其他代理') + (' :'+ports if ports else ''),
                 'pac':_t('使用 PAC 自动配置'), 'unsupported':_t('无 GNOME 桌面会话；终端可用 domino shell on'), 'unknown':_t('无法确认')}.get(routing,_t('无法确认'))
        row(_t('系统代理'), styled(value,'32' if routing == 'domino' else '33'))
    if 'shell_proxy' in result:
        shell = result['shell_proxy']
        value = (_t('策略已开启') if shell.get('enabled') else _t('策略已关闭')) if 'enabled' in shell else _t('策略无法读取')
        row(_t('终端代理'), value + _t('  ·  domino shell status 查看当前终端'))
    if result.get('proxy_port'):
        row(_t('代理地址'), f"http://127.0.0.1:{text(result['proxy_port'])}")
    kernel = 'Mihomo ' + text(result.get('version') or _t('版本未知'))
    if result.get('arch'): kernel += '  ·  ' + text(result['arch'])
    row(_t('内核'), kernel)
    if result.get('requires_source_online'):
        row(_t('上游依赖'), styled(_t('需要源电脑保持在线'),'33'))
    if result.get('awaiting_subscription'):
        lines += ['',_t('  下一步：domino add "名称"；domino switch "名称"。')]
    elif not result.get('active'):
        lines += ['',_t('  启动服务：domino start')]
    elif not result.get('healthy'):
        lines += ['',_t('  排查连接：domino logs；domino nodes')]
    elif system_proxy is not None and system_proxy.get('routing') not in ['domino','unsupported']:
        lines += ['',_t('  接通系统代理：domino start')]
    return '\n'.join([*lines,''])


def collect_status(check_exit=True):
    app, service = current_installation()
    result = {'installed': (app / 'data/config.json').is_file(), 'service': service.name,
              'active': systemctl('is-active', service), 'enabled': systemctl('is-enabled', service), 'healthy': False,
              'controller_reachable':False,'exit_checked':False}
    if result['installed']:
        import domino_shell
        try:
            result['shell_proxy'] = domino_shell.status(app, HOME)
        except ValueError:
            result['shell_proxy'] = {'policy_only': True, 'current_shell_applied': False, 'error': 'SHELL_POLICY_INVALID'}
        config = json.loads((app / 'data/config.json').read_text())
        pending = subscription_pending(app, config)
        result['awaiting_subscription'] = pending
        if pending:
            result['note'] = _t('待添加并切换订阅。')
        manifest = json.loads((app / 'manifest.json').read_text()) if (app / 'manifest.json').is_file() else {}
        result.update(proxy_port=config['mixed-port'], version=manifest.get('version'), arch=manifest.get('arch'), subscription=subscription_name(app),
                      mode=config.get('mode','rule'))
        if manifest.get('platform') == 'darwin':
            result['service'] = 'local.domino.mihomo'
            result['autostart_scope'] = 'user-login'
            import domino_macos
            result['system_proxy'] = domino_macos.system_proxy_overview(result['proxy_port'])
        elif sys.platform == 'linux':
            import domino_linux
            result['system_proxy'] = domino_linux.system_proxy_overview(result['proxy_port'])
        result['deployment_method'] = manifest.get('deployment_method', 'independent')
        result['requires_source_online'] = manifest.get('requires_source_online', False)
        if result['active']:
            try:
                result['version'] = json.loads(controller(app / 'data', '/version')).get('version')
                result['mode'] = json.loads(controller(app / 'data', '/configs')).get('mode', config.get('mode', 'rule'))
                result['controller_reachable']=True
                if not pending and check_exit:
                    result['exit_checked']=True
                    result.update(probe(result['proxy_port'], manifest.get('test_url', DEFAULT_TEST)))
            except (InstallError, OSError, ValueError, KeyError):
                result['check_error'] = _t('代理控制接口或独立出网检查失败')
    return result


def status(as_json=False):
    result = collect_status()
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
        print(status_text(result, color=color))
    return 0 if result['healthy'] else 3


def proxy_state():
    app, _ = current_installation()
    config_path = app / 'data/config.json'
    if not config_path.is_file():
        raise InstallError(_t('目标尚未安装本工具管理的代理。'))
    config = json.loads(config_path.read_text())
    try:
        live = json.loads(controller(app / 'data', '/proxies'))['proxies']
        running = json.loads(controller(app / 'data', '/configs'))
        config['mode'] = running.get('mode', config.get('mode', 'rule'))
    except (OSError, ValueError, KeyError):
        raise InstallError(_t('无法读取 Mihomo 节点，请先运行 status 检查服务。')) from None
    return config, live


def proxy_inventory(live, *, api=None):
    api = api or api_json
    """Include provider members that the top-level proxy API does not enumerate."""
    live=dict(live)
    missing={name for item in live.values() for name in item.get('all',[]) if name not in live}
    if not missing: return live
    try: providers=api('/providers/proxies').get('providers',{})
    except InstallError as error:
        if error.code=='RESOURCE_NOT_FOUND': return live
        raise
    members={}
    for provider,item in providers.items():
        for node in item.get('proxies',[]):
            if not isinstance(node,dict) or not node.get('name'): continue
            if node['name'] in live and (str(item.get('vehicleType','')).lower()=='compatible' or live[node['name']].get('provider-name')==provider): continue
            members.setdefault(node['name'],[]).append((provider,node))
    for name,items in members.items():
        for provider,node in items:
            label=name if len(items)==1 and name not in live else provider+'::'+name
            value=dict(node,_domino_original=name,_domino_provider=provider,
                _domino_delay='/providers/proxies/'+urllib.parse.quote(provider,safe='')+'/'+urllib.parse.quote(name,safe='')+'/healthcheck')
            live[label]=value
    return live


def current_proxy_paths(mode, live, group=None, *, include_nodes=False):
    """Resolve runtime selections without assuming a rule-mode request's destination."""
    if group:
        roots = [group]
    elif mode == 'direct':
        roots = ['DIRECT']
    elif mode == 'global':
        roots = ['GLOBAL']
    else:
        groups = [name for name, item in live.items() if name != 'GLOBAL' and isinstance(item.get('all'), list)]
        roots = [name for name in groups if str(live[name].get('type', '')).lower() in ['selector', 'select']] or groups
    paths = []
    for root in roots:
        path, seen, name, terminal = [], set(), root, None
        while True:
            if name in seen:
                path.append(name + _t('（循环引用）'))
                break
            seen.add(name)
            path.append(name)
            item = live.get(name)
            if name == 'DIRECT':
                path[-1] += _t('（直连）')
                break
            if name in ['REJECT', 'REJECT-DROP']:
                path[-1] += _t('（拒绝连接）')
                break
            if item is None:
                path[-1] += _t('（节点信息不可用）')
                break
            if not isinstance(item.get('all'), list):
                if name not in ['PASS', 'COMPATIBLE']:
                    terminal = name
                break
            if str(item.get('type', '')).lower() in ['loadbalance', 'load-balance']:
                path[-1] += _t('（按连接分配）')
                break
            selected = item.get('now')
            if not selected:
                path[-1] += _t('（尚未选定节点）')
                break
            name = selected
        path = ' → '.join(path)
        paths.append({'path':path, 'node':terminal} if include_nodes else path)
    return paths


def collect_nodes(group=None, *, include_current=False):
    config, live = proxy_state()
    live=proxy_inventory(live)
    groups = []
    actual_nodes = []
    for name, item in live.items():
        if isinstance(item.get('all'), list):
            if name == 'GLOBAL' and config.get('mode', 'rule') != 'global' and group != 'GLOBAL':
                continue
            groups.append({'name': name, 'type': item.get('type'), 'current': item.get('now'),
                           'selectable': item.get('type', '').lower() in ['selector', 'select'],
                           'choices': item['all']})
        elif name not in ['DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'COMPATIBLE']:
            actual_nodes.append({'name': name, 'type': item.get('type')})
    if group:
        groups = [g for g in groups if g['name'] == group]
        if not groups:
            raise InstallError(_t('没有找到该策略组，请先运行 nodes 查看名称。'))
        actual_nodes = []
    result = {'mode': config.get('mode', 'rule'), 'groups': groups, 'nodes': actual_nodes}
    if include_current:
        result['current_proxy_paths'] = current_proxy_paths(result['mode'], live, group)
    return result


def nodes(group=None, as_json=False):
    result=collect_nodes(group, include_current=not as_json)
    groups,actual_nodes=result['groups'],result['nodes']
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mode = {'rule':_t('规则模式'),'global':_t('全局模式'),'direct':_t('直连模式')}.get(result['mode'],result['mode'])
    human_header(_t('节点'),_t('{0}  ·  {1} 策略组  ·  {2} 节点', mode, len(groups), len(actual_nodes)))
    app, _ = current_installation()
    human_row(_t('当前配置'), (subscription_name(app) or _t('未关联配置库的配置'), '1'))
    for index, path in enumerate(result['current_proxy_paths']):
        human_row((_t('组内当前选择') if group else _t('当前代理')) if index == 0 else '', (path, '1;32'))
    if not result['current_proxy_paths']:
        human_row(_t('当前代理'), _t('无法确定（未发现可用策略组）'))
    if result['mode'] == 'rule' and not group:
        print(_t('  按规则分流；以上为手动策略组（无手动组时为自动策略组）的当前选择。'))
    if group:
        print()
        for choice in groups[0]['choices']:
            current = choice == groups[0]['current']
            print('  ' + human_style(('* ' if current else '  ')+choice,'32' if current else '0'))
    if actual_nodes:
        selected_by = {}
        for g in groups:
            if g['current']:
                label = g['name'] + (_t('（手动）') if g['selectable'] else _t('（自动）'))
                selected_by.setdefault(g['current'], []).append(label)
        rows = []
        for item in actual_nodes:
            selectors = selected_by.get(item['name'], [])
            name = ('* ' + item['name'], '32') if selectors else '  ' + item['name']
            rows.append([name, item['type'], '、'.join(selectors) if selectors else '—'])
        print()
        human_table([_t('节点名称'),_t('协议'),_t('当前选中该节点的策略组')], rows)
        print(_t('\n  * 表示被策略组当前选中，不代表所有请求都走该节点。'))
    if not group:
        print(_t('\n  查看组内节点：domino nodes --group "策略组名称"'))


def select_node(group, node, *, render=True):
    _, live = proxy_state()
    item = live.get(group)
    if not item or not isinstance(item.get('all'), list):
        raise InstallError(_t('策略组不存在，请先用 nodes 查看。'))
    if item.get('type', '').lower() not in ['selector', 'select']:
        raise InstallError(_t('该组由自动策略选择；请切换上层可手动选择的策略组。'))
    if node not in item['all']:
        raise InstallError(_t('指定节点不在该策略组中，未更改任何选择。'))
    if item.get('now') == node:
        if not render: return {'group':group,'node':node,'changed':False}
        human_header(_t('节点选择'),_t('● 当前已选择，无需切换'))
        human_row(_t('策略组'),group)
        human_row(_t('当前节点'),node)
        return {'group':group,'node':node,'changed':False}
    route = '/proxies/' + urllib.parse.quote(group, safe='')
    app, _ = current_installation()
    controller(app / 'data', route, {'name': node})
    # Acknowledge only the state observed back from the controller.
    current = json.loads(controller(app / 'data', route)).get('now')
    if current != node:
        raise InstallError(_t('切换请求已发送，但读回的选择尚未一致；请用 nodes 核实。'),code='READBACK_MISMATCH',effect='unknown')
    if not render: return {'group':group,'node':node,'changed':True}
    human_header(_t('节点选择'),_t('● 已切换'))
    human_row(_t('策略组'),group)
    human_row(_t('当前节点'),node)
    print(_t('\n  新连接将使用该选择；已有长连接可能需要重新连接。'))
    return {'group':group,'node':node,'changed':True}


def service_action(action, non_interactive=False, lines=100, follow=False):
    manifest = APP / 'manifest.json'
    if sys.platform == 'darwin' and (not manifest.exists() or json.loads(manifest.read_text()).get('platform') == 'darwin'):
        import domino_macos
        return domino_macos.service_action(sys.modules[__name__], action, lines, follow,batch=non_interactive)
    app, service = current_installation()
    if not (app / 'data/config.json').is_file():
        raise InstallError(_t('本机尚未安装 Domino 代理。'))
    with legacy_layout() if service == LEGACY_SERVICE else nullcontext():
        owned_service()
    if action == 'logs' and not 1 <= lines <= 10000:
        raise InstallError(_t('日志行数必须在 1–10000 之间。'))
    run(['sudo', *(['-n'] if non_interactive else []), '-v'])
    if action == 'logs':
        command = ['journalctl', '-u', service.name, '-n', str(lines), '--no-pager']
        if follow:
            command += ['-f']
        run(['sudo', '-n', *command])
    else:
        if action == 'stop':
            system_proxy('off', render=False)
        sudo('systemctl', action, service.name)
        proxy = None
        if action in ['start','restart']:
            try: proxy = system_proxy('on', render=False)
            except DomainError as error:
                raise InstallError(_t('服务已启动，但系统代理未接通：')+str(error),code=error.code,exit_code=error.exit_code,effect='unknown') from None
        human_header(_t('运行状态'),{'start':_t('● 已开启'),'stop':_t('● 已关闭'),'restart':_t('● 已重启')}[action], '31' if action == 'stop' else '32')
        human_row(_t('管理服务'),service.name)
        if proxy and proxy.get('supported'):
            human_row(_t('系统代理'),_t('已开启（HTTP / HTTPS / SOCKS）'))
            human_row(_t('代理目标'),f"127.0.0.1:{proxy['proxies']['http']['port']}（Domino）")
        elif action != 'stop':
            human_row(_t('系统代理'),_t('无 GNOME 桌面会话；代理入口已就绪'))
            human_row(_t('终端代理'),_t('使用 domino shell on/off/status 独立管理'))
        else:
            human_row(_t('系统代理'),_t('已解除 Domino 接管；无桌面时不修改系统代理'))


def system_proxy(action=None, service=None, as_json=False, non_interactive=False, *, render=True):
    if sys.platform == 'darwin':
        import domino_macos as backend
    else:
        import domino_linux as backend
    return backend.system_proxy(sys.modules[__name__],action,service,as_json,non_interactive,render=render)


def api_json(route, payload=None, *, method=None, timeout=3):
    app, _ = current_installation()
    if not (app / 'data/config.json').is_file():
        raise InstallError(_t('尚未安装 Domino 运行环境，请先运行安装程序。'),code='NOT_INSTALLED',exit_code=3)
    value = controller(app / 'data', route, payload, method=method, timeout=timeout)
    return json.loads(value) if value else None


def show(value, as_json=False):
    if as_json or isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif not value:
        print(_t('暂无数据。'))
    else:
        for item in value:
            print(item)


def set_option(key, value=None, as_json=False, *, render=True):
    app, _ = current_installation()
    running = api_json('/configs')
    if value is None:
        if not render: return {key:running.get(key)}
        if as_json: show({key: running.get(key)},True)
        else: show_option(key,running.get(key))
        return {key:running.get(key)}
    path = app / 'data/config.json'
    before=path.read_bytes()
    config=json.loads(before)
    previous = running.get(key)
    acknowledged=False
    try:
        api_json('/configs', {key: value}, method='PATCH')
        acknowledged=True
        if api_json('/configs').get(key) != value:
            raise InstallError(_t('设置读回不一致。'),code='READBACK_MISMATCH',effect='unknown')
        config[key] = value
        write_private(path, json.dumps(config, ensure_ascii=False, indent=2))
    except BaseException as failure:
        if isinstance(failure,DomainError) and not acknowledged and failure.effect=='none': raise
        try:
            if path.read_bytes()!=before: write_private(path,before)
            api_json('/configs', {key: previous}, method='PATCH')
            if api_json('/configs').get(key)!=previous: raise RuntimeError()
        except BaseException:
            raise InstallError(_t('设置保存失败且恢复未完成。'),code='RECOVERY_INCOMPLETE',effect='unknown') from None
        raise InstallError(_t('设置保存失败，已恢复原设置。'),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    result={key:value,'persisted':True}
    if render:
        if as_json: show(result,True)
        else: show_option(key,value,persisted=True)
    return result


def show_option(key, value, persisted=False):
    names = {'rule':_t('规则模式'),'global':_t('全局模式'),'direct':_t('直连模式'),'debug':_t('调试'),'info':_t('信息'),
             'warning':_t('警告'),'error':_t('错误'),'silent':_t('静默')}
    options = ('rule', 'global', 'direct') if key == 'mode' else ('debug', 'info', 'warning', 'error', 'silent')
    human_header(_t('代理模式') if key == 'mode' else _t('日志级别'))
    human_table([_t('模式') if key == 'mode' else _t('级别'), _t('值')], [
        [(('● ' if option == value else '  ') + names[option], '32' if option == value else '0'), option]
        for option in options])
    if value not in options:
        human_row(_t('当前模式') if key == 'mode' else _t('当前级别'), (human_text(value), '33'))
    if persisted: human_row(_t('保存'),_t('已写入配置，重启后保留'))


def resolve_delay_name(query, names, kind):
    if query in names:
        return query
    needle = (query or '').strip().casefold()
    matches = sorted(name for name in names if needle and needle in name.casefold())
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise InstallError(_t('匹配到多个{0}，请使用完整名称。候选：', kind) + '；'.join(matches))
    raise InstallError(_t('没有找到指定{0}；请运行 domino nodes 查看名称。', kind))


DELAY_NODE_WORKERS = 32
DELAY_CONFIG_WORKERS = 3
from threading import Lock
_DELAY_PORT_LOCK = Lock()
_DELAY_PORTS = set()


class _DelayProgress:
    """One terminal writer; worker threads only update counters."""
    def __init__(self, enabled=True, *, force=False, configs=False):
        from threading import Event
        self.stream = sys.stderr
        self.enabled = enabled and (force or self.stream.isatty())
        self.configs = configs
        self.config_total = 0
        self.registered = {}
        self.finished = set()
        self.completed = self.available = 0
        self.lock = Lock()
        self.stop = Event()
        self.thread = None
        self.started = time.monotonic()

    def __enter__(self):
        return self

    def start(self, configs=0):
        if not self.enabled or self.thread is not None:
            return
        from threading import Thread
        self.config_total = configs
        self.started = time.monotonic()
        sys.stdout.flush()
        self._draw()
        self.thread = Thread(target=self._animate, name='domino-delay-progress', daemon=True)
        self.thread.start()

    def nodes(self, key, count):
        with self.lock:
            self.registered[key] = count

    def node_done(self, ok):
        with self.lock:
            self.completed += 1
            self.available += bool(ok)

    def config_done(self, key):
        with self.lock:
            self.finished.add(key)

    def _draw(self):
        with self.lock:
            elapsed = time.monotonic() - self.started
            total = sum(self.registered.values())
            known = (len(set(self.registered) | self.finished) == self.config_total
                     if self.configs else bool(self.registered))
            count = (f'{self.completed}/{total}' + ('' if known else '+')
                     if known or total else '0/?')
            status = _t('正在检测') if known else _t('加载配置')
            percent = min(100, int(self.completed * 100 / total)) if known and total else None
            if known and not total:
                percent = 100
            details = f' {percent:3d}%' if percent is not None else '  ...'
            details += _t(' · 节点 {0} · 可用 {1} · 不可用 {2}', count, self.available, self.completed - self.available)
            if self.configs:
                details += _t(' · 配置 {0}/{1}', len(self.finished), self.config_total)
            details += f' · {elapsed:.1f}s'
            columns = shutil.get_terminal_size(fallback=(100, 24)).columns
            width = max(4, min(20, columns - human_width(status + details) - 7))
            if percent is None:
                bar = [' '] * width
                bar[int(elapsed * 10) % width] = '='
                bar = ''.join(bar)
            else:
                filled = width * percent // 100
                bar = '=' * filled + '-' * (width - filled)
            line = f'  {status} [{bar}]' + details
            while line and human_width(line) >= columns:
                line = line[:-1]
            self.stream.write('\r\033[2K' + line)
            self.stream.flush()

    def _animate(self):
        while not self.stop.wait(.1):
            self._draw()

    def close(self, final=False):
        if self.thread is None:
            return
        self.stop.set()
        self.thread.join()
        self.thread = None
        if final:
            self._draw()
            self.stream.write('\n')
        else:
            self.stream.write('\r\033[2K')
        self.stream.flush()

    def __exit__(self, kind, value, traceback):
        self.close()


@contextmanager
def _delay_port():
    # Keep separate concurrent cores from choosing the same released port.
    with _DELAY_PORT_LOCK:
        while True:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            if port not in _DELAY_PORTS:
                _DELAY_PORTS.add(port)
                break
    try:
        yield port
    finally:
        with _DELAY_PORT_LOCK:
            _DELAY_PORTS.discard(port)


def _delay_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        from concurrent.futures import CancelledError
        raise CancelledError()


def _delay_results(futures, cancel=None):
    from concurrent.futures import TimeoutError as FutureTimeout
    results = []
    for future in futures:
        if cancel is None:
            results.append(future.result())
            continue
        while True:
            _delay_cancelled(cancel)
            try:
                results.append(future.result(timeout=.1))
                break
            except FutureTimeout:
                continue
    return results


@contextmanager
def isolated_delay_config(name, *, _cancel=None):
    """Run a cached profile on a disposable controller without touching services."""
    import secrets
    import domino_subscriptions
    import domino_cli
    _delay_cancelled(_cancel)
    manager = domino_subscriptions.Manager(sys.modules[__name__])
    item = manager.find(name)
    cached = manager.cached(item)  # Never download or activate an uncached profile.
    core = manager.app / 'mihomo'
    if not core.is_file():
        raise InstallError(_t('缺少 Mihomo 内核，无法测试配置。'), code='NOT_INSTALLED', exit_code=3)
    with tempfile.TemporaryDirectory(prefix='domino-delay-') as directory, _delay_port() as port:
        data = Path(directory) / 'data'
        shutil.copytree(cached, data, ignore=shutil.ignore_patterns('source', 'cache.db', 'cache.db-*'))
        raw = json.loads((data / 'config.json').read_text())
        profile = domino_cli.sanitize_profile(raw, {}, 0, port)
        profile['rules'] = ['MATCH,DIRECT']
        profile.pop('rule-providers', None)
        profile.pop('sub-rules', None)
        providers = profile.get('proxy-providers', {})
        for provider in providers.values():
            if provider.get('type') == 'http':
                provider['type'] = 'file'
            for key in ('url', 'interval', 'proxy', 'header'):
                provider.pop(key, None)
            provider['health-check'] = {'enable': False}
        profile['proxy-groups'] = [{'name': 'DominoDelay-' + secrets.token_hex(8), 'type': 'select',
            'proxies': ['DIRECT'] + [node['name'] for node in profile.get('proxies', [])], 'use': list(providers)}]
        write_private(data / 'config.json', json.dumps(profile, ensure_ascii=False))
        process = subprocess.Popen([str(core), '-d', str(data), '-f', str(data / 'config.json')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def api(route, **options):
            return json.loads(controller(data, route, **options))
        try:
            deadline = time.monotonic() + 10
            while True:
                _delay_cancelled(_cancel)
                if process.poll() is not None:
                    raise InstallError(_t('配置测速临时内核启动失败；请检查缓存配置和依赖资源。'), code='DELAY_CORE_FAILED')
                try:
                    response = api('/proxies', timeout=.2)
                    group = profile['proxy-groups'][0]['name']
                    if group in response.get('proxies', {}):
                        break
                except (InstallError, OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    raise InstallError(_t('配置测速临时内核启动超时。'), code='DELAY_CORE_TIMEOUT', exit_code=7)
                time.sleep(.05)
            yield api
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def delay_summary(url='https://www.gstatic.com/generate_204', timeout_ms=5000, as_json=False, *, render=True, _progress=None):
    """Aggregate bounded HTTPS node probes for every saved configuration."""
    if _progress is None:
        with _DelayProgress(enabled=render and not as_json, configs=True) as progress:
            return delay_summary(url, timeout_ms, as_json, render=render, _progress=progress)
    if not 100 <= timeout_ms <= 60000:
        raise InstallError(_t('测速超时必须在 100–60000 毫秒之间。'))
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise InstallError(_t('测速 URL 必须是无内嵌凭据的 HTTPS 地址。'))
    import domino_subscriptions
    manager = domino_subscriptions.Manager(sys.modules[__name__])
    active = manager.active_id()
    results = []
    if render and not as_json:
        human_header(_t('配置出网检测'), _t('{0} 个配置 · 逐节点 HTTPS 检测', len(manager.registry['items'])))
    if manager.registry['items']:
        _progress.start(configs=len(manager.registry['items']))
    def measure(item):
        _delay_cancelled(cancel)
        result = {'name': item['name'], 'active': item['id'] == active,
                  'total': item.get('node_count'), 'available': None, 'unavailable': None}
        if not item.get('revision'):
            result.update(status='uncached', message=_t('未缓存，请先更新或捕获配置。'))
        else:
            try:
                nodes = delay(config=item['name'], url=url, timeout_ms=timeout_ms, render=False,
                              _pool=node_pool, _cancel=cancel, _progress=_progress)
                available = sum(bool(node['ok']) for node in nodes)
                result.update(status='tested', total=len(nodes), available=available,
                              unavailable=len(nodes)-available)
            except (DomainError, OSError, ValueError, KeyError) as error:
                result.update(status='error', error_code=error.code if isinstance(error, DomainError) else 'CONFIG_DELAY_FAILED',
                              message=_t('配置加载或测速失败，请检查缓存和内核；当前配置未改变。'))
        _progress.config_done(item['name'])
        return result
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    cancel = Event()
    node_pool = ThreadPoolExecutor(max_workers=DELAY_NODE_WORKERS)
    config_pool = ThreadPoolExecutor(max_workers=DELAY_CONFIG_WORKERS)
    futures = []
    try:
        futures = [config_pool.submit(measure, item) for item in manager.registry['items']]
        results = _delay_results(futures)
    except BaseException:
        cancel.set()
        for future in futures:
            future.cancel()
        node_pool.shutdown(wait=False, cancel_futures=True)
        config_pool.shutdown(wait=True, cancel_futures=True)
        node_pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        config_pool.shutdown(wait=True)
        node_pool.shutdown(wait=True)
    _progress.close(final=True)
    if not render:
        return results
    if as_json:
        show(results, True)
    elif results:
        human_table([_t('配置名称'), _t('节点总数'), _t('可用'), _t('超时/不可用'), _t('检测状态')], [
            [('● ' if item['active'] else '') + item['name'], item['total'] if item['total'] is not None else '—',
             (str(item['available']), '32') if item['available'] is not None else '—',
             (str(item['unavailable']), '31' if item['unavailable'] else '2') if item['unavailable'] is not None else '—',
             _t('已检测') if item['status']=='tested' else item['message']] for item in results])
        human_row(_t('查看明细'), _t('domino test "配置名"；可用表示该节点本次 HTTPS 请求成功。'), wrap=True)
    else:
        human_row(_t('配置库为空'), _t('请先用 domino catch 捕获配置，或用 domino add 添加订阅。'), wrap=True)
    return results


def delay_usage(label, live, api):
    """Read current usage only for human output; never use a disposable core's choices."""
    usage = {'active':None, 'current':None, 'nodes':set(), 'paths':[], 'known':False}
    try:
        import domino_subscriptions
        manager = domino_subscriptions.Manager(sys.modules[__name__])
        active = manager.active_id()
        usage['current'] = next((item['name'] for item in manager.registry['items'] if item['id'] == active), None)
        usage['active'] = label is None or manager.find(label)['id'] == active
        if not usage['active']:
            return usage
        if label is not None:
            api = lambda route: api_json(route, timeout=1)
            live = proxy_inventory(api('/proxies')['proxies'], api=api)
        mode = api('/configs').get('mode')
        if mode not in ['rule', 'global', 'direct']:
            return usage
        details = current_proxy_paths(mode, live, include_nodes=True)
        usage.update(known=True, paths=[item['path'] for item in details],
                     nodes={item['node'] for item in details if item['node'] is not None})
    except (DomainError, OSError, ValueError, KeyError, TypeError):
        pass
    return usage


def delay(node=None, group=None, url='https://www.gstatic.com/generate_204', timeout_ms=5000, as_json=False, *, name=None, config=None, render=True, _api=None, _label=None, _pool=None, _cancel=None, _progress=None, ui_result=False):
    if _progress is None:
        with _DelayProgress(enabled=render and not as_json) as progress:
            progress.start()
            return delay(node, group, url, timeout_ms, as_json, name=name, config=config, render=render,
                         _api=_api, _label=_label, _pool=_pool, _cancel=_cancel, _progress=progress, ui_result=ui_result)
    if not 100 <= timeout_ms <= 60000:
        raise InstallError(_t('测速超时必须在 100–60000 毫秒之间。'))
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise InstallError(_t('测速 URL 必须是无内嵌凭据的 HTTPS 地址。'))
    if config is not None and any(value is not None for value in (name, node, group)):
        raise InstallError(_t('配置、节点和策略组只能选择一种测速对象。'))
    if _api is None and (config is not None or name is not None):
        import domino_subscriptions
        manager = domino_subscriptions.Manager(sys.modules[__name__])
        selected_config = config or next((item['name'] for item in manager.registry['items'] if item['name'] == name), None)
        if selected_config is not None:
            with isolated_delay_config(selected_config, **({'_cancel': _cancel} if _cancel is not None else {})) as isolated_api:
                return delay(url=url, timeout_ms=timeout_ms, as_json=as_json, render=render,
                             _api=isolated_api, _label=selected_config, _pool=_pool, _cancel=_cancel, _progress=_progress, ui_result=ui_result)
    api = _api or api_json
    live = proxy_inventory(api('/proxies')['proxies'], **({'api': api} if _api else {}))
    if name is not None:
        resolved = resolve_delay_name(name, live, _t('节点或策略组'))
        if isinstance(live[resolved].get('all'), list):
            group = resolved
        else:
            node = resolved
    if group is not None:
        group = resolve_delay_name(group, [name for name, item in live.items() if isinstance(item.get('all'), list)], _t('策略组'))
        names = live[group]['all']
        names=[label for name in names for label in ([name] if name in live else
            [label for label,item in live.items() if item.get('_domino_original')==name] or [name])]
    elif node is not None:
        names = [resolve_delay_name(node, live, _t('节点'))]
    else:
        names = sorted(key for key, item in live.items() if not isinstance(item.get('all'), list)
                       and key not in ['DIRECT','REJECT','REJECT-DROP','PASS','COMPATIBLE']
                       and item.get('type','').casefold() not in ['direct','reject','rejectdrop','pass','passrule','compatible'])
        if not names:
            raise InstallError(_t('没有可测速的节点；请运行 domino nodes 查看配置。'))
    from concurrent.futures import ThreadPoolExecutor
    _progress.nodes(_label, len(names))
    def test(name):
        _delay_cancelled(_cancel)
        query = urllib.parse.urlencode({'url': url, 'timeout': timeout_ms})
        route = live.get(name,{}).get('_domino_delay','/proxies/' + urllib.parse.quote(name, safe='') + '/delay')+'?'+query
        try:
            result = api(route, timeout=timeout_ms / 1000 + 2)
            row = {'name': name, 'delay_ms': result['delay'], 'ok': True}
        except (InstallError, OSError, ValueError, KeyError):
            row = {'name': name, 'delay_ms': None, 'ok': False}
        _progress.node_done(row['ok'])
        return row
    pool = _pool or ThreadPoolExecutor(max_workers=DELAY_NODE_WORKERS)
    futures = []
    try:
        for name in names:
            _delay_cancelled(_cancel)
            futures.append(pool.submit(test, name))
        results = _delay_results(futures, _cancel)
    except BaseException:
        for future in futures:
            future.cancel()
        if _pool is None:
            pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        if _pool is None:
            pool.shutdown(wait=True)
    if not render: return results
    _progress.close(final=True)
    if as_json:
        if ui_result:
            usage=delay_usage(_label,live,api)
            usage['nodes']=sorted(usage['nodes'])
            show({'results':results,'usage':usage,'configuration':_label},True)
        else:
            show(results, True)
    else:
        available=sum(bool(item['ok']) for item in results)
        usage = delay_usage(_label, live, api)
        config_label = ('● ' if usage['active'] is True else '') + _label if _label else None
        human_header(_t('节点测速'), (_t('配置 ') + config_label + '  ·  ' if config_label else '') + _t('{0} 节点  ·  {1} 可用  ·  {2} 超时/不可用', len(results), available, len(results) - available),
                     '32' if results and available == len(results) else '33')
        if _label:
            human_row(_t('配置状态'), (_t('● 当前使用中'), '1;32') if usage['active'] is True else
                      _t('未启用 · 当前使用 ') + (usage['current'] or _t('未关联配置库的配置')) if usage['active'] is False else _t('当前使用状态无法确认'))
        if usage['active']:
            for index, path in enumerate(usage['paths']):
                human_row(_t('当前代理') if index == 0 else '', (path, '1;32'))
            if not usage['known']:
                human_row(_t('当前节点'), _t('读取失败，本次不标记正在使用的节点'))
        human_table([_t('节点名称'),_t('延迟'),_t('使用状态')],[
            [(('● ' + item['name'], '1;32') if item['name'] in usage['nodes'] else item['name']),
             (str(item['delay_ms'])+' ms','32') if item['ok'] else (_t('超时/不可用'),'31'),
             (_t('当前选中'),'32') if item['name'] in usage['nodes'] else '—'] for item in results])
        print(_t('\n  ● 表示当前配置或策略组当前选中的节点；实际请求按代理模式和规则分流。'))
    return results


def collect_connections():
    data = api_json('/connections')
    values = []
    for item in data.get('connections') or []:
        metadata = item.get('metadata', {})
        values.append({'id':item.get('id'),'network':metadata.get('network'),
            'host':metadata.get('host') or metadata.get('destinationIP'),'port':metadata.get('destinationPort'),
            'process':metadata.get('process'),'rule':item.get('rule'),'chains':item.get('chains'),
            'upload':item.get('upload'),'download':item.get('download')})
    return {'uploadTotal':data.get('uploadTotal'),'downloadTotal':data.get('downloadTotal'),'connections':values}


def connections(close=None, close_all=False, as_json=False, *, render=True):
    if close or close_all:
        route = '/connections' + ('/' + urllib.parse.quote(close, safe='') if close else '')
        api_json(route, method='DELETE')
        if not render: return {'closed':close or 'all'}
        if as_json: show({'closed': close or 'all'},True)
        else:
            human_header(_t('连接'),_t('● 已关闭全部连接') if close_all else _t('● 已关闭指定连接'))
            if close: human_row(_t('连接 ID'),close)
        return
    data=collect_connections()
    values=data['connections']
    if not render: return data
    if as_json:
        show({'uploadTotal': data.get('uploadTotal'), 'downloadTotal': data.get('downloadTotal'), 'connections': values}, True)
    else:
        human_header(_t('连接'),_t('{0} 个活跃连接', len(values)))
        if not values: print(_t('  暂无活跃连接。'))
        for item in values:
            print('  ' + human_style(f"{item['host']}:{item['port']}") + '  ·  ' + human_text(item['network']) + '  ·  ' + human_text(item['rule']))
            print('    ' + human_text(' / '.join(item['chains'] or []) or '—') + '  ·  ID ' + human_text(item['id']))
            print()
    return data


def traffic_samples(watch=False, interval=1.0, count=0):
    if not .2 <= interval <= 60 or count < 0:
        raise InstallError(_t('流量刷新间隔必须为 0.2–60 秒；次数不能为负。'))
    previous = api_json('/connections')
    before = time.monotonic()
    samples = 0
    while True:
        time.sleep(interval)
        current = api_json('/connections')
        now = time.monotonic()
        elapsed = max(now - before, .001)
        up = current.get('uploadTotal', 0)
        down = current.get('downloadTotal', 0)
        result = {'upload_bytes_per_second': max(0, up - previous.get('uploadTotal', 0)) / elapsed,
                  'download_bytes_per_second': max(0, down - previous.get('downloadTotal', 0)) / elapsed,
                  'upload_total': up, 'download_total': down,
                  'connections': len(current.get('connections') or []), 'memory': current.get('memory')}
        yield result
        samples += 1
        if not watch or (count and samples >= count):
            break
        previous, before = current, now


def traffic_reading(current, previous=None, elapsed=0):
    """Dashboard rates stay unknown until a valid interval, including core resets."""
    up, down = current.get('uploadTotal', 0), current.get('downloadTotal', 0)
    valid = (previous is not None and elapsed > 0 and up >= previous.get('uploadTotal', 0)
             and down >= previous.get('downloadTotal', 0))
    return {'upload_bytes_per_second': (up-previous.get('uploadTotal', 0))/elapsed if valid else None,
            'download_bytes_per_second': (down-previous.get('downloadTotal', 0))/elapsed if valid else None,
            'upload_total': up, 'download_total': down,
            'connections': len(current.get('connections') or []), 'memory': current.get('memory')}


class _TrafficMonitor:
    def __init__(self, interval):
        from collections import deque
        from threading import Event, Lock
        self.interval, self.stop, self.lock = interval, Event(), Lock()
        self.history = deque(maxlen=120)
        self.sample, self.error, self.samples = None, None, 0
        self.thread = None

    def start(self):
        from threading import Thread
        self.thread = Thread(target=self._run, name='domino-traffic-monitor', daemon=True)
        self.thread.start()

    def _run(self):
        previous = before = None
        first = True
        while not self.stop.is_set():
            try:
                current = api_json('/connections', timeout=min(3, max(1, self.interval)))
                now = time.monotonic()
                sample = traffic_reading(current, previous, now-before if before is not None else 0)
                previous, before = {'uploadTotal': sample['upload_total'], 'downloadTotal': sample['download_total']}, now
                error = None
            except (DomainError, OSError, ValueError, TypeError, KeyError, AttributeError):
                previous = before = sample = None
                error = _t('控制接口不可用，正在重试…')
            if self.stop.is_set():
                break
            with self.lock:
                self.sample, self.error = sample, error
                self.history.append((sample['upload_bytes_per_second'], sample['download_bytes_per_second']) if sample else (None, None))
                # A healthy first read is a baseline, not a measured interval.
                self.samples += int(not first or error is not None)
            first = False
            if self.stop.wait(self.interval):
                break

    def snapshot(self):
        with self.lock:
            return self.sample, self.error, list(self.history), self.samples

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=3.2)


def traffic_graph(history, index, width):
    values = [sample[index] for sample in history[-max(1, width):]]
    peak = max((value for value in values if value is not None), default=None)
    bars = '▁▂▃▄▅▆▇█'
    return ''.join('·' if value is None else ' ' if value == 0 or peak == 0
                   else bars[min(7, int(value/peak*7))] for value in values), peak


def traffic_frame(sample, error, history, interval, columns):
    """The complete content shared by inline and full-screen displays."""
    def value(key, *, rate=False):
        number = sample.get(key) if sample else None
        return human_size(number, rate) if number is not None else '—'
    rows = [
        (_t('Domino · 流量监控'), 'title'),
        (_t('仅统计经过 Domino 的流量 · 每 {0:g} 秒刷新 · {1}', interval, time.strftime('%H:%M:%S')), 'muted'),
        ('', 'space'),
        (error or (_t('正在连接控制接口…') if sample is None else
                   _t('正在采样速率…') if sample['upload_bytes_per_second'] is None else _t('实时监控中')), 'error' if error else 'muted'),
        ('', 'space'),
        (_t('↑ 上传  ') + value('upload_bytes_per_second', rate=True), 'up'),
        (_t('↓ 下载  ') + value('download_bytes_per_second', rate=True), 'down'),
        (_t('累计上传  ') + value('upload_total') + _t('    累计下载  ') + value('download_total'), 'plain'),
        (_t('活跃连接  {0}    内核内存  ', sample['connections'] if sample else '—') + value('memory'), 'plain'),
        ('', 'space')]
    for index, label, style in [(0, _t('上传'), 'up'), (1, _t('下载'), 'down')]:
        graph, peak = traffic_graph(history, index, max(1, columns-3))
        rows += [(label + _t('近期趋势 · 峰值 ') + (human_size(peak, True) if peak is not None else '—'), 'muted'),
                 (graph, style)]
    rows += [('', 'space'), (_t('q / Esc / Ctrl+C 退出 · 累计值自内核启动计数'), 'muted')]
    return rows


def draw_traffic(screen, sample, error, history, interval, styles):
    import curses
    height, width = screen.getmaxyx()
    screen.erase()
    def line(y, text, style='plain'):
        if not 0 <= y < height or width < 3:
            return
        text = human_text(text)
        while text and human_width(text) > width-3:
            text = text[:-1]
        try:
            screen.addstr(y, 1, text, styles.get(style, 0))
        except curses.error:
            pass
    rows = traffic_frame(sample, error, history, interval, width)
    if height < len(rows):
        rows = [row for row in rows if row[1] != 'space']
    for y, (text, role) in enumerate(rows[:-1]):
        line(y, text, role)
    line(height-1, *rows[-1])
    screen.refresh()


def traffic_dashboard(interval=1.0, count=0):
    if not .2 <= interval <= 60 or count < 0:
        raise InstallError(_t('流量刷新间隔必须为 0.2–60 秒；次数不能为负。'))
    try:
        import curses
        import termios
    except ImportError:
        raise InstallError(_t('终端缺少全屏支持；可用 domino traffic --json 读取单次采样。')) from None
    try:
        terminal = sys.stdin.fileno()
        terminal_state = termios.tcgetattr(terminal)
    except (OSError, ValueError, termios.error):
        raise InstallError(_t('全屏流量监控需要交互终端；可用 domino traffic --json 读取单次采样。')) from None
    monitor = _TrafficMonitor(interval)
    def run(screen):
        styles = {'title': curses.A_BOLD, 'up': curses.A_BOLD, 'down': curses.A_BOLD, 'muted': curses.A_DIM}
        try: curses.curs_set(0)
        except curses.error: pass
        if curses.has_colors() and 'NO_COLOR' not in os.environ:
            try:
                curses.start_color()
                curses.use_default_colors()
                for index, (name, color) in enumerate([('title', curses.COLOR_CYAN), ('up', curses.COLOR_GREEN),
                        ('down', curses.COLOR_CYAN), ('error', curses.COLOR_RED)], 1):
                    curses.init_pair(index, color, -1)
                    styles[name] = curses.color_pair(index) | curses.A_BOLD
            except curses.error:
                pass
        screen.timeout(100)
        monitor.start()
        while True:
            sample, error, history, samples = monitor.snapshot()
            draw_traffic(screen, sample, error, history, interval, styles)
            if count and samples >= count:
                return
            if screen.getch() in (ord('q'), ord('Q'), 27, 3):
                return
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
    except curses.error:
        raise InstallError(_t('无法打开流量监控终端；可用 domino traffic --json 读取单次采样。')) from None
    finally:
        # Preserve caller input settings as well as curses' screen cleanup.
        try: termios.tcsetattr(terminal, termios.TCSANOW, terminal_state)
        except (OSError, termios.error): pass
        monitor.close()


def traffic_compact(interval=1.0, count=0, *, _input=None, _output=None):
    """An inline application owns only its rows and retains the final complete frame."""
    if not .2 <= interval <= 60 or count < 0:
        raise InstallError(_t('流量刷新间隔必须为 0.2–60 秒；次数不能为负。'))
    import asyncio
    try:
        import domino_tui
        domino_tui.load_toolkit()
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
    except (ImportError, RuntimeError):
        raise InstallError(_t('终端显示组件不可用，请更新 Domino 安装包；全屏显示可使用 domino traffic --full。')) from None
    monitor = _TrafficMonitor(interval)
    bindings = KeyBindings()
    @bindings.add('q')
    @bindings.add('Q')
    @bindings.add('escape')
    @bindings.add('c-c')
    def exit_panel(event):
        event.app.exit()
    def content():
        sample, error, history, _ = monitor.snapshot()
        size = app.output.get_size()
        rows = traffic_frame(sample, error, history, interval, size.columns)
        if size.rows < len(rows)+1:
            rows = [row for row in rows if row[1] != 'space']
        fragments = []
        for index, (text, role) in enumerate(rows):
            if index: fragments.append(('', '\n'))
            fragments.append(('class:'+role, ' ' + human_text(text)))
        return fragments
    styles = {} if 'NO_COLOR' in os.environ else {
        'title': 'bold ansicyan', 'up': 'bold ansigreen', 'down': 'bold ansicyan',
        'error': 'ansired', 'muted': 'ansibrightblack'}
    app = Application(layout=Layout(Window(FormattedTextControl(content), wrap_lines=True,
                          dont_extend_height=True, always_hide_cursor=True)),
                      key_bindings=bindings, style=Style.from_dict(styles), full_screen=False,
                      erase_when_done=False, input=_input, output=_output)
    async def refresh():
        while True:
            app.invalidate()
            if count and monitor.snapshot()[3] >= count:
                app.exit()
                return
            await asyncio.sleep(.1)
    try:
        monitor.start()
        app.run(pre_run=lambda: app.create_background_task(refresh()))
    except KeyboardInterrupt:
        pass
    finally:
        monitor.close()


def traffic(watch=False, interval=1.0, count=0, as_json=False, *, dashboard=False, compact=False):
    if dashboard and not as_json:
        return traffic_dashboard(interval, count)
    if compact and not as_json:
        return traffic_compact(interval, count)
    if not as_json:
        human_header(_t('流量'),_t('仅统计经过 Domino 的流量'))
    for result in traffic_samples(watch,interval,count):
        if as_json:
            print(json.dumps(result), flush=True)
        else:
            print('  ↑ ' + human_size(result['upload_bytes_per_second'],True) + '  ↓ ' + human_size(result['download_bytes_per_second'],True)
                  + _t('  ·  累计 ↑') + human_size(result['upload_total']) + ' ↓' + human_size(result['download_total']) + _t('  ·  {0} 连接', result['connections']),flush=True)


def custom_rules_path():
    path = HOME / '.config/domino/rules.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise InstallError(_t('自定义规则路径不能是符号链接。'))
    return path


def custom_rules():
    path = custom_rules_path()
    if not path.exists():
        return []
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise InstallError(_t('自定义规则文件格式无效。'))
    items = value.get('prepend')
    if value.get('schema') != 1 or not isinstance(items, list) or any(not isinstance(v, str) for v in items):
        raise InstallError(_t('自定义规则文件格式无效。'))
    return items


def base_rules(data, config):
    path = data / 'rules-base.json'
    items = json.loads(path.read_text()) if path.is_file() else config.get('rules', [])
    if not isinstance(items, list) or any(not isinstance(v, str) for v in items):
        raise InstallError(_t('基础规则必须为字符串列表。'))
    return items


def compose_custom_rules(config, prepend=None):
    prepend = custom_rules() if prepend is None else prepend
    base = config.get('rules', [])
    if not isinstance(base, list) or any(not isinstance(v, str) for v in base):
        raise InstallError(_t('基础规则必须为字符串列表。'))
    return dict(config, rules=list(dict.fromkeys(prepend)) + [v for v in base if v not in prepend])


def prepare_custom_rules(data):
    path = data / 'config.json'
    config = json.loads(path.read_text())
    candidate = compose_custom_rules(config)
    write_private(data / 'rules-base.json', json.dumps(config.get('rules', []), ensure_ascii=False))
    write_private(path, json.dumps(candidate, ensure_ascii=False, indent=2))


def rule_selections():
    return {name: v['now'] for name, v in api_json('/proxies')['proxies'].items()
            if str(v.get('type', '')).lower() in ['selector', 'select'] and v.get('now')}


def restore_rule_selections(selections):
    live = api_json('/proxies')['proxies']
    for name, value in selections.items():
        if value in live.get(name, {}).get('all', []):
            api_json('/proxies/' + urllib.parse.quote(name, safe=''), {'name': value})


def edit_rule(value, remove=False, as_json=False, *, render=True, validate_only=False):
    value = value.strip()
    if not value or len(value) > 8192 or ',' not in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise InstallError(_t('请提供单行 Mihomo 规则，例如 DOMAIN-SUFFIX,example.com,DIRECT。'))
    saved = custom_rules()
    if remove and value not in saved:
        raise InstallError(_t('未找到该自定义规则；使用 domino rules --custom 查看原文。'))
    if not remove and value in saved:
        if not render: return {'changed':False,'rule':value,'message':_t('该自定义规则已存在。')}
        if as_json: show({'changed': False, 'rule': value, 'message': _t('该自定义规则已存在。')},True)
        else:
            human_header(_t('自定义规则'),_t('● 规则已存在，无需重复添加'))
            human_row(_t('规则'),value)
        return
    app, _ = current_installation()
    data = app / 'data'
    path = data / 'config.json'
    if not path.is_file() or not (app / 'mihomo').is_file():
        raise InstallError(_t('尚未安装内核，请先运行安装程序。'))
    config = json.loads(path.read_text())
    runtime = api_json('/configs')
    selections = rule_selections()
    base = base_rules(data, config)
    prepend = [v for v in saved if v != value] if remove else [value, *saved]
    candidate = compose_custom_rules(dict(config, rules=base), prepend)
    for key in ['mode', 'log-level']:
        if key in runtime:
            candidate[key] = runtime[key]
    pending = data / ('.rules-' + uuid.uuid4().hex + '.json')
    try:
        write_private(pending, json.dumps(candidate, ensure_ascii=False))
        try:
            run([str(app / 'mihomo'), '-t', '-d', str(data), '-f', str(pending)],
                capture_output=True, text=True, timeout=90)
        except (InstallError, OSError):
            raise InstallError(_t('规则校验失败，请检查语法、出口名称及引用的资源；原配置未修改。')) from None
        if validate_only:
            return {'would_change':True,'rule':value}
        paths = [path, data / 'rules-base.json', custom_rules_path()]
        before = [p.read_bytes() if p.exists() else None for p in paths]
        backup = BACKUPS / ('rules-' + uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        for index, content in enumerate(before):
            if content is not None:
                write_private(backup / f'file-{index}', content)
        write_private(backup / 'rules-state.json', json.dumps({'schema': 1, 'paths': [str(p) for p in paths],
                      'exists': [content is not None for content in before]}))
        live_dirty = False
        try:
            write_private(paths[2], json.dumps({'schema': 1, 'prepend': prepend}, ensure_ascii=False, indent=2))
            write_private(paths[1], json.dumps(base, ensure_ascii=False))
            write_private(path, pending.read_bytes())
            live_dirty = True
            api_json('/configs?force=true', {'path': str(path)}, method='PUT', timeout=45)
            restore_rule_selections(selections)
            api_json('/rules')
        except BaseException:
            try:
                for item, content in zip(paths, before):
                    if content is None:
                        item.unlink(missing_ok=True)
                    else:
                        write_private(item, content)
                if live_dirty:
                    api_json('/configs?force=true', {'path': str(path)}, method='PUT', timeout=45)
                    restore_rule_selections(selections)
            except BaseException:
                raise InstallError(_t('规则应用失败且恢复未完成；备份：') + str(backup),code='RECOVERY_INCOMPLETE',effect='unknown') from None
            raise InstallError(_t('规则未应用，已恢复原配置；备份：') + str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
        result = {'changed': True, 'action': 'remove' if remove else 'add', 'rule': value,
                  'mode': candidate.get('mode', 'rule'), 'backup': str(backup)}
        if not render: return result
        if as_json:
            show(result, True)
        else:
            human_header(_t('自定义规则'),_t('● 已删除') if remove else _t('● 已新增并置顶'))
            human_row(_t('规则'),value)
            if result['mode'] != 'rule':
                human_row(_t('生效条件'),_t('切换规则模式：domino mode --set rule'))
            human_row(_t('保存'),_t('已持久保存，后续新连接使用当前配置'))
            human_row(_t('备份'),backup)
        return result
    finally:
        pending.unlink(missing_ok=True)


def collect_rules(match=None, limit=50, custom=False):
    if not 1 <= limit <= 100000:
        raise InstallError(_t('规则显示数量必须在 1–100000 之间。'))
    if custom:
        values = custom_rules()
        if match:
            values = [v for v in values if match.lower() in v.lower()]
        return {'total':len(values),'rules':values[:limit],'source':'custom'}
    values = api_json('/rules').get('rules', [])
    if match:
        values = [item for item in values if match.lower() in json.dumps(item, ensure_ascii=False).lower()]
    return {'total':len(values),'rules':values[:limit]}


def rules(match=None, limit=50, as_json=False, custom=False):
    result=collect_rules(match,limit,custom)
    if as_json:
        show(result, True)
    elif custom:
        human_header(_t('自定义规则'),_t('{0} 条  ·  从上到下匹配', result['total']))
        for value in result['rules']: print('  '+human_text(value))
        if not result['rules']: print(_t('  暂无自定义规则。'))
    else:
        human_header(_t('分流规则'),_t('{0} 条匹配  ·  显示 {1} 条', result['total'], len(result['rules'])))
        if result['rules']: human_table([_t('类型'),_t('匹配内容'),_t('出口')],[[item.get('type'),item.get('payload'),item.get('proxy')] for item in result['rules']])
        else: print(_t('  没有匹配的规则。'))
    return result


def collect_providers(kind='proxy', update=None):
    route = '/providers/' + ('proxies' if kind == 'proxy' else 'rules')
    data = api_json(route).get('providers', {})
    if update:
        if update not in data:
            raise InstallError(_t('没有找到指定 provider。'))
        if str(data[update].get('vehicleType', '')).lower() not in ['http', 'file']:
            raise InstallError(_t('该集合是内置节点快照，没有独立订阅更新地址；请使用 configs add/switch 管理完整配置订阅。'))
        api_json(route + '/' + urllib.parse.quote(update, safe=''), method='PUT', timeout=60)
        data = api_json(route).get('providers', {})
    result = []
    for name, item in data.items():
        result.append({'name': name, 'type': item.get('type'), 'vehicleType': item.get('vehicleType'),
                       'updatedAt': item.get('updatedAt'),
                       'count': len(item.get('proxies', [])) if kind == 'proxy' else item.get('ruleCount')})
    return result


def providers(kind='proxy', update=None, as_json=False):
    result=collect_providers(kind,update)
    if as_json: show(result,True)
    else:
        human_header(_t('节点集合') if kind == 'proxy' else _t('规则集合'),_t('{0} 个集合', len(result)) + (_t('  ·  已更新 ')+human_text(update) if update else ''))
        if result:
            origins={'HTTP':_t('在线'),'File':_t('本地文件'),'Compatible':_t('内置'),'Inline':_t('内嵌')}
            human_table([_t('名称'),_t('数量'),_t('来源'),_t('更新时间')],[[item['name'],item['count'],origins.get(item['vehicleType'],item['vehicleType']),human_time(item['updatedAt'])] for item in result])
        else: print(_t('  暂无集合。'))
    return result


def shell_environment(unset=False):
    names = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY']
    if unset:
        print('export DOMINO_SHELL_MODE=manual')
        print('unset ' + ' '.join(names))
        return
    app, _ = current_installation()
    config = json.loads((app / 'data/config.json').read_text())
    number = config['mixed-port']
    if type(number) is not int or not 1024 <= number <= 65535:
        raise InstallError(_t('代理端口无效。'))
    print('export DOMINO_SHELL_MODE=manual')
    for name in names[:4]:
        print(f'export {name}=http://127.0.0.1:{number}')
    for name in names[4:6]:
        print(f'export {name}=socks5h://127.0.0.1:{number}')
    for name in names[6:]:
        print(f'export {name}=localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16')


def shell_proxy(action=None, as_json=False, *, render=True):
    import domino_shell
    app, _ = current_installation()
    if action not in (None, 'on', 'off'):
        raise InstallError(_t('终端代理动作必须是 on 或 off。'), code='INVALID_ARGUMENT')
    try:
        if action:
            if not (app / 'data/config.json').is_file():
                raise InstallError(_t('请先安装 Domino，再设置终端代理。'))
            policy = domino_shell.read_policy(app)
            if action == 'on':
                domino_shell.proxy_port(app)
            enabled = action == 'on'
            if policy['enabled'] != enabled:
                write_private(app / 'shell-policy.json', json.dumps({'version': 1, 'enabled': enabled}))
        result = domino_shell.status(app, HOME)
    except (ValueError, OSError) as error:
        raise InstallError(_t('终端代理策略读取或写入失败；请检查安装与策略文件。'), code='SHELL_POLICY_INVALID') from error
    if render:
        if as_json:
            show(result, True)
        else:
            enabled = result['enabled']
            human_header(_t('终端代理'), _t('● 策略已开启') if enabled else _t('● 策略已关闭'),
                         '32' if enabled else '31')
            human_row(_t('作用'), _t('让终端（Terminal）中支持代理环境变量的程序使用代理'), wrap=True)
            human_row(_t('操作'), _t('使用 Domino 代理') if enabled else _t('恢复原代理设置，保留手动修改'))
            try:
                number = domino_shell.proxy_port(app)
            except ValueError:
                number = None
            human_row(_t('代理端口'), str(number) if number else _t('未配置'))
            print()
            human_row(_t('开启目标'), _t('以下为开启 Domino 终端代理时设置的变量'), wrap=True)
            desired = domino_shell._desired(number) if number else {}
            for lower in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
                human_row(lower + ' / ' + lower.upper(), desired.get(lower, _t('未配置')), wrap=True)
            if action is None:
                print()
                human_row(_t('当前环境'), _t('本次命令继承的已导出变量（同步前）；地址不含账号密码'), wrap=True)
                for lower in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
                    upper = lower.upper()
                    names = [lower] if os.environ.get(lower) == os.environ.get(upper) else [lower, upper]
                    for name in names:
                        label = lower + ' / ' + upper if len(names) == 1 else name
                        human_row(label, domino_shell.display_value(name, os.environ.get(name)), wrap=True)
            print()
            human_row(_t('生效'), _t('已接入终端返回命令行后同步；on/off 后用 domino shell status 查看'), wrap=True)
            if not result['integration_available']:
                human_row(_t('终端接入'), _t('未检测到完整集成；安装后加载 ~/.config/domino/proxy.env'), wrap=True)
    return result


def overview():
    """Fast, read-only UI snapshot; never run an external connectivity probe."""
    app, service = current_installation()
    path = app / 'data/config.json'
    result = {'installed': path.is_file(), 'active': False, 'reachable': False, 'groups': [],
              'node_count': None, 'connections': 0, 'upload_total': 0, 'download_total': 0,
              'stats_available': False, 'client': 'Domino', 'service': service.name}
    if not path.is_file():
        result['error'] = _t('尚未安装运行环境，请先运行安装程序。')
        show(result, True)
        return
    config = json.loads(path.read_text())
    manifest_path = app / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    result.update(mode=config.get('mode', 'rule'), proxy_port=config['mixed-port'], version=manifest.get('version'), subscription=subscription_name(app),
                  awaiting_subscription=subscription_pending(app, config))
    if manifest.get('platform') == 'darwin':
        result['service'] = 'local.domino.mihomo'
        import domino_macos
        result['system_proxy'] = domino_macos.system_proxy_overview(config['mixed-port'])
    elif sys.platform == 'linux':
        import domino_linux
        result['system_proxy'] = domino_linux.system_proxy_overview(config['mixed-port'])
    result['active'] = systemctl('is-active')
    try:
        runtime = api_json('/configs', timeout=1.5)
        proxies = proxy_inventory(api_json('/proxies', timeout=1.5)['proxies'])
        stats = api_json('/connections', timeout=1.5)
        result.update(reachable=True, active=True, stats_available=True, node_count=0, mode=runtime.get('mode', result['mode']),
                      connections=len(stats.get('connections') or []),
                      upload_total=stats.get('uploadTotal', 0), download_total=stats.get('downloadTotal', 0),
                      memory=stats.get('memory'),log_level=runtime.get('log-level'))
        for name, item in proxies.items():
            if isinstance(item.get('all'), list):
                if name == 'GLOBAL' and result['mode'] != 'global':
                    continue
                result['groups'].append({'name': name, 'type': item.get('type'), 'current': item.get('now'),
                                          'selectable': str(item.get('type', '')).lower() in ['selector', 'select'],
                                          'choices': item['all']})
            elif name not in ['DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'COMPATIBLE']:
                result['node_count'] += 1
        order = {item['name']: index for index, item in enumerate(config.get('proxy-groups', []))}
        result['groups'].sort(key=lambda item: -1 if item['name'] == 'GLOBAL' else order.get(item['name'], len(order)))
    except (InstallError, OSError, ValueError, KeyError):
        result['error'] = _t('控制接口暂不可用；可使用 /start 或 /logs 检查。')
    show(result, True)


def subscription_arguments(parser):
    actions = parser.add_mutually_exclusive_group()
    for flag, help_text in [
        ('add', _t('保存命名订阅；不切换当前配置')),
        ('update', _t('更新订阅；当前订阅校验成功后自动应用')),
        ('use', _t('切换订阅；首次使用时自动下载')),
        ('remove', _t('删除非当前订阅')),
        ('rename', _t('重命名，配合 --new-name')),
        ('set-url', _t('修改地址，配合 --url')),
        ('import-current', _t('保存当前配置为本地快照')),
    ]:
        actions.add_argument('--' + flag, metavar='NAME', help=help_text)
    actions.add_argument('--update-all', action='store_true', help=_t('更新全部在线订阅'))
    actions.add_argument('--refresh-usage', action='store_true', help=_t('仅刷新订阅套餐流量；不更新或切换运行配置'))
    parser.add_argument('--url', help=_t('完整配置 HTTPS 订阅地址；省略时隐藏输入'))
    parser.add_argument('--new-name')
    parser.add_argument('--json', action='store_true')


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('install')
    p.add_argument('bundle')
    p = sub.add_parser('status')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('doctor')
    p.add_argument('--url', required=True)
    p.add_argument('--insecure', action='store_true')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('nodes')
    p.add_argument('--group')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('select')
    p.add_argument('--group', required=True)
    p.add_argument('--node', required=True)
    p = sub.add_parser('rollback')
    p.add_argument('--backup')
    p.add_argument('--non-interactive', action='store_true')
    p = sub.add_parser('uninstall')
    p.add_argument('--yes', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--non-interactive', action='store_true')
    p = sub.add_parser('env')
    p.add_argument('--unset', action='store_true')
    sub.add_parser('overview')
    sub.add_parser('catch-options')
    sub.add_parser('agent')
    p=sub.add_parser('scan')
    p.add_argument('--source')
    p.add_argument('--json',action='store_true')
    p.add_argument('--columns',type=int,help=argparse.SUPPRESS)
    for action in ['mode', 'log-level']:
        p = sub.add_parser(action)
        p.add_argument('--set', choices=['rule', 'global', 'direct'] if action == 'mode' else ['debug', 'info', 'warning', 'error', 'silent'])
        p.add_argument('--json', action='store_true')
    p = sub.add_parser('delay')
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--name')
    choice.add_argument('--config')
    choice.add_argument('--summary', action='store_true')
    choice.add_argument('--all', action='store_true')
    choice.add_argument('--node')
    choice.add_argument('--group')
    p.add_argument('--url', default='https://www.gstatic.com/generate_204')
    p.add_argument('--timeout', type=int, default=5000)
    p.add_argument('--json', action='store_true')
    p.add_argument('--progress', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--ui-result',action='store_true',help=argparse.SUPPRESS)
    p = sub.add_parser('connections')
    choice = p.add_mutually_exclusive_group()
    choice.add_argument('--close')
    choice.add_argument('--all', action='store_true')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('traffic')
    p.add_argument('--watch', action='store_true')
    display = p.add_mutually_exclusive_group()
    display.add_argument('--dashboard', action='store_true', help=argparse.SUPPRESS)
    display.add_argument('--compact', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--count', type=int, default=0)
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('rules')
    mutation = p.add_mutually_exclusive_group()
    mutation.add_argument('--add', dest='add_rule')
    mutation.add_argument('--remove', dest='remove_rule')
    p.add_argument('--custom', action='store_true')
    p.add_argument('--match')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('providers')
    p.add_argument('--kind', choices=['proxy', 'rule'], default='proxy')
    p.add_argument('--update')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('proxy')
    p.add_argument('--set', choices=['on', 'off'])
    p.add_argument('--service')
    p.add_argument('--json', action='store_true')
    p.add_argument('--non-interactive', action='store_true')
    p = sub.add_parser('shell')
    p.add_argument('--set', choices=['on', 'off'])
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('configs')
    subscription_arguments(p)
    for action in ['start', 'stop', 'restart', 'logs']:
        p = sub.add_parser(action)
        p.add_argument('--non-interactive', action='store_true')
        if action == 'logs':
            p.add_argument('--lines', type=int, default=100)
            p.add_argument('--follow', action='store_true')
    sub.add_parser('restart-vscode')
    for child in sub.choices.values():
        child.add_argument('--color',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    formatted = args.action in ['status','nodes','select','rollback','mode','log-level','delay','connections',
                               'traffic','rules','providers','proxy','shell','configs','start','stop','restart','scan','uninstall']
    live_traffic = getattr(args,'dashboard',False) or getattr(args,'compact',False)
    with human_output(formatted and not getattr(args,'json',False) and not live_traffic,color=True if args.color else None):
        return _run_command(args)


def _run_command(args):
    try:
        if args.action=='catch-options':
            import domino_cli
            items=[]
            for path in domino_cli.capture_candidates(include_saved=True):
                identity=domino_cli.source_identity(path)
                items.append({'path':str(path),'name':domino_cli.source_name(path,identity) or path.name})
            show(items,True)
            return
        if args.action=='scan':
            import domino_cli
            return domino_cli.inspect_source(args) if args.source else domino_cli.list_sources(args)
        if args.action in ['install', 'rollback', 'configs', 'rules','agent','delay','traffic','uninstall']:
            def cancelled(*_):
                raise KeyboardInterrupt
            signal.signal(signal.SIGHUP, cancelled)
            signal.signal(signal.SIGTERM, cancelled)
        if args.action=='agent':
            import domino_agent_backend
            return domino_agent_backend.run(sys.modules[__name__])
        if args.action == 'install':
            with deployment_lock():
                if sys.platform == 'darwin':
                    import domino_macos
                    domino_macos.install(sys.modules[__name__], Path(args.bundle).resolve())
                else:
                    install(Path(args.bundle).resolve())
        elif args.action == 'uninstall':
            import domino_uninstall
            return domino_uninstall.uninstall(sys.modules[__name__], yes=args.yes,
                non_interactive=args.non_interactive, dry_run=args.dry_run)
        elif args.action == 'status':
            return status(args.json)
        elif args.action == 'doctor':
            if sys.platform != 'darwin':
                raise InstallError(_t('doctor 当前仅支持 macOS。'))
            import domino_doctor
            domino_doctor.doctor(sys.modules[__name__], args.url, insecure=args.insecure, as_json=args.json)
        elif args.action == 'nodes':
            nodes(args.group, args.json)
        elif args.action == 'select':
            with deployment_lock():
                select_node(args.group, args.node)
        elif args.action == 'rollback':
            with deployment_lock():
                if sys.platform == 'darwin':
                    import domino_macos
                    domino_macos.rollback(sys.modules[__name__], args.backup)
                else:
                    rollback(args.backup, args.non_interactive)
        elif args.action in ['mode', 'log-level']:
            with deployment_lock():
                set_option(args.action, args.set, args.json)
        elif args.action == 'delay':
            with _DelayProgress(enabled=not args.json or args.ui_result, force=args.progress, configs=args.summary) as progress:
                if args.summary:
                    delay_summary(args.url, args.timeout, args.json, _progress=progress)
                else:
                    progress.start()
                    delay(args.node, args.group, args.url, args.timeout, args.json,
                          name=args.name, config=args.config, _progress=progress,ui_result=args.ui_result)
        elif args.action == 'connections':
            connections(args.close, args.all, args.json)
        elif args.action == 'traffic':
            traffic(args.watch, args.interval, args.count, args.json, dashboard=args.dashboard, compact=args.compact)
        elif args.action == 'rules':
            if args.add_rule is not None or args.remove_rule is not None:
                with deployment_lock():
                    edit_rule(args.add_rule if args.add_rule is not None else args.remove_rule,
                              remove=args.remove_rule is not None, as_json=args.json)
            else:
                rules(args.match, args.limit, args.json, args.custom)
        elif args.action == 'providers':
            providers(args.kind, args.update, args.json)
        elif args.action == 'proxy':
            with deployment_lock():
                system_proxy(args.set,args.service,args.json,args.non_interactive)
        elif args.action == 'shell':
            if args.set:
                with deployment_lock():
                    shell_proxy(args.set, args.json)
            else:
                shell_proxy(as_json=args.json)
        elif args.action == 'env':
            shell_environment(args.unset)
        elif args.action == 'configs':
            if '__file__' not in globals() or not Path(__file__).with_name('domino_subscriptions.py').exists():
                sys.path.insert(0, str(APP / 'cli'))
            try:
                import domino_subscriptions
            except ImportError:
                raise InstallError(_t('目标管理程序缺少订阅组件，请先更新该设备的 Domino。')) from None
            if (args.use or args.update or args.update_all) and custom_rules() and not getattr(domino_subscriptions, 'CUSTOM_RULES', False):
                raise InstallError(_t('目标订阅组件版本过旧，请先更新该设备的 Domino，以保留自定义规则。'))
            with deployment_lock():
                domino_subscriptions.run(sys.modules[__name__], args)
        elif args.action == 'overview':
            overview()
        elif args.action in ['start', 'stop', 'restart', 'logs']:
            with deployment_lock() if args.action != 'logs' else nullcontext():
                service_action(args.action, args.non_interactive,
                               getattr(args, 'lines', 100), getattr(args, 'follow', False))
        else:
            restart_vscode()
        return 0
    except (InstallError, RuntimeError, OSError, ValueError, KeyError) as exc:
        message = str(exc) if isinstance(exc, (InstallError, RuntimeError)) else type(exc).__name__
        print(_t('失败：') + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(_t('已取消。'), file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
