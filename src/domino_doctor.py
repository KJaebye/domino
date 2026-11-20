# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Bounded, read-only connectivity diagnostics on macOS and Linux."""
from domino_i18n import tr as _t
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import urllib.parse
from domino_macos import launch, domain, LABEL, system_proxy_overview


def validate_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ValueError()
        parsed.port
        return parsed
    except (ValueError, TypeError):
        raise ValueError(_t('诊断地址必须是无凭据、查询参数和 fragment 的 HTTPS URL。')) from None


def system_hosts(host):
    """Return only the requested host's addresses; never dump other hosts entries."""
    try:
        path = Path('/etc/hosts')
        if path.stat().st_size > 1024 * 1024:
            return []
        addresses = []
        for line in path.read_text().splitlines():
            fields = line.partition('#')[0].split()
            if len(fields) > 1 and host.lower().rstrip('.') in [v.lower().rstrip('.') for v in fields[1:]]:
                try:
                    addresses.append(str(ipaddress.ip_address(fields[0])))
                except ValueError:
                    pass
        return sorted(set(addresses))
    except (OSError, UnicodeError):
        return []


def resolve_system(host, port):
    # An OS DNS lookup can block beyond a network change. Isolate it so timeout
    # actually terminates the lookup rather than leaving a background thread.
    code = 'import socket,json,sys; print(json.dumps(sorted({v[4][0] for v in socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)})))'
    try:
        result = subprocess.run([sys.executable, '-I', '-c', code, host, str(port)],
                                capture_output=True, text=True, timeout=4)
        return sorted({str(ipaddress.ip_address(v)) for v in json.loads(result.stdout)}) if not result.returncode else []
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return []


def probe_result(result):
    code = result.stdout.strip() if result else ''
    status = int(code) if re.fullmatch(r'[1-5]\d\d', code) else None
    exit_code = result.returncode if result else None
    reachable = exit_code == 0 and status is not None
    stage = (None if reachable and status < 400 else 'http' if reachable else
             {5: 'proxy_dns', 6: 'dns', 7: 'connection', 28: 'timeout',
              35: 'tls', 60: 'certificate', 97: 'tunnel'}.get(exit_code, 'request'))
    return {'ok': bool(reachable and status < 400), 'reachable': reachable,
            'curl_exit': exit_code, 'http_status': status, 'failure_stage': stage}


def doctor(ctx, url=None, *, insecure=False, as_json=False):
    url = url or getattr(ctx, 'DEFAULT_TEST', 'https://www.cloudflare.com/cdn-cgi/trace')
    try:
        parsed = validate_url(url)
    except ValueError as error:
        raise ctx.InstallError(str(error)) from None
    app, service = ctx.current_installation()
    path = app / 'data/config.json'
    config = json.loads(path.read_text()) if path.is_file() else {}
    number = config.get('mixed-port')
    if config and (type(number) is not int or not 1 <= number <= 65535):
        raise ctx.InstallError(_t('代理端口无效。'))

    def command(arguments):
        try:
            return subprocess.run(arguments, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None

    binary = app / 'mihomo'
    uuids = responsible = agent_pid = process_info = None
    version = command([str(binary), '-v']) if binary.is_file() else None
    if sys.platform == 'darwin':
        load = command(['otool', '-l', str(binary)]) if binary.is_file() else None
        uuids = re.findall(r'\buuid ([0-9A-Fa-f-]{36})', load.stdout) if load and load.returncode == 0 else None
        agent = launch('print', domain() + '/' + LABEL, check=False)
        import domino_macos_app as native_app
        launcher = native_app.app_path(app) / native_app.EXECUTABLE
        if launcher.is_file():
            native_load = command(['otool', '-l', str(launcher)])
            program = re.search(r'^\s*program = (.+)$', agent.stdout, re.M)
            responsible = {'path': str(native_app.app_path(app)), 'bundle_id': native_app.BUNDLE_ID,
                           'agent_uses_launcher': bool(program and program[1].strip() == str(launcher)),
                           'mach_o_uuids': re.findall(r'\buuid ([0-9A-Fa-f-]{36})', native_load.stdout)
                               if native_load and native_load.returncode == 0 else None}
        pid = re.search(r'^\s*pid = (\d+)', agent.stdout, re.M)
        agent_pid = int(pid[1]) if pid else None
        process = command(['ps', '-p', pid[1], '-o', 'pid=,ppid=']) if pid else None
        process_info = process.stdout.strip() if process and process.returncode == 0 else None
        routing = system_proxy_overview(number) if number else {'routing': 'unknown', 'ports': []}
    else:
        import domino_linux
        routing = domino_linux.system_proxy_overview(number) if number else {'routing': 'unknown', 'ports': []}

    addresses = resolve_system(parsed.hostname, parsed.port or 443)
    hosts = system_hosts(parsed.hostname)
    routes = []
    for address in addresses[:4]:
        interface = None
        if sys.platform == 'darwin':
            route = command(['route', '-n', 'get', address])
            match = re.search(r'interface:\s*(\S+)', route.stdout) if route else None
            interface = match[1] if match else None
        else:
            route = command(['ip', '-j', 'route', 'get', address])
            try:
                values = json.loads(route.stdout) if route and route.returncode == 0 else []
                interface = values[0].get('dev') if values else None
            except (ValueError, TypeError, KeyError, IndexError):
                pass
        routes.append({'address': address, 'interface': interface})
    listening = False
    if number:
        with socket.socket() as listener:
            listener.settimeout(1)
            listening = listener.connect_ex(('127.0.0.1', number)) == 0
    def probe(proxy):
        arguments = ['curl', '--silent', '--show-error', '--output', '/dev/null',
                     '--write-out', '%{http_code}', '--connect-timeout', '4', '--max-time', '8',
                     '--noproxy', '' if proxy else '*', '--proxy', proxy or '']
        if insecure:
            arguments.append('--insecure')
        return probe_result(command(arguments + ['--url', url]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        native_task = pool.submit(probe, None)
        proxied = probe(f'http://127.0.0.1:{number}') if number else {
            'ok': False, 'reachable': False, 'curl_exit': None, 'http_status': None, 'failure_stage': 'not_installed'}
        native = native_task.result()
    core_addresses = None
    if number and callable(getattr(ctx, 'api_json', None)):
        try:
            reply = ctx.api_json('/dns/query?' + urllib.parse.urlencode({'name': parsed.hostname, 'type': 'A'}), timeout=2)
            core_addresses = sorted({str(ipaddress.ip_address(v['data'])) for v in reply.get('Answer', []) if v.get('type') == 1})
        except (OSError, ValueError, TypeError, KeyError, ctx.InstallError):
            pass
    hints = []
    if uuids == [] and not (responsible and responsible['agent_uses_launcher'] and responsible['mach_o_uuids']):
        hints.append(_t('核心缺少 LC_UUID，且未确认使用具有 UUID 的原生应用启动器；请检查负责程序的身份和本地网络授权。仅补核心 UUID 不足以保证修复。'))
    dns = config.get('dns') or {}
    if native['ok'] and not proxied['reachable']:
        if hosts and (not dns.get('enable') or not dns.get('use-system-hosts', True)):
            hints.append(_t('系统 hosts 包含目标，但内核未启用系统 hosts；请更新运行配置后重试。'))
        elif core_addresses == [] and addresses and not (hosts and dns.get('enable') and dns.get('use-system-hosts', True)):
            hints.append(_t('系统能解析目标，内核没有返回地址；请检查内核 DNS 与 VPN 的分流 DNS。'))
        hints.append(_t('系统直连成功、代理请求失败；请结合 domino logs 确认是否命中 DIRECT，再检查 DNS、VPN 路由和程序权限。'))
    if not number:
        hints.append(_t('尚未安装本机运行环境；系统直连已单独检查，代理路径未检测。'))
    if (native['reachable'] and native['failure_stage'] == 'http') or (proxied['reachable'] and proxied['failure_stage'] == 'http'):
        hints.append(_t('已收到 HTTPS 响应；HTTP 错误应检查目标服务或访问权限，不应直接判断为 DNS 或代理断网。'))
    result = {'platform': sys.platform, 'url': url, 'checked_at': datetime.now().astimezone().isoformat(timespec='seconds'),
              'installed': bool(config), 'binary': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None,
              'version': version.stdout.splitlines()[0] if version and version.returncode == 0 and version.stdout else None,
              'mach_o_uuids': uuids, 'agent_pid': agent_pid, 'responsible_app': responsible, 'pid_ppid': process_info,
              'system_proxy': routing, 'proxy_listening': listening, 'dns_routes': routes,
              'resolution': {'system_addresses': addresses, 'hosts_addresses': hosts, 'core_addresses': core_addresses,
                             'internal_dns_enabled': bool(dns.get('enable')), 'system_hosts_enabled': bool(dns.get('enable') and dns.get('use-system-hosts', True))},
              'certificate_verified': not insecure, 'native': native, 'configured_proxy': proxied,
              'routing_note': _t('代理探测沿用当前分流规则；成功不代表命中 DIRECT，CONNECT 200 不计为 HTTPS 成功。'), 'hints': hints}
    if as_json:
        ctx.show(result, True)
    else:
        ctx.human_header(_t('连接诊断'), _t('仅检查，不修改网络设置'))
        ctx.human_row(_t('目标地址'), url, wrap=True)
        for label, value in ((_t('系统直连'), native), (_t('Domino 请求'), proxied)):
            text = 'HTTP ' + str(value['http_status']) if value['reachable'] else _t('失败阶段：{0}', value['failure_stage'])
            ctx.human_row(label, text)
        ctx.human_row(_t('系统解析'), ', '.join(addresses) or _t('未返回地址'))
        ctx.human_row(_t('内部 DNS 查询'), ', '.join(core_addresses) if core_addresses else
                      _t('无 DNS 记录；系统 hosts 提供映射') if core_addresses == [] and hosts and dns.get('enable') and dns.get('use-system-hosts', True) else
                      _t('未返回地址') if core_addresses == [] else _t('未能检查'))
        ctx.human_row(_t('检查时间'), result['checked_at'])
        ctx.human_row(_t('路由说明'), result['routing_note'], wrap=True)
        for hint in hints:
            ctx.human_row(_t('排查建议'), hint, wrap=True)
    return result
