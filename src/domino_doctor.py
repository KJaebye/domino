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


def connection_summary(native, proxied, *, installed, insecure=False, private_target=False):
    native_connected, proxy_connected = bool(native['reachable']), bool(proxied['reachable'])
    status = proxied.get('http_status')
    if not installed:
        state, tone = 'not_checked', '33'
        summary = _t('代理路径未检测：尚未安装本机运行环境')
        next_step = _t('请先运行 domino-install，再检查代理路径。')
    elif proxy_connected:
        state, tone = ('connected', '32') if status < 400 else ('http_error', '33')
        if status in (401, 403):
            summary = _t('已连通，但网站要求登录或授权')
            next_step = _t('请在浏览器登录，或确认账号有访问权限。')
        elif status >= 400:
            summary = _t('已连通，但网站返回错误')
            next_step = _t('请确认网址路径是否正确。') if status == 404 else _t('网络已连通，请检查网站服务状态。')
        else:
            summary = _t('已连通：通过 Domino 可以访问该地址')
            next_step = _t('请在浏览器打开该地址，继续跳转或登录。') if status >= 300 else _t('可在浏览器打开该地址，确认页面和登录功能。')
        if insecure:
            tone = '33'
            summary = _t('已收到网站响应，但跳过了证书校验')
            next_step = _t('请去掉 --insecure 重新检测，以确认网站证书有效。')
    elif native_connected:
        state, tone = 'proxy_failed', '31'
        summary = _t('Domino 未连通；系统直连可以到达网站')
        next_step = _t('请先执行 domino status，再用 --verbose 查看 DNS 和路由详情。')
    else:
        state, tone = 'both_failed', '31'
        summary = _t('未连通：系统直连和 Domino 都未收到网站响应')
        next_step = _t('请先连接公司网络或 VPN，再重新检测。') if private_target else _t('请先确认当前网络和目标网址可用，再重新检测。')
    return {'state': state, 'summary': summary, 'tone': tone,
            'native_connected': native_connected, 'domino_connected': proxy_connected, 'next_step': next_step}


def connection_message(value):
    status = value.get('http_status')
    if value['reachable']:
        if status >= 500:
            return _t('已连通，但网站服务异常（HTTP {0}）', status)
        if status in (401, 403):
            return _t('已连通，网站要求登录或授权（HTTP {0}）', status)
        if status == 404:
            return _t('已连通，但页面不存在（HTTP 404）')
        if status >= 400:
            return _t('已连通，但网站返回错误（HTTP {0}）', status)
        if status >= 300:
            return _t('已连通，网站要求跳转（HTTP {0}）', status)
        return _t('已连通，网站正常响应（HTTP {0}）', status)
    stages = {'proxy_dns': _t('代理地址无法解析'), 'dns': _t('域名无法解析'),
              'connection': _t('无法建立连接'), 'timeout': _t('连接或响应超时'),
              'tls': _t('安全连接握手失败'), 'certificate': _t('网站证书校验未通过'),
              'tunnel': _t('代理隧道建立失败'), 'request': _t('未收到网站响应')}
    if value.get('failure_stage') == 'not_installed':
        return _t('未检测（尚未安装本机服务）')
    return _t('未连通：{0}', stages.get(value.get('failure_stage'), _t('未收到网站响应')))


def doctor(ctx, url=None, *, insecure=False, as_json=False, verbose=False):
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
    conclusion = connection_summary(native, proxied, installed=bool(config), insecure=insecure,
        private_target=any(ipaddress.ip_address(v).is_private for v in addresses + hosts))
    result['conclusion'] = {k: v for k, v in conclusion.items() if k != 'tone'}
    if as_json:
        ctx.show(result, True)
    else:
        ctx.human_header(_t('连接诊断'), conclusion['summary'], tone=conclusion['tone'])
        ctx.human_row(_t('目标地址'), url, wrap=True)
        for label, value in ((_t('系统直连'), native), (_t('经过 Domino'), proxied)):
            tone = '32' if value['ok'] and not insecure else '33' if value['reachable'] or value.get('failure_stage') == 'not_installed' else '31'
            ctx.human_row(label, (connection_message(value), tone))
        if verbose:ctx.human_row(_t('检查时间'), ctx.human_time(result['checked_at']))
        if verbose or insecure or conclusion['state']!='connected' or any(300 <= (v.get('http_status') or 0) < 500 for v in (native,proxied)):
            print()
            ctx.human_row(_t('下一步'), conclusion['next_step'], wrap=True)
        if verbose:
            print()
            ctx.human_row(_t('详细信息'), _t('仅检查，不修改网络设置'))
            ctx.human_row(_t('系统解析'), ', '.join(addresses) or _t('未返回地址'))
            ctx.human_row(_t('内部 DNS 查询'), ', '.join(core_addresses) if core_addresses else
                          _t('无 DNS 记录；系统 hosts 提供映射') if core_addresses == [] and hosts and dns.get('enable') and dns.get('use-system-hosts', True) else
                          _t('未返回地址') if core_addresses == [] else _t('未能检查'))
            ctx.human_row(_t('路由接口'), ', '.join(v['interface'] or '?' for v in routes) or _t('未能检查'))
            ctx.human_row(_t('路由说明'), result['routing_note'], wrap=True)
            for hint in hints:
                ctx.human_row(_t('排查建议'), hint, wrap=True)

    return result
