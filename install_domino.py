#!/usr/bin/env python3
"""Target-side installer; standard library only. No credential values in output."""
from __future__ import annotations

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
                raise InstallError('目标已有另一个修改操作在执行，请稍后重试。',code='LOCKED',exit_code=6,retryable=True) from None
        yield


def run(args, **kwargs):
    try:
        return subprocess.run(args, check=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        if args[:3]==['sudo','-n','-v']:
            raise InstallError('需要预先授权 sudo；机器接口不会询问密码。',code='AUTH_REQUIRED',exit_code=4) from None
        raise InstallError(f'远端步骤失败（退出码 {exc.returncode}）。') from None
    except subprocess.TimeoutExpired:
        raise InstallError('远端步骤超时。') from None


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
            raise InstallError('代理环境标记不完整，停止修改启动文件。')
        if begin in old:
            start = old.index(begin)
            if old.index(end) < start:
                raise InstallError('代理环境标记顺序无效。')
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
            print('VS Code/Codex 旧进程已退出，PID：' + str(stopped))
            return
        time.sleep(0.5)
    raise InstallError('代理已部署，但旧 VS Code 进程未退出；未强制终止：' + str(remaining))


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
        raise InstallError('同名服务不是本工具管理的，停止以免覆盖。')


def owned_installations():
    for legacy in (False, True):
        if legacy:
            with legacy_layout():
                owned_service()
        else:
            owned_service()
    if APP.is_symlink() or LEGACY_APP.is_symlink():
        raise InstallError('安装目录是符号链接，停止。')


def controller(data, route, payload=None, *, method=None, timeout=3):
    config = json.loads((data / 'config.json').read_text())
    address = config.get('external-controller', '')
    if not re.fullmatch(r'127\.0\.0\.1:\d+', address):
        raise InstallError('控制接口地址不是预期的回环地址。')
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
        raise InstallError('控制接口拒绝请求。',code=code,exit_code=exit_code,details={'http_status':error.code}) from None
    except (TimeoutError,urllib.error.URLError) as error:
        timeout_error=isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError)
        raise InstallError('控制接口请求超时。' if timeout_error else '无法连接控制接口。',
            code='TIMEOUT' if timeout_error else 'CONTROLLER_UNREACHABLE',exit_code=7 if timeout_error else 5,
            retryable=True,effect='unknown' if writing else 'none') from None


def probe(proxy_port, url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise InstallError('出网检查 URL 无效。')
    result = run(['curl', '--noproxy', '', '--proxy', f'http://127.0.0.1:{proxy_port}',
                  '--fail', '--silent', '--show-error', '--connect-timeout', '8',
                  '--max-time', '25', '--proto', '=https', '--config', '-'],
                 input='url = ' + json.dumps(url) + '\n', capture_output=True, text=True, timeout=30)
    country = next((s[4:] for s in result.stdout.splitlines() if re.fullmatch(r'loc=[A-Z]{2}', s)), None)
    return {'healthy': True, 'exit_country': country}


def _snapshot(kind='deploy', backup=None):
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
            raise InstallError('受管理的环境文件是符号链接，未覆盖。')
        state['files'][name] = {'exists': path.exists()}
        if path.exists():
            mode = path.stat().st_mode & 0o777
            write_private(backup / f'file-{i}', path.read_bytes(), mode)
            state['files'][name]['mode'] = mode
    cli = HOME / '.local/bin/domino'
    state['cli_file'] = {'exists': cli.exists()}
    if cli.exists():
        state['cli_file']['mode'] = cli.stat().st_mode & 0o777
        write_private(backup / 'cli-launcher', cli.read_bytes(), state['cli_file']['mode'])
    write_private(backup / 'snapshot.json', json.dumps(state))
    return backup


def snapshot(kind='deploy'):
    backup = _snapshot(kind)
    # Publish only after both installation layouts and the external registry are captured.
    pending = backup / 'snapshot.pending'
    (backup / 'snapshot.json').rename(pending)
    with legacy_layout():
        _snapshot(kind, backup / 'legacy')
    import domino_subscriptions
    domino_subscriptions.snapshot_registry(sys.modules[__name__], backup)
    pending.rename(backup / 'snapshot.json')
    return backup


def _restore(backup):
    state = json.loads((backup / 'snapshot.json').read_text())
    if state.get('schema') != 1 or set(state['files']) != set(ENV_FILES):
        raise InstallError('备份格式无效，未恢复。')
    owned_service()
    # Restore the whole user-level app and environment, including first-install failure.
    if SERVICE.exists():
        sudo('systemctl', 'stop', SERVICE.name)
    if APP.exists():
        if APP.is_symlink():
            raise InstallError('安装目录是符号链接，停止恢复。')
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
        if item['exists']:
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
        raise InstallError('恢复未完成；保留的完整备份：' + str(backup),
                           code='RECOVERY_INCOMPLETE', effect='unknown') from None


def _restore_installations(backup):
    owned_installations()
    state = json.loads((backup / 'snapshot.json').read_text())
    expected_files = LEGACY_ENV_FILES if backup.parent == LEGACY_BACKUPS else ENV_FILES
    if state.get('schema') != 1 or set(state['files']) != set(expected_files):
        raise InstallError('备份格式无效，未恢复。')
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
        raise InstallError('用户或目录名称不适合自动生成 systemd 服务。')
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
    for name in ['.bashrc', '.zshrc']:
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
    write_private(home / '.config/domino/proxy.env', domino_shell.integration(app, sys.executable, legacy_port))
    body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
    names = ['.bashrc', '.zshrc']
    if linux:
        names.append('.vscode-server/server-env-setup')
    for name in names:
        path = home / name
        old = path.read_text() if path.exists() else ('#!/bin/sh\n' if name.endswith('server-env-setup') else '')
        mode = path.stat().st_mode & 0o777 if path.exists() else (0o700 if name.endswith('server-env-setup') else 0o600)
        write_private(path, managed_block(old, body), mode)


def configure_environment(proxy_port, *, legacy_port=None):
    configure_shell_environment(APP, HOME, linux=True, legacy_port=legacy_port)


def install_cli(bundle):
    if not (bundle / 'cli').is_dir():
        return
    shutil.copytree(bundle / 'cli', APP / 'cli')
    launcher = f'''#!/usr/bin/env python3
{CLI_MARKER}
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path.home() / '.local/share/domino/cli'))
runpy.run_module('domino_cli', run_name='__main__')
'''
    write_private(HOME / '.local/bin/domino', launcher, 0o700)


def owned_cli(path):
    if path.is_symlink():
        return False
    if not path.exists():
        return True
    text = path.read_text()
    # Accept our own launcher and the console entry point installed from our wheel.
    return CLI_MARKER in text or ('from domino_cli import main' in text and 'sys.exit(main())' in text)


def install(bundle):
    if os.getuid() == 0:
        raise InstallError('请用普通 SSH 用户部署，脚本只为系统服务步骤调用 sudo。')
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('schema') != 1:
        raise InstallError('安装包版本不受支持。')
    arch = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}.get(platform.machine())
    if arch != manifest.get('arch'):
        raise InstallError('安装包架构与目标设备不一致。')
    proxy_port, api_port = manifest['proxy_port'], manifest['api_port']
    if any(not isinstance(p, int) or isinstance(p, bool) or not 1024 <= p <= 65535 for p in [proxy_port, api_port]) or proxy_port == api_port:
        raise InstallError('安装包端口配置无效。')
    config = json.loads((bundle / 'data/config.json').read_text())
    if (config.get('mixed-port') != proxy_port or config.get('external-controller') != f'127.0.0.1:{api_port}'
            or config.get('allow-lan', False) or config.get('tun', {}).get('enable', False)):
        raise InstallError('安装包配置与安全监听端口不一致。')
    import domino_subscriptions
    domino_subscriptions.validate_install_registration(sys.modules[__name__], bundle)
    for command in ['sudo', 'systemctl', 'curl']:
        if not shutil.which(command):
            raise InstallError('目标缺少依赖：' + command)
    owned_installations()
    cli = HOME / '.local/bin/domino'
    if not owned_cli(cli):
        raise InstallError('~/.local/bin/domino 已被其他程序使用，未覆盖。')
    body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
    for name in dict.fromkeys(ENV_FILES + LEGACY_ENV_FILES):
        path = HOME / name
        if path.is_symlink():
            raise InstallError('受管理的环境文件是符号链接，停止。')
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
                raise InstallError(f'目标端口 {number} 已被其他服务占用，未修改。')
    prepare_custom_rules(bundle / 'data')
    run([str(bundle / 'mihomo'), '-t', '-d', str(bundle / 'data'), '-f', str(bundle / 'data/config.json')],
        capture_output=True, text=True, timeout=60)
    run(['sudo', *(['-n'] if manifest.get('non_interactive') else []), '-v'])
    user = run(['id', '-un'], capture_output=True, text=True).stdout.strip()
    group = run(['id', '-gn'], capture_output=True, text=True).stdout.strip()
    unit = unit_text(user, group)
    pending = manifest.get('awaiting_subscription') and not (config.get('proxies') or config.get('proxy-providers'))
    shell_state = prepare_shell_policy(APP, HOME, system='linux', shell_env=manifest['shell_env'], pending=pending)
    backup = snapshot()
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
        install_cli(bundle)
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
                    raise InstallError('服务控制接口未就绪。')
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
            print('部署未完成，正在恢复服务、节点配置和环境文件…', file=sys.stderr)
        except OSError:
            pass  # Still restore if the SSH terminal disconnected.
        try:
            restore(backup)
        except BaseException:
            raise InstallError('自动恢复未完成。保留的完整备份：' + str(backup),code='RECOVERY_INCOMPLETE',effect='unknown') from None
        if isinstance(failure,KeyboardInterrupt):
            failure.domino_effect='rolled_back'
            raise
        raise InstallError('部署未完成，已恢复原状态；备份：'+str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        globals().pop('_domino_registry_backup', None)
    print('服务已运行并启用开机自启；代理端口：' + str(proxy_port))
    if health is None:
        print('基础环境已就绪，待添加订阅：domino configs add "名称"；domino configs switch "名称"。')
    else:
        print('代理出网校验通过；出口地区：' + (health['exit_country'] or '未返回'))
    if manifest['shell_env']:
        print('终端代理策略：' + ('已开启' if shell_state[0]['enabled'] else '已关闭') + '；与系统代理独立，使用 domino shell on/off/status 管理。')
        print('已有终端请加载一次：. "$HOME/.config/domino/proxy.env"；Bash 登录配置需已加载 .bashrc。')
        print('其他已接入终端下次提示符同步；运行中的 VS Code / Server 不会更新环境。')
    print('部署前备份：' + backup.name)
    if (APP / 'cli').is_dir():
        print('目标机管理和继续部署：~/.local/bin/domino status localhost；~/.local/bin/domino USER@IP')


def select_backup(name=None):
    if name:
        if name in ['.', '..'] or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise InstallError('备份 ID 无效。')
        for directory in (BACKUPS, LEGACY_BACKUPS):
            candidate = directory / name
            if not candidate.is_symlink() and (candidate / 'snapshot.json').is_file():
                return candidate
        raise InstallError('备份不存在或来自不支持自动恢复的旧版本。')
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
    raise InstallError('没有本版本工具生成的可恢复备份。')


def rollback(name=None, non_interactive=False):
    if os.getuid() == 0:
        raise InstallError('请使用部署时的普通 SSH 用户回滚。')
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
            raise InstallError('回滚和自动恢复未完成。当前状态备份：' + safety.name,code='RECOVERY_INCOMPLETE',effect='unknown') from None
        raise InstallError('回滚未完成，已恢复操作前状态。',code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        globals().pop('_domino_registry_backup', None)
    print('已恢复部署前状态：' + backup.name)
    print('回滚前状态也已保存：' + safety.name)


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
    if not value: return '尚未更新'
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp.astimezone().strftime('%Y-%m-%d %H:%M %z') if stamp.year >= 1970 else '尚未更新'
    except (ValueError,TypeError,OverflowError):
        return human_text(value)


def status_text(result, system_proxy=None, *, color=False):
    text = human_text
    def styled(value, code):
        return human_style(value,code,color=color)
    if not result.get('installed'):
        summary, tone = '○ 尚未安装运行环境', '33'
    elif result.get('awaiting_subscription'):
        summary, tone = ('● 服务已运行 · 待添加订阅' if result.get('active') else '○ 服务已停止 · 待添加订阅'), '33'
    elif not result.get('active'):
        summary, tone = '○ 服务已停止', '33'
    elif result.get('healthy'):
        summary, tone = '● 代理出网正常', '32'
    else:
        summary, tone = '● 服务运行中 · 连通检查未通过', '31'
    lines = human_header_text('运行状态',summary,tone,color=color).splitlines()
    if not result.get('installed'):
        return '\n'.join([*lines,'  下一步：运行安装程序。',''])
    subscription = result.get('subscription') or ('待添加订阅' if result.get('awaiting_subscription') else '独立配置（未绑定订阅）')
    mode = {'rule':'规则模式','global':'全局模式','direct':'直连模式'}.get(result.get('mode'),'模式未知')
    country = result.get('exit_country') or ('未知' if result.get('healthy') else '未检测')
    lines += ['  订阅 ' + styled(subscription,'1') + '  ·  ' + mode + '  ·  出口 ' + styled(country,'1')]
    def row(label, value):
        lines.append('  ' + styled(label,'2') + ' '*(10-2*len(label)) + value)
    startup = ('登录时自启' if result.get('autostart_scope') == 'user-login' else '开机自启') if result.get('enabled') else '未启用自启动'
    row('服务', ('运行中' if result.get('active') else '已停止') + '  ·  ' + startup)
    if system_proxy is not None:
        routing = system_proxy.get('routing','unknown')
        ports = '/'.join(text(number) for number in system_proxy.get('ports',[]))
        value = {'domino':'已指向 Domino' + (f" :{result['proxy_port']}" if result.get('proxy_port') else ''),
                 'off':'未开启', 'other':'指向其他代理' + (' :'+ports if ports else ''),
                 'mixed':'部分指向其他代理' + (' :'+ports if ports else ''),
                 'pac':'使用 PAC 自动配置', 'unknown':'无法确认'}.get(routing,'无法确认')
        row('系统代理', styled(value,'32' if routing == 'domino' else '33'))
    if 'shell_proxy' in result:
        shell = result['shell_proxy']
        value = ('策略已开启' if shell.get('enabled') else '策略已关闭') if 'enabled' in shell else '策略无法读取'
        row('终端代理', value + '  ·  domino shell status 查看当前终端')
    if result.get('proxy_port'):
        row('代理地址', f"http://127.0.0.1:{text(result['proxy_port'])}")
    kernel = 'Mihomo ' + text(result.get('version') or '版本未知')
    if result.get('arch'): kernel += '  ·  ' + text(result['arch'])
    row('内核', kernel)
    if result.get('requires_source_online'):
        row('上游依赖', styled('需要源电脑保持在线','33'))
    if result.get('awaiting_subscription'):
        lines += ['','  下一步：domino configs add "名称"；domino configs switch "名称"。']
    elif not result.get('active'):
        lines += ['','  启动服务：domino start']
    elif not result.get('healthy'):
        lines += ['','  排查连接：domino logs；domino nodes']
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
            result['note'] = '待添加并切换订阅。'
        manifest = json.loads((app / 'manifest.json').read_text()) if (app / 'manifest.json').is_file() else {}
        result.update(proxy_port=config['mixed-port'], version=manifest.get('version'), arch=manifest.get('arch'), subscription=subscription_name(app),
                      mode=config.get('mode','rule'))
        if manifest.get('platform') == 'darwin':
            result['service'] = 'local.domino.mihomo'
            result['autostart_scope'] = 'user-login'
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
                result['check_error'] = '代理控制接口或独立出网检查失败'
    return result


def status(as_json=False):
    result = collect_status()
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        system_proxy = None
        if result.get('service') == 'local.domino.mihomo':
            import domino_macos
            system_proxy = domino_macos.system_proxy_overview(result.get('proxy_port'))
        color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
        print(status_text(result, system_proxy, color=color))
    return 0 if result['healthy'] else 3


def proxy_state():
    app, _ = current_installation()
    config_path = app / 'data/config.json'
    if not config_path.is_file():
        raise InstallError('目标尚未安装本工具管理的代理。')
    config = json.loads(config_path.read_text())
    try:
        live = json.loads(controller(app / 'data', '/proxies'))['proxies']
        running = json.loads(controller(app / 'data', '/configs'))
        config['mode'] = running.get('mode', config.get('mode', 'rule'))
    except (OSError, ValueError, KeyError):
        raise InstallError('无法读取 Mihomo 节点，请先运行 status 检查服务。') from None
    return config, live


def proxy_inventory(live):
    """Include provider members that the top-level proxy API does not enumerate."""
    live=dict(live)
    missing={name for item in live.values() for name in item.get('all',[]) if name not in live}
    if not missing: return live
    try: providers=api_json('/providers/proxies').get('providers',{})
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


def collect_nodes(group=None):
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
            raise InstallError('没有找到该策略组，请先运行 nodes 查看名称。')
        actual_nodes = []
    result = {'mode': config.get('mode', 'rule'), 'groups': groups, 'nodes': actual_nodes}
    return result


def nodes(group=None, as_json=False):
    result=collect_nodes(group)
    groups,actual_nodes=result['groups'],result['nodes']
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mode = {'rule':'规则模式','global':'全局模式','direct':'直连模式'}.get(result['mode'],result['mode'])
    human_header('节点',f"{mode}  ·  {len(groups)} 策略组  ·  {len(actual_nodes)} 节点")
    group_rows=[]
    for g in groups:
        group_rows.append([g['name'],(g['current'] or '由策略决定','1'),'手动选择' if g['selectable'] else '自动策略'])
    if group_rows: human_table(['策略组','当前选择','类型'],group_rows)
    if group:
        print()
        for choice in groups[0]['choices']:
            current = choice == groups[0]['current']
            print('  ' + human_style(('* ' if current else '  ')+choice,'32' if current else '0'))
    if actual_nodes:
        selected_by = {}
        for g in groups:
            if g['current']:
                label = g['name'] + ('（手动）' if g['selectable'] else '（自动）')
                selected_by.setdefault(g['current'], []).append(label)
        rows = []
        for item in actual_nodes:
            selectors = selected_by.get(item['name'], [])
            name = ('* ' + item['name'], '32') if selectors else '  ' + item['name']
            rows.append([name, item['type'], '、'.join(selectors) if selectors else '—'])
        print()
        human_table(['节点名称','协议','当前选中该节点的策略组'], rows)
        print('\n  * 表示被策略组当前选中，不代表所有请求都走该节点。')
    if not group:
        print('\n  查看组内节点：domino nodes --group "策略组名称"')


def select_node(group, node, *, render=True):
    _, live = proxy_state()
    item = live.get(group)
    if not item or not isinstance(item.get('all'), list):
        raise InstallError('策略组不存在，请先用 nodes 查看。')
    if item.get('type', '').lower() not in ['selector', 'select']:
        raise InstallError('该组由自动策略选择；请切换上层可手动选择的策略组。')
    if node not in item['all']:
        raise InstallError('指定节点不在该策略组中，未更改任何选择。')
    if item.get('now') == node:
        if not render: return {'group':group,'node':node,'changed':False}
        human_header('节点选择','● 当前已选择，无需切换')
        human_row('策略组',group)
        human_row('当前节点',node)
        return {'group':group,'node':node,'changed':False}
    route = '/proxies/' + urllib.parse.quote(group, safe='')
    app, _ = current_installation()
    controller(app / 'data', route, {'name': node})
    # Acknowledge only the state observed back from the controller.
    current = json.loads(controller(app / 'data', route)).get('now')
    if current != node:
        raise InstallError('切换请求已发送，但读回的选择尚未一致；请用 nodes 核实。',code='READBACK_MISMATCH',effect='unknown')
    if not render: return {'group':group,'node':node,'changed':True}
    human_header('节点选择','● 已切换')
    human_row('策略组',group)
    human_row('当前节点',node)
    print('\n  新连接将使用该选择；已有长连接可能需要重新连接。')
    return {'group':group,'node':node,'changed':True}


def service_action(action, non_interactive=False, lines=100, follow=False):
    manifest = APP / 'manifest.json'
    if sys.platform == 'darwin' and (not manifest.exists() or json.loads(manifest.read_text()).get('platform') == 'darwin'):
        import domino_macos
        return domino_macos.service_action(sys.modules[__name__], action, lines, follow,batch=non_interactive)
    app, service = current_installation()
    if not (app / 'data/config.json').is_file():
        raise InstallError('本机尚未安装 Domino 代理。')
    with legacy_layout() if service == LEGACY_SERVICE else nullcontext():
        owned_service()
    if action == 'logs' and not 1 <= lines <= 10000:
        raise InstallError('日志行数必须在 1–10000 之间。')
    run(['sudo', *(['-n'] if non_interactive else []), '-v'])
    if action == 'logs':
        command = ['journalctl', '-u', service.name, '-n', str(lines), '--no-pager']
        if follow:
            command += ['-f']
        run(['sudo', '-n', *command])
    else:
        sudo('systemctl', action, service.name)
        human_header('服务',{'start':'● 已启动','stop':'○ 已停止','restart':'● 已重启'}[action], '33' if action == 'stop' else '32')
        human_row('管理服务',service.name)


def api_json(route, payload=None, *, method=None, timeout=3):
    app, _ = current_installation()
    if not (app / 'data/config.json').is_file():
        raise InstallError('尚未安装 Domino 运行环境，请先运行安装程序。',code='NOT_INSTALLED',exit_code=3)
    value = controller(app / 'data', route, payload, method=method, timeout=timeout)
    return json.loads(value) if value else None


def show(value, as_json=False):
    if as_json or isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif not value:
        print('暂无数据。')
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
            raise InstallError('设置读回不一致。',code='READBACK_MISMATCH',effect='unknown')
        config[key] = value
        write_private(path, json.dumps(config, ensure_ascii=False, indent=2))
    except BaseException as failure:
        if isinstance(failure,DomainError) and not acknowledged and failure.effect=='none': raise
        try:
            if path.read_bytes()!=before: write_private(path,before)
            api_json('/configs', {key: previous}, method='PATCH')
            if api_json('/configs').get(key)!=previous: raise RuntimeError()
        except BaseException:
            raise InstallError('设置保存失败且恢复未完成。',code='RECOVERY_INCOMPLETE',effect='unknown') from None
        raise InstallError('设置保存失败，已恢复原设置。',code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    result={key:value,'persisted':True}
    if render:
        if as_json: show(result,True)
        else: show_option(key,value,persisted=True)
    return result


def show_option(key, value, persisted=False):
    names = {'rule':'规则模式','global':'全局模式','direct':'直连模式','debug':'调试','info':'信息',
             'warning':'警告','error':'错误','silent':'静默'}
    human_header('代理模式' if key == 'mode' else '日志级别',names.get(value,human_text(value)))
    if persisted: human_row('保存','已写入配置，重启后保留')


def resolve_delay_name(query, names, kind):
    if query in names:
        return query
    needle = (query or '').strip().casefold()
    matches = sorted(name for name in names if needle and needle in name.casefold())
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise InstallError(f'匹配到多个{kind}，请使用完整名称。候选：' + '；'.join(matches))
    raise InstallError(f'没有找到指定{kind}；请运行 domino nodes 查看名称。')


def delay(node=None, group=None, url='https://www.gstatic.com/generate_204', timeout_ms=5000, as_json=False, *, name=None, render=True):
    if not 100 <= timeout_ms <= 60000:
        raise InstallError('测速超时必须在 100–60000 毫秒之间。')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise InstallError('测速 URL 必须是无内嵌凭据的 HTTPS 地址。')
    live = proxy_inventory(api_json('/proxies')['proxies'])
    if name is not None:
        resolved = resolve_delay_name(name, live, '节点或策略组')
        if isinstance(live[resolved].get('all'), list):
            group = resolved
        else:
            node = resolved
    if group is not None:
        group = resolve_delay_name(group, [name for name, item in live.items() if isinstance(item.get('all'), list)], '策略组')
        names = live[group]['all']
        names=[label for name in names for label in ([name] if name in live else
            [label for label,item in live.items() if item.get('_domino_original')==name] or [name])]
    elif node is not None:
        names = [resolve_delay_name(node, live, '节点')]
    else:
        names = sorted(key for key, item in live.items() if not isinstance(item.get('all'), list)
                       and key not in ['DIRECT','REJECT','REJECT-DROP','PASS','COMPATIBLE']
                       and item.get('type','').casefold() not in ['direct','reject','rejectdrop','pass','passrule','compatible'])
        if not names:
            raise InstallError('没有可测速的节点；请运行 domino nodes 查看配置。')
    from concurrent.futures import ThreadPoolExecutor
    def test(name):
        query = urllib.parse.urlencode({'url': url, 'timeout': timeout_ms})
        route = live.get(name,{}).get('_domino_delay','/proxies/' + urllib.parse.quote(name, safe='') + '/delay')+'?'+query
        try:
            result = api_json(route, timeout=timeout_ms / 1000 + 2)
            return {'name': name, 'delay_ms': result['delay'], 'ok': True}
        except (InstallError, OSError, ValueError, KeyError):
            return {'name': name, 'delay_ms': None, 'ok': False}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(test, names))
    if not render: return results
    if as_json:
        show(results, True)
    else:
        available=sum(bool(item['ok']) for item in results)
        human_header('节点测速',f'{len(results)} 节点  ·  {available} 可用  ·  {len(results)-available} 超时/不可用',
                     '32' if results and available == len(results) else '33')
        human_table(['节点名称','延迟'],[[item['name'],(str(item['delay_ms'])+' ms','32') if item['ok'] else ('超时/不可用','31')] for item in results])
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
            human_header('连接','● 已关闭全部连接' if close_all else '● 已关闭指定连接')
            if close: human_row('连接 ID',close)
        return
    data=collect_connections()
    values=data['connections']
    if not render: return data
    if as_json:
        show({'uploadTotal': data.get('uploadTotal'), 'downloadTotal': data.get('downloadTotal'), 'connections': values}, True)
    else:
        human_header('连接',f'{len(values)} 个活跃连接')
        if not values: print('  暂无活跃连接。')
        for item in values:
            print('  ' + human_style(f"{item['host']}:{item['port']}") + '  ·  ' + human_text(item['network']) + '  ·  ' + human_text(item['rule']))
            print('    ' + human_text(' / '.join(item['chains'] or []) or '—') + '  ·  ID ' + human_text(item['id']))
            print()
    return data


def traffic_samples(watch=False, interval=1.0, count=0):
    if not .2 <= interval <= 60 or count < 0:
        raise InstallError('流量刷新间隔必须为 0.2–60 秒；次数不能为负。')
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


def traffic(watch=False, interval=1.0, count=0, as_json=False):
    if not as_json:
        human_header('流量','仅统计经过 Domino 的流量')
    for result in traffic_samples(watch,interval,count):
        if as_json:
            print(json.dumps(result), flush=True)
        else:
            print('  ↑ ' + human_size(result['upload_bytes_per_second'],True) + '  ↓ ' + human_size(result['download_bytes_per_second'],True)
                  + '  ·  累计 ↑' + human_size(result['upload_total']) + ' ↓' + human_size(result['download_total']) + f"  ·  {result['connections']} 连接",flush=True)


def custom_rules_path():
    path = HOME / '.config/domino/rules.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise InstallError('自定义规则路径不能是符号链接。')
    return path


def custom_rules():
    path = custom_rules_path()
    if not path.exists():
        return []
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise InstallError('自定义规则文件格式无效。')
    items = value.get('prepend')
    if value.get('schema') != 1 or not isinstance(items, list) or any(not isinstance(v, str) for v in items):
        raise InstallError('自定义规则文件格式无效。')
    return items


def base_rules(data, config):
    path = data / 'rules-base.json'
    items = json.loads(path.read_text()) if path.is_file() else config.get('rules', [])
    if not isinstance(items, list) or any(not isinstance(v, str) for v in items):
        raise InstallError('基础规则必须为字符串列表。')
    return items


def compose_custom_rules(config, prepend=None):
    prepend = custom_rules() if prepend is None else prepend
    base = config.get('rules', [])
    if not isinstance(base, list) or any(not isinstance(v, str) for v in base):
        raise InstallError('基础规则必须为字符串列表。')
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
        raise InstallError('请提供单行 Mihomo 规则，例如 DOMAIN-SUFFIX,example.com,DIRECT。')
    saved = custom_rules()
    if remove and value not in saved:
        raise InstallError('未找到该自定义规则；使用 domino rules --custom 查看原文。')
    if not remove and value in saved:
        if not render: return {'changed':False,'rule':value,'message':'该自定义规则已存在。'}
        if as_json: show({'changed': False, 'rule': value, 'message': '该自定义规则已存在。'},True)
        else:
            human_header('自定义规则','● 规则已存在，无需重复添加')
            human_row('规则',value)
        return
    app, _ = current_installation()
    data = app / 'data'
    path = data / 'config.json'
    if not path.is_file() or not (app / 'mihomo').is_file():
        raise InstallError('尚未安装内核，请先运行安装程序。')
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
            raise InstallError('规则校验失败，请检查语法、出口名称及引用的资源；原配置未修改。') from None
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
                raise InstallError('规则应用失败且恢复未完成；备份：' + str(backup),code='RECOVERY_INCOMPLETE',effect='unknown') from None
            raise InstallError('规则未应用，已恢复原配置；备份：' + str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
        result = {'changed': True, 'action': 'remove' if remove else 'add', 'rule': value,
                  'mode': candidate.get('mode', 'rule'), 'backup': str(backup)}
        if not render: return result
        if as_json:
            show(result, True)
        else:
            human_header('自定义规则','● 已删除' if remove else '● 已新增并置顶')
            human_row('规则',value)
            if result['mode'] != 'rule':
                human_row('生效条件','切换规则模式：domino mode --set rule')
            human_row('保存','已持久保存，后续新连接使用当前配置')
            human_row('备份',backup)
        return result
    finally:
        pending.unlink(missing_ok=True)


def collect_rules(match=None, limit=50, custom=False):
    if not 1 <= limit <= 100000:
        raise InstallError('规则显示数量必须在 1–100000 之间。')
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
        human_header('自定义规则',f"{result['total']} 条  ·  从上到下匹配")
        for value in result['rules']: print('  '+human_text(value))
        if not result['rules']: print('  暂无自定义规则。')
    else:
        human_header('分流规则',f"{result['total']} 条匹配  ·  显示 {len(result['rules'])} 条")
        if result['rules']: human_table(['类型','匹配内容','出口'],[[item.get('type'),item.get('payload'),item.get('proxy')] for item in result['rules']])
        else: print('  没有匹配的规则。')
    return result


def collect_providers(kind='proxy', update=None):
    route = '/providers/' + ('proxies' if kind == 'proxy' else 'rules')
    data = api_json(route).get('providers', {})
    if update:
        if update not in data:
            raise InstallError('没有找到指定 provider。')
        if str(data[update].get('vehicleType', '')).lower() not in ['http', 'file']:
            raise InstallError('该集合是内置节点快照，没有独立订阅更新地址；请使用 configs add/switch 管理完整配置订阅。')
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
        human_header('节点集合' if kind == 'proxy' else '规则集合',f'{len(result)} 个集合' + ('  ·  已更新 '+human_text(update) if update else ''))
        if result:
            origins={'HTTP':'在线','File':'本地文件','Compatible':'内置','Inline':'内嵌'}
            human_table(['名称','数量','来源','更新时间'],[[item['name'],item['count'],origins.get(item['vehicleType'],item['vehicleType']),human_time(item['updatedAt'])] for item in result])
        else: print('  暂无集合。')
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
        raise InstallError('代理端口无效。')
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
        raise InstallError('终端代理动作必须是 on 或 off。', code='INVALID_ARGUMENT')
    try:
        if action:
            if not (app / 'data/config.json').is_file():
                raise InstallError('请先安装 Domino，再设置终端代理。')
            policy = domino_shell.read_policy(app)
            if action == 'on':
                domino_shell.proxy_port(app)
            enabled = action == 'on'
            if policy['enabled'] != enabled:
                write_private(app / 'shell-policy.json', json.dumps({'version': 1, 'enabled': enabled}))
        result = domino_shell.status(app, HOME)
    except (ValueError, OSError) as error:
        raise InstallError('终端代理策略读取或写入失败；请检查安装与策略文件。', code='SHELL_POLICY_INVALID') from error
    if render:
        if as_json:
            show(result, True)
        else:
            enabled = result['enabled']
            human_header('终端代理', '● 已开启' if enabled else '● 已关闭',
                         '32' if enabled else '31')
            human_row('策略含义', '已接入的终端会使用 Domino 代理' if enabled else '不再要求已接入的终端使用 Domino 代理')
            human_row('当前终端', '开启不代表代理变量已同步' if enabled else '关闭不代表代理变量已清空；原有或手动设置的代理可能仍保留')
            human_row('检查变量', 'env | grep -i proxy（请在当前终端执行）')
            human_row('手动同步', '. "$HOME/.config/domino/proxy.env"')
            human_row('作用边界', '不改变系统代理；已接入终端在下次提示符同步，已运行程序不受影响')
    return result


def overview():
    """Fast, read-only UI snapshot; never run an external connectivity probe."""
    app, service = current_installation()
    path = app / 'data/config.json'
    result = {'installed': path.is_file(), 'active': False, 'reachable': False, 'groups': [],
              'node_count': 0, 'connections': 0, 'upload_total': 0, 'download_total': 0,
              'stats_available': False, 'client': 'Domino', 'service': service.name}
    if not path.is_file():
        result['error'] = '尚未安装运行环境，请先运行安装程序。'
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
    result['active'] = systemctl('is-active')
    try:
        runtime = api_json('/configs', timeout=1.5)
        proxies = proxy_inventory(api_json('/proxies', timeout=1.5)['proxies'])
        stats = api_json('/connections', timeout=1.5)
        result.update(reachable=True, active=True, stats_available=True, mode=runtime.get('mode', result['mode']),
                      connections=len(stats.get('connections') or []),
                      upload_total=stats.get('uploadTotal', 0), download_total=stats.get('downloadTotal', 0))
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
        result['error'] = '控制接口暂不可用；可使用 /start 或 /logs 检查。'
    show(result, True)


def subscription_arguments(parser):
    actions = parser.add_mutually_exclusive_group()
    for flag, help_text in [
        ('add', '保存命名订阅；不切换当前配置'),
        ('update', '更新订阅；当前订阅校验成功后自动应用'),
        ('use', '切换订阅；首次使用时自动下载'),
        ('remove', '删除非当前订阅'),
        ('rename', '重命名，配合 --new-name'),
        ('set-url', '修改地址，配合 --url'),
        ('import-current', '保存当前配置为本地快照'),
    ]:
        actions.add_argument('--' + flag, metavar='NAME', help=help_text)
    actions.add_argument('--update-all', action='store_true', help='更新全部在线订阅')
    parser.add_argument('--url', help='完整配置 HTTPS 订阅地址；省略时隐藏输入')
    parser.add_argument('--new-name')
    parser.add_argument('--json', action='store_true')


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('install')
    p.add_argument('bundle')
    p = sub.add_parser('status')
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
    p = sub.add_parser('env')
    p.add_argument('--unset', action='store_true')
    sub.add_parser('overview')
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
    choice.add_argument('--all', action='store_true')
    choice.add_argument('--node')
    choice.add_argument('--group')
    p.add_argument('--url', default='https://www.gstatic.com/generate_204')
    p.add_argument('--timeout', type=int, default=5000)
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('connections')
    choice = p.add_mutually_exclusive_group()
    choice.add_argument('--close')
    choice.add_argument('--all', action='store_true')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('traffic')
    p.add_argument('--watch', action='store_true')
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
                               'traffic','rules','providers','proxy','shell','configs','start','stop','restart','scan']
    with human_output(formatted and not getattr(args,'json',False),color=True if args.color else None):
        return _run_command(args)


def _run_command(args):
    try:
        if args.action=='scan':
            import domino_cli
            return domino_cli.inspect_source(args) if args.source else domino_cli.list_sources(args)
        if args.action in ['install', 'rollback', 'configs', 'rules','agent']:
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
        elif args.action == 'status':
            return status(args.json)
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
            delay(args.node, args.group, args.url, args.timeout, args.json, name=args.name)
        elif args.action == 'connections':
            connections(args.close, args.all, args.json)
        elif args.action == 'traffic':
            traffic(args.watch, args.interval, args.count, args.json)
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
            if sys.platform != 'darwin':
                raise InstallError('系统代理开关当前支持 macOS；Linux 应用请使用代理环境变量或手动设置代理。')
            import domino_macos
            with deployment_lock():
                domino_macos.system_proxy(sys.modules[__name__], args.set, args.service, args.json, args.non_interactive)
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
                raise InstallError('目标管理程序缺少订阅组件，请先更新该设备的 Domino。') from None
            if (args.use or args.update or args.update_all) and custom_rules() and not getattr(domino_subscriptions, 'CUSTOM_RULES', False):
                raise InstallError('目标订阅组件版本过旧，请先更新该设备的 Domino，以保留自定义规则。')
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
        print('失败：' + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('已取消。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
