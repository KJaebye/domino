#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Deploy independent proxy access and manage local or remote Domino services."""
from __future__ import annotations
from domino_i18n import tr as _t

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
import copy
import gzip
import hashlib
import ipaddress
import importlib.util
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import getproxies
from domino_model import DomainError

VERSION = '1.3.0'
BUILD_CHANNEL = 'development'
PACKAGE_MANAGED = False
DESCRIPTION = '捕获本机代理，并一键部署到指定 IP 的设备上，让翻墙像 domino 一样简单。'
SUBSCRIPTION_USER_AGENT = 'clash.meta'
DEFAULT_PROXY_PORT = 17897
DEFAULT_API_PORT = 19091
RELEASE_API = 'https://api.github.com/repos/MetaCubeX/mihomo/releases/latest'
REMOTE_SCRIPT = Path(__file__).with_name('install_domino.py')
CLI_MODULES = ('domino_translations.py','domino_i18n.py','domino_cli.py','install_domino.py','domino_macos.py','domino_linux.py','domino_tui.py',
               'domino_subscriptions.py','domino_install.py','domino_model.py',
               'domino_store.py','domino_service.py','domino_resources.py','domino_logs.py','domino_agent.py','domino_agent_backend.py','domino_shell.py','domino_sources.py','domino_completion.py','domino_uninstall.py','domino_client_sources.py','domino_cli_sync.py','domino_doctor.py','domino_macos_app.py','domino_macos_app_build.py')
DEFAULT_CLASH = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
DEFAULT_SOCKET = Path('/tmp/verge/verge-mihomo.sock')


class ToolError(DomainError):
    pass


class ReportedCommandError(ToolError):
    def __init__(self, returncode):
        self.returncode = returncode
        super().__init__(_t('本机管理失败（退出码 {0}）。', returncode))


def _run_process(args, **kwargs):
    # Inherited file descriptors bypass redirect_stdout. Relay finite human
    # output through the same frame, including remote commands and installers.
    # stdin/stderr remain attached for authentication and interactive prompts.
    from install_domino import _HumanOutput
    stream=sys.stdout
    if not isinstance(stream,_HumanOutput) or kwargs.get('capture_output') or 'stdout' in kwargs:
        return subprocess.run(args,check=True,**kwargs)
    stream.flush()
    kwargs['env']={**(os.environ if kwargs.get('env') is None else kwargs['env']),
                   'COLUMNS':str(shutil.get_terminal_size((100,24)).columns)}
    read_fd,write_fd=os.pipe()
    errors=[]
    def relay():
        try:
            import codecs
            decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
            with os.fdopen(read_fd,'rb',buffering=0) as output:
                while True:
                    chunk=output.read(8192)
                    if not chunk:break
                    stream.write(decoder.decode(chunk).replace('\r\n','\n'))
                    stream.flush()
                stream.write(decoder.decode(b'',final=True))
        except BaseException as error:
            errors.append(error)
    reader=threading.Thread(target=relay,daemon=True)
    reader.start()
    try:
        return subprocess.run(args,check=True,stdout=write_fd,**kwargs)
    finally:
        os.close(write_fd)
        reader.join()
        if errors:raise errors[0]


def run(args, *, stage=None, **kwargs):
    stage = stage or _t('命令')
    try:
        return _run_process(args, **kwargs)
    except subprocess.CalledProcessError as exc:
        if stage==_t('下载') and args[0]=='curl' and exc.returncode in [16,92,95] and '--http1.1' not in args:
            return run([args[0],'--http1.1',*args[1:]],stage=stage,**kwargs)
        # Never interpolate argv/stderr: provider URLs and configs may contain credentials.
        if stage == _t('下载') and isinstance(exc.stdout, str) and re.fullmatch(r'[45]\d\d', exc.stdout.strip()):
            status = int(exc.stdout.strip())
            reason = {401:_t('订阅凭据无效或缺失'),403:_t('服务器拒绝访问'),404:_t('订阅地址不存在'),429:_t('请求过于频繁')}.get(status,_t('服务器返回错误'))
            raise ToolError(_t('下载失败（HTTP {0}：{1}；curl 退出码 {2}）。', status, reason, exc.returncode),code='DOWNLOAD_AUTH' if status in [401,403] else 'DOWNLOAD_NOT_FOUND' if status==404 else 'DOWNLOAD_UNAVAILABLE',exit_code=4 if status in [401,403] else 3 if status==404 else 5,retryable=status==429 or status>=500) from None
        if stage==_t('下载'):
            raise ToolError(_t('下载失败（退出码 {0}）。', exc.returncode),code='TIMEOUT' if exc.returncode==28 else 'DOWNLOAD_UNAVAILABLE',exit_code=7 if exc.returncode==28 else 5,retryable=True) from None
        if stage == _t('本机管理') and not kwargs.get('capture_output') and kwargs.get('stderr') is None:
            raise ReportedCommandError(exc.returncode) from None
        raise ToolError(_t('{0}失败（退出码 {1}）。', stage, exc.returncode)) from None
    except subprocess.TimeoutExpired:
        raise ToolError(_t('{0}超时。', stage)) from None


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data.encode() if isinstance(data, str) else data)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def cache_dir():
    configured = os.environ.get('DOMINO_CACHE')
    base = Path(configured).expanduser() if configured else (
        Path.home() / ('Library/Caches/domino' if sys.platform == 'darwin' else '.cache/domino'))
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if base.is_symlink():
        raise ToolError(_t('缓存目录不能是符号链接。'))
    base.chmod(0o700)
    return base


def port(value):
    try:
        value = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(_t('端口必须是整数。')) from None
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError(_t('代理端口必须在 1024–65535 之间。'))
    return value


def ssh_port(value):
    try:
        value = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(_t('SSH 端口必须是整数。')) from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError(_t('SSH 端口必须在 1–65535 之间。'))
    return value


def destination(value, user=None):
    if value.count('@') > 1:
        raise ToolError(_t('目标格式应为 IP、SSH 别名或 user@IP。'))
    if '@' in value:
        embedded, value = value.split('@', 1)
        if user and embedded != user:
            raise ToolError(_t('--user 与目标中的用户名不一致。'))
        user = embedded
    if user and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
        raise ToolError(_t('SSH 用户名无效。'))
    host = value[1:-1] if value.startswith('[') and value.endswith(']') else value
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r'[\d.]+', host) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', host):
            raise ToolError(_t('目标必须是合法 IP、主机名或 SSH Host 别名。')) from None
    return (user + '@' if user else '') + host


def normalize_arch(machine):
    mapping = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}
    try:
        return mapping[machine]
    except KeyError:
        raise ToolError(_t('暂不支持目标架构 {0}；支持 ARM64 和 x86_64。', machine)) from None


def download(url, path, proxy=None, *, user_agent=None, timeout_seconds=300):
    if urlsplit(url).scheme != 'https':
        raise ToolError(_t('下载地址必须使用 HTTPS。'))
    args = ['curl', '--fail', '--location', '--silent', '--show-error',
            '--connect-timeout', str(min(10, timeout_seconds)), '--max-time', str(timeout_seconds), '--retry', '2' if timeout_seconds == 300 else '0',
            '--proto', '=https', '--proto-redir', '=https']
    config = 'url = ' + json.dumps(url) + '\n'
    if user_agent:
        config += 'user-agent = ' + json.dumps(user_agent) + '\n'
    if proxy:
        config += 'proxy = ' + json.dumps(proxy) + '\n'
    args += ['--config', '-', '-o', str(path), '--write-out', '%{http_code}']
    # Header files can contain cookies and private redirect URLs; keep them in a
    # private temporary directory and return only the subscription usage header.
    with tempfile.TemporaryDirectory(prefix='domino-http-') as directory:
        headers = Path(directory) / 'headers'
        headers.touch(mode=0o600)
        run([*args, '--dump-header', str(headers)], stage=_t('下载'), input=config, text=True, capture_output=True)
        with headers.open('rb') as stream:
            content = stream.read(1024 * 1024 + 1)
        result = {}
        if len(content) <= 1024 * 1024:
            for line in content.decode('iso-8859-1').splitlines():
                if line.startswith('HTTP/'):
                    result = {}  # Ignore CONNECT, redirects, interim and retry responses.
                elif ':' in line:
                    key, value = line.split(':', 1)
                    if key.lower() == 'subscription-userinfo':
                        result['subscription-userinfo'] = value.strip()
        return result


def download_subscription_usage(url, proxy=None):
    with tempfile.TemporaryDirectory(prefix='domino-usage-') as directory:
        return download(url, Path(directory) / 'response', proxy,
                        user_agent=SUBSCRIPTION_USER_AGENT, timeout_seconds=15)


def download_resource(label, url, path, proxy=None, **kwargs):
    try:
        return download(url, path, proxy, **kwargs)
    except ToolError as error:
        raise ToolError(label + '：' + str(error),code=error.code,exit_code=error.exit_code,retryable=error.retryable,effect=error.effect,details=error.details) from None


def load_yaml(path):
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml
    except ImportError:
        vendor = Path(__file__).parent / '_vendor'
        if (vendor / 'yaml').is_dir():
            sys.path.insert(0, str(vendor))
            import yaml
        else:
            yaml = None
    if yaml is None:
        if not shutil.which('ruby'):
            raise ToolError(_t('读取 YAML 需要 PyYAML（python3 -m pip install PyYAML），或提供 JSON 配置。'))
        code = 'puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), [], [], true))'
        result = run(['ruby', '-ryaml', '-rjson', '-e', code, str(path)],
                     stage=_t('读取 Clash 配置'), capture_output=True, text=True)
        return json.loads(result.stdout)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        raise ToolError(_t('Clash YAML 配置解析失败；配置内容未输出。')) from None


def xdg_directory(variable, fallback):
    value = Path(os.environ.get(variable) or fallback)
    return value if value.is_absolute() else Path.home() / fallback


def verge_roots():
    app_id = 'io.github.clash-verge-rev.clash-verge-rev'
    return [Path.home() / 'Library/Application Support' / app_id,
            xdg_directory('XDG_DATA_HOME', '.local/share') / app_id,
            xdg_directory('XDG_CONFIG_HOME', '.config') / 'clash-verge']


def verge_source_root(path):
    resolved = Path(path).resolve()
    return next((root for root in verge_roots()
                 if resolved == (root / 'clash-verge.yaml').resolve()
                 or resolved.is_relative_to((root / 'profiles').resolve())), None)


def discover_sources():
    from domino_client_sources import discover
    candidates = [Path.home() / '.local/share/domino/data/config.json',
                  Path.home() / '.local/share/robot-clash/data/config.json',
                  *(root / 'clash-verge.yaml' for root in verge_roots()),
                  *(xdg_directory('XDG_CONFIG_HOME', '.config') / client / filename
                    for client in ('clash', 'mihomo') for filename in ('config.yaml', 'config.yml')),
                  *discover()]
    return list(dict.fromkeys(p for p in candidates if p.is_file()))


def discover_source():
    return next(iter(discover_sources()), None)


def read_verge_profiles():
    """Read saved configuration identities only; never execute client transforms."""
    profiles, warnings = {}, []
    for root in verge_roots():
        saved, notes = read_verge_index(root)
        profiles.update(saved)
        warnings.extend(notes)
    return profiles, list(dict.fromkeys(warnings))


def read_verge_index(root):
    index = root / 'profiles.yaml'
    profiles, warnings = {}, []
    if not index.exists() and not index.is_symlink():
        return profiles, warnings
    invalid = _t('Clash Verge 配置索引存在无效或不安全的项目，已跳过；其他来源不受影响。')
    try:
        base = root.resolve()
        directory = (root / 'profiles').resolve()
        if (index.is_symlink() or (root / 'profiles').is_symlink() or not directory.is_relative_to(base)
                or index.stat().st_size > 2 * 1024 * 1024):
            raise ValueError('Invalid profile index')
        data = load_yaml(index)
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise ValueError('Invalid profile index')
    except (DomainError, OSError, ValueError, TypeError, RuntimeError):
        return profiles, [_t('Clash Verge 配置索引无法读取或解析；其他来源不受影响。')]
    current = data.get('current')
    if current is not None and not isinstance(current, str):
        current = None
        warnings.append(invalid)
    uids, ambiguous = {}, set()
    for entry in data['items']:
        if not isinstance(entry, dict):
            warnings.append(invalid)
            continue
        if entry.get('type') not in ('remote', 'local'):
            continue
        uid, name, filename = (entry.get(key) for key in ('uid', 'name', 'file'))
        if (not all(isinstance(value, str) and value and '\0' not in value for value in (uid, name, filename))
                or Path(filename).is_absolute() or '..' in Path(filename).parts or '\\' in filename):
            warnings.append(invalid)
            continue
        try:
            path = (root / 'profiles' / filename).resolve()
            if path == directory or not path.is_relative_to(directory):
                raise ValueError('Invalid profile path')
        except (OSError, ValueError, RuntimeError):
            warnings.append(invalid)
            continue
        if uid in uids or path in profiles:
            warnings.append(_t('Clash Verge 配置索引有重复标识或文件，当前启用项无法可靠确认。'))
            ambiguous.add(path)
            if uid in uids:
                ambiguous.add(uids[uid])
        uids.setdefault(uid, path)
        profiles.setdefault(path, {'source_kind': 'profile', 'profile_id': uid,
            'profile_name': name, 'client_current': uid == current,
            'check_note': _t('保存配置不对应独立运行入口，未检查出网；不包含客户端合并或脚本处理。')})
    if current not in uids:
        ambiguous.update(profiles)
    for path in ambiguous:
        if path in profiles:
            profiles[path]['client_current'] = None
    return profiles, list(dict.fromkeys(warnings))


def source_identity(path, *, profiles=None):
    try:
        from domino_client_sources import identity
        client = identity(path)
        if client:
            return client
        resolved = Path(path).resolve()
        if profiles is None:
            root = verge_source_root(resolved)
            if root is None or not resolved.is_relative_to((root / 'profiles').resolve()):
                return {}
            profiles, _ = read_verge_profiles()
        return dict(profiles.get(resolved, {}))
    except (OSError, ValueError, RuntimeError):
        return {}


def load_source(path):
    from domino_client_sources import load
    converted = load(path)
    return converted if converted is not None else load_yaml(path)


def source_name(path, identity):
    from domino_client_sources import client_name
    client = client_name(path)
    if identity:
        return (client or 'Clash Verge') + ' · ' + identity['profile_name']
    return client


def source_config(args):
    if args.source:
        path = Path(args.source).expanduser().resolve()
    else:
        path = discover_source()
        if path is None:
            raise ToolError(_t('没有找到可独立部署的 Domino 或 Clash/Mihomo 配置。请用 --source 指定兼容配置，或用 --subscription 提供完整配置订阅；仅有本机代理端口或专用隧道客户端无法独立迁移。'))
    if not path.is_file():
        raise ToolError(_t('指定的源配置文件不存在。'))
    if managed_source_identity(path):
        from domino_sources import read_source
        raw, _ = read_source(path.parent)
    else:
        raw = load_source(path)
    if not isinstance(raw, dict) or not (raw.get('proxies') or raw.get('proxy-providers')):
        raise ToolError(_t('源文件不是包含节点的 Clash/Mihomo 配置。'))
    if args.command == 'init' and path.parent == Path.home() / '.local/share/domino/data':
        from install_domino import base_rules
        raw = dict(raw, rules=base_rules(path.parent, raw))
    mixed = raw.get('mixed-port') or raw.get('port')
    if (getattr(args, 'subscription', None) or (args.command == 'init' and args.source)
            or managed_source_identity(path)
            or source_identity(path).get('source_kind') == 'profile'):
        proxy = args.local_proxy or discover_proxy()
    else:
        proxy = args.local_proxy or (f'http://127.0.0.1:{mixed}' if mixed else None)
    return path, raw, proxy


@contextmanager
def source_input(args):
    if not getattr(args, 'subscription', None):
        yield args
        return
    if args.controller or args.controller_socket:
        raise ToolError(_t('直接使用订阅时不读取本机客户端控制接口，请移除 --controller 和 --controller-socket。'))
    with tempfile.TemporaryDirectory(prefix='domino-subscription-', dir=cache_dir()) as directory:
        source = Path(directory) / 'config.yaml'
        download_resource(_t('完整配置订阅'), args.subscription, source, args.local_proxy or discover_proxy(), user_agent=SUBSCRIPTION_USER_AGENT)
        source.chmod(0o600)
        prepared = copy.copy(args)
        prepared.source = str(source)
        yield prepared


def discover_proxy():
    proxies = getproxies()
    for key in ('https', 'http', 'all'):
        value = proxies.get(key)
        if value:
            parsed = urlsplit(value)
            if parsed.scheme in ('http', 'https', 'socks5', 'socks5h') and parsed.hostname:
                return value
    return None


def public_proxy(value):
    if not value:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    if ':' in host:
        host = '[' + host + ']'
    return f"{parsed.scheme}://{host}" + (f':{parsed.port}' if parsed.port else '')


def managed_source_identity(path):
    from domino_sources import is_managed_snapshot
    if is_managed_snapshot(path):
        return {'source_kind': 'import-snapshot',
                'check_note': _t('Domino 导入源快照只检查文件兼容性，不检查其中保存的旧代理端口。')}
    return {}


def source_details(path, *, identity=None):
    identity = (managed_source_identity(path) or source_identity(path)) if identity is None else identity
    result = {'source': 'domino' if path.parent.parent.name in ['domino', 'robot-clash'] else 'clash-config',
              'config': str(path), 'compatible_config_found': False, 'proxy': None, **identity}
    if identity.get('source_kind') == 'import-snapshot':
        from domino_sources import read_source
        raw, _ = read_source(path.parent)
    else:
        try:
            raw = load_source(path)
        except DomainError as error:
            if error.code != 'UNSUPPORTED_CLIENT_CONFIG':
                raise
            result['config_error'] = str(error)
            return result
    if isinstance(raw, dict) and (raw.get('proxies') or raw.get('proxy-providers')):
        try:
            sanitize_profile(raw, {}, DEFAULT_PROXY_PORT, DEFAULT_API_PORT)
            result['compatible_config_found'] = True
        except ToolError as error:
            result['config_error'] = str(error)
    else:
        result['config_error'] = _t('该文件不是兼容的 Clash/Mihomo 节点配置。')
    if isinstance(raw, dict) and identity.get('source_kind') not in ['profile', 'import-snapshot']:
        number = raw.get('mixed-port') or raw.get('port')
        if number:
            result['proxy'] = f'http://127.0.0.1:{port(number)}'
    if result['source'] == 'domino' and path.parent.name == 'data':
        from domino_sources import public_info
        result['import_source'] = public_info(path.parent)
        import install_domino
        current_name = install_domino.subscription_name(path.parent.parent)
        if current_name:
            result['current_config'] = current_name
    return result


PROBE_STAGES = {'proxy_dns': '代理地址解析', 'dns': '目标地址解析', 'proxy': '代理入口连接', 'tunnel': 'HTTPS 隧道建立', 'tls': 'HTTPS / TLS 握手', 'http': 'HTTPS 响应', 'request': '出网请求'}


def check_source_proxy(proxy, *, timeout=5):
    try:
        details=probe_source(proxy, 'https://www.cloudflare.com/cdn-cgi/trace', timeout=timeout)
        result={'healthy': True, 'exit_checked': True}
        if isinstance(details,dict): result['check_details']=details
        return result
    except (ToolError, OSError) as error:
        result={'healthy': False, 'exit_checked': True,
                'check_error':_t('未能完成代理出网检查，请检查客户端状态和日志。')}
        if isinstance(error,ToolError) and error.code.startswith('PROBE_') and isinstance(error.details,dict):
            result.update(check_error=str(error),check_code=error.code,check_stage=error.details['stage'],
                          check_hint=error.details['hint'],check_details=error.details['metrics'])
        return result


def collect_sources():
    """Discover compatible configuration sources and check their proxy endpoints read-only."""
    paths = discover_sources()
    default = paths[0].resolve() if paths else None
    profiles, warnings = read_verge_profiles()
    candidates = {}
    for path in [*paths, *profiles]:
        candidates.setdefault(path.resolve(), path)
    sources = []
    for resolved, path in candidates.items():
        identity = source_identity(path, profiles=profiles)
        if source_name(path, identity):
            name = source_name(path, identity)
        elif path.parent.parent.name in ['domino', 'robot-clash']:
            name = 'Domino' if path.parent.parent.name == 'domino' else 'robot-clash'
        elif path.name == 'clash-verge.yaml':
            name = _t('Clash Verge · 运行配置')
        elif path.parent.name in ['clash', 'mihomo']:
            name = 'Mihomo' if path.parent.name == 'mihomo' else 'Clash'
        else:
            name = 'Clash/Mihomo'
        try:
            item = source_details(path, identity=identity)
        except (DomainError, OSError, ValueError, TypeError, AttributeError, KeyError, argparse.ArgumentTypeError):
            item = {'source': 'clash-config', 'config': str(path), 'compatible_config_found': False,
                    'proxy': None, 'config_error': _t('配置无法读取或解析。'), **identity}
        item.update(name=name, default=resolved == default)
        sources.append(item)
    proxies = list(dict.fromkeys(item['proxy'] for item in sources if item['proxy']))
    checks = {}
    if proxies:
        with ThreadPoolExecutor(max_workers=min(4, len(proxies))) as executor:
            checks = dict(zip(proxies, executor.map(check_source_proxy, proxies)))
    for item in sources:
        item.update(checks.get(item['proxy'], {'healthy': False, 'exit_checked': False}))
    result = {'sources': sources}
    managed = collect_managed_configs(sources)
    if managed is not None:
        result['managed_configs'] = managed
    if warnings:
        result['warnings'] = warnings
    return result


def collect_managed_configs(sources):
    """Read the public registry projection without loading or activating caches."""
    import domino_subscriptions
    home = Path.home()
    index = home / '.config/domino/subscriptions/index.json'
    if not index.exists() and not index.is_symlink():
        return None
    runtime = next((item for item in sources if item.get('source') == 'domino'), None)
    app = Path(runtime['config']).parent.parent if runtime else home / '.local/share/domino'
    context = argparse.Namespace(HOME=home, APP=app, InstallError=ToolError)
    try:
        return domino_subscriptions.Manager(context).listing()
    except (DomainError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return {'configs': [], 'active': None, 'error': _t('配置库无法读取，请检查 Domino 配置目录；外部来源扫描不受影响。')}


def profile_status(item):
    current = item.get('client_current')
    return _t('客户端当前启用（索引）') if current is True else _t('已保存（非当前）') if current is False else _t('已保存（当前项无法确认）')


def source_display_groups(sources):
    """Group related files for humans only; collected machine records stay intact."""
    grouped = sources
    for root in verge_roots():
        grouped = verge_display_group(grouped, root)
    return grouped


def verge_display_group(sources, root):
    current = [item for item in sources if item.get('source_kind') == 'profile'
               and item.get('client_current') is True and item.get('compatible_config_found')
               and Path(item['config']).resolve().is_relative_to((root / 'profiles').resolve())]
    runtime = [item for item in sources if item.get('source_kind') != 'profile'
               and Path(item['config']).resolve() == (root / 'clash-verge.yaml').resolve()]
    if len(current) != 1 or len(runtime) != 1:
        return sources
    profile, running = current[0], runtime[0]
    profile_path = Path(profile['config']).resolve()
    if (not profile_path.is_relative_to((root / 'profiles').resolve())
            or profile_path == Path(running['config']).resolve()):
        return sources
    merged = dict(running, name=profile['name'],
                  default=running['default'] or profile['default'], display_profile=profile)
    return [merged if item is running else item for item in sources if item is not profile]


def display_import_source(item, row):
    """Render only the public provenance projection, never stored source contents."""
    info = item.get('import_source')
    if not info:
        return
    if item.get('current_config'):
        row(_t('当前配置'), item['current_config'])
    if info['status'] == 'known':
        label = info.get('label', _t('导入源快照'))
        if info.get('profile_name') and info.get('association') == 'index':
            label += '（' + info['profile_name'] + _t(' 为客户端索引关联）')
        row(_t('导入来源'), label)
        row(_t('源快照'), (str(info['snapshot_path']).replace(str(Path.home()) + '/', '~/', 1), '2'))
        if info.get('captured_at'):
            from install_domino import human_time
            row(_t('导入时间'), human_time(info['captured_at']))
    else:
        row(_t('导入来源'), (_t('源快照不可用') if info['status'] == 'invalid' else _t('未记录（旧版运行配置）'), '33'))


def display_scan_source(item, row):
    row(_t('来源'),(item['name']+(_t(' · 默认导入来源') if item['default'] else ''),'1'))
    profile = item.get('display_profile')
    if profile or item.get('source_kind') == 'profile':
        row(_t('配置选择'), profile_status(profile or item))
    state = _t('可用') if item['healthy'] else _t('检查未通过') if item['exit_checked'] else _t('未检查（保存配置）') if item.get('source_kind') == 'profile' else _t('未检查')
    row(_t('入口出网'),(state,'32' if item['healthy'] else '31' if item['exit_checked'] else '33'))
    row(_t('代理入口'),item['proxy'] or (_t('未关联运行入口') if item.get('source_kind') == 'profile' else _t('未配置')))
    row(_t('配置状态'),(_t('兼容'),'32') if item['compatible_config_found'] else (_t('不可用'),'33'))
    path=Path(item['config'])
    try: display='~/'+str(path.relative_to(Path.home()))
    except ValueError: display=str(path)
    row(_t('运行配置') if profile or item.get('import_source') else _t('原始配置') if item.get('source_kind') == 'profile' else _t('配置文件'),(display,'2'))
    display_import_source(item, row)
    if profile:
        original = Path(profile['config'])
        try: original_display = '~/' + str(original.relative_to(Path.home()))
        except ValueError: original_display = str(original)
        row(_t('原始配置'), (original_display, '2'))
        if profile['compatible_config_found'] != item['compatible_config_found']:
            row(_t('原始状态'), (_t('兼容'), '32') if profile['compatible_config_found'] else (_t('不可用'), '33'))
        row(_t('检查范围'), (_t('按客户端索引关联；出网结果属于运行入口，未核验内核加载内容与文件一致。'), '2'))
    if item.get('check_note'):
        row(_t('检查范围'),(item['check_note'],'2'))
    if item.get('config_error'):
        row(_t('配置检查'),(item['config_error'],'33'))
    if item.get('check_error'):
        if item.get('check_stage'):
            row(_t('失败阶段'),(_t(PROBE_STAGES.get(item['check_stage'],'出网请求')),'33'))
        row(_t('出网检查'),(item['check_error'],'33'))
        if item.get('check_hint'): row(_t('排查建议'),(item['check_hint'],'2'))


def list_sources(args):
    result = collect_sources()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        import install_domino as output
        with output.human_output():
            def row(label,value):
                output.human_row(label,value,wrap=True,columns=getattr(args,'columns',None))
            def section(title, detail):
                text = f'── {title} · {detail} '
                columns = getattr(args, 'columns', None) or shutil.get_terminal_size((100, 24)).columns
                rule = '─' * max(2, min(60, columns-2-output.human_width(text)))
                print('  ' + output.human_style(text + rule, '1;36'))
                print()
            sources = source_display_groups(result['sources'])
            external = [item for item in sources if item.get('source') != 'domino' and item['name'] not in ['Domino', 'robot-clash']]
            managed = result.get('managed_configs')
            configs = managed.get('configs', []) if managed else []
            registry_error = managed.get('error') if managed else None
            summary = _t('外部配置 {0} 个 · ', len(external)) + (_t('Domino 配置库无法读取') if registry_error else _t('Domino 管理 {0} 个', len(configs)))
            output.human_header(_t('配置扫描'), summary)
            section(_t('外部配置'), _t('{0} 个配置', len(external)))
            if external:
                for index, item in enumerate(external):
                    if index: print()
                    if getattr(args,'verbose',False):
                        display_scan_source(item, row)
                    else:
                        row(_t('来源'),(item['name']+(_t(' · 默认导入来源') if item['default'] else ''),'1'))
                        profile=item.get('display_profile') or item
                        if profile.get('source_kind')=='profile':row(_t('配置选择'),profile_status(profile))
                        row(_t('配置状态'),_t('兼容') if item['compatible_config_found'] else _t('不可用'))
                        if item.get('proxy'):row(_t('代理入口'),item['proxy'])
                        state=(_t('已连通') if item['healthy'] else _t('检查未通过') if item['exit_checked'] else
                               _t('未检查（保存配置）') if item.get('source_kind')=='profile' else _t('未检测'))
                        row(_t('入口出网'),(state,'32' if item['healthy'] else '31' if item['exit_checked'] else '2'))
                        if item.get('check_note') and item['name'].startswith('v2rayN'):row(_t('捕获范围'),(item['check_note'],'33'))
                        for key,label in [('config_error',_t('配置检查')),('check_error',_t('出网检查')),('check_hint',_t('排查建议'))]:
                            if item.get(key):row(label,(item[key],'33'))
            else:
                row(_t('配置'), _t('未发现外部配置。'))
            print()
            section(_t('Domino 管理'), _t('配置库无法读取') if registry_error else _t('{0} 个配置', len(configs)))
            if configs:
                rows=[
                    [('● ' if item['active'] else '  ') + item['name'],
                     _t('在线订阅') if item['kind'] == 'subscription' else _t('配置快照'),
                     item['node_count'] if item.get('node_count') is not None else '—',
                     _t('已缓存') if item['cached'] else _t('未缓存'),
                     output.human_time(item['updated_at']) if item.get('updated_at') else _t('尚未更新')]
                    for item in configs]
                detailed=getattr(args,'verbose',False)
                width=5 if detailed else 4 if any(not item['cached'] for item in configs) else 3
                output.human_table([_t('配置名称'),_t('类型'),_t('节点'),_t('缓存'),_t('更新时间')][:width],
                                   [r[:width] for r in rows])
            elif not registry_error:
                row(_t('配置库'), _t('尚未登记配置；可用 domino catch 捕获或 domino add 添加。'))
            if registry_error:
                row(_t('配置检查'), (registry_error, '33'))
            for warning in result.get('warnings', []):
                row(_t('扫描提示'), (warning, '33'))
    return 0


def collect_source(args):
    path = Path(args.source).expanduser().resolve() if getattr(args, 'source', None) else discover_source()
    identity = (managed_source_identity(path) or source_identity(path)) if path else {}
    saved = identity.get('source_kind') in ['profile', 'import-snapshot']
    proxy = None if saved else discover_proxy()
    kind = 'local-proxy' if proxy else 'unknown'
    result = {'source': kind, 'config': str(path) if path else None,
              'compatible_config_found': False, 'healthy': False, 'exit_checked': False,
              'note': _t('独立部署需要兼容的节点配置；本机代理端口、系统隧道/TUN 在线不代表配置可迁移。'), **identity}
    if path:
        try:
            details = source_details(path, identity=identity)
        except (DomainError, OSError, ValueError, TypeError, AttributeError, KeyError, argparse.ArgumentTypeError):
            if not saved:
                raise
            details = {'source': 'clash-config', 'config_error': _t('配置无法读取或解析。')}
        if details.get('proxy'):
            proxy = details['proxy']
        result.update({key: value for key, value in details.items() if key != 'proxy'})
    result['proxy'] = public_proxy(proxy)
    if proxy:
        result.update(check_source_proxy(proxy,timeout=25))
    return result


def inspect_source(args):
    result=collect_source(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        import install_domino as output
        with output.human_output():
            compatible = result['compatible_config_found']
            output.human_header(_t('部署来源'),_t('● 找到兼容节点配置') if compatible else _t('○ 未找到可独立部署的节点配置'),'32' if compatible else '33')
            kinds={'domino':_t('Domino 配置'),'clash-config':_t('Clash/Mihomo 配置'),'local-proxy':_t('仅有本机代理入口'),'unknown':_t('未发现')}
            label = source_name(Path(result['config']), result if result.get('source_kind') == 'profile' else {}) if result['config'] else None
            output.human_row(_t('配置来源'), label or kinds.get(result['source'],result['source']))
            if result.get('source_kind') == 'profile':
                output.human_row(_t('配置选择'), profile_status(result))
                output.human_row(_t('入口出网'), _t('未检查（保存配置）'))
                if getattr(args,'verbose',False):output.human_row(_t('检查范围'), result['check_note'], wrap=True, columns=getattr(args,'columns',None))
            if result.get('source_kind') == 'import-snapshot':
                output.human_row(_t('入口出网'), _t('未检查（导入源快照）'))
                if getattr(args,'verbose',False):output.human_row(_t('检查范围'), result['check_note'], wrap=True, columns=getattr(args,'columns',None))
            if getattr(args,'verbose',False):
                if result['config']:output.human_row(_t('运行配置') if result.get('import_source') else _t('配置文件'),result['config'])
                display_import_source(result, lambda label, value: output.human_row(label, value, wrap=True, columns=getattr(args, 'columns', None)))
            elif (result.get('import_source') or {}).get('status')=='invalid':
                output.human_row(_t('导入来源'),(_t('源快照不可用'),'33'))
            if result['proxy']:
                output.human_row(_t('代理入口'),result['proxy'])
                output.human_row(_t('入口出网'),(_t('可用'),'32') if result['healthy'] else (_t('检查未通过'),'31'))
            if result.get('config_error'): output.human_row(_t('配置检查'),result['config_error'])
            if result.get('check_error'):
                columns=getattr(args,'columns',None)
                if result.get('check_stage'):
                    output.human_row(_t('失败阶段'),(_t(PROBE_STAGES.get(result['check_stage'],'出网请求')),'33'),wrap=True,columns=columns)
                output.human_row(_t('出网检查'),(result['check_error'],'33'),wrap=True,columns=columns)
                if result.get('check_hint'):
                    output.human_row(_t('排查建议'),(result['check_hint'],'2'),wrap=True,columns=columns)
            if getattr(args,'verbose',False):print(_t('\n  此处检查可迁移的配置和对应代理入口；运行及系统代理状态请用 domino status 查看。'))
    return 0 if result['healthy'] else 3


def probe_error(returncode, metrics, timeout):
    connected=metrics.get('proxy_connected',False)
    tunnel=metrics.get('connect_status',0)
    tls=metrics.get('tls_established',False)
    status=metrics.get('http_status',0)
    code,stage='PROBE_FAILED','request'
    reason=_t('出网请求失败（curl {0}）。', returncode)
    hint=_t('请结合客户端日志检查当前节点、分流规则及目标网站。')
    if tunnel==407:
        code,stage,reason='PROBE_PROXY_AUTH','tunnel',_t('代理入口要求身份认证（HTTP 407）。')
        hint=_t('请检查本机代理的认证设置；控制接口密钥与代理认证不是同一项。')
    elif tunnel>=400:
        code,stage,reason='PROBE_TUNNEL_REJECTED','tunnel',_t('代理入口拒绝建立 HTTPS 隧道（HTTP {0}）。', tunnel)
    elif returncode==7:
        code,stage,reason='PROBE_PORT_UNREACHABLE','proxy',_t('无法连接配置中的代理端口，请求尚未进入代理。')
        hint=_t('确认原客户端已启动，并检查代理端口和监听地址是否与配置一致。')
    elif returncode in [5,6]:
        code,stage='PROBE_DNS_FAILED','proxy_dns' if returncode==5 else 'dns'
        reason=_t('代理地址解析失败。') if returncode==5 else _t('目标网站地址解析失败。')
        hint=_t('检查相关 DNS 设置和域名解析；当前错误不能直接说明节点是否可用。')
    elif returncode==28:
        if 'proxy_connected' not in metrics:
            code,stage,reason='PROBE_REQUEST_TIMEOUT','request',_t('出网请求超时；未能获取足够信息判断失败发生在哪个连接阶段（请求时限 {0} 秒）。', timeout)
            hint=_t('请重试或查看客户端日志，当前结果不能直接认定为端口不可达或节点超时。')
        elif not connected:
            code,stage,reason='PROBE_CONNECT_TIMEOUT','proxy',_t('在 {0} 秒内未能连接代理入口。', timeout)
            hint=_t('检查客户端是否运行、监听地址是否正确，以及本机防火墙设置。')
        elif tunnel!=200:
            code,stage,reason='PROBE_TUNNEL_TIMEOUT','tunnel',_t('代理端口已连接，但在 {0} 秒内未完成 HTTPS 隧道建立。', timeout)
            hint=_t('可能是上游节点连接或转发超时，需结合客户端日志确认具体原因。')
        elif not tls:
            code,stage,reason='PROBE_TLS_TIMEOUT','tls',_t('代理已接受 HTTPS 隧道，但 TLS 握手在 {0} 秒内未完成。', timeout)
            hint=_t('隧道被接受不代表节点已连通；请检查当前节点、上游链路和客户端日志。')
        else:
            code,stage,reason='PROBE_RESPONSE_TIMEOUT','http',_t('TLS 握手已完成，但 HTTPS 响应在 {0} 秒内未完成。', timeout)
            hint=_t('检查目标网站响应及上游链路，当前结果不属于本机端口不可达。')
    elif returncode in [51,60]:
        code,stage,reason='PROBE_TLS_CERTIFICATE','tls',_t('TLS 证书校验失败。')
        hint=_t('检查系统时间、证书信任链及是否存在 HTTPS 拦截；不要仅据此认定节点离线。')
    elif returncode==35:
        code,stage,reason='PROBE_TLS_FAILED','tls',_t('HTTPS / TLS 握手失败或连接被中断（curl 35）。')
        if connected: reason=_t('代理端口已连接，但 ')+reason
        hint=_t('节点连接失败或超时也可能表现为此错误；请结合客户端日志判断，不能直接归因为证书问题。')
    elif returncode==22 and status:
        code,stage,reason='PROBE_HTTP_ERROR','http',_t('目标网站返回 HTTP {0}。', status)
        hint=_t('已收到 HTTP 错误响应；检查测试网站是否拒绝请求或服务异常。')
    elif returncode in [52,55,56]:
        code='PROBE_CONNECTION_CLOSED'
        stage='http' if tls else 'tls' if tunnel==200 else 'tunnel'
        reason=_t('请求过程中连接被关闭、重置或未返回有效响应（curl {0}）。', returncode)
        hint=_t('可能涉及节点、上游链路或目标网站；需要客户端日志进一步定位。')
    return ToolError(reason,code=code,exit_code=7 if returncode==28 else 5,retryable=True,
                     details={'stage':stage,'hint':hint,'metrics':metrics})


def probe_source(proxy, url, *, timeout=25):
    marker='\nDOMINO_PROBE '
    report={'http_status':'%{http_code}','connect_status':'%{http_connect}',
            'tcp_seconds':'%{time_connect}','tls_seconds':'%{time_appconnect}','total_seconds':'%{time_total}'}
    command = ['curl', '--fail', '--silent', '--show-error', '--connect-timeout', str(min(8, timeout)), '--max-time', str(timeout),
               '--write-out',marker+json.dumps(report), '--noproxy', '*']
    config = 'url = ' + json.dumps(url) + '\n'
    if proxy:
        command[-1] = ''
        config += 'proxy = ' + json.dumps(proxy) + '\n'
    metrics={'timeout_seconds':timeout,'test_host':urlsplit(url).hostname}
    try:
        process=subprocess.run(command + ['--config', '-'],input=config,text=True,capture_output=True,timeout=timeout+5)
    except subprocess.TimeoutExpired:
        metrics['curl_exit_code']=28
        raise probe_error(28,metrics,timeout) from None
    except OSError:
        raise ToolError(_t('无法启动出网检查所需的 curl。'),code='PROBE_UNAVAILABLE',exit_code=5,
                        details={'stage':'request','hint':_t('请确认系统已安装可用的 curl。'),'metrics':metrics}) from None
    metrics['curl_exit_code']=process.returncode
    try:
        data=json.loads(process.stdout.rsplit(marker,1)[1])
        metrics.update(http_status=int(data['http_status']),connect_status=int(data['connect_status']),
                       proxy_connected=float(data['tcp_seconds'])>0 or int(data['connect_status'])>0,
                       tls_established=float(data['tls_seconds'])>0,
                       elapsed_ms=round(float(data['total_seconds'])*1000))
    except (ValueError,TypeError,KeyError,IndexError):
        if process.returncode==0:
            raise ToolError(_t('出网检查返回的诊断信息无效。'),code='PROBE_INVALID_RESPONSE',exit_code=5,
                            details={'stage':'request','hint':_t('请检查 curl 版本或重试出网检查。'),'metrics':metrics}) from None
    if process.returncode:
        raise probe_error(process.returncode,metrics,timeout)
    return metrics


def live_selections(args, raw, source):
    if getattr(args, 'subscription', None) or (args.command == 'init' and args.source):
        return {}
    if managed_source_identity(source) or source_identity(source).get('source_kind') == 'profile':
        if args.command != 'deploy' or getattr(args, 'verbose', False):
            print(_t('提示：导入保存配置，保留文件内默认节点；不读取客户端运行选择或执行合并/脚本。'), file=sys.stderr)
        return {}
    controller = args.controller
    socket = args.controller_socket
    if not controller and not socket:
        candidate = raw.get('external-controller-unix')
        if candidate and Path(candidate).is_socket():
            socket = candidate
        elif source.parent == DEFAULT_CLASH and DEFAULT_SOCKET.is_socket():
            socket = str(DEFAULT_SOCKET)
        else:
            controller = raw.get('external-controller')
    if not controller and not socket:
        if args.command != 'deploy' or getattr(args, 'verbose', False):
            print(_t('提示：未连接源 Clash 控制接口，将保留配置中的默认节点。'), file=sys.stderr)
        return {}
    url = controller or 'http://localhost'
    if '://' not in url:
        url = 'http://' + url
    parsed = urlsplit(url)
    if parsed.hostname not in ['localhost', '127.0.0.1', '::1']:
        raise ToolError(_t('源控制接口必须是本机回环地址。'))
    args_curl = ['curl', '--noproxy', '*', '--silent', '--show-error', '--fail', '--max-time', '5']
    if socket:
        args_curl += ['--unix-socket', socket]
    # The secret is passed through curl's stdin config, not command line arguments.
    secret = str(raw.get('secret') or '')
    header = 'Authorization: Bearer ' + secret
    curl_config = 'header = ' + json.dumps(header) + '\n'
    result = run(args_curl + ['--config', '-', url.rstrip('/') + '/proxies'],
                 input=curl_config, capture_output=True, text=True, stage=_t('读取源 Clash 当前节点'))
    try:
        live = json.loads(result.stdout)['proxies']
    except (ValueError, KeyError):
        raise ToolError(_t('源 Clash 控制接口返回无效数据。')) from None
    selected = {g['name']: live[g['name']]['now'] for g in raw.get('proxy-groups', [])
                if g.get('type') == 'select' and g['name'] in live
                and live[g['name']].get('now') in live[g['name']].get('all', [])}
    if str(raw.get('mode', 'rule')).lower() == 'global':
        global_group = live.get('GLOBAL', {})
        if global_group.get('now') in global_group.get('all', []):
            selected['GLOBAL'] = global_group['now']
    return selected


def sanitize_profile(raw, selections, proxy_port, api_port):
    mode = str(raw.get('mode', 'rule')).lower()
    if mode not in ['rule', 'global']:
        raise ToolError(_t('源 Clash 未处于规则或全局代理模式，请先在源客户端启用代理。'))
    keep = {'proxies', 'proxy-groups', 'rules', 'hosts', 'ipv6', 'unified-delay',
            'tcp-concurrent', 'global-client-fingerprint', 'geodata-mode',
            'geodata-loader', 'geox-url', 'proxy-providers', 'rule-providers', 'sub-rules'}
    profile = copy.deepcopy({k: v for k, v in raw.items() if k in keep})
    validate_independent_nodes(profile.get('proxies', []))
    for provider in profile.get('proxy-providers', {}).values():
        if provider.get('type') == 'inline':
            validate_independent_nodes(provider.get('payload', []))
    profile.update({'mixed-port': proxy_port, 'allow-lan': False,
                    'bind-address': '127.0.0.1', 'mode': mode, 'log-level': 'warning',
                    'find-process-mode': 'off', 'external-controller': f'127.0.0.1:{api_port}',
                    'secret': secrets.token_urlsafe(32), 'tun': {'enable': False},
                    'profile': {'store-selected': True}})
    from domino_sources import independent_dns
    profile['dns'] = independent_dns(profile)
    for item in profile.get('proxies', []) + profile.get('proxy-groups', []):
        item.pop('interface-name', None)
        item.pop('routing-mark', None)
    for group in profile.get('proxy-groups', []):
        selected = selections.get(group['name'])
        if selected in group.get('proxies', []):
            group['proxies'].remove(selected)
            group['proxies'].insert(0, selected)
    return profile


def validate_independent_nodes(nodes):
    for node in nodes:
        server = str(node.get('server', '')).strip('[]').lower().rstrip('.')
        local = server in ['localhost', 'localhost.localdomain'] or server.endswith('.localhost')
        try:
            address = ipaddress.ip_address(server)
            local = local or address.is_loopback or address.is_unspecified
        except ValueError:
            pass
        if local:
            raise ToolError(_t('源节点依赖本机回环代理，无法独立迁移。请提供可由目标机直接连接的节点配置。'))


def provider_resources(profile, source_dir, data, proxy, *, resolver=None, allow_download=True):
    from domino_sources import ResourceResolver
    resolver = resolver or ResourceResolver(source_dir / "config.yaml")
    origins = {}
    for kind in ['proxy-providers', 'rule-providers']:
        for name, provider in profile.get(kind, {}).items():
            kind_type = provider.get('type')
            if kind_type not in ['http', 'file']:
                if kind_type == 'inline':
                    continue
                raise ToolError(_t('存在无法迁移的 provider 类型；未部署任何内容。'))
            original = provider.get('path')
            local = resolver.find(original) if original else None
            suffix = '.mrs' if provider.get('format') == 'mrs' else '.yaml'
            name_hash = hashlib.sha256((kind + ':' + name).encode()).hexdigest()[:20]
            relative = Path('providers') / kind / (name_hash + suffix)
            target = data / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if local and local.is_file():
                shutil.copy2(local, target)
            elif allow_download and kind_type == 'http' and provider.get('url'):
                download_resource(_t('provider 配置资源'), provider['url'], target, proxy)
            else:
                raise ToolError(_t('provider 缓存文件缺失；请检查引用路径或使用 --resource-dir 指定资源目录。'),
                                code='SOURCE_RESOURCE_MISSING', exit_code=3)
            target.chmod(0o600)
            provider['path'] = relative.as_posix()
            origins[(kind, name)] = local
    return origins


def release_asset(release, arch, system='linux'):
    if not isinstance(release, dict):
        raise ToolError(_t('官方 release 元数据格式无效。'))
    tag = release.get('tag_name', '')
    if release.get('prerelease') or not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ToolError(_t('官方 release 元数据不是有效稳定版本。'))
    # v1 is the portable amd64 baseline; never assume AVX2/v3 support on a target.
    if system not in ['linux', 'darwin']:
        raise ToolError(_t('目标系统仅支持 Linux 或 macOS。'))
    name = (f'mihomo-darwin-{arch}-{tag}.gz' if system == 'darwin' else
            f'mihomo-linux-{arch}-{tag}.gz' if arch == 'arm64' else f'mihomo-linux-amd64-v1-{tag}.gz')
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ToolError(_t('官方 release 安装包列表无效。'))
    asset = next((a for a in assets if isinstance(a, dict) and a.get('name') == name), None)
    digest = asset.get('digest') if asset else None
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ToolError(_t('官方 release 缺少匹配架构的安装包或 SHA-256 值。'))
    url = asset.get('browser_download_url', '')
    from domino_resources import asset_allowed
    if not isinstance(url, str) or not asset_allowed(url,tag):
        raise ToolError(_t('安装包来源不符合当前资源源地址。'))
    return tag, asset


def prepare(args, arch, work):
    with source_input(args) as prepared:
        return prepare_source(prepared, arch, work)


def cached_init_release(args, arch, system, cache):
    """Reuse only a prior installation's matching, hash-verified release archive."""
    if args.command != 'init' or args.mihomo_version != 'latest':
        return None
    manifest_path = Path.home() / '.local/share/domino/manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            return None
        tag, digest = manifest.get('version'), manifest.get('sha256_gzip')
        if (manifest.get('platform', 'linux') != system or manifest.get('arch') != arch
                or not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+', tag)
                or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            return None
        name = (f'mihomo-{system}-{arch}-{tag}.gz' if system == 'darwin' or arch == 'arm64'
                else f'mihomo-linux-amd64-v1-{tag}.gz')
        archive = cache / name
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            return None
        return tag, {'name': name, 'digest': 'sha256:' + digest}
    except (OSError, ValueError):
        return None


CLI_RESOURCES = ('domino_assets/__init__.py', 'domino_assets/Domino.icns')


def copy_cli(bundle):
    cli = bundle / 'cli'
    # Preserve expected UI dependency packages from an offline bundle. All paths
    # were already checked by unpack_bundle; top-level scripts are replaced below.
    with tempfile.TemporaryDirectory(prefix='domino-ui-deps-') as directory:
        saved = Path(directory)
        for name in ['prompt_toolkit', 'wcwidth', 'yaml']:
            previous = cli / '_vendor' / name
            if previous.is_dir():
                shutil.copytree(previous, saved / name)
        previous_licenses = cli / '_vendor/licenses'
        if previous_licenses.is_dir():
            shutil.copytree(previous_licenses, saved / 'licenses')
        if cli.exists():
            shutil.rmtree(cli)
        cli.mkdir(mode=0o700)
        for name in CLI_MODULES:
            if name in globals().get('SOURCE_MODULES',{}): private_write(cli/name,SOURCE_MODULES[name])
            else: shutil.copy2(Path(__file__).with_name(name), cli / name)
        for name in CLI_RESOURCES:
            target = cli / name
            target.parent.mkdir(mode=0o700, exist_ok=True)
            shutil.copy2(Path(__file__).parent / name, target)
        from domino_completion import SCRIPTS
        for shell, text in SCRIPTS.items():
            private_write(cli / ("completion." + shell), text)
        for name in ['prompt_toolkit', 'wcwidth', 'yaml']:
            spec = importlib.util.find_spec(name)
            source = Path(spec.origin).parent if spec and spec.origin else None
            if source is None:
                for candidate in [saved / name, Path.home() / '.local/share/domino/cli/_vendor' / name]:
                    if candidate.is_dir():
                        source = candidate
                        break
            if source:
                target = cli / '_vendor' / name
                target.parent.mkdir(mode=0o700, exist_ok=True)
                shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', '*.dylib'))
                licenses = target.parent / 'licenses'
                licenses.mkdir(exist_ok=True)
                for directory in [saved / 'licenses', source.parent / 'licenses']:
                    if directory.is_dir():
                        for path in directory.glob(name + '-*'):
                            if path.is_file():
                                shutil.copy2(path, licenses / path.name)
                try:
                    distribution = importlib.metadata.distribution('PyYAML' if name == 'yaml' else name)
                    for item in distribution.files or []:
                        if Path(item).name in ['LICENSE', 'AUTHORS.rst']:
                            shutil.copy2(distribution.locate_file(item), licenses / (name + '-' + Path(item).name))
                except importlib.metadata.PackageNotFoundError:
                    pass


def prepare_source(args, arch, work):
    if getattr(args, '_captured_source', None) is not None:
        source, raw, proxy, selections = args._captured_source
    elif getattr(args, 'base_install', False):
        source = work / 'base.json'
        raw = {'mode':'rule','proxies':[],'proxy-groups':[],'rules':['MATCH,REJECT']}
        proxy, selections = args.local_proxy or discover_proxy(), {}
    else:
        source, raw, proxy = source_config(args)
        selections = live_selections(args, raw, source)
    # Reject incompatible captured data before downloads or packaging side effects.
    sanitize_profile(raw, selections, args.proxy_port, args.api_port)
    from domino_sources import create_source, derive_runtime, origin_info, read_source
    origin = getattr(args, '_captured_origin', None)
    if origin is None and not getattr(args, 'base_install', False):
        origin = origin_info(raw, source, subscription=getattr(args, 'subscription', None))
    cache = cache_dir()
    system = getattr(args, 'target_system', 'linux')
    cached = cached_init_release(args, arch, system, cache)
    if cached:
        tag, asset = cached
        print(_t('复用已安装 Mihomo {0} 的已校验缓存 / {1}。', tag, arch), flush=True)
    else:
        metadata = work / 'release.json'
        from domino_resources import release_url
        download_resource(_t('Mihomo 版本信息'), release_url(args.mihomo_version,RELEASE_API), metadata, proxy)
        tag, asset = (release_asset(json.loads(metadata.read_text()), arch, system) if system != 'linux'
                      else release_asset(json.loads(metadata.read_text()), arch))
    archive = cache / asset['name']
    expected = asset['digest'].split(':', 1)[1]
    valid = archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    if not valid:
        pending = work / 'binary.gz'
        if getattr(args, 'command', None) == 'deploy' and not getattr(args, 'verbose', False):
            deployment_progress(_t('下载'), f'Mihomo {tag} / {arch}…')
        else:
            print(_t('下载官方 Mihomo {0} / {1}…', tag, arch), flush=True)
        download_resource(_t('Mihomo 内核'), asset['browser_download_url'], pending, proxy)
        if hashlib.sha256(pending.read_bytes()).hexdigest() != expected:
            raise ToolError(_t('官方二进制 SHA-256 校验失败。'))
        private_write(archive, pending.read_bytes())
    bundle = work / 'bundle'
    data = bundle / 'data'
    data.mkdir(parents=True, mode=0o700)
    with gzip.open(archive, 'rb') as src, (bundle / 'mihomo').open('wb') as dst:
        shutil.copyfileobj(src, dst)
    (bundle / 'mihomo').chmod(0o755)
    if getattr(args, 'base_install', False):
        profile = sanitize_profile(raw, selections, args.proxy_port, args.api_port)
    else:
        preserved = source.parent / 'source'
        owned_runtime = (source.name == 'config.json' and source.parent.name == 'data'
                         and source.parent.parent.name in ['domino', 'robot-clash'])
        # Deploy the current effective configuration, not a historical import. Carry
        # its original snapshot separately so re-export never rewrites provenance.
        if owned_runtime and (preserved.exists() or preserved.is_symlink()):
            read_source(preserved)
            shutil.copytree(preserved, data / 'source')
            runtime_source = work / 'runtime-source'
            create_source(raw, source, runtime_source, proxy=proxy, metadata=origin,
                          resource_dirs=getattr(args, 'resource_dir', ()))
        else:
            runtime_source = data / 'source'
            create_source(raw, source, runtime_source, proxy=proxy, metadata=origin,
                          online=bool(getattr(args, 'subscription', None)),
                          resource_dirs=getattr(args, 'resource_dir', ()))
        profile = derive_runtime(runtime_source, data, selections, args.proxy_port, args.api_port)
        registration = {'version': 1, 'kind': 'subscription' if getattr(args, 'subscription', None) else 'snapshot'}
        if owned_runtime and getattr(args, 'installing', False) and not (args.source or args.subscription):
            registration['preserve_current'] = True
        if getattr(args, 'subscription', None):
            registration['url'] = args.subscription
            if getattr(args, 'name', None):
                registration['name'] = args.name
        private_write(bundle / 'registration.json', json.dumps(registration))
    private_write(data / 'config.json', json.dumps(profile, ensure_ascii=False, indent=2) + '\n')
    private_write(data / 'rules-base.json', json.dumps(profile.get('rules', []), ensure_ascii=False))
    if getattr(args, 'installing', False) and not (args.source or args.subscription):
        marker = source.parent / 'subscription.json'
        if marker.is_file() and source.parent.parent.name in ['domino','robot-clash']:
            identifier = json.loads(marker.read_text()).get('id')
            if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
                raise ToolError(_t('当前订阅关联记录无效，未重新安装。'))
            private_write(data / 'subscription.json', json.dumps({'id':identifier}))
    private_write(bundle / 'selections.json', json.dumps(selections, ensure_ascii=False))
    manifest = {'schema': 1, 'version': tag, 'arch': arch, 'proxy_port': args.proxy_port,
                'api_port': args.api_port, 'sha256_gzip': expected,
                'shell_env': not args.no_shell_env, 'test_url': args.test_url}
    manifest['non_interactive'] = getattr(args, 'batch', False)
    manifest['deployment_method'] = 'independent'
    manifest['requires_source_online'] = False
    manifest['platform'] = system
    manifest['cli_version'] = VERSION
    if getattr(args, 'base_install', False):
        manifest['awaiting_subscription'] = True
    private_write(bundle / 'manifest.json', json.dumps(manifest))
    if REMOTE_SCRIPT.name in globals().get('SOURCE_MODULES',{}): private_write(bundle/REMOTE_SCRIPT.name,SOURCE_MODULES[REMOTE_SCRIPT.name])
    else: shutil.copy2(REMOTE_SCRIPT, bundle / REMOTE_SCRIPT.name)
    copy_cli(bundle)
    core = Path(args.core).expanduser() if args.core else next((p for p in [
        Path.home() / '.local/share/domino/mihomo',
        Path('/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo')]
        if p.is_file()), Path('/nonexistent-domino-core'))
    if core.is_file():
        run([str(core), '-t', '-d', str(data), '-f', str(data / 'config.json')],
            capture_output=True, text=True, timeout=60, stage=_t('本机配置校验'))
    package = work / 'domino.tar.gz'
    with tarfile.open(package, 'w:gz') as tf:
        for item in sorted(bundle.iterdir()):
            tf.add(item, arcname=item.name)
    package.chmod(0o600)
    if args.command != 'deploy' or getattr(args, 'verbose', False):
        print(_t('安装包就绪：{0} / {1}，{2} 个内联节点，{3} 个节点 provider。', tag, arch, len(profile.get('proxies', [])), len(profile.get('proxy-providers', {}))), flush=True)
    return package, manifest


def remote_source(source):
    # Strip only documentation strings from the in-memory SSH program. Keep
    # executable tokens, source line numbers and all copyright/license headers.
    import ast
    data = source.encode('utf-8')
    offsets = [0]
    for line in data.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    spans = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                spans.append((offsets[first.lineno-1]+first.col_offset,
                              offsets[first.end_lineno-1]+first.end_col_offset,
                              first.end_lineno-first.lineno, isinstance(node, ast.Module)))
    for start, end, lines, module in sorted(spans, reverse=True):
        data = data[:start] + (b'' if module else b'pass') + b'\n' * lines + data[end:]
    import io
    import tokenize
    source = data.decode('utf-8')
    lines = source.splitlines(keepends=True)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and not any(word in token.string.lower() for word in ['spdx', 'copyright']):
            row, column = token.start
            lines[row-1] = lines[row-1][:column] + '\n'
    return ''.join(lines)


def compact_remote_source(source):
    import ast
    stripped = remote_source(source)
    tree = ast.parse(stripped)
    compact = ast.unparse(tree) + '\n'
    try:
        restored = ast.parse(compact, feature_version=(3, 9))
    except SyntaxError:
        return stripped
    if ast.dump(tree, include_attributes=False) != ast.dump(restored, include_attributes=False):
        raise ToolError(_t('远端源码压缩校验失败，未执行远端操作。'))
    headers = [line for line in stripped.splitlines() if line.startswith(('# SPDX', '# Copyright'))]
    return '\n'.join(headers) + '\n' + compact



class SSH:
    def __init__(self, args):
        self.args=args
        self.target = destination(args.target, args.user)
        self.options = ['-o', 'ClearAllForwardings=yes', '-o', 'ForwardX11=no',
                        '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
                        '-o', 'ServerAliveCountMax=3']
        if args.ssh_port:
            self.options += ['-p', str(args.ssh_port)]
        if args.identity:
            self.options += ['-i', str(Path(args.identity).expanduser())]
        if args.batch:
            self.options += ['-o', 'BatchMode=yes']
        if getattr(args,'machine_mode',False):
            self.options += ['-o','ConnectTimeout=10','-o','ConnectionAttempts=1']
        if args.command == 'deploy' and not getattr(args, 'verbose', False):
            self.options += ['-o', 'LogLevel=ERROR']
        self.temp = None

    def __enter__(self):
        # Keep below macOS's Unix socket pathname length limit.
        self.temp = tempfile.TemporaryDirectory(prefix='domino-ssh-', dir='/tmp')
        self.socket = str(Path(self.temp.name) / 'ctl')
        try:
            kwargs={'capture_output':True,'text':True,'timeout':30} if getattr(self.args,'machine_mode',False) else {}
            run(['ssh', '-M', '-S', self.socket, '-fN', '-o', 'ControlPersist=600',
                 *self.options, self.target], stage=_t('SSH 认证'),**kwargs)
        except Exception:
            self.temp.cleanup()
            raise
        return self

    def call(self, command, *, tty=False, **kwargs):
        return run(self.command_argv(command, tty), stage=_t('远端操作'), **kwargs)

    def command_argv(self, command, tty=False):
        return ['ssh', '-tt' if tty else '-T', '-S', self.socket, '-o', 'ControlMaster=no',
                *self.options, self.target, command]

    def action_argv(self, action, *options, tty=False):
        names=['domino_translations','domino_i18n','domino_model','domino_shell']
        if action in ['start', 'stop', 'restart', 'status', 'logs', 'overview', 'uninstall', 'doctor']:
            names += ['domino_macos', 'domino_linux']
        if action == 'doctor': names += ['domino_doctor']
        if action == 'uninstall': names += ['domino_uninstall']
        if action == 'proxy': names += ['domino_macos', 'domino_linux']
        if action == 'traffic': names += ['domino_tui']
        if action in ['agent','scan','configs','rollback','delay','cli','catch-options']: names += ['domino_subscriptions','domino_macos','domino_linux','domino_cli','domino_store','domino_service','domino_resources','domino_logs','domino_tui','domino_install','domino_agent','domino_agent_backend','domino_sources','domino_completion','domino_uninstall','domino_client_sources']
        if action == 'cli': names += ['domino_cli_sync']
        if 'domino_macos' in names: names += ['domino_macos_app']
        modules={name:compact_remote_source(Path(__file__).with_name(name+'.py').read_text()) for name in names}
        backend = compact_remote_source(REMOTE_SCRIPT.read_text())
        code = ('import sys,types;from pathlib import Path\n'
                '__domino_sources='+json.dumps(modules,ensure_ascii=False,separators=(',',':'))+'\n__domino_backend='+json.dumps(backend,ensure_ascii=False)+'\n'
                'import os;os.environ["DOMINO_LANG"]='+repr(__import__('domino_i18n').get_language())+'\n'
                '__domino_build__='+repr(__import__('install_domino').cli_build_info())+'\n'
                'for name,source in __domino_sources.items():\n'
                ' m=types.ModuleType(name);m.__file__=str(Path.home()/".local/share/domino/cli"/(name+".py"));sys.modules[name]=m;exec(compile(source,m.__file__,"exec"),m.__dict__)\n'
                'if "domino_cli" in sys.modules: sys.modules["domino_cli"].SOURCE_MODULES={**{name+".py":source for name,source in __domino_sources.items()},"install_domino.py":__domino_backend}\n'
                'sys.modules["install_domino"]=sys.modules["__main__"]\n'
                'exec(compile(__domino_backend,"<domino-backend>","exec"))')
        if action == 'cli':
            code = ('import sys,tempfile;from pathlib import Path\n'
                    '__sources='+json.dumps({**{name+'.py':text for name,text in modules.items()}, 'install_domino.py':backend},ensure_ascii=False,separators=(',',':'))+'\n'
                    'import os;os.environ["DOMINO_LANG"]='+repr(__import__('domino_i18n').get_language())+'\n'
                    'with tempfile.TemporaryDirectory(prefix="domino-command-") as directory:\n'
                    ' root=Path(directory)\n'
                    ' for name,source in __sources.items(): (root/name).write_text(source)\n'
                    ' sys.path[:0]=[str(root),str(Path.home()/".local/share/domino/cli/_vendor")]\n'
                    ' from domino_cli import main\n'
                    ' raise SystemExit(main(sys.argv[2:]))\n')
        import base64,bz2
        code = 'import base64,bz2;exec(compile(bz2.decompress(base64.b85decode('+repr(base64.b85encode(bz2.compress(code.encode(),9)).decode())+')),"<domino-remote>","exec"))'
        command = 'python3 -c ' + shlex.quote(code) + ' ' + shlex.join([action, *options])
        # Arguments are already included; retain room below the per-argument
        # bound for the terminating NUL and transport framing.
        if len(command.encode()) >= 128*1024-256:
            if len(shlex.join([action, *options]).encode()) >= 128*1024-1024:
                raise ToolError(_t('远端命令过长，请缩短参数；机器请求请用 --input 通过标准输入传入。'))
            from domino_cli_sync import streamed_remote_argv
            return streamed_remote_argv(self.command_argv, code, action, options, tty)
        return self.command_argv(command, tty)

    def info(self):
        code = ('import json,os,platform,shutil,sys; print(json.dumps({'
                '"system":platform.system(),"arch":platform.machine(),'
                '"python":list(sys.version_info[:2]),'
                '"home":os.path.expanduser("~"),"uid":os.getuid(),'
                '"systemd":os.path.isdir("/run/systemd/system"),'
                '"missing":[x for x in ["sudo","systemctl","curl","tar"] if not shutil.which(x)]}))')
        result = self.call('python3 -c ' + shlex.quote(code), capture_output=True, text=True)
        try:
            info = json.loads(result.stdout)
        except ValueError:
            raise ToolError(_t('无法解析目标信息；请检查目标 Python 3 或 shell 启动脚本输出。')) from None
        if info['system'] != 'Linux' or not info['systemd']:
            raise ToolError(_t('目标必须是使用 systemd 的 Linux 设备。'))
        if tuple(info['python']) < (3, 9):
            raise ToolError(_t('目标需要 Python 3.9 或更高版本。'))
        if info['uid'] == 0:
            raise ToolError(_t('请使用普通 SSH 用户（需有 sudo 权限），不要直接以 root 部署。'))
        normalize_arch(info['arch'])
        if info['missing']:
            raise ToolError(_t('目标缺少依赖：') + ', '.join(info['missing']))
        return info

    def action(self, action, *options, tty=False, **kwargs):
        return run(self.action_argv(action, *options, tty=tty), stage=_t('远端操作'), **kwargs)

    def __exit__(self, *exc):
        subprocess.run(['ssh', '-S', self.socket, '-O', 'exit', *self.options, self.target],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.temp.cleanup()


def update_vscode(target, proxy_port, path=None):
    path = path or Path.home() / 'Library/Application Support/Code/User/settings.json'
    if not path.is_file():
        raise ToolError(_t('找不到 VS Code 用户设置，请通过 --vscode-settings 指定路径。'))
    old = path.read_text()
    try:
        settings = json.loads(old)
    except ValueError:
        raise ToolError(_t('VS Code 设置包含 JSONC 注释或无效 JSON，未覆盖；请手动设置该主机代理。')) from None
    for key in ['remote.SSH.httpProxy', 'remote.SSH.httpsProxy']:
        current = settings.get(key, {})
        if isinstance(current, str):
            current = {'*': current} if current else {}
        if not isinstance(current, dict):
            raise ToolError(_t('现有 VS Code 代理设置类型不支持自动合并。'))
        settings[key] = {**current, target: f'http://127.0.0.1:{proxy_port}'}
    shutil.copy2(path, path.with_name('settings.json.bak-domino-' + time.strftime('%Y%m%d-%H%M%S')))
    private_write(path, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')


def deployment_progress(label, message):
    import install_domino as output
    output.human_row(label, (message, '2'), wrap=True)
    sys.stdout.flush()


def deployment_summary(target, result):
    import install_domino as output
    before, after = result.get('cli_before'), result['cli_version']
    country = result.get('exit_country') or _t('地区未返回')
    nodes = result.get('node_count')
    proxy = country + (_t(' · {0} 个节点', nodes) if type(nodes) is int else '')
    if result.get('provider_count'):
        proxy += _t(' · {0} 个节点集', result['provider_count'])
    command = 'domino ' + shlex.quote(target)
    version = f'{before} → {after}' if before and before != after else after
    if result.get('kept_newer'):
        version += _t('（保留目标新版）')
    with output.human_output():
        output.human_header(_t('部署完成'), target)
        output.human_row(_t('代理出网'), proxy)
        if result.get('system_proxy_supported') is not None:
            output.human_row(_t('系统代理'), _t('已接通') if result.get('system_proxy_enabled') else _t('无 GNOME 桌面会话'))
        if getattr(output,'OUTPUT_VERBOSE',False) or result.get('kept_newer') or before and before!=after:
            output.human_row(_t('CLI 版本'), version)
        enabled = result.get('shell_enabled')
        if type(enabled) is bool:
            output.human_row(_t('终端代理'), _t('已开启') if enabled else _t('已关闭；开启：') + command + ' shell on', wrap=True)
        output.human_row(_t('查看状态'), command + ' status', wrap=True)


def deploy(args, ssh, info, work):
    verbose = getattr(args, 'verbose', False)
    if not verbose:
        deployment_progress(_t('准备'), _t('配置与内核…'))
    package, manifest = prepare(args, normalize_arch(info['arch']), work)
    from domino_cli_sync import SyncError, license_text, make_wheel
    files = {name: (globals()['SOURCE_MODULES'][name].encode() if name in globals().get('SOURCE_MODULES', {})
                    else Path(__file__).with_name(name).read_bytes()) for name in CLI_MODULES}
    files.update({name: (Path(__file__).parent / name).read_bytes() for name in CLI_RESOURCES})
    try:
        wheel = make_wheel(files, work / f'domino_proxy-{VERSION}-py3-none-any.whl', VERSION, license_text())
    except SyncError as error:
        raise ToolError(str(error)) from None
    stage = ssh.call('umask 077; mktemp -d "$HOME/.domino-deploy.XXXXXXXX"',
                     capture_output=True, text=True).stdout.strip()
    expected_parent = Path(info['home'])
    if Path(stage).parent != expected_parent or not re.fullmatch(r'\.domino-deploy\.[A-Za-z0-9]+', Path(stage).name):
        raise ToolError(_t('远端临时目录不符合预期，停止上传。'))
    try:
        with package.open('rb') as payload:
            ssh.call('tar -xzf - -C ' + shlex.quote(stage), stdin=payload)
        with wheel.open('rb') as payload:
            ssh.call('umask 077; cat > ' + shlex.quote(stage + '/' + wheel.name), stdin=payload)
        ssh.call('python3 ' + shlex.quote(stage + '/cli/domino_cli_sync.py') + ' ' + shlex.quote(stage) + ' ' + VERSION +
                 (' --verbose' if verbose else ''),
                 tty=not args.batch)
        response = ssh.call('cat ' + shlex.quote(stage + '/deployment-summary.json'), capture_output=True, text=True)
        try:
            result = json.loads(response.stdout)
            if (not isinstance(result, dict) or result.get('schema') != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', result['cli_version'])
                    or not result.get('verified')):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ToolError(_t('部署已执行，但无法核实最终结果；请运行 domino ') + shlex.quote(ssh.target) + ' status。') from None
        if args.vscode:
            try:
                update_vscode(ssh.target, manifest['proxy_port'],
                              Path(args.vscode_settings).expanduser() if args.vscode_settings else None)
            except (ToolError, OSError):
                raise ToolError(_t('设备代理已部署成功，但本地 VS Code 设置未完成；无需重新安装设备服务。')) from None
            print(_t('本地 VS Code 主机代理已更新。'))
        if args.restart_vscode:
            ssh.action('restart-vscode')
        deployment_summary(ssh.target, result)
    finally:
        # Only remove the validated, freshly created staging directory.
        try:
            ssh.call('rm -rf -- ' + shlex.quote(stage), capture_output=True, timeout=20)
        except ToolError:
            print(_t('提示：远端临时目录未清理，请稍后检查。'), file=sys.stderr)


class DominoHelpFormatter(argparse.HelpFormatter):
    def _format_action_invocation(self, action):
        if getattr(action, '_domino_plain_command', False):
            default = self._get_default_metavar_for_positional(action)
            return ' '.join(self._metavar_formatter(action, default)(1))
        return super()._format_action_invocation(action)


class DominoDelayHelpFormatter(DominoHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class DelayAdvancedHelp(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        build_parser(advanced_delay_help=True).parse_args(['test','--help'])


class DominoParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', DominoHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        if getattr(self,'machine_mode',False):
            raise DomainError(_t('参数不符合命令定义，请通过 capabilities 查看参数。'),code='INVALID_ARGUMENT',exit_code=2)
        from install_domino import human_output
        with redirect_stdout(sys.stderr),human_output(),redirect_stderr(sys.stdout):
            super().error(message)

    def parse_args(self, args=None, namespace=None):
        arguments = list(sys.argv[1:] if args is None else args)
        commands = next((action.choices for action in self._actions if isinstance(action,argparse._SubParsersAction)), {})
        root = self.prog == 'domino' and 'deploy' in commands
        start=0
        prefix = None
        if root and len(arguments) >= 2 and not arguments[0].startswith('-') and arguments[0] not in commands and arguments[0] not in ['clients','source','subs','log-level'] and arguments[1] in commands:
            prefix = arguments.pop(0)
            try:
                destination(prefix)
            except DomainError:
                self.error(_t('目标地址无效；远端格式为 domino USER@IP COMMAND。'))
            if arguments[0] in ['deploy', 'plan']:
                arguments.insert(1, prefix)
        elif root and arguments and not arguments[0].startswith('-'):
            target = arguments[0]
            if target not in commands and is_target_address(target):
                arguments.insert(0,'deploy')
        command_arguments = list(arguments)
        defaults = {'configs': ({'list', 'add', 'switch', 'update', 'rename', 'remove', 'set-url'}, 'list'),
                    'proxy': ({'status', 'on', 'off'}, 'status'),
                    'shell': ({'status', 'on', 'off'}, 'status')}
        if root and start<len(arguments) and arguments[start] in defaults:
            actions, default = defaults[arguments[start]]
            if arguments[start] in ['proxy','shell'] and len(arguments) > start+1:
                action = arguments[start+1]
                if action not in actions and not action.startswith('-') and not is_target_address(action):
                    label = _t('系统代理') if arguments[start] == 'proxy' else _t('终端代理')
                    group = arguments[start]
                    self.error(_t('未知{0}动作：{1}。可用动作：status、on、off；关闭请用 domino {2} off；查询远程主机请用 domino HOST {3} status。', label, action, group, group))
            action_index=start+1
            while action_index<len(arguments) and arguments[action_index]=='--verbose':action_index+=1
            if action_index==len(arguments) or arguments[action_index] not in actions | {'-h', '--help'}:
                arguments.insert(start+1, default)
        result = super().parse_args(arguments, namespace)
        if root:
            if prefix is not None:
                if result.command == 'rules' and getattr(result, 'target', None) in ['add','remove']:
                    if result.rule_target not in (None, prefix):
                        self.error(_t('目标只能指定一次。'))
                    result.rule_target = prefix
                else:
                    if getattr(result, 'target', None) not in (None, prefix):
                        self.error(_t('目标只能放在命令前：domino USER@IP COMMAND。'))
                    result.target = prefix
            elif not hasattr(result, 'target'):
                result.target = None
            result.remote_arguments = command_arguments
            if result.command in CONFIG_COMMANDS:
                result.configs_action = result.command
                result.command = 'configs'
        return result


CONFIG_COMMANDS = ('list', 'add', 'switch', 'update', 'remove', 'rename', 'set-url')


def format_group_help(commands):
    """Keep subcommands in their own group's help, using plain labels."""
    for group in commands.choices.values():
        for action in group._actions:
            if isinstance(action, argparse._SubParsersAction):
                format_group_help(action)
                for child in action._get_subactions():
                    child._domino_plain_command = True
        inline = getattr(group, 'inline_command_help', ())
        if inline:
            section = group.add_argument_group(_t('子命令'))
            for child in inline:
                child._domino_plain_command = True
            section._group_actions.extend(inline)


def build_parser(*, advanced_delay_help=False, installing=False, machine_mode=False):
    parser = DominoParser(prog='domino', description=_t(DESCRIPTION),
                          usage='domino [USER@IP] COMMAND [ARGS] [options]',
                          epilog=_t('本机：domino list；远端：domino user@host list；部署：domino user@host deploy。'))
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--lang', choices=['zh', 'en'], help=_t('仅本次命令使用的语言：zh 或 en'))
    sub = parser.add_subparsers(dest='command', required=True)
    language = sub.add_parser('language', aliases=['lang'], help=_t('查看或保存界面语言'))
    language.add_argument('language', nargs='?', choices=['zh', 'en'], help=_t('zh 为中文，en 为英文；保存后对后续命令生效'))
    source_options = argparse.ArgumentParser(add_help=False)
    source_options.add_argument('--local-proxy', help=_t('源电脑下载使用的代理，例如 http://127.0.0.1:7897；不作为目标机上游'))
    source_options.add_argument('--controller', help=_t('源 Clash 本机控制接口 URL'))
    source_options.add_argument('--controller-socket', help=_t('源 Clash Unix 控制 socket'))
    source_options.add_argument('--resource-dir', action='append', default=[], help=_t('附加本地资源目录；可重复指定，用于 provider、证书和 Geo 数据库'))
    source_options.add_argument('--core', help=_t('本机 Mihomo 可执行文件，用于提前校验配置'))
    source_options.add_argument('--mihomo-version', default='latest', help=_t('固定内核版本，例如 v1.19.33；默认最新稳定版，本机重复安装优先复用已安装版本的已校验缓存'))
    source_options.add_argument('--proxy-port', type=port, default=DEFAULT_PROXY_PORT,
                                help=_t('代理端口，默认 {0}', DEFAULT_PROXY_PORT))
    source_options.add_argument('--api-port', type=port, default=DEFAULT_API_PORT,
                                help=_t('本机控制接口端口，默认 {0}', DEFAULT_API_PORT))
    source_options.add_argument('--no-shell-env', action='store_true', help=_t('不设置目标终端/VS Code 的代理环境'))
    source_options.add_argument('--test-url', default='https://www.cloudflare.com/cdn-cgi/trace', help=_t('部署后 HTTPS 出网验证地址'))
    source_parent = argparse.ArgumentParser(add_help=False, parents=[source_options])
    source_group = source_parent.add_mutually_exclusive_group()
    source_group.add_argument('--source', help=_t('当前生效的 Clash/Mihomo YAML 或 JSON 配置'))
    source_group.add_argument('--subscription', help=_t('返回完整 Clash/Mihomo 配置的 HTTPS 订阅链接'))
    p = sub.add_parser('catch', parents=[source_options], help=_t('选择并捕获外部代理配置'),
                       description=_t('选择本机 Clash/Mihomo 运行配置或保存配置；catch all 捕获全部。\n捕获成功后自动开启 Domino；已有安装保留当前配置和节点选择。'))
    p.add_argument('capture_scope', nargs='?', choices=['all'], help=_t('捕获所有兼容配置，并跳过重复项'))
    p.add_argument('--source', help=_t('明确选择本地 Clash/Mihomo 配置文件'))
    p.add_argument('--yes', action='store_true', help=_t('接受捕获影响，跳过最终确认；多个来源仍需选择或指定 all'))
    p.add_argument('--batch', action='store_true', help=_t('禁止 sudo 密码询问；不代表同意导入'))
    p.set_defaults(subscription=None, bundle=None, name=None)
    def target_options(optional=False, parent=None, include_target=True):
        if parent is None:
            parent = argparse.ArgumentParser(add_help=False)
        description = (_t('localhost 管理当前用户的本机；USER@IP 或 SSH 别名管理远端；省略时等同 localhost')
                       if optional else _t('目标 IP、SSH Host 别名或 USER@IP；本机请运行安装程序'))
        if include_target:
            parent.add_argument('target', **({'nargs': '?'} if optional else {}), help=argparse.SUPPRESS)
        parent.add_argument('--user', help=_t('SSH 用户名；省略时使用 SSH 配置'))
        parent.add_argument('--ssh-port', type=ssh_port, help=_t('SSH 端口；省略时使用 SSH 配置，通常为 22'))
        parent.add_argument('--identity', help=_t('SSH 私钥路径，密码不会保存'))
        if '--batch' not in parent._option_string_actions:
            parent.add_argument('--batch', action='store_true', help=_t('禁止 SSH 和 sudo 密码询问'))
        return parent
    target_parent = target_options()
    manage_parent = target_options(optional=True)
    p = sub.add_parser('deploy', parents=[target_parent, source_parent], help=_t('将代理部署到指定电脑'),
                       prog='domino', usage='domino USER@IP deploy [options]',
                       description=_t('选择本机兼容配置部署到指定电脑；未指定来源时，交互终端先显示配置选择菜单。'))
    p.add_argument('--verbose', action='store_true', help=_t('显示配置路径、完整安装过程和终端接入说明'))
    p.add_argument('--vscode', action='store_true', help=_t('同时更新本机 VS Code 对该目标的代理设置'))
    p.add_argument('--vscode-settings', help=_t('VS Code 用户 settings.json 路径'))
    p.add_argument('--restart-vscode', action='store_true', help=_t('停止目标当前用户的 VS Code/Codex 进程以应用环境'))
    sub.add_parser('plan', parents=[target_parent, source_parent], help=_t('只检查目标和源配置，不修改设备'))
    p = sub.add_parser('status', parents=[manage_parent], help=_t('查看服务、系统代理目标和实际出网状态'),
                       description=_t('查看服务、自启动、代理端口及实际出网状态，同时显示系统代理是否开启及其目标。Domino 默认代理地址为 127.0.0.1:{0}，自定义端口时显示实际值。', DEFAULT_PROXY_PORT))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('scan', help=_t('扫描外部代理配置和 Domino 管理的代理配置'),
                       description=_t('分区展示外部客户端配置和 Domino 管理的配置列表，分别统计数量。\n保存配置只检查兼容性，不借用运行端口证明出网；运行入口并发检查，每个超时 5 秒。\n使用 --source 检查指定来源，不切换或管理来源客户端。'))
    p.add_argument('--json', action='store_true')
    p.add_argument('--source', help=_t('检查指定的本地 Clash/Mihomo 配置文件'))
    p = sub.add_parser('doctor', parents=[manage_parent], help=_t('比较系统直连与代理 HTTPS，检查 DNS 和路由（不修改设置）'))
    p.add_argument('--url', default='https://www.cloudflare.com/cdn-cgi/trace', help=_t('无凭据和查询参数的 HTTPS 地址；省略时检查默认公网地址'))
    p.add_argument('--insecure', action='store_true', help=_t('仅诊断时跳过证书校验'))
    p.add_argument('--verbose', action='store_true', help=_t('显示 DNS、hosts 和路由等排查详情'))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('nodes', parents=[manage_parent], help=_t('查看策略组、当前选择和可用节点'))
    p.add_argument('--group', help=_t('只查看指定策略组的候选节点'))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('select', parents=[manage_parent if machine_mode else target_options(optional=True, include_target=False)],
                       help=_t('交互选择节点，或按名称切换节点'), usage='domino [USER@IP] select [NAME] [options]',
                       description=_t('不带名称打开节点选择菜单；填写名称或关键词，匹配多个时选择候选编号。\n多个手动策略组可选时再选择策略组；仅修改当前配置的节点选择。'),
                       epilog=_t('示例：domino select；domino select "日本"；domino USER@IP select；domino select "日本" --group "节点选择"；含方括号或空格的节点名必须加引号。'))
    if not machine_mode:
        p.add_argument('name', nargs='?', metavar='NAME', help=_t('节点名称或关键词；省略时交互选择'))
        p.set_defaults(target=None)
    p.add_argument('--group', required=machine_mode, help=_t('指定手动策略组；省略时按可选范围选择'))
    p.add_argument('--node', required=machine_mode, help=_t('兼容写法：指定该组中的完整节点或下层策略组名称'))
    for action, help_text in [('start', _t('开启 Domino，接通系统代理')), ('stop', _t('关闭 Domino，恢复系统代理')), ('restart', _t('重启 Domino 并接通系统代理')), ('logs', _t('查看代理服务日志'))]:
        description = {
            'start': _t('启动 Domino 服务，等待内核就绪后开启 HTTP、HTTPS、SOCKS 系统代理，并指向 Domino 代理地址（默认 127.0.0.1:{0}，自定义时使用实际端口）。', DEFAULT_PROXY_PORT),
            'stop': _t('先恢复仍由 Domino 接管的系统代理设置，再停止服务；保留其他程序之后的修改。'),
            'restart': _t('重启 Domino 服务，并重新开启系统代理，指向 Domino 代理地址（默认 127.0.0.1:{0}，自定义时使用实际端口）。', DEFAULT_PROXY_PORT),
        }.get(action, help_text + '。')
        p = sub.add_parser(action, parents=[manage_parent], help=help_text,
                           description=description + _t(' 系统代理支持 macOS 和 Ubuntu GNOME 桌面；无桌面服务器提供代理入口，终端代理通过 domino shell 独立管理。'))
        if action == 'logs':
            p.add_argument('--lines', type=int, default=100)
            p.add_argument('--follow', action='store_true')
    p = sub.add_parser('mode', parents=[manage_parent], help=_t('查看或设置代理模式'))
    p.add_argument('--set', choices=['rule', 'global', 'direct'])
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('log', parents=[target_options(optional=True, include_target=False)],
                       help=_t('查看或设置日志级别；日志内容用 logs 查看'),
                       usage='domino [USER@IP] log [LEVEL] [options]',
                       description=_t('列出全部日志级别，用 ● 标记当前项；填写级别直接设置。日志内容使用 domino logs 查看。'),
                       epilog=_t('示例：domino log；domino log debug；domino USER@IP log warning。'))
    p.add_argument('level', nargs='?', choices=['debug', 'info', 'warning', 'error', 'silent'], metavar='LEVEL')
    p.add_argument('--set', choices=['debug', 'info', 'warning', 'error', 'silent'], help=argparse.SUPPRESS)
    p.add_argument('--json', action='store_true')
    p.set_defaults(target=None)
    p = sub.add_parser('test', aliases=['delay'], parents=[target_options(optional=True, include_target=False)], help=_t('汇总全部配置的节点连通性，或查看指定配置的节点延迟'),
                      usage='domino [USER@IP] test [NAME] [options]',
                      formatter_class=DominoDelayHelpFormatter,
                      description=(_t('测试 HTTPS 请求延迟，结果单位为毫秒（ms），不测下载带宽。\n不带名称检测所有配置，汇总可用和超时/不可用节点数；填写完整配置名查看节点明细。\n完整名称优先；部分名称唯一时直接使用，匹配多个时列出候选。') if advanced_delay_help else
                                   _t('汇总所有配置的节点总数、可用数和超时/不可用数；填写配置名查看逐节点延迟。\n本机省略目标；远端使用 domino USER@IP test NAME。')),
                      epilog=(_t('示例：\n  domino test                          汇总本机所有配置\n  domino test 自动选择                 测组内各项，可省略名称前的符号\n  domino test 美国TRI002                测唯一匹配的节点\n  domino test "[HY2]美国TRI002"          使用完整名称；方括号、空格需加引号\n  domino test 自动选择 --timeout 10000  单项最多等待 10 秒\n  domino user@192.0.2.10 test   汇总远端所有配置\n  domino user@192.0.2.10 test 自动选择  测远端指定组\n\n--url 和 --timeout 后必须填写值；使用默认值时省略整个选项。\nSSH 别名示例：domino my-server test；支持 --user、--ssh-port、--identity、--batch。\n未找到名称时，可运行 domino nodes 查看节点和策略组。') if advanced_delay_help else
                             _t('常用示例：\n  domino test                         汇总本机所有配置\n  domino test feiniao                 测配置 feiniao 的全部节点\n  domino user@192.0.2.10 test      汇总远端所有配置\n  domino test --timeout 10000         超时设为 10 秒\n\n高级用法：domino test --help-all')))
    p.set_defaults(command='test')
    sub._choices_actions[-1].metavar = 'test'
    p._positionals.title = _t('位置参数')
    p._optionals.title = _t('选项')
    p._option_string_actions['--help'].help = _t('显示帮助并退出')
    p.add_argument('name', nargs='?', metavar='NAME', help=_t('节点或策略组名称，可用唯一部分名称；省略或 all 按配置汇总'))
    p.add_argument('target', nargs='?', metavar='TARGET', help=argparse.SUPPRESS)
    choice = p.add_argument_group(_t('兼容写法（通常无需使用）')).add_mutually_exclusive_group()
    choice.add_argument('--config', help=_t('测试配置库中指定配置的全部节点，不切换当前配置'))
    choice.add_argument('--node', help=_t('测速节点的完整名称或唯一部分名称；含方括号、空格时请加引号'))
    choice.add_argument('--group', help=_t('明确按策略组名称匹配，测试组内各项'))
    choice.add_argument('--all', action='store_true', help=_t('按配置汇总，等同不填写名称'))
    p.add_argument('--url', default='https://www.gstatic.com/generate_204', help=_t('HTTPS 测速地址（默认：https://www.gstatic.com/generate_204）'))
    p.add_argument('--timeout', type=int, default=5000, metavar='MS', help=_t('单项超时，默认 5000 毫秒（5 秒），范围 100–60000'))
    p.add_argument('--json', action='store_true', help=_t('输出 JSON，供脚本或 Agent 使用'))
    p.add_argument('--help-all', action=DelayAdvancedHelp, nargs=0, help=argparse.SUPPRESS)
    if not advanced_delay_help:
        for action in p._actions:
            if action.dest not in ['help','timeout','json','config']:
                action.help = argparse.SUPPRESS
    p = sub.add_parser('connections', parents=[manage_parent], help=_t('查看连接及其规则/节点，或关闭连接'))
    choice = p.add_mutually_exclusive_group()
    choice.add_argument('--close')
    choice.add_argument('--all', action='store_true')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('traffic', parents=[manage_parent], help=_t('内嵌动态流量面板，--full 使用全屏'),
                       description=_t('默认内嵌刷新全部流量信息、趋势图和峰值，保留终端历史；--full 切换为全屏。\nq、Esc 或 Ctrl+C 退出。\nJSON 和重定向默认单次采样；--watch 可持续输出采样。'))
    p.add_argument('--full', action='store_true', help=_t('使用全屏显示；内容和功能与默认内嵌面板一致'))
    p.add_argument('--watch', action='store_true', help=_t('持续采样；终端默认开启，JSON / 重定向时可显式使用'))
    p.add_argument('--interval', type=float, default=1, help=_t('刷新间隔，默认 1 秒，范围 0.2–60 秒'))
    p.add_argument('--count', type=int, default=0, help=_t('持续采样次数，0 表示直到退出'))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('rules', parents=[manage_parent], help=_t('分流规则管理'),
                       usage='domino [USER@IP] rules [--match TEXT | --custom] [--limit N] [--json]\n'
                             '       domino [USER@IP] rules add "RULE" [--json]\n'
                             '       domino [USER@IP] rules remove "RULE" [--json]',
                       description=_t('规则示例：DOMAIN-SUFFIX,example.com,DIRECT。新增规则默认置顶，先校验再生效。'))
    p.inline_command_help = [
        argparse.Action([], dest='add', metavar='add', help=_t('添加自定义规则')),
        argparse.Action([], dest='remove', metavar='remove', help=_t('删除自定义规则')),
    ]
    p.add_argument('rule', nargs='?', help=_t('add/remove 后的完整 Mihomo 规则，请用引号包裹'))
    p.add_argument('rule_target', nargs='?', help=argparse.SUPPRESS)
    p.set_defaults(add_rule=None, remove_rule=None)
    p.add_argument('--custom', action='store_true', help=_t('查看自定义规则原文'))
    p.add_argument('--match')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('providers', parents=[manage_parent], help=_t('节点与规则集合管理'))
    p.add_argument('--kind', choices=['proxy', 'rule'], default='proxy')
    p.add_argument('--update')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('configs', help=_t('配置管理（在线订阅与快照）'),
                       description=_t('直接运行 domino list 查看列表；使用下列子命令管理在线订阅与配置快照。'))
    subscription_commands = p.add_subparsers(dest='configs_action')
    query = subscription_commands.add_parser('list', parents=[manage_parent], help=_t('查看 Domino 管理的所有代理配置'),
                                             description=_t('查看配置列表；可使用 --import-current 保存当前配置快照。'))
    from install_domino import subscription_arguments
    subscription_arguments(query)
    for legacy in query._actions:
        if legacy.dest in ['add','use','update','remove','rename','set_url','update_all','url','new_name']:
            legacy.help = argparse.SUPPRESS
    details = {'add': _t('添加命名订阅，默认隐藏输入地址；可用 --url 提供完整配置订阅地址。'),
               'switch': _t('切换本机当前配置；在线订阅首次使用时自动下载。'),
               'update': _t('更新指定订阅；名称为 all 时更新全部在线订阅。'),
               'rename': _t('修改配置名称，保留配置内容和订阅地址。'),
               'remove': _t('删除非当前配置；当前使用的配置需先切换后再删除。'),
               'set-url': _t('设置或修改订阅地址，默认隐藏输入；本地快照设置地址后可在线更新。')}
    for action, help_text in [('add', _t('添加订阅配置')), ('switch', _t('切换本机配置')), ('update', _t('更新配置（all 表示全部在线订阅）')),
                              ('rename', _t('重命名配置')), ('remove', _t('删除配置')), ('set-url', _t('设置订阅地址'))]:
        p = subscription_commands.add_parser(action, help=help_text, description=details[action])
        p.add_argument('name', help=_t('配置名称') + (_t('；all 表示全部在线订阅') if action == 'update' else ''))
        if action == 'rename':
            p.add_argument('new_name', help=_t('新的配置名称'))
        if action in ['add', 'set-url']:
            p.add_argument('--url', help=_t('完整配置 HTTPS 订阅地址；省略时隐藏输入'))
        target_options(optional=True, parent=p)
        p.add_argument('--json', action='store_true')
    p = sub.add_parser('proxy', help=_t('系统代理管理'))
    proxy_commands = p.add_subparsers(dest='proxy_action')
    details = {'status': _t('查看当前系统代理，省略动作时默认执行此操作。'),
               'on': _t('将系统代理指向 Domino，并保存此前的设置。'),
               'off': _t('恢复开启 Domino 系统代理前保存的设置。')}
    for action, help_text in [('status', _t('查看系统代理（默认）')), ('on', _t('开启系统代理')),
                              ('off', _t('恢复原代理设置'))]:
        p = proxy_commands.add_parser(action, parents=[manage_parent], help=help_text, description=details[action])
        p.add_argument('--set', choices=['on', 'off'], help=argparse.SUPPRESS)
        p.add_argument('--service', help=_t('macOS 网络服务名称，默认使用当前出站网络服务'))
        p.add_argument('--json', action='store_true')
    p = sub.add_parser('shell', help=_t('终端代理管理'),
                       description=_t('通过代理环境变量让终端（Terminal）中的程序使用 Domino；on 开启、off 恢复原变量、status 查看端口和环境变量。'),
                       epilog=_t('已接入终端返回命令行后同步。接入方法：. "$HOME/.config/domino/proxy.env"'))
    shell_commands = p.add_subparsers(dest='shell_action')
    for action, text in [('status',_t('查看终端代理状态')),('on',_t('使用 Domino 代理')),('off',_t('恢复原代理设置'))]:
        child = shell_commands.add_parser(action, parents=[manage_parent], help=text,description=text)
        child.add_argument('--json', action='store_true')
    sub.add_parser('ui', parents=[manage_parent], help=_t('打开纯终端交互控制台'))
    p = sub.add_parser('env', parents=[manage_parent], help=_t('输出当前 shell 的代理设置，使用 eval "$(domino env)" 生效'))
    p.add_argument('--unset', action='store_true')
    p = sub.add_parser('completion', help=_t('输出 zsh / bash 的 Tab 补全脚本'))
    p.add_argument('shell', choices=['zsh', 'bash'])
    p = sub.add_parser('rollback', parents=[manage_parent], help=_t('恢复本机或指定电脑上一次部署前的服务和环境文件'))
    p.add_argument('--backup', help=_t('指定本工具生成的备份 ID，默认最近一次'))
    p = sub.add_parser('uninstall', parents=[manage_parent], help=_t('卸载运行环境并清理终端接入、配置及备份'),
                       usage='domino [USER@IP] uninstall [options]',
                       description=_t('恢复 Domino 接管的代理，停止并移除服务，删除内核、配置库、备份和默认缓存。仅清理 Domino 的终端标记区块；包管理器安装的 CLI 由原包管理器卸载。'))
    p.add_argument('--yes', action='store_true', help=_t('确认删除运行配置、配置库与备份'))
    p.add_argument('--dry-run', action='store_true', help=_t('只预览清理范围，不修改任何文件或服务'))
    p = sub.add_parser('export', parents=[source_parent], help=_t('导出内核和配置，供目标电脑离线安装'),
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description=_t('将 Mihomo 内核、节点与分流规则、相关资源及 Domino 管理程序打包为 .tar.gz。\n在本机生成安装包后，将包复制到另一台 Linux 电脑进行安装。\n适合目标电脑无法下载内核或管理依赖的情况；安装后仍需能连接代理节点。\n安装包包含节点凭据，请交给需要使用该配置的人。'),
                       epilog=_t('示例：在本机准备 Linux ARM64 安装包\n  domino export --arch arm64 --output ./domino-linux-arm64.tar.gz\n\n复制到目标电脑后运行安装程序\n  ./install.sh --bundle ./domino-linux-arm64.tar.gz\n\n目标尚未安装 Domino 命令时，首次离线引导步骤见 README。'))
    p.add_argument('--arch', choices=['arm64', 'amd64'], required=True,
                   help=_t('目标 Linux 电脑的架构：ARM64 选 arm64，x86_64 选 amd64'))
    p.add_argument('--output', required=True, help=_t('安装包输出路径（包含节点凭据，权限 600）'))
    p = sub.add_parser('init', parents=[source_parent], help=_t('在本机 macOS/Linux 安装独立代理和管理命令'))
    if installing:
        p.prog = './install.sh'
        p.description = _t('安装 Domino 内核、配置和后台服务；未提供节点配置时先准备基础环境，随后用 configs add/switch 配置订阅。')
    p.add_argument('--bundle', help=_t('使用 Domino export 生成的离线安装包'))
    p.add_argument('--name', help=_t('为 --subscription 保存名称；省略时沿用已有名称或使用订阅主机名'))
    p.add_argument('--batch', action='store_true', help=_t('禁止 sudo 密码询问'))
    # Keep the legacy local installation entry point working but hidden from help.
    sub._choices_actions = [action for action in sub._choices_actions if action.dest != 'init']
    # Flat configuration commands share the same backend and argument definitions.
    for action in CONFIG_COMMANDS:
        child = subscription_commands.choices[action]
        public = sub.add_parser(action, parents=[child], add_help=False,
                                help=next((a.help for a in subscription_commands._choices_actions if a.dest == action), action),
                                description=child.description)
        public.set_defaults(configs_action=action)
    sub._choices_actions = [a for a in sub._choices_actions if a.dest not in ['configs', 'proxy']]
    for command in ['catch', 'scan', 'export', 'init']:
        target_options(parent=sub.choices[command], include_target=False)
    detailed_commands={'catch','deploy','status','scan','nodes','select','mode','log','test','configs','proxy','shell','init','start','stop','restart',
                       'rules','providers',*CONFIG_COMMANDS}
    def detail_option(child):
        if '--verbose' not in child._option_string_actions:
            child.add_argument('--verbose',action='store_true',default=argparse.SUPPRESS,help=_t('显示路径、诊断信息和操作说明'))
        for action in child._actions:
            if isinstance(action,argparse._SubParsersAction):
                for nested in {id(p):p for p in action.choices.values()}.values():detail_option(nested)
    for command in detailed_commands:detail_option(sub.choices[command])
    sub.metavar = 'COMMAND'
    if machine_mode:
        sub.add_parser('capabilities',parents=[manage_parent])
        p=sub.add_parser('call',parents=[target_options(include_target=False)])
        p.add_argument('operation')
        p.add_argument('target',nargs='?',help=argparse.SUPPRESS)
        def mark(parser):
            parser.machine_mode=True
            for action in parser._actions:
                if isinstance(action,argparse._SubParsersAction):
                    for child in action.choices.values(): mark(child)
        mark(parser)
    format_group_help(sub)
    return parser


def local_target():
    if sys.platform not in ['linux', 'darwin'] or (sys.platform == 'linux' and not Path('/run/systemd/system').is_dir()):
        raise ToolError(_t('安装支持 macOS 和使用 systemd 的 Linux。'))
    if os.getuid() == 0:
        raise ToolError(_t('请以具有 sudo 权限的普通用户安装，不要直接使用 root。'))
    dependencies = ['curl', 'launchctl'] if sys.platform == 'darwin' else ['curl', 'sudo', 'systemctl']
    missing = [name for name in dependencies if not shutil.which(name)]
    if missing:
        raise ToolError(_t('本机缺少依赖：') + ', '.join(missing))
    return normalize_arch(platform.machine())


def unpack_bundle(package, directory):
    # Compatible with Python 3.9: reject links, special files and escaping paths explicitly.
    with tarfile.open(package, 'r:gz') as archive:
        for member in archive:
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts or not (member.isdir() or member.isfile()):
                raise ToolError(_t('离线包包含不安全的路径或文件类型，未安装。'))
            destination = directory / relative
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(0o600)
    for name in ['mihomo', 'manifest.json', 'data/config.json', 'selections.json']:
        if not (directory / name).is_file():
            raise ToolError(_t('离线包缺少必要文件，请使用 Domino export 重新生成。'))
    (directory / 'mihomo').chmod(0o755)


def command_overview_snapshot():
    """Bounded loopback reads only; no service, desktop, traffic or exit probes."""
    import install_domino as output
    app,_=output.current_installation()
    path=app/'data/config.json'
    result={'installed':path.is_file(),'reachable':False,'node_count':None,'group_count':None,'cli_build':output.cli_build_info()}
    if not result['installed']: return result
    try:
        config=json.loads(path.read_text())
        result.update(mode=config.get('mode'),proxy_port=config.get('mixed-port'),subscription=output.subscription_name(app),
                      awaiting_subscription=output.subscription_pending(app,config))
        def read(route):
            try:
                return json.loads(output.controller(app/'data',route,timeout=.5))
            except (DomainError,OSError,ValueError,KeyError,TypeError):return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            runtime,proxies=list(pool.map(read,['/configs','/proxies']))
        if isinstance(runtime,dict):result['mode']=runtime.get('mode',result.get('mode'))
        if not isinstance(runtime,dict) or not isinstance(proxies,dict) or not isinstance(proxies.get('proxies'),dict):return result
        result['reachable']=True
        def provider_api(route):
            value=read(route)
            if not isinstance(value,dict):raise output.InstallError(_t('无法读取节点信息。'))
            return value
        live=output.proxy_inventory(proxies['proxies'],api=provider_api)
        groups=[name for name,item in live.items() if isinstance(item.get('all'),list)
                and (name!='GLOBAL' or result['mode']=='global')]
        nodes=[name for name,item in live.items() if not isinstance(item.get('all'),list)
               and name not in ['DIRECT','REJECT','REJECT-DROP','PASS','COMPATIBLE']]
        result.update(node_count=len(nodes),group_count=len(groups))
    except (DomainError,OSError,ValueError,KeyError,TypeError,AttributeError):pass
    return result


def common_operations():
    import install_domino as output
    import domino_tui
    def command_text(command):
        return ' '.join(output.human_style(token, '33' if token in ['USER@IP', 'COMMAND'] or
                                          token.startswith('[') and token.endswith(']') else '1;36')
                        for token in command.split())
    groups = [
        (_t('常用入口'), [
            ('domino USER@IP', _t('将代理部署到指定电脑（等同 domino USER@IP deploy）')),
            ('domino ui', _t('打开交互控制台')),
            ('domino scan', _t('扫描外部代理配置和 Domino 管理的代理配置')),
            ('domino list', _t('查看 Domino 管理的所有代理配置')),
            ('domino language en / zh', _t('查看或保存界面语言')),
            ('domino catch', _t('选择并捕获外部代理配置'))]),
        (_t('节点与检测'), [
            ('domino nodes', _t('查看当前配置的节点和策略组')),
            ('domino select [NAME]', _t('选择节点；可输入名称或关键词')),
            ('domino test [CONFIG]', _t('检测全部配置；指定配置查看各节点结果'))]),
        (_t('服务与代理'), [
            ('domino start', _t('开启 Domino，接通系统代理（默认端口 {0}）', DEFAULT_PROXY_PORT)),
            ('domino stop', _t('关闭 Domino，恢复系统代理设置')),
            ('domino status', _t('查看服务、系统代理和出网状态')),
            ('domino uninstall', _t('卸载运行环境，清理配置和终端接入')),
            ('domino shell on', _t('终端使用 Domino 代理')),
            ('domino shell off', _t('恢复终端原代理设置')),
            ('domino shell status', _t('查看终端代理状态')),
            ('domino traffic', _t('查看内嵌动态流量面板'))])]
    width = max(len(command) for _, rows in groups for command, _ in rows)
    snapshot = command_overview_snapshot()
    with output.human_output():
        print(domino_tui.command_banner(snapshot,VERSION,
                                      columns=shutil.get_terminal_size((100,24)).columns))
        if not snapshot.get('reachable') or snapshot.get('awaiting_subscription'):
            output.human_row(_t('建议下一步'), command_text(output.recommended_action(snapshot)), wrap=True)
        output.human_header(_t('命令概览'))
        print('  ' + output.human_style('usage:', '1') + ' ' + command_text('domino [USER@IP] COMMAND [ARGS] [options]'))
        for title, rows in groups:
            print('\n  ' + output.human_style(title, '1;36'))
            for command, description in rows:
                description = description.replace('domino USER@IP deploy', command_text('domino USER@IP deploy'))
                print('  ' + command_text(command) + ' ' * (width-len(command)+2) + description)
        print('\n  ' + command_text('domino -h') + ' ' * (width-len('domino -h')+2) +
              _t('查看完整帮助；') + command_text('domino COMMAND -h') + _t(' 查看命令参数'))


def owned_source(path):
    resolved = path.resolve()
    roots = [Path.home() / '.local/share' / name for name in ['domino', 'robot-clash']]
    return any(path.absolute().is_relative_to(root.absolute()) or resolved.is_relative_to(root.resolve())
               for root in roots)


def source_candidates(*, include_saved=False, include_owned=False):
    candidates = []
    seen = set()
    profiles, _ = read_verge_profiles() if include_saved else ({}, [])
    for path in [*discover_sources(), *profiles]:
        try:
            resolved = path.resolve()
            if (not include_owned and owned_source(path)) or resolved in seen:
                continue
            seen.add(resolved)
            if source_details(path)['compatible_config_found']:
                candidates.append(path)
        except (DomainError, OSError, ValueError, TypeError, AttributeError, KeyError,
                RuntimeError, argparse.ArgumentTypeError):
            continue
    return candidates


def capture_candidates(*, include_saved=False):
    return source_candidates(include_saved=include_saved)


def select_deployment_source(args):
    """Choose a local source before connecting, downloading, or changing a target."""
    if args.source or args.subscription or not sys.stdin.isatty():
        return args
    paths = source_candidates(include_saved=True, include_owned=True)
    if not paths:
        raise ToolError(_t('未发现兼容配置，请用 --source 指定配置，或用 --subscription 提供完整配置订阅。'))
    source_choices(paths, title=_t('选择部署配置'), summary=_t('{0} 个本机配置 · 目标 {1}', len(paths), args.target),
                   compact=not getattr(args, 'verbose', False))
    try:
        value = input(_t('  选择配置    编号（回车取消）：')).strip()
    except EOFError:
        value = ''
    if not value:
        import install_domino as output
        with output.human_output():
            output.human_header(_t('部署已取消'), _t('未修改目标设备。'), '33')
        return None
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= len(paths):
        raise ToolError(_t('配置编号无效，未部署。'))
    selected = copy.copy(args)
    selected.source = str(paths[int(value) - 1].resolve())
    return selected


def capture_input(label, hint):
    import install_domino as output
    prompt = '  ' + output.human_style(label, '2') + ' ' * max(2, output.HUMAN_LABEL_WIDTH-output.human_width(label)) + hint
    try:
        return input(prompt).strip()
    except EOFError:
        return ''
    except KeyboardInterrupt as error:
        error.domino_capture_prompt = True
        raise


def capture_cancelled():
    import install_domino as output
    with output.human_output():
        output.human_header(_t('捕获已取消'), _t('未修改本机 Domino。'), '33')


def source_choices(paths, *, title, summary, allow_all=False, compact=False):
    import install_domino as output
    saved = False
    with output.human_output():
        output.human_header(title, summary)
        for index, path in enumerate(paths, 1):
            if index > 1 and not compact: print()
            identity = source_identity(path)
            if source_name(path, identity):
                name = source_name(path, identity)
            elif path.name == 'clash-verge.yaml':
                name = _t('Clash Verge · 运行配置')
            elif owned_source(path):
                name = ('robot-clash' if path.parent.parent.name == 'robot-clash' else 'Domino') + _t(' · 当前配置')
            else:
                name = path.name
            if compact and identity.get('source_kind') == 'profile':
                saved = True
                name += _t('（当前保存项）') if identity.get('client_current') else _t('（已保存）')
            output.human_row(str(index), (name, '1'), wrap=True)
            if compact:
                continue
            if identity:
                output.human_row(_t('配置选择'), (profile_status(identity), '2'), wrap=True)
                if identity.get('check_note') and source_name(path, identity).startswith('v2rayN'):
                    output.human_row(_t('捕获范围'), (identity['check_note'], '2'), wrap=True)
            try: display = '~/' + str(path.relative_to(Path.home()))
            except ValueError: display = str(path)
            output.human_row(_t('配置文件'), (display, '2'), wrap=True)
        print()
        if compact:
            if saved:
                output.human_row(_t('保存配置'), _t('使用文件内默认节点'), wrap=True)
            return
        if allow_all:
            output.human_row('all', (_t('全部配置'), '1'))
        output.human_row(_t('选择方式'), _t('输入编号或 all；回车取消。') if allow_all else _t('输入配置编号；回车取消。'), wrap=True)


def capture_choices(paths, *, allow_all=True):
    source_choices(paths, title=_t('选择捕获配置'), summary=_t('{0} 个外部配置 · 重复项自动跳过', len(paths)),
                   allow_all=allow_all)


def capture_status(label, text, tone):
    import install_domino as output
    with output.human_output():
        output.human_row(label, (text, tone), wrap=True)


def start_after_capture(args):
    """Start Domino using its current configuration, just like `domino start`."""
    import install_domino as output
    try:
        with output.deployment_lock():
            output.service_action('start', non_interactive=args.batch)
    except (DomainError, OSError, ValueError, RuntimeError) as error:
        reason = str(error) if isinstance(error, DomainError) else type(error).__name__
        raise ToolError(_t('配置已保存，但自动开启 Domino 失败：') + reason,
                        code=getattr(error, 'code', 'OPERATION_FAILED'), effect='unknown') from None


def catch(args):
    import install_domino as output
    from domino_subscriptions import Manager
    interactive = sys.stdin.isatty()
    if args.capture_scope and args.source:
        raise ToolError(_t('catch all 不能与 --source 同时使用。'))
    if not interactive and not args.yes:
        raise ToolError(_t('捕获需要确认。请在终端运行 domino catch；脚本明确指定 --yes；--batch 不代表同意。'))
    if args.source:
        paths = [Path(args.source).expanduser()]
        if owned_source(paths[0]):
            raise ToolError(_t('catch 不能捕获 Domino 或 robot-clash 自有配置。'))
    else:
        paths = capture_candidates(include_saved=True)
        if not paths:
            raise ToolError(_t('未发现兼容配置，请用 domino catch --source PATH 指定，或用 domino add 添加订阅。'))
        if args.capture_scope != 'all':
            if not interactive and len(paths) > 1:
                raise ToolError(_t('发现多个配置，请使用 --source 或 catch all 明确选择；--yes 不会自动选择来源。'))
            if interactive:
                capture_choices(paths)
                value = capture_input(_t('选择配置'), _t('编号 / all（回车取消）：'))
                if not value:
                    capture_cancelled()
                    return 0
                if value.lower() != 'all':
                    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= len(paths):
                        raise ToolError(_t('配置编号无效，未捕获。'))
                    paths = [paths[int(value) - 1]]
    installed = (Path.home() / '.local/share/domino/data/config.json').is_file()
    # Save selected sources before starting Domino with its current configuration.
    if installed:
        with output.human_output():
            output.human_header(_t('捕获配置到 Domino'), _t('{0} 个来源 · 重复项跳过', len(paths)))
            output.human_row(_t('运行影响'), _t('保存到配置库，保留当前配置和节点选择；完成后自动启动 Domino 并接通系统代理。终端代理策略保持不变。'), wrap=True)
            if any(source_name(path, {}).startswith('v2rayN') for path in paths if source_name(path, {})):
                output.human_row(_t('捕获范围'), _t('v2rayN 仅导入节点快照，不迁移其分流、DNS 或客户端设置。'), wrap=True)
        if not args.yes and capture_input(_t('确认捕获'), '[y/N] ').lower() not in ('y', 'yes'):
            capture_cancelled()
            return 0
    added = skipped = failed = 0
    for path in paths:
        prepared = copy.copy(args)
        prepared.source = str(path)
        try:
            if not installed:
                _install_capture(prepared)
                # Cancellation of bootstrap must stop the entire batch.
                if not (Path.home() / '.local/share/domino/data/config.json').is_file():
                    return 0
                installed = True
                added += 1
                continue
            source, raw, proxy = source_config(prepared)
            # Saved library entries use file defaults. A stopped source controller
            # must not prevent copying an otherwise complete saved configuration.
            with output.deployment_lock():
                item, changed = Manager(output).capture(source, raw, proxy, core=args.core, resource_dirs=args.resource_dir)
            added += int(changed)
            skipped += int(not changed)
            capture_status(_t('已捕获') if changed else _t('已跳过'), item['name'], '32' if changed else '2')
        except (DomainError, OSError, ValueError, TypeError) as error:
            failed += 1
            with redirect_stdout(sys.stderr):
                capture_status(_t('捕获失败'), path.name + _t('；请检查配置、依赖资源或内核校验。'), '31')
            if isinstance(error, TypeError):
                raise ToolError(_t('来源配置数据结构无效，未导入。')) from None
            if not installed or len(paths) == 1:
                raise
    if added + skipped:
        start_after_capture(args)
    with output.human_output():
        output.human_header(_t('捕获完成'), _t('新增/更新 {0} · 跳过 {1} · 失败 {2}', added, skipped, failed), '33' if failed else '32')
        output.human_row(_t('查看配置'), 'domino list')
        output.human_row(_t('切换配置'), _t('domino switch "配置名"'))
    return 1 if failed else 0


def _install_capture(args):
    import install_domino as output
    interactive = sys.stdin.isatty()
    if not interactive and not args.yes:
        raise ToolError(_t('捕获需要确认。请在终端运行 domino catch；脚本明确指定 --yes 才会导入，--batch 不代表同意。'))
    prepared = copy.copy(args)
    if args.source:
        path = Path(args.source).expanduser()
        if owned_source(path):
            raise ToolError(_t('catch 用于捕获外部配置，不能将 Domino 或 robot-clash 自有配置作为来源。'))
    else:
        candidates = capture_candidates()
        if not candidates:
            raise ToolError(_t('未发现可捕获的外部 Clash/Mihomo 配置。请用 domino catch --source PATH 指定兼容配置，或用 domino add 添加订阅；仅有本地代理端口无法独立复制。'))
        if len(candidates) > 1:
            if not interactive:
                raise ToolError(_t('发现多个外部配置，请使用 --source 明确选择；--yes 不会自动选择来源。'))
            capture_choices(candidates, allow_all=False)
            value = capture_input(_t('选择配置'), _t('配置编号（回车取消）：'))
            if not value:
                capture_cancelled()
                return 0
            if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= len(candidates):
                raise ToolError(_t('来源编号无效，未导入。'))
            path = candidates[int(value) - 1]
        else:
            path = candidates[0]
    prepared.source = str(path)
    try:
        source, raw, proxy = source_config(prepared)
        selections = live_selections(prepared, raw, source)
        sanitize_profile(raw, selections, args.proxy_port, args.api_port)
    except (TypeError, AttributeError):
        raise ToolError(_t('来源配置或控制接口数据结构无效，未导入；请检查 Clash/Mihomo 配置。')) from None
    # Capture once: the configuration approved here is the one packed after confirmation.
    prepared._captured_source = (source, raw, proxy, selections)
    from domino_sources import origin_info
    prepared._captured_origin = origin_info(raw, source)
    with output.human_output():
        output.human_header(_t('捕获本机代理配置'), _t('确认后安装或替换当前用户的 Domino 独立服务'))
        output.human_row(_t('来源文件'), (str(source).replace(str(Path.home()) + '/', '~/', 1), '2'), wrap=True)
        if source_name(source, {}) == 'v2rayN':
            output.human_row(_t('捕获范围'), source_identity(source)['check_note'], wrap=True)
        output.human_row(_t('目标电脑'), _t('本机 · 当前用户'))
        output.human_row(_t('节点选择'), _t('已读取 {0} 个手动选择', len(selections)) if selections else _t('使用配置默认节点（未读取到手动选择）'))
        output.human_row(_t('配置模式'), str(raw.get('mode', 'rule')))
        output.human_row(_t('监听端口'), _t('代理 {0} · 控制接口 {1}（仅本机）', args.proxy_port, args.api_port))
        output.human_row(_t('安装影响'), _t('安装独立内核和后台服务；已有 Domino 配置将被替换、服务将重启，并保留部署前备份。'), wrap=True)
        if (Path.home() / '.local/share/robot-clash').exists():
            output.human_row(_t('旧版迁移'), _t('检测到 robot-clash；现有安装流程会迁移旧版服务和文件。'), wrap=True)
        environment = (_t('不更新终端代理集成') if args.no_shell_env else
                       _t('更新命令 PATH 和终端代理集成；全新安装默认关闭，已有策略按安装器规则保留或迁移'))
        output.human_row(_t('环境影响'), environment, wrap=True)
        output.human_row(_t('来源客户端'), _t('保持运行，不修改其配置或节点选择；初始化后自动开启 Domino 并接通系统代理，不开启 TUN。'), wrap=True)
        output.human_row(_t('配置登记'), _t('保存独立导入源快照并设为 Domino 当前配置；已有在线订阅保留，不自动导入其他发现项。'), wrap=True)
    if not args.yes and capture_input(_t('确认导入'), '[y/N] ').lower() not in ['y', 'yes']:
        capture_cancelled()
        return 0
    prepared.command = 'init'
    initialize(prepared)
    if getattr(args,'verbose',False):
        with output.human_output():
            output.human_header(_t('初始化完成'), _t('独立代理已就绪'))
            output.human_row(_t('查看状态'), 'domino status')
    return 0


def initialize(args):
    if args.bundle and (args.source or args.subscription):
        raise ToolError(_t('--bundle 不能与 --source 或 --subscription 同时使用。'))
    if args.name and not args.subscription:
        raise ToolError(_t('--name 需与 --subscription 配合使用。'))
    if getattr(args, 'installing', False) and not (args.source or args.subscription or args.bundle):
        existing = next((Path.home() / name / 'data/config.json' for name in
                         ['.local/share/domino', '.local/share/robot-clash']
                         if (Path.home() / name / 'data/config.json').is_file()), None)
        if existing:
            current = load_yaml(existing)
            manifest_path = existing.parent.parent / 'manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            args.base_install = bool(manifest.get('awaiting_subscription') and not (current.get('proxies') or current.get('proxy-providers')))
            if 'proxy' not in args.port_overrides:
                args.proxy_port = port(current['mixed-port'])
            if 'api' not in args.port_overrides:
                args.api_port = port(current['external-controller'].rsplit(':',1)[1])
    if args.proxy_port == args.api_port:
        raise ToolError(_t('代理端口和控制端口不能相同。'))
    if args.subscription:
        import install_domino
        import domino_subscriptions
        subscriptions = domino_subscriptions.Manager(install_domino)
        subscriptions.url(args.subscription)
        if args.name:
            existing = next((v for v in subscriptions.registry['items'] if v.get('url') == args.subscription), None)
            if not existing or existing['name'] != args.name:
                subscriptions.available_name(args.name)
    arch = local_target()
    args.target_system = 'darwin' if sys.platform == 'darwin' else 'linux'
    with tempfile.TemporaryDirectory(prefix='domino-init-', dir=cache_dir()) as directory:
        work = Path(directory)
        if args.bundle:
            bundle = work / 'offline'
            bundle.mkdir(mode=0o700)
            unpack_bundle(Path(args.bundle).expanduser(), bundle)
            manifest_path = bundle / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['non_interactive'] = args.batch
            if args.no_shell_env:
                manifest['shell_env'] = False
            private_write(manifest_path, json.dumps(manifest))
            copy_cli(bundle)
        else:
            prepare(args, arch, work)
            bundle = work / 'bundle'
        manifest_path = bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['package_managed_cli'] = PACKAGE_MANAGED
        private_write(manifest_path, json.dumps(manifest))
        # Run the current trusted installer, not an installer script supplied by the archive.
        run([sys.executable, str(REMOTE_SCRIPT), 'install', str(bundle),*(['--verbose'] if getattr(args,'verbose',False) else [])], stage=_t('本机安装'))


def is_local_target(target):
    return target is None or target.lower().rstrip('.') in ['localhost', '127.0.0.1', '::1', '[::1]']


def is_target_address(value):
    if is_local_target(value) or '@' in value:
        return True
    try:
        ipaddress.ip_address(value[1:-1] if value.startswith('[') and value.endswith(']') else value)
        return True
    except ValueError:
        return False


def normalize_command(args):
    """Map public commands onto shared local/remote management operations."""
    if args.command == 'log':
        level = getattr(args, 'level', None)
        if level is not None:
            if args.set is not None and args.set != level:
                raise ToolError(_t('日志级别只能指定一次；使用 domino log debug 等命令。'))
            args.set = level
        args.command = 'log'
    elif args.command == 'select':
        name = getattr(args, 'name', None)
        if name is not None and args.node is not None:
            if args.group and args.target is None and is_target_address(name):
                args.target, args.name = name, None
            else:
                raise ToolError(_t('节点只能指定一次；用 domino [USER@IP] select "节点名"，或 --group 与 --node。'))
    elif args.command == 'test':
        if args.name == 'all':
            args.name = None
        if args.name is not None and (args.node is not None or args.group is not None or args.all or args.config is not None):
            raise ToolError(_t('测速对象只能指定一次；远端格式为 domino USER@IP test NAME。'))
    elif args.command == 'proxy':
        if args.proxy_action in ['on', 'off']:
            if args.set is not None and args.set != args.proxy_action:
                raise ToolError(_t('系统代理动作与 --set 不一致，请使用 domino proxy on 或 domino proxy off。'))
            args.set = args.proxy_action
    elif args.command == 'shell':
        args.set = args.shell_action if args.shell_action in ['on','off'] else None
    elif args.command == 'rules':
        if args.add_rule is not None or args.remove_rule is not None:
            return args
        if args.target in ['add', 'remove']:
            if args.rule is None or args.match or args.custom:
                raise ToolError(_t('用法：domino [USER@IP] rules ') + args.target + _t(' "完整规则"；查询请单独使用 --match 或 --custom。'))
            setattr(args, 'add_rule' if args.target == 'add' else 'remove_rule', args.rule)
            args.target = args.rule_target
        elif args.rule is not None or args.rule_target is not None:
            raise ToolError(_t('用法：domino [USER@IP] rules，或 domino [USER@IP] rules add/remove "完整规则"。'))
    elif args.command == 'configs' and getattr(args,'configs_action',None):
        if args.configs_action != 'list':
            action, name = args.configs_action, args.name
            new_name = args.new_name if action == 'rename' else None
            url = args.url if action in ['add', 'set-url'] else None
            for key in ['add', 'update', 'use', 'remove', 'rename', 'set_url', 'import_current', 'url']:
                setattr(args, key, None)
            args.new_name = new_name
            args.url = url
            args.update_all = action == 'update' and name == 'all'
            if not args.update_all:
                setattr(args, {'add':'add', 'switch':'use', 'update':'update', 'rename':'rename', 'remove':'remove', 'set-url':'set_url'}[action], name)
        args.configs_action = None
    return args


def management_options(args):
    normalize_command(args)
    options = []
    if args.command!='doctor' and getattr(args,'verbose',False):options+=['--verbose']
    if args.command == 'doctor':
        options += ['--url', args.url]
        if args.insecure: options += ['--insecure']
        if args.verbose: options += ['--verbose']
    if args.command=='scan':
        if args.source: options+=['--source',args.source]
    if args.command == 'configs':
        if args.batch and (args.add or args.set_url) and args.url is None:
            raise ToolError(_t('非交互模式添加订阅或修改地址时需要 --url。'))
        for key in ['add', 'update', 'use', 'remove', 'rename', 'set_url', 'import_current', 'url', 'new_name']:
            value = getattr(args, key)
            if value is not None:
                options += ['--' + key.replace('_', '-') + '=' + value]
        if args.update_all:
            options += ['--update-all']
        if getattr(args, 'refresh_usage', False):
            options += ['--refresh-usage']
    if args.command in ['status', 'nodes'] and args.json:
        options += ['--json']
    if args.command in ['nodes', 'select'] and args.group:
        options += ['--group=' + args.group]
    if args.command == 'select' and args.node is not None:
        options += ['--node=' + args.node]
    if args.command in ['mode', 'log', 'proxy', 'shell']:
        if args.set:
            options += ['--set', args.set]
    if args.command == 'proxy' and args.service:
        options += ['--service', args.service]
    if args.command == 'test':
        options += (['--config=' + args.config] if args.config is not None else
                    ['--node=' + args.node] if args.node is not None else
                    ['--group=' + args.group] if args.group is not None else
                    ['--name=' + args.name] if args.name is not None else ['--summary'])
        options += ['--url', args.url, '--timeout', str(args.timeout)]
    if args.command == 'connections':
        options += ['--close=' + args.close] if args.close else ['--all'] if args.all else []
    if args.command == 'env' and args.unset:
        options += ['--unset']
    if args.command == 'traffic':
        options += ['--interval', str(args.interval), '--count', str(args.count)]
        if args.watch:
            options += ['--watch']
    if args.command == 'rules':
        for key, flag in [('add_rule', '--add'), ('remove_rule', '--remove')]:
            value = getattr(args, key)
            if value is not None:
                options += [flag + '=' + value]
        if args.custom:
            options += ['--custom']
        options += ['--limit', str(args.limit)]
        if args.match:
            options += ['--match=' + args.match]
    if args.command == 'providers':
        options += ['--kind', args.kind]
        if args.update:
            options += ['--update=' + args.update]
    if args.command not in ['status', 'nodes'] and getattr(args, 'json', False):
        options += ['--json']
    if args.command == 'rollback' and args.backup:
        options += ['--backup', args.backup]
    if args.command == 'uninstall':
        options += [flag for flag, enabled in [('--yes', args.yes), ('--dry-run', args.dry_run)] if enabled]
    privileged = (args.command in ['start', 'stop', 'restart', 'logs', 'rollback', 'proxy', 'uninstall'] or
                  (args.command == 'configs' and (args.add or args.set_url) and args.url is None))
    if privileged and args.batch and args.command != 'configs':
        options += ['--non-interactive']
    if args.command == 'logs':
        if not 1 <= args.lines <= 10000:
            raise ToolError(_t('--lines 必须在 1–10000 之间。'))
        options += ['--lines', str(args.lines)]
        if args.follow:
            options += ['--follow']
    return options, privileged


def select_matches(query, names):
    names = list(dict.fromkeys(names))
    if query in names:
        return [query]
    needle = query.strip().casefold()
    return [name for name in names if needle and needle in name.casefold()]


def select_match(query, names, kind):
    matches = select_matches(query, names)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolError(_t('没有找到匹配的{0}；请运行 domino nodes 查看名称。', kind))
    import install_domino as output
    raise ToolError(_t('匹配到多个{0}，请使用完整名称（含方括号或空格时加引号）：', kind) +
                    '；'.join(shlex.quote(output.human_text(name)) for name in matches))


def select_menu(title, entries, *, group=None, nodes=False):
    import install_domino as output
    node_menu = nodes or group is not None
    while True:
        with output.human_output():
            output.human_header(title, (_t('策略组 ') + group['name']) if group else
                                _t('{0} 个候选节点', len(entries)) if nodes else _t('{0} 个手动策略组', len(entries)))
            if group:
                output.human_row(_t('当前选择'), group.get('current') or _t('未选择'), wrap=True)
                output.human_table([_t('编号'), _t('节点 / 策略'), _t('状态')], [
                    [str(i), entry['name'], (_t('● 当前'), '32') if entry['name'] == group.get('current') else '—']
                    for i, entry in enumerate(entries, 1)])
            elif nodes:
                output.human_table([_t('编号'), _t('节点 / 策略'), _t('可选策略组')], [
                    [str(i), entry['name'], entry['groups']] for i, entry in enumerate(entries, 1)])
            else:
                output.human_table([_t('编号'), _t('策略组'), _t('当前选择')], [
                    [str(i), entry['name'], entry.get('current') or _t('未选择')] for i, entry in enumerate(entries, 1)])
            if output.OUTPUT_VERBOSE:output.human_row(_t('选择方式'), _t('输入编号或名称；关键词可继续筛选；回车取消。'), wrap=True)
        label=_t('选择')
        prompt = '  ' + output.human_style(label, '2') + ' ' * max(2,output.HUMAN_LABEL_WIDTH-output.human_width(label)) + _t('编号 / 名称（回车取消）：')
        try:
            value = input(prompt).strip()
        except EOFError:
            value = ''
        if not value:
            with output.human_output():
                output.human_header(_t('节点选择已取消'), _t('未修改节点选择。'), '33')
            return None
        if value.isascii() and value.isdecimal() and 1 <= int(value) <= len(entries):
            return entries[int(value)-1]['name']
        matches = select_matches(value, [entry['name'] for entry in entries])
        if len(matches) > 1:
            entries = [entry for entry in entries if entry['name'] in matches]
            continue
        return select_match(value, [entry['name'] for entry in entries], _t('节点') if node_menu else _t('策略组'))


def resolve_selection(args, ssh=None, *, interactive=True):
    """Resolve a human selection read-only; the backend rechecks before writing."""
    query = getattr(args, 'name', None) or args.node
    interactive = interactive and sys.stdin.isatty()
    if query is None and not interactive:
        raise ToolError(_t('非交互选择需要节点名；使用 domino [USER@IP] select "节点名" --group "策略组名"。'))
    request = copy.copy(args)
    request.command, request.group, request.json = 'nodes', None, True
    response = manage(request, ssh, capture=True)
    try:
        inventory = json.loads(response.stdout)
        groups = [group for group in inventory['groups'] if group['selectable'] and group['choices']]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ToolError(_t('无法读取可选节点列表，请先运行 domino nodes 检查。')) from None
    if not groups:
        raise ToolError(_t('没有可手动选择的策略组；自动策略组不能直接切换节点。'))
    if args.group is not None:
        name = select_match(args.group, [group['name'] for group in groups], _t('手动策略组'))
        groups = [group for group in groups if group['name'] == name]
    elif inventory.get('mode') == 'global' and any(group['name'] == 'GLOBAL' for group in groups):
        groups = [group for group in groups if group['name'] == 'GLOBAL']
    if query is not None:
        names = [name for group in groups for name in group['choices']]
        matches = select_matches(query, names)
        if interactive and len(matches) > 1:
            entries = [{'name': name, 'groups': '；'.join(group['name'] for group in groups if name in group['choices'])}
                       for name in matches]
            node = select_menu(_t('选择匹配节点'), entries, nodes=True)
            if node is None:
                return None
        else:
            node = select_match(query, names, _t('节点或下层策略组'))
        groups = [group for group in groups if node in group['choices']]
    if len(groups) > 1:
        if not interactive:
            from install_domino import human_text
            raise ToolError(_t('该节点属于多个手动策略组，请用 --group 指定：') + '；'.join(human_text(group['name']) for group in groups))
        name = select_menu(_t('选择策略组'), groups)
        if name is None:
            return None
        groups = [group for group in groups if group['name'] == name]
    group = groups[0]
    if query is None:
        node = select_menu(_t('选择节点'), [{'name': name} for name in group['choices']], group=group)
        if node is None:
            return None
    selected = copy.copy(args)
    selected.group, selected.node, selected.name = group['name'], node, None
    return selected


def management_action(command):
    return {'test': 'delay', 'log': 'log-level'}.get(command, command)


@contextmanager
def traffic_terminal(full=False):
    """A subprocess interrupted by its caller may not get to restore the terminal."""
    import termios
    terminal = state = None
    try:
        terminal = sys.stdin.fileno()
        state = termios.tcgetattr(terminal)
    except (OSError, ValueError, termios.error):
        pass
    try:
        yield
    except BaseException:
        try:
            sys.stdout.write(('\033[?1049l' if full else '') + '\033[0m\033[?2004l\033[?25h\n')
            sys.stdout.flush()
        except OSError:
            pass
        raise
    finally:
        if state is not None:
            try: termios.tcsetattr(terminal, termios.TCSANOW, state)
            except (OSError, termios.error): pass


def manage(args, ssh=None, capture=False):
    normalize_command(args)
    if args.command == 'select' and (not args.group or not args.node):
        args = resolve_selection(args, ssh, interactive=not capture)
        if args is None:
            return None
    options, privileged = management_options(args)
    backend_command = management_action(args.command)
    dashboard = (args.command == 'traffic' and not args.json and not capture
                 and sys.stdout.isatty() and sys.stdin.isatty() and os.environ.get('TERM') != 'dumb')
    if args.command == 'traffic' and args.full and not dashboard:
        raise ToolError(_t('--full 需要交互终端，不能用于 JSON、重定向或捕获输出。'))
    if dashboard:
        options += ['--dashboard' if args.full else '--compact']
    elif not capture and not getattr(args,'json',False) and args.command not in ['env','logs'] and sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM')!='dumb':
        options += ['--color']
    if args.command == 'test' and not args.json and not capture and sys.stderr.isatty():
        # SSH uses no remote PTY; carry the caller's terminal preference explicitly.
        options += ['--progress']
    with traffic_terminal(args.full) if dashboard else nullcontext():
        if ssh is not None:
            kwargs = {'capture_output': True, 'text': True} if capture else {}
            if dashboard:
                return ssh.action(backend_command, *options, tty=True, **kwargs)
            if privileged:
                return ssh.action(backend_command, *options, tty=not args.batch, **kwargs)
            return ssh.action(backend_command, *options, **kwargs)
        result = run([sys.executable, str(REMOTE_SCRIPT), backend_command, *options], stage=_t('本机管理'),
                     **({'capture_output': True, 'text': True} if capture else {}))
        return result


def terminal_ui(args, ssh=None):
    if not sys.stdin.isatty():
        raise ToolError(_t('交互控制台需要终端，请在终端运行 domino ui；脚本请使用各子命令及 --json。'))
    import domino_tui
    async def execute(arguments, capture=False, timeout=75, on_progress=None):
        command = (argparse.Namespace(command=arguments[0], target=arguments[1]) if arguments[0] in ['overview','catch-options']
                   else normalize_command(build_parser().parse_args(arguments)))
        command.batch = args.batch or getattr(command,'batch',False)
        options, privileged = management_options(command)
        if capture and command.command=='test':
            options+=['--ui-result']
            if on_progress is not None:options+=['--progress']
        if command.command=='scan':
            options+=['--columns',str(max(20,shutil.get_terminal_size((100,24)).columns-4))]
        if capture and not getattr(command,'json',False) and command.command not in ['overview','catch-options','logs'] and 'NO_COLOR' not in os.environ:
            options+=['--color']
        backend_command = management_action(command.command)
        if command.command=='catch':
            if capture:raise ToolError(_t('捕获配置需要前台交互确认。'))
            tokens=command.remote_arguments
            if command.batch and '--batch' not in tokens:tokens=[*tokens,'--batch']
            argv=(ssh.action_argv('cli',*tokens,tty=not command.batch) if ssh else [sys.executable,str(Path(__file__)),*tokens])
            if not ssh and PACKAGE_MANAGED:
                argv=[sys.executable,str(Path(__file__).with_name('domino_install.py')),'--package-cli',*tokens]
        else:
            if command.command=='traffic' and command.full:
                if capture:raise ToolError(_t('--full 需要前台交互终端。'))
                options+=['--dashboard']
            tty=(privileged and not args.batch or command.command=='traffic' and command.full) and not capture
            argv = (ssh.action_argv(backend_command, *options, tty=tty)
                    if ssh else [sys.executable, str(REMOTE_SCRIPT), backend_command, *options])
        process = await asyncio.create_subprocess_exec(*argv,
                    stdout=asyncio.subprocess.PIPE if capture else None,
                    stderr=asyncio.subprocess.PIPE if capture else None,
                    start_new_session=capture and command.command=='test')
        try:
            if capture and on_progress is not None and command.command=='test':
                async def progress_stream():
                    import codecs
                    decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
                    chunks=[];pending=''
                    while True:
                        chunk=await process.stderr.read(4096)
                        if not chunk:break
                        chunks.append(chunk);chunks=chunks[-16:]
                        pending+=decoder.decode(chunk)
                        lines=re.split(r'[\r\n]',pending)
                        for line in lines:
                            clean=domino_tui.clean(line).strip()
                            if clean.startswith((_t('正在检测'),_t('加载配置'))):on_progress(clean)
                        pending=lines[-1][-1000:]
                    return b''.join(chunks)
                async def communicate_progress():
                    out,err,_=await asyncio.gather(process.stdout.read(),progress_stream(),process.wait())
                    return out,err
                stdout,stderr=await asyncio.wait_for(communicate_progress(),timeout=timeout)
            else:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except BaseException:
            if process.returncode is None:
                grouped=capture and command.command=='test'
                if grouped:
                    import signal
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                else:process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 12 if grouped else 2)
                except asyncio.TimeoutError:
                    if grouped:
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    else:process.kill()
                    await process.wait()
            raise
        if capture and command.command in ['status','scan'] and process.returncode == 3 and stdout:
            return (stdout or b'').decode(errors='replace')
        if process.returncode:
            detail = (stderr or b'').decode(errors='replace').strip()
            # Only the managed installer's deliberately sanitized error line is shown.
            message = next((line for line in detail.splitlines() if line.startswith(('失败：', 'Error:'))), None)
            raise ToolError(message or _t('{0} 操作失败（退出码 {1}）。', command.command, process.returncode))
        return (stdout or b'').decode(errors='replace') if capture else ''
    try:
        domino_tui.run(args.target or 'localhost', execute, version=VERSION)
    except RuntimeError as error:
        raise ToolError(str(error)) from None


def main(argv=None, *, installing=False):
    arguments = list(sys.argv[1:] if argv is None else argv)
    from domino_i18n import configure, get_language, set_language
    try:
        arguments = configure(arguments)
        if not installing and arguments[:1] in (['language'], ['lang']) and '--help' not in arguments and '-h' not in arguments:
            if len(arguments) > 2:
                raise ValueError('Usage: domino language [zh|en] / 用法：domino language [zh|en]')
            selected = set_language(arguments[1]) if len(arguments) == 2 else get_language()
            from install_domino import human_output
            with human_output():
                print(_t('界面语言：{0}', 'English (en)' if selected == 'en' else '简体中文 (zh)'))
            return 0
    except (OSError, ValueError) as error:
        from install_domino import human_output
        with redirect_stdout(sys.stderr),human_output():
            print(str(error))
        return 2
    if not installing and arguments[:1] == ['completion']:
        from domino_completion import main as complete
        return complete(arguments[1:])
    machine_flags = ['--protocol-version','--non-interactive','--input','--if-revision','--request-id','--dry-run']
    if arguments[:1] == ['uninstall'] or len(arguments) > 1 and arguments[1] == 'uninstall':
        machine_flags.remove('--dry-run')
    json_mode = '--output=json' in arguments or any(arguments[i:i+2] == ['--output','json'] for i in range(len(arguments)-1))
    if not installing and arguments and (arguments[0].split('=',1)[0] == '--output' or
            any(value.split('=',1)[0] in machine_flags for value in arguments) or (json_mode and 'export' not in arguments[:2])):
        import domino_agent
        module=sys.modules.get(__name__)
        if getattr(module,'build_parser',None) is not build_parser:
            import domino_cli
            module=domino_cli
        return domino_agent.main(arguments,module)
    if not installing and not arguments:
        common_operations()
        return 0
    parser = build_parser(installing=installing)
    if installing:
        installer = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction)).choices['init']
        args = installer.parse_args(arguments)
        args.command = 'init'
    else:
        if '-h' in arguments or '--help' in arguments:
            from install_domino import human_output
            with human_output():
                args = parser.parse_args(arguments)
        else:
            args = parser.parse_args(arguments)
    if installing:
        args.installing = True
        args.port_overrides = {kind for kind, flag in [('proxy','--proxy-port'),('api','--api-port')]
                               if any(value == flag or value.startswith(flag+'=') for value in arguments)}
        args.base_install = not (args.source or args.subscription or args.bundle) and not any(
            (Path.home() / name / 'data/config.json').is_file()
            for name in ['.local/share/domino', '.local/share/robot-clash'])
    from install_domino import human_output,output_details
    live=(args.command=='ui' or args.command=='logs' and getattr(args,'follow',False) or
          args.command=='traffic' and sys.stdout.isatty() and sys.stdin.isatty() and os.environ.get('TERM')!='dumb')
    formatted=not (getattr(args,'json',False) or args.command in ['env','plan','overview','catch-options'] or live)
    with output_details(getattr(args,'verbose',False)),human_output(formatted):
        return _dispatch(args,installing=installing)


def _dispatch(args, *, installing=False):
    try:
        normalize_command(args)
        if args.command in ('language', 'lang'):
            raise ToolError(_t('语言偏好保存在本机；请使用 domino language zh 或 domino language en。'), exit_code=2)
        if args.command == 'scan' and is_local_target(args.target):
            return inspect_source(args) if args.source else list_sources(args)
        if args.command in ['deploy', 'plan', 'export', 'init', 'catch']:
            if args.mihomo_version != 'latest' and not re.fullmatch(r'v\d+\.\d+\.\d+', args.mihomo_version):
                raise ToolError(_t('内核版本必须是 latest 或 vX.Y.Z。'))
            if args.proxy_port == args.api_port and not installing:
                raise ToolError(_t('代理端口和控制端口不能相同。'))
            url = urlsplit(args.test_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ToolError(_t('出网检查地址必须是无嵌入凭据的 HTTPS URL。'))
        if args.command == 'logs' and not 1 <= args.lines <= 10000:
            raise ToolError(_t('--lines 必须在 1–10000 之间。'))
        if args.command == 'deploy' and args.restart_vscode and (not args.vscode or args.no_shell_env):
            raise ToolError(_t('--restart-vscode 需要 --vscode，且不能使用 --no-shell-env。'))
        if args.command in ['deploy', 'rollback', 'init'] and not args.batch and not sys.stdin.isatty() and not (sys.platform == 'darwin' and args.command in ['init', 'rollback']):
            raise ToolError(_t('部署、安装或回滚需要在终端运行，以便安全输入认证密码。'))
        if args.command in ['catch', 'export', 'init'] and not is_local_target(getattr(args, 'target', None)):
            with SSH(args) as ssh:
                options = []
                tokens = iter(args.remote_arguments)
                for value in tokens:
                    if value in ['--user','--ssh-port','--identity']:
                        next(tokens, None)
                    elif not any(value.startswith(flag+'=') for flag in ['--user','--ssh-port','--identity']):
                        options.append(value)
                ssh.action('cli', *options, tty=not args.batch)
            return 0
        if args.command == 'catch':
            if sys.platform != 'darwin' and not sys.stdin.isatty() and not args.batch:
                raise ToolError(_t('非交互捕获请同时使用 --yes --batch；--batch 仅禁止密码询问。'))
            return catch(args)
        if args.command == 'init':
            initialize(args)
            return 0
        if args.command == 'export':
            with tempfile.TemporaryDirectory(prefix='domino-', dir=cache_dir()) as temp:
                package, _ = prepare(args, args.arch, Path(temp))
                output = Path(args.output).expanduser().resolve()
                private_write(output, package.read_bytes())
                print(_t('离线安装包已导出：') + str(output))
            return 0
        management = ['status', 'nodes', 'select', 'start', 'stop', 'restart', 'logs', 'rollback', 'uninstall', 'doctor',
                      'mode', 'log', 'test', 'connections', 'traffic', 'rules', 'providers', 'configs', 'proxy', 'shell', 'ui', 'env', 'scan']
        if args.command in management and is_local_target(args.target):
            if args.user or args.ssh_port or args.identity:
                raise ToolError(_t('localhost 直接管理当前用户的本机，不能附加 SSH 参数；需切换用户时请使用 USER@localhost 通过 SSH 管理。'))
            if args.command == 'ui':
                terminal_ui(args)
            else:
                manage(args)
            return 0
        if args.command == 'deploy':
            destination(args.target, args.user)
            args = select_deployment_source(args)
            if args is None:
                return 0
        with SSH(args) as ssh:
            if args.command in management:
                if args.command == 'ui':
                    terminal_ui(args, ssh)
                else:
                    manage(args, ssh)
            else:
                info = ssh.info()
                if args.command == 'plan':
                    with source_input(args) as prepared:
                        _, raw, _ = source_config(prepared)
                        sanitize_profile(raw, {}, args.proxy_port, args.api_port)
                    print(json.dumps({'target': ssh.target, 'arch': normalize_arch(info['arch']),
                                      'system': info['system'], 'proxy_port': args.proxy_port,
                                      'mode': raw.get('mode', 'rule'),
                                      'nodes': len(raw.get('proxies', [])),
                                      'providers': len(raw.get('proxy-providers', {})),
                                      'deployment_method': 'independent',
                                      'requires_source_online': False,
                                      'changes': [_t('独立 systemd 代理服务'), _t('当前节点和规则配置')] +
                                                 ([] if args.no_shell_env else [_t('当前用户代理环境')]),
                                      'target_modified': False}, ensure_ascii=False, indent=2))
                else:
                    with tempfile.TemporaryDirectory(prefix='domino-', dir=cache_dir()) as temp:
                        deploy(args, ssh, info, Path(temp))
        return 0
    except ReportedCommandError as exc:
        return exc.returncode
    except (DomainError, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        message = str(exc) if isinstance(exc, DomainError) else type(exc).__name__
        from install_domino import human_error
        human_error(_t('失败：') + message)
        return 1
    except KeyboardInterrupt as error:
        if getattr(error, 'domino_capture_prompt', False):
            with redirect_stdout(sys.stderr):
                capture_cancelled()
        else:
            from install_domino import human_error
            human_error(_t('已取消。'))
        return 130


if __name__ == '__main__':
    sys.exit(main())
