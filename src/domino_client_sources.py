# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Read-only configuration sources for ClashX and v2rayN imports."""
from domino_i18n import tr as _t
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from domino_model import DomainError


def _error(message=None):
    message = message or _t('v2rayN 配置无法读取或格式不受支持；未输出配置内容。')
    raise DomainError(message, code='UNSUPPORTED_CLIENT_CONFIG', exit_code=2) from None


def _xdg(key, default):
    value = Path(os.environ.get(key) or default)
    return value if value.is_absolute() else Path.home() / default


def clash_directories():
    return list(dict.fromkeys([Path.home() / '.config/clash',
                               _xdg('XDG_CONFIG_HOME', '.config') / 'clash']))


def v2ray_directories():
    home = Path.home()
    roots = [home / 'Library/Application Support/v2rayN',
             _xdg('XDG_DATA_HOME', '.local/share') / 'v2rayN',
             _xdg('XDG_CONFIG_HOME', '.config') / 'v2rayN', home / 'v2rayN',
             home / 'Applications/v2rayN.app/Contents/MacOS',
             Path('/Applications/v2rayN.app/Contents/MacOS'), Path('/opt/v2rayN')]
    return list(dict.fromkeys(root / 'guiConfigs' for root in roots))


def discover():
    paths = []
    for directory in clash_directories():
        try:
            if directory.is_dir() and not directory.is_symlink():
                paths.extend(sorted(p for p in directory.iterdir()
                                    if p.suffix.lower() in ('.yaml', '.yml') and p.is_file() and not p.is_symlink()))
        except OSError:
            continue
    for root in v2ray_directories():
        for filename in ('guiNDB.db', 'guiNConfig.json'):
            path = root / filename
            try:
                if path.is_file() and not path.is_symlink():
                    paths.append(path)
                    break
            except OSError:
                continue
    return paths


def client_name(path):
    path = Path(path)
    if path.name in ('guiNDB.db', 'guiNConfig.json'):
        return 'v2rayN'
    if any(path.parent.resolve() == root.resolve() for root in clash_directories()):
        return 'ClashX / Clash'
    return None


def identity(path):
    path = Path(path)
    client = client_name(path)
    if client == 'v2rayN':
        name, note = _t('节点快照'), _t('转换全部支持的节点为 Mihomo 快照；不迁移 v2rayN 分流、DNS、链式代理或客户端设置，不检查保存端口。')
    elif client and path.name not in ('config.yaml', 'config.yml'):
        name, note = path.stem, _t('ClashX 保存配置；未核验客户端当前加载项，不检查保存端口。')
    else:
        return {}
    return {'source_kind': 'profile', 'profile_id': path.name, 'profile_name': name,
            'client_current': None, 'check_note': note}


def _read(path, limit):
    if path.is_symlink() or path.stat().st_size > limit:
        _error()
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        _error()
    return data


def _json(path):
    data = json.loads(_read(path, 16 * 1024 * 1024).decode('utf-8-sig'))
    if not isinstance(data, dict):
        _error()
    return {key.lower(): value for key, value in data.items()}


def _rows(path):
    # Read copies so SQLite cannot create or alter the client's WAL/SHM files.
    files = [path, path.with_name(path.name + '-wal')]
    def signature():
        return [(p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns)
                if p.exists() or p.is_symlink() else None for p in files]
    before = signature()
    with tempfile.TemporaryDirectory(prefix='domino-client-') as directory:
        target = Path(directory) / path.name
        for source in files:
            if not source.exists() and not source.is_symlink():
                continue
            destination = Path(directory) / source.name
            destination.write_bytes(_read(source, 64 * 1024 * 1024))
            destination.chmod(0o600)
        if before != signature():
            _error(_t('v2rayN 数据库正在变化，请稍后重试。'))
        with closing(sqlite3.connect(str(target), timeout=1)) as database:
            database.execute('PRAGMA query_only=ON')
            database.row_factory = sqlite3.Row
            return [dict(row) for row in database.execute('SELECT * FROM ProfileItem ORDER BY IndexId LIMIT 5001')]


def _extra(value):
    if not value:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        _error()
    return {key.lower(): item for key, item in value.items()}


def _truth(value):
    return str(value).lower() in ('true', '1')


def _node(row, number):
    row = {key.lower(): value for key, value in row.items()}
    kind = {1: 'vmess', 3: 'ss', 4: 'socks5', 5: 'vless', 6: 'trojan',
            7: 'hysteria2', 8: 'tuic', 10: 'http', 11: 'anytls'}.get(row.get('configtype'))
    if kind is None:
        _error(_t('v2rayN 含自定义配置、链式代理或暂不支持的协议；请导出完整 Clash/Mihomo 配置后导入。'))
    extra, transport = _extra(row.get('protoextra')), _extra(row.get('transportextra'))
    if any(row.get(key) for key in ('cert', 'certsha', 'echconfiglist', 'verifypeercertbyname',
                                    'finalmask', 'mldsa65verify', 'presocksport')):
        _error(_t('v2rayN 含暂不支持的证书、加密或前置代理设置；未生成不完整配置。'))
    allowed = {'alterid', 'vmesssecurity', 'ssmethod', 'flow', 'vlessencryption', 'salamanderpass',
               'upmbps', 'downmbps', 'ports', 'hopinterval', 'congestioncontrol'}
    if any(value not in (None, '', False, 0) for key, value in extra.items() if key not in allowed):
        _error(_t('v2rayN 含暂不支持的协议扩展；未生成不完整配置。'))
    name = row.get('remarks') or '节点'
    if not isinstance(name, str) or len(name) > 160 or any(ord(c) < 32 or ord(c) == 127 for c in name) or '://' in name:
        name = '节点'
    server, port = row.get('address'), row.get('port')
    if not isinstance(server, str) or not server or type(port) is not int or not 1 <= port <= 65535:
        _error()
    node = {'name': f'{name} · {number}', 'type': kind, 'server': server, 'port': port}
    password = row.get('password') or row.get('id') or ''
    if kind in ('vmess', 'vless'):
        node['uuid'] = password
        if kind == 'vmess':
            node.update(cipher=extra.get('vmesssecurity') or row.get('security') or 'auto',
                        alterId=int(extra.get('alterid') or row.get('alterid') or 0))
        else:
            if extra.get('vlessencryption') not in (None, '', 'none'):
                _error(_t('v2rayN 的 VLESS encryption 暂不支持转换。'))
            if extra.get('flow') or row.get('flow'):
                node['flow'] = extra.get('flow') or row['flow']
    elif kind == 'ss':
        node.update(cipher=extra.get('ssmethod') or row.get('security'), password=password)
        if not node['cipher']:
            _error()
    else:
        if password:
            node['password'] = password
        if row.get('username'):
            node['uuid' if kind == 'tuic' else 'username'] = row['username']
    if kind not in ('socks5', 'http') and not password:
        _error()
    security = row.get('streamsecurity') or ''
    if security not in ('', 'none', 'tls', 'reality'):
        _error(_t('v2rayN TLS 设置暂不支持转换。'))
    if (kind == 'ss' and security not in ('', 'none')) or (kind == 'trojan' and security == 'none'):
        _error(_t('v2rayN 此协议的 TLS 设置暂不支持转换。'))
    if security == 'reality':
        if kind != 'vless' or not row.get('publickey'):
            _error(_t('v2rayN Reality 配置不完整或协议暂不支持。'))
        node['reality-opts'] = {'public-key': row['publickey'], 'short-id': row.get('shortid') or ''}
    if security in ('tls', 'reality') or kind in ('trojan', 'hysteria2', 'tuic', 'anytls'):
        if kind in ('vmess', 'vless', 'socks5', 'http'):
            node['tls'] = True
        node['skip-cert-verify'] = _truth(row.get('allowinsecure'))
        if row.get('sni'):
            node['servername' if kind in ('vmess', 'vless') else 'sni'] = row['sni']
        if row.get('fingerprint') and kind in ('vmess', 'vless', 'trojan'):
            node['client-fingerprint'] = row['fingerprint']
        if row.get('alpn'):
            node['alpn'] = [item.strip() for item in row['alpn'].split(',') if item.strip()]
    network = row.get('network') or 'tcp'
    if network not in ('tcp', 'raw', 'ws', 'grpc'):
        _error(_t('v2rayN 传输暂仅支持 TCP、WebSocket 和 gRPC；未生成不完整配置。'))
    if network in ('ws', 'grpc'):
        if kind not in ('vmess', 'vless', 'trojan'):
            _error(_t('v2rayN 此协议的传输方式暂不支持转换。'))
        node['network'] = network
        if network == 'ws':
            node['ws-opts'] = {'path': transport.get('path') or row.get('path') or '/'}
            host = transport.get('host') or row.get('requesthost')
            if host:
                node['ws-opts']['headers'] = {'Host': host}
            if '?ed=' in node['ws-opts']['path'] or '&ed=' in node['ws-opts']['path']:
                _error(_t('v2rayN WebSocket early-data 暂不支持转换。'))
        else:
            if ((transport.get('grpcmode') or row.get('headertype')) not in (None, '', 'none', 'gun')
                    or transport.get('grpcauthority') or row.get('requesthost')):
                _error(_t('v2rayN gRPC 扩展暂不支持转换。'))
            node['grpc-opts'] = {'grpc-service-name': transport.get('grpcservicename') or row.get('path') or ''}
    elif (transport.get('rawheadertype') or row.get('headertype') or 'none') != 'none':
        _error(_t('v2rayN TCP 伪装暂不支持转换。'))
    if kind == 'hysteria2':
        if extra.get('salamanderpass'):
            node.update(obfs='salamander', **{'obfs-password': extra['salamanderpass']})
        for source, target in (('upmbps', 'up'), ('downmbps', 'down'), ('ports', 'ports'), ('hopinterval', 'hop-interval')):
            if extra.get(source):
                node[target] = extra[source]
    if kind == 'tuic':
        if not node.get('uuid'):
            _error()
        if extra.get('congestioncontrol'):
            node['congestion-controller'] = extra['congestioncontrol']
    return node


def load(path):
    """Return a portable node-only profile, never v2rayN routing or subscriptions."""
    path = Path(path)
    if client_name(path) != 'v2rayN':
        return None
    try:
        config = _json(path) if path.name == 'guiNConfig.json' else {}
        rows = config.get('vmess') if config else _rows(path)
        if not isinstance(rows, list) or not rows or len(rows) > 5000:
            _error(_t('v2rayN 未保存节点、节点超过 5000 个或配置格式不受支持。'))
        nodes = [_node(row, i) for i, row in enumerate(rows, 1)]
        if not config and (path.parent / 'guiNConfig.json').is_file():
            config = _json(path.parent / 'guiNConfig.json')
        selected = next((i for i, row in enumerate(rows)
                         if config.get('indexid') and _extra(row).get('indexid') == config['indexid']), None)
        names = [node['name'] for node in nodes]
        if selected is not None:
            names.insert(0, names.pop(selected))
        return {'mode': 'rule', 'proxies': nodes,
                'proxy-groups': [{'name': 'v2rayN', 'type': 'select', 'proxies': names}],
                'rules': ['MATCH,v2rayN']}
    except DomainError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, sqlite3.Error, OverflowError):
        _error()
