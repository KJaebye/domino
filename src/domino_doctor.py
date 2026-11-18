# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Read-only macOS connectivity and core identity diagnostics."""
from domino_i18n import tr as _t
import json
import re
import socket
import subprocess
from domino_macos import launch, domain, LABEL, system_proxy_overview

def doctor(ctx, url, *, insecure=False, as_json=False):
    """Compare native and configured proxy HTTPS paths without changing routing."""
    import hashlib
    import urllib.parse
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ctx.InstallError(_t('诊断地址必须是无凭据、查询参数和 fragment 的 HTTPS URL。'))
    app, _ = ctx.current_installation()
    config = json.loads((app / 'data/config.json').read_text())
    number = config['mixed-port']
    if type(number) is not int or not 1 <= number <= 65535:
        raise ctx.InstallError(_t('代理端口无效。'))

    def command(arguments):
        try:
            return subprocess.run(arguments, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None

    binary = app / 'mihomo'
    load = command(['otool', '-l', str(binary)])
    uuids = re.findall(r'\buuid ([0-9A-Fa-f-]{36})', load.stdout) if load and load.returncode == 0 else None
    version = command([str(binary), '-v'])
    agent = launch('print', domain() + '/' + LABEL, check=False)
    import domino_macos_app as native_app
    responsible = None
    launcher = native_app.app_path(app) / native_app.EXECUTABLE
    if launcher.is_file():
        native_load = command(['otool', '-l', str(launcher)])
        program = re.search(r'^\s*program = (.+)$', agent.stdout, re.M)
        responsible = {'path': str(native_app.app_path(app)), 'bundle_id': native_app.BUNDLE_ID,
                       'agent_uses_launcher': bool(program and program[1].strip() == str(launcher)),
                       'mach_o_uuids': re.findall(r'\buuid ([0-9A-Fa-f-]{36})', native_load.stdout)
                           if native_load and native_load.returncode == 0 else None}
    pid = re.search(r'^\s*pid = (\d+)', agent.stdout, re.M)
    process = command(['ps', '-p', pid[1], '-o', 'pid=,ppid=']) if pid else None
    addresses = []
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)})
    except OSError:
        pass
    routes = []
    for address in addresses[:4]:
        route = command(['route', '-n', 'get', address])
        interface = re.search(r'interface:\s*(\S+)', route.stdout) if route else None
        routes.append({'address': address, 'interface': interface[1] if interface else None})
    with socket.socket() as listener:
        listener.settimeout(1)
        listening = listener.connect_ex(('127.0.0.1', number)) == 0

    def probe(proxy):
        arguments = ['curl', '--silent', '--show-error', '--output', '/dev/null',
                     '--write-out', '%{http_code}', '--connect-timeout', '4', '--max-time', '8',
                     '--noproxy', '' if proxy else '*', '--proxy', proxy or '']
        if insecure:
            arguments.append('--insecure')
        result = command(arguments + ['--url', url])
        # Never echo curl stderr, headers, response bodies or configuration secrets.
        code = result.stdout.strip() if result else ''
        return {'ok': bool(result and result.returncode == 0 and re.fullmatch(r'[1-5]\d\d', code)),
                'curl_exit': result.returncode if result else None,
                'http_status': int(code) if re.fullmatch(r'[1-5]\d\d', code) else None}

    native = probe(None)
    proxied = probe(f'http://127.0.0.1:{number}')
    hints = []
    if uuids == [] and not (responsible and responsible['agent_uses_launcher'] and responsible['mach_o_uuids']):
        hints.append(_t('核心缺少 LC_UUID，且未确认使用具有 UUID 的原生应用启动器；请检查负责程序的身份和本地网络授权。仅补核心 UUID 不足以保证修复。'))
    if native['ok'] and not proxied['ok']:
        hints.append(_t('系统直连成功、代理请求失败；请结合 domino logs 确认是否命中 DIRECT，再比较 Terminal 与 LaunchAgent。'))
    result = {'binary': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'version': version.stdout.splitlines()[0] if version and version.returncode == 0 and version.stdout else None,
              'mach_o_uuids': uuids, 'agent_pid': int(pid[1]) if pid else None,
              'responsible_app': responsible,
              'pid_ppid': process.stdout.strip() if process and process.returncode == 0 else None,
              'system_proxy': system_proxy_overview(number), 'proxy_listening': listening,
              'dns_routes': routes, 'certificate_verified': not insecure,
              'native': native, 'configured_proxy': proxied,
              'routing_note': _t('代理探测沿用当前分流规则；成功不代表命中 DIRECT，CONNECT 200 不计为 HTTPS 成功。'),
              'hints': hints}
    ctx.show(result, as_json)
    return result
