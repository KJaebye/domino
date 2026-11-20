# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Private named subscriptions; cache updates and transactional runtime switching."""
from __future__ import annotations
from domino_i18n import tr as _t

import copy
from datetime import datetime, timezone
import getpass
import json
import stat
from pathlib import Path
import re
import secrets
import shutil
import string
import sys
import tempfile
from urllib.parse import urlsplit, quote
import uuid
from domino_model import DomainError


class RecoveryError(DomainError):
    def __init__(self,message):
        super().__init__(message,code='RECOVERY_INCOMPLETE',effect='unknown')


CUSTOM_RULES = True
GEO_FILES = ('Country.mmdb', 'geoip.metadb', 'geoip.dat', 'geosite.dat', 'ASN.mmdb')


def subscription_usage(value):
    """Keep only valid server-reported counters, never the raw response header."""
    if not isinstance(value, str) or len(value) > 8192:
        return None
    fields = {}
    for field in value.split(';'):
        key, separator, number = field.strip().partition('=')
        key, number = key.lower().strip(), number.strip()
        if key not in ('upload', 'download', 'total', 'expire'):
            continue
        if key == 'expire' and not re.fullmatch(r'[0-9]{1,20}', number):
            continue
        if not separator or key in fields or not re.fullmatch(r'[0-9]{1,20}', number) or int(number) > 2**64 - 1:
            return None
        fields[key] = int(number)
    return fields if all(key in fields for key in ('upload', 'download', 'total')) else None


def usage_summary(item):
    usage = item.get('usage')
    if not isinstance(usage, dict) or any(type(usage.get(key)) is not int or not 0 <= usage[key] <= 2**64 - 1
                                          for key in ('upload', 'download', 'total')):
        return None
    used, total = usage['upload'] + usage['download'], usage['total']
    status = ('exceeded' if used > total else 'critical' if used * 100 >= total * 90 else
              'warning' if used * 100 >= total * 70 else 'normal') if total else 'unknown'
    return {'upload_bytes': usage['upload'], 'download_bytes': usage['download'], 'used_bytes': used,
            'total_bytes': total, 'percent_used': used * 100 / total if total else None,
            'status': status, 'checked_at': item.get('usage_checked_at'),
            'stale': item.get('usage_error') == 'request_failed'}


def usage_cell(ctx, item):
    usage = item.get('usage')
    if usage is None:
        message = {'request_failed': _t('获取失败'), 'no_subscription': _t('未关联订阅')}.get(item.get('usage_error'))
        return (message or (_t('未提供') if item.get('usage_checked_at') else _t('未获取')), '2')
    used, total = usage['used_bytes'], usage['total_bytes']
    text = ctx.human_size(used) + ' / ' + (ctx.human_size(total) if total else _t('未知总量'))
    if total:
        # Truncate to avoid a green 69.99% value being displayed as yellow's 70.0%.
        percentage = used * 1000 // total
        text += f' ({percentage // 10}.{percentage % 10}%)'
    if usage['status'] == 'exceeded':
        text += _t(' 已超额')
    if usage['stale']:
        text += _t(' · 缓存')
    return text, {'normal': '32', 'warning': '33', 'critical': '31', 'exceeded': '2', 'unknown': '2'}[usage['status']]


def _invalid():
    raise DomainError(_t('配置登记或备份数据无效。'), code='INVALID_REGISTRATION', exit_code=2)


def _source_identity(kind, value):
    import hashlib
    return hashlib.sha256((kind + ':' + value).encode()).hexdigest()


def _safe_path(path):
    from domino_sources import _unsafe_parents
    path = Path(path)
    if path.is_symlink() or _unsafe_parents(path):
        _invalid()
    return path


def _safe_directory(path):
    path = _safe_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        _invalid()
    path.chmod(0o700)
    return path


def _private_tree(root):
    from domino_sources import _check_tree
    _check_tree(root)
    for path in [root, *root.rglob('*')]:
        path.chmod(0o700 if path.is_dir() else 0o600)


def _validate_registry(registry):
    if not isinstance(registry, dict) or registry.get('schema') != 1 or not isinstance(registry.get('items'), list):
        _invalid()
    ids, names = set(), set()
    for item in registry['items']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', item['id']):
            _invalid()
        name = item.get('name')
        if not isinstance(name, str) or not name or len(name) > 100 or name.strip() != name or any(ord(c) < 32 or ord(c) == 127 for c in name):
            _invalid()
        if item['id'] in ids or name in names or item.get('kind') not in ('snapshot', 'subscription'):
            _invalid()
        ids.add(item['id'])
        names.add(name)
        if item.get('revision') is not None and not re.fullmatch(r'[a-f0-9]{32}', str(item['revision'])):
            _invalid()
        if 'url' in item:
            value = item['url']
            if not isinstance(value, str):
                _invalid()
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                _invalid()


def _validate_cache(path):
    from domino_sources import _check_tree, read_source
    path = _safe_path(path)
    _check_tree(path)
    try:
        config = json.loads((path / 'config.json').read_text())
        from domino_sources import _relative, _validate_profile, _walk_certs
        _validate_profile(config)
        for kind in ('proxy-providers', 'rule-providers'):
            for provider in config.get(kind, {}).values():
                if provider.get('path'):
                    _relative(path, provider['path'])
                elif provider.get('type') in ('http', 'file'):
                    _invalid()
        for _, _, value in _walk_certs(config):
            _relative(path, value)
        import domino_cli as tool
        for provider in config.get('proxy-providers', {}).values():
            if provider.get('path'):
                payload = tool.load_yaml(_relative(path, provider['path']))
                for _, _, value in _walk_certs(payload):
                    _relative(path, value)
        if (path / 'source').exists() or (path / 'source').is_symlink():
            read_source(path / 'source')
    except (OSError, ValueError, TypeError, RuntimeError):
        _invalid()


def _node_count(profile, data):
    import domino_cli as tool
    count = len(profile.get('proxies', []))
    for provider in profile.get('proxy-providers', {}).values():
        if provider.get('type') == 'inline':
            count += len(provider.get('payload', []))
        elif provider.get('path'):
            count += len(tool.load_yaml(data / provider['path']).get('proxies', []))
    return count


def _capture_digest(source):
    """Compare portable content, ignoring client-only ports, secrets and metadata."""
    import hashlib
    import domino_cli as tool
    from domino_sources import read_source
    raw, metadata = read_source(source)
    if raw.get('mode') == 'direct':
        raw['mode'] = 'rule'
    profile = tool.sanitize_profile(raw, {}, tool.DEFAULT_PROXY_PORT, tool.DEFAULT_API_PORT)
    profile.pop('secret', None)
    from domino_resources import geo_requirements
    needed = geo_requirements(profile, source)
    # Unused shared Geo caches do not distinguish otherwise identical profiles.
    content = {'config': profile, 'files': {n: h for n, h in metadata['files'].items()
               if n != 'config.json' and (n not in GEO_FILES or n in needed)}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _registry_root(ctx):
    root = Path(ctx.HOME) / '.config/domino/subscriptions'
    _safe_path(root)
    _safe_path(root / 'index.json')
    _safe_path(root / 'cache')
    return root


def snapshot_registry(ctx, backup: Path):
    """Back up exact index bytes/mode and every immutable revision it references."""
    root = _registry_root(ctx)
    target = _safe_path(Path(backup) / 'registry')
    if target.exists():
        _invalid()
    index = root / 'index.json'
    registry = json.loads(index.read_text()) if index.exists() else {'schema': 1, 'items': []}
    _validate_registry(registry)
    revisions = sorted({v['revision'] for v in registry['items'] if v.get('revision')})
    for revision in revisions:
        _validate_cache(root / 'cache' / revision)
    target.mkdir(parents=True, mode=0o700)
    state = {'version': 1, 'present': index.exists(),
             'index_mode': stat.S_IMODE(index.stat().st_mode) if index.exists() else None,
             'revisions': revisions, 'created': []}
    if index.exists():
        ctx.write_private(target / 'index.json', index.read_bytes())
    for revision in revisions:
        shutil.copytree(root / 'cache' / revision, target / 'cache' / revision)
    ctx.write_private(target / 'state.json', json.dumps(state))
    _private_tree(target)
    ctx._domino_registry_backup = target


def _backup_state(target):
    from domino_sources import _check_tree
    _check_tree(target)
    try:
        state = json.loads((target / 'state.json').read_text())
        if not isinstance(state, dict) or set(state) != {'version', 'present', 'index_mode', 'revisions', 'created'} or state['version'] != 1 or not isinstance(state['present'], bool):
            _invalid()
        for key in ('revisions', 'created'):
            if not isinstance(state[key], list) or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{32}', v) for v in state[key]) or len(set(state[key])) != len(state[key]):
                _invalid()
        if set(state['revisions']) & set(state['created']):
            _invalid()
        if state['present']:
            if type(state['index_mode']) is not int or not 0 <= state['index_mode'] <= 0o777:
                _invalid()
            registry = json.loads((target / 'index.json').read_text())
            _validate_registry(registry)
            if sorted({v['revision'] for v in registry['items'] if v.get('revision')}) != sorted(state['revisions']):
                _invalid()
        elif state['index_mode'] is not None or state['revisions'] or (target / 'index.json').exists():
            _invalid()
        for revision in state['revisions']:
            _validate_cache(target / 'cache' / revision)
        return state
    except (OSError, ValueError, TypeError, KeyError):
        _invalid()


def restore_registry(ctx, backup: Path):
    """Restore only the recorded registry and transaction-created revisions."""
    target = Path(backup) / 'registry'
    if not target.exists() and not target.is_symlink():
        return  # Older backups have no authority to remove a current registry.
    state = _backup_state(target)
    root = _registry_root(ctx)
    for revision in set(state['revisions']) | set(state['created']):
        path = _safe_path(root / 'cache' / revision)
        if path.exists():
            from domino_sources import _check_tree
            _check_tree(path)
    if state['present'] or state['revisions']:
        _safe_directory(root)
    for revision in state['revisions']:
        destination = root / 'cache' / revision
        _safe_directory(destination.parent)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(target / 'cache' / revision, destination)
        _private_tree(destination)
    index = root / 'index.json'
    if state['present']:
        ctx.write_private(index, (target / 'index.json').read_bytes())
        index.chmod(state['index_mode'])
    else:
        index.unlink(missing_ok=True)
    for revision in state['created']:
        shutil.rmtree(root / 'cache' / revision, ignore_errors=False) if (root / 'cache' / revision).exists() else None


def _track_revision(ctx, revision):
    target = getattr(ctx, '_domino_registry_backup', None)
    if target is None:
        return
    target = Path(target)
    state = _backup_state(target)
    if revision not in state['created']:
        state['created'].append(revision)
        ctx.write_private(target / 'state.json', json.dumps(state))


def _registration(bundle):
    bundle = Path(bundle)
    _safe_path(bundle)
    path = _safe_path(bundle / 'registration.json')
    if not path.exists():
        return {'version': 1, 'kind': 'snapshot'}
    try:
        envelope = json.loads(path.read_text())
        if not isinstance(envelope, dict) or set(envelope) - {'version', 'kind', 'name', 'url', 'preserve_current'} or envelope.get('version') != 1 or envelope.get('kind') not in ('snapshot', 'subscription'):
            _invalid()
        name = envelope.get('name')
        if name is not None and (not isinstance(name, str) or not name or len(name) > 100 or name.strip() != name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
            _invalid()
        if 'preserve_current' in envelope and type(envelope['preserve_current']) is not bool:
            _invalid()
        if envelope['kind'] == 'subscription':
            if envelope.get('preserve_current'):
                _invalid()
            value = envelope.get('url')
            if not isinstance(value, str):
                _invalid()
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                _invalid()
        elif 'url' in envelope:
            _invalid()
        return envelope
    except (OSError, ValueError, TypeError):
        _invalid()


def validate_install_registration(ctx, bundle: Path):
    """Preflight before installer destructive writes; performs no mutations."""
    try:
        from domino_sources import read_source
        _registration(bundle)
        data = Path(bundle) / 'data'
        _validate_cache(data)
        config = json.loads((data / 'config.json').read_text())
        marker = data / 'subscription.json'
        if marker.exists():
            value = json.loads(marker.read_text())
            if not isinstance(value, dict) or set(value) != {'id'} or not isinstance(value['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['id']):
                _invalid()
        rules = data / 'rules-base.json'
        if rules.exists() and (not isinstance(json.loads(rules.read_text()), list) or any(not isinstance(v, str) for v in json.loads(rules.read_text()))):
            _invalid()
        selections = Path(bundle) / 'selections.json'
        if selections.exists():
            value = json.loads(selections.read_text())
            if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
                _invalid()
        root = _registry_root(ctx)
        if (root / 'index.json').exists():
            _validate_registry(json.loads((root / 'index.json').read_text()))
        return config
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        _invalid()

def register_installed(ctx, bundle: Path):
    """Commit prepared baseline/source inside the installer's rollback boundary."""
    config = validate_install_registration(ctx, bundle)
    if not (config.get('proxies') or config.get('proxy-providers')):
        return
    manager = Manager(ctx)
    # Installation may move APP; do not consult a stale manifest/controller here.
    manager.app, manager.data = Path(ctx.APP), Path(ctx.APP) / 'data'
    return manager.register_prepared(Path(bundle), _registration(bundle))


class Manager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.root = ctx.HOME / '.config/domino/subscriptions'
        self.index = self.root / 'index.json'
        for path in [ctx.HOME / '.config', self.root.parent, self.root, self.index]:
            if path.is_symlink():
                raise ctx.InstallError(_t('配置存储路径不能是符号链接。'))
        try:
            self.registry = json.loads(self.index.read_text()) if self.index.exists() else {'schema': 1, 'items': []}
            _validate_registry(self.registry)
        except (OSError, ValueError, TypeError, DomainError):
            raise ctx.InstallError(_t('配置目录格式不受支持。')) from None
        self.app = ctx.current_installation()[0] if hasattr(ctx, 'current_installation') else ctx.APP
        self.data = self.app / 'data'

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.ctx.write_private(self.index, json.dumps(self.registry, ensure_ascii=False, indent=2))

    def name(self, value):
        if not value or len(value) > 100 or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise self.ctx.InstallError(_t('配置名称需为 1–100 个字符，不能含控制字符或首尾空白。'))
        return value

    def find(self, name):
        self.name(name)
        for item in self.registry['items']:
            if item['name'] == name:
                return item
        raise self.ctx.InstallError(_t('未找到配置：') + name,code='SUBSCRIPTION_NOT_FOUND',exit_code=3)

    def available_name(self, name):
        self.name(name)
        if any(item['name'] == name for item in self.registry['items']):
            raise self.ctx.InstallError(_t('配置名称已存在：') + name,code='SUBSCRIPTION_EXISTS',exit_code=6)

    def unique_name(self, value):
        base = self.name(value[:100])
        names = {item['name'] for item in self.registry['items']}
        name = base
        while name in names:
            suffix = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(6))
            name = base[:93] + '-' + suffix
        return name

    def url(self, value):
        if value is None:
            if not sys.stdin.isatty():
                raise self.ctx.InstallError(_t('隐藏输入需要交互终端；脚本请使用 --url。'))
            value = getpass.getpass(_t('完整配置订阅地址（隐藏输入）：'))
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise self.ctx.InstallError(_t('订阅地址必须是无嵌入用户名和密码的 HTTPS URL。'),code='INVALID_SUBSCRIPTION_URL',exit_code=2)
        return value

    def active_id(self):
        marker = self.data / 'subscription.json'
        return json.loads(marker.read_text()).get('id') if marker.is_file() else None

    def config(self):
        path = self.data / 'config.json'
        if not path.is_file() or not (self.app / 'mihomo').is_file():
            raise self.ctx.InstallError(_t('尚未安装运行环境，请先运行安装程序，再下载或切换订阅。'))
        return json.loads(path.read_text())

    def cached(self, item):
        revision = item.get('revision', '')
        if not re.fullmatch(r'[a-f0-9]{32}', revision):
            raise self.ctx.InstallError(_t('订阅尚未下载，请先更新或使用该订阅。'))
        path = self.root / 'cache' / revision
        _validate_cache(path)
        return path

    def listing(self):
        active = self.active_id()
        values = []
        for item in self.registry['items']:
            values.append({k: item.get(k) for k in ['name', 'kind', 'updated_at', 'node_count', 'group_count']})
            values[-1].update(active=item['id'] == active, cached=bool(item.get('revision')),
                              host=urlsplit(item.get('url', '')).hostname,
                              usage=usage_summary(item), usage_checked_at=item.get('usage_checked_at'),
                              usage_error=item.get('usage_error'))
        current = next((v['name'] for v in values if v['active']), None)
        return {'active': current, 'current_source': current or (_t('未关联订阅的当前配置') if (self.data / 'config.json').exists() else _t('尚未初始化')),
                'configs': values}

    def show(self, as_json):
        result = self.listing()
        if as_json:
            self.ctx.show(result, True)
            return
        pending = not (self.data/'config.json').is_file() or self.ctx.subscription_pending(self.app)
        current = result['active'] or (_t('待添加订阅') if pending else _t('独立配置（未绑定订阅）'))
        self.ctx.human_header(_t('配置'),_t('{0} 个配置 · 在线订阅 / 快照', len(result['configs'])))
        self.ctx.human_row(_t('当前配置'),(current,'1'))
        active = next((item for item in result['configs'] if item['active']), None)
        if active:
            self.ctx.human_row(_t('套餐流量'), usage_cell(self.ctx, active))
            if active.get('usage_checked_at'):
                self.ctx.human_row(_t('流量更新'), self.ctx.human_time(active['usage_checked_at']))
        if not result['configs']:
            print(_t('\n  添加订阅：domino add "名称"'))
            return
        print()
        rows=[]
        for item in result['configs']:
            name = ('● ' if item['active'] else '  ') + item['name']
            rows.append([(name,'32' if item['active'] else None),_t('在线订阅') if item['kind'] == 'subscription' else _t('配置快照'),
                         item['node_count'],usage_cell(self.ctx, item),self.ctx.human_time(item['updated_at']) if item['updated_at'] else _t('尚未下载'),item['host'] or _t('本地')])
        self.ctx.human_table([_t('配置名称'),_t('类型'),_t('节点'),_t('套餐已用 / 总量'),_t('更新时间'),_t('来源')],rows)
        print(_t('\n  套餐数据来自订阅服务；domino list --refresh-usage 仅刷新流量，不切换或重载配置。'))

    def register_current(self, url, name=None):
        url = self.url(url)
        existing = next((item for item in self.registry['items'] if item.get('url') == url), None)
        if name is None:
            name = existing['name'] if existing else self.unique_name(urlsplit(url).hostname)
        if not existing or existing['name'] != name:
            self.available_name(name)
        item = self.fetch({'id': existing['id'] if existing else uuid.uuid4().hex,
                           'name': name, 'kind': 'subscription', 'url': url}, snapshot=True)
        item['selections'] = self.selections()
        if existing:
            self.replace(item)
        else:
            self.registry['items'].append(item)
        self.save()
        self.ctx.write_private(self.data / 'subscription.json', json.dumps({'id': item['id']}))

    def capture(self, source, raw, proxy=None, *, core=None, resource_dirs=()):
        """Validate and cache a private external profile without touching runtime."""
        import domino_cli as tool
        from domino_sources import create_source, derive_runtime
        _safe_directory(self.root)
        with tempfile.TemporaryDirectory(prefix='.capture-', dir=self.root) as directory:
            bundle = Path(directory)
            data = bundle / 'data'
            data.mkdir(mode=0o700)
            create_source(raw, source, data / 'source', proxy=proxy, geo_dirs=(self.data,), require_geo=True, resource_dirs=resource_dirs)
            digest = _capture_digest(data / 'source')
            for item in self.registry['items']:
                if item.get('revision'):
                    cached_source = self.cached(item) / 'source'
                    if cached_source.is_dir() and _capture_digest(cached_source) == digest:
                        return item, False
            profile = derive_runtime(data / 'source', data, {}, tool.DEFAULT_PROXY_PORT, tool.DEFAULT_API_PORT)
            self.ctx.write_private(data / 'config.json', json.dumps(profile, ensure_ascii=False))
            binary = Path(core).expanduser() if core else self.app / 'mihomo'
            if not binary.is_file():
                raise self.ctx.InstallError(_t('缺少配置校验内核，请先安装 Domino 或使用 --core。'))
            self.ctx.run([str(binary), '-t', '-d', str(data), '-f', str(data / 'config.json')],
                         capture_output=True, text=True, timeout=90, stage=_t('本机配置校验'))
            return self.register_prepared(bundle, {'version': 1, 'kind': 'snapshot'}, activate=False), True

    def register_prepared(self, bundle, envelope, *, activate=True):
        from domino_sources import create_source, origin_info, read_source
        saved_registry = copy.deepcopy(self.registry)
        prepared = bundle / 'data'
        baseline = json.loads((prepared / 'config.json').read_text())
        if (prepared / 'rules-base.json').is_file():
            baseline['rules'] = json.loads((prepared / 'rules-base.json').read_text())
        source = prepared / 'source'
        temporary = None
        try:
            if not source.exists():
                # Explicit old-bundle installation can honestly capture its prepared
                # runtime, but must never download or guess a historical origin.
                temporary = tempfile.TemporaryDirectory(prefix='domino-legacy-source-')
                source = Path(temporary.name) / 'source'
                for kind in ('proxy-providers', 'rule-providers'):
                    for provider in baseline.get(kind, {}).values():
                        value = provider.get('path')
                        if provider.get('type') in ('http', 'file') and (not value or not (prepared / value).is_file()):
                            _invalid()
                metadata = origin_info(baseline, prepared / 'config.json')
                metadata.update(capture_kind='legacy-runtime-snapshot', origin_label=_t('旧版运行配置快照'))
                metadata['identity'] = _source_identity('legacy-runtime-snapshot', metadata['parsed_digest'])
                create_source(baseline, prepared / 'config.json', source, metadata=metadata, _offline=True)
                # The local materialized source supplies portable provider/cert refs.
                baseline = json.loads((source / 'config.json').read_text())
                if not (self.data / 'source').exists():
                    shutil.copytree(source, self.data / 'source')
            _, metadata = read_source(source)
            existing = None
            if envelope['kind'] == 'subscription':
                existing = next((v for v in self.registry['items'] if v.get('kind') == 'subscription' and v.get('url') == envelope['url']), None)
            else:
                existing = next((v for v in self.registry['items'] if v.get('kind') == 'snapshot' and v.get('source_identity') == metadata['identity']), None)
                if envelope.get('preserve_current'):
                    marker = prepared / 'subscription.json'
                    identifier = json.loads(marker.read_text()).get('id') if marker.is_file() else None
                    prior = next((v for v in self.registry['items'] if v['id'] == identifier), None)
                    if prior and prior.get('revision'):
                        try:
                            _, old_source = read_source(self.cached(prior) / 'source')
                            if old_source['identity'] == metadata['identity']:
                                existing = prior
                        except FileNotFoundError:
                            pass
            # A changed capture of the active source becomes a separate snapshot;
            # its active marker and cache revision continue to describe the runtime.
            if not activate and existing and existing['id'] == self.active_id():
                existing = None
            name = existing['name'] if existing else envelope.get('name')
            if not name:
                if envelope['kind'] == 'subscription':
                    name = urlsplit(envelope['url']).hostname
                else:
                    name = metadata.get('profile_name') or metadata['origin_label']
            if not existing:
                name = self.unique_name(name)
            self.name(name)
            item = copy.deepcopy(existing) if existing else {'id': uuid.uuid4().hex, 'name': name, 'kind': envelope['kind']}
            if envelope['kind'] == 'subscription':
                item.update(kind='subscription', url=envelope['url'])
            revision = uuid.uuid4().hex
            cache = _safe_directory(self.root / 'cache')
            _track_revision(self.ctx, revision)
            destination = cache / revision
            try:
                destination.mkdir(mode=0o700)
                shutil.copytree(source, destination / 'source')
                for relative in metadata['files']:
                    if relative != 'config.json':
                        self.ctx.write_private(destination / relative, (source / relative).read_bytes())
                # Copy the prepared baseline rather than re-sanitizing or using the
                # installed effective (target-overlay) config.
                for path in prepared.iterdir():
                    if path.name in ('config.json', 'source', 'subscription.json', 'cache.db', 'rules-base.json'):
                        continue
                    if path.is_dir():
                        shutil.copytree(path, destination / path.name, dirs_exist_ok=True)
                    elif path.is_file():
                        self.ctx.write_private(destination / path.name, path.read_bytes())
                self.ctx.write_private(destination / 'config.json', json.dumps(baseline, ensure_ascii=False))
                _private_tree(destination)
                _validate_cache(destination)
                item.update(revision=revision, source_identity=metadata['identity'],
                            source_digest=metadata['snapshot_digest'],
                            updated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                            node_count=_node_count(baseline, destination), group_count=len(baseline.get('proxy-groups', [])))
                selections = bundle / 'selections.json'
                item['selections'] = json.loads(selections.read_text()) if selections.is_file() else {}
                self.replace(item) if existing else self.registry['items'].append(item)
                self.save()
                if activate:
                    self.ctx.write_private(self.data / 'subscription.json', json.dumps({'id': item['id']}))
            except BaseException:
                # Installer registry backup owns full rollback; a failed cache
                # construction alone can always discard its unreferenced revision.
                if not activate:
                    self.registry = saved_registry
                if not any(v.get('revision') == revision for v in self.registry['items']):
                    shutil.rmtree(destination, ignore_errors=True)
                raise
            return item
        finally:
            if temporary is not None:
                temporary.cleanup()

    def selections(self):
        live = self.ctx.api_json('/proxies')['proxies']
        return {name: value['now'] for name, value in live.items()
                if str(value.get('type', '')).lower() in ['selector', 'select'] and value.get('now')}

    def restore_selections(self, selections, global_fallback=()):
        live = self.ctx.api_json('/proxies')['proxies']
        for name, selected in selections.items():
            if selected in live.get(name, {}).get('all', []):
                self.ctx.api_json('/proxies/' + quote(name, safe=''), {'name': selected})
        choices = live.get('GLOBAL', {}).get('all', [])
        if global_fallback and selections.get('GLOBAL') not in choices:
            selected = next((name for name in global_fallback if name in choices), None)
            if selected:
                self.ctx.api_json('/proxies/GLOBAL', {'name': selected})

    def fetch(self, item, snapshot=False):
        # Each immutable cache revision owns the same-version source and runtime.
        import domino_cli as tool
        from domino_sources import create_source, derive_runtime, origin_info
        current = self.config()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        cache = self.root / 'cache'
        _safe_directory(cache)
        revision = uuid.uuid4().hex
        configured = bool(current.get('proxies') or current.get('proxy-providers'))
        proxy = f"http://127.0.0.1:{current['mixed-port']}" if configured and self.ctx.systemctl('is-active') else tool.discover_proxy()
        with tempfile.TemporaryDirectory(prefix='.fetch-', dir=self.root) as directory:
            work = Path(directory)
            if snapshot:
                raw, source = dict(current, rules=self.ctx.base_rules(self.data, current)), self.data / 'config.json'
                metadata = origin_info(raw, source)
                metadata.update(capture_kind='runtime-snapshot', origin_label=_t('当前运行配置快照'))
                metadata['identity'] = _source_identity('runtime-snapshot', metadata['parsed_digest'])
            else:
                source = work / 'subscription.yaml'
                headers = tool.download(item['url'], source, proxy, user_agent=tool.SUBSCRIPTION_USER_AGENT)
                raw = tool.load_yaml(source)
                metadata = origin_info(raw, source, subscription=True)
            if not isinstance(raw, dict) or not (raw.get('proxies') or raw.get('proxy-providers')):
                raise self.ctx.InstallError(_t('订阅必须返回完整 Clash/Mihomo 配置；不支持节点链接列表或登录页面。'))
            data = work / 'data'
            data.mkdir(mode=0o700)
            try:
                create_source(raw, source, data / 'source', proxy=proxy, metadata=metadata, online=not snapshot)
                # Preserve capture mode in source; runtime imports retain the legacy
                # direct -> rule adjustment without rewriting provenance.
                runtime_source = data / 'source'
                profile = derive_runtime(runtime_source, data, {}, current['mixed-port'], int(current['external-controller'].rsplit(':', 1)[1]))
            except DomainError:
                raise self.ctx.InstallError(_t('订阅源配置或依赖无效，未更改运行配置。')) from None
            for name in GEO_FILES:
                if (self.data / name).is_file() and not (data / name).exists():
                    self.ctx.write_private(data / name, (self.data / name).read_bytes())
            self.ctx.write_private(data / 'config.json', json.dumps(profile, ensure_ascii=False))
            self.ctx.run([str(self.app / 'mihomo'), '-t', '-d', str(data), '-f', str(data / 'config.json')],
                         capture_output=True, text=True, timeout=90)
            node_count = _node_count(profile, data)
            _private_tree(data)
            data.rename(cache / revision)
        updated = copy.deepcopy(item)
        updated.update(revision=revision, updated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                       node_count=node_count, group_count=len(profile.get('proxy-groups', [])))
        if not snapshot:
            updated.update(usage=subscription_usage(headers.get('subscription-userinfo') if isinstance(headers, dict) else None),
                           usage_checked_at=updated['updated_at'])
            updated.pop('usage_error', None)
        return updated

    def refresh_usage(self):
        """Refresh account counters without updating source caches or the live core."""
        import domino_cli as tool
        proxy = tool.discover_proxy()
        responses = {}
        for item in self.registry['items']:
            try:
                url = item.get('url') or self.source_subscription_url(item)
            except (DomainError, OSError, ValueError):
                item.update(usage=None, usage_error='no_subscription')
                continue
            try:
                if url not in responses:
                    responses[url] = tool.download_subscription_usage(url, proxy)
                headers = responses[url]
                item.update(usage=subscription_usage(headers.get('subscription-userinfo') if isinstance(headers, dict) else None),
                            usage_checked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
                item.pop('usage_error', None)
            except (DomainError, OSError, RuntimeError, ValueError):
                item['usage_error'] = 'request_failed'
        if self.registry['items']:
            self.save()

    def replace(self, item):
        self.registry['items'] = [item if old['id'] == item['id'] else old for old in self.registry['items']]

    def apply(self, item):
        from domino_sources import _check_tree
        _check_tree(self.data)
        current = self.config()
        runtime = self.ctx.api_json('/configs')  # Fail before writes if the service is stopped.
        old_selections = self.selections()
        active = self.active_id()
        for old in self.registry['items']:
            if old['id'] == active:
                old['selections'] = old_selections
        selections = dict(old_selections if active == item['id'] else item.get('selections', {}))
        if 'GLOBAL' not in selections and 'GLOBAL' in old_selections:
            selections['GLOBAL'] = old_selections['GLOBAL']
        cached = self.cached(item)
        candidate = json.loads((cached / 'config.json').read_text())
        base = list(candidate.get('rules', []))
        candidate = self.ctx.compose_custom_rules(candidate)
        from domino_sources import independent_dns
        candidate['dns'] = independent_dns(candidate)
        for key in ['mixed-port', 'external-controller', 'secret']:
            candidate[key] = current[key]
        candidate['mode'] = runtime.get('mode', current.get('mode', 'rule'))
        candidate['log-level'] = runtime.get('log-level', current.get('log-level', 'warning'))
        revision = uuid.uuid4().hex
        resources = self.data / 'subscription-resources' / revision
        for kind in ['proxy-providers', 'rule-providers']:
            for provider in candidate.get(kind, {}).values():
                if provider.get('path'):
                    provider['path'] = str(resources / provider['path'])
        from domino_sources import _walk_certs
        for node, key, value in _walk_certs(candidate):
            node[key] = str(resources / value)
        backup = self.ctx.BACKUPS / ('subscription-' + uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        shutil.copytree(self.data, backup / 'data')
        index_before = self.index.read_bytes() if self.index.exists() else None
        index_mode = stat.S_IMODE(self.index.stat().st_mode) if self.index.exists() else None
        file_modes = {path.name: stat.S_IMODE(path.stat().st_mode) for path in self.data.iterdir() if path.is_file()}
        if index_before is not None:
            self.ctx.write_private(backup / 'index.json', index_before)
        live_dirty = False
        try:
            shutil.copytree(cached, resources)
            import domino_cli as tool
            for provider in json.loads((cached / 'config.json').read_text()).get('proxy-providers', {}).values():
                if provider.get('path'):
                    payload_path = resources / provider['path']
                    payload = tool.load_yaml(payload_path)
                    for node, key, value in _walk_certs(payload):
                        node[key] = str(resources / value)
                    self.ctx.write_private(payload_path, json.dumps(payload, ensure_ascii=False))
            active_source = self.data / 'source'
            if active_source.exists() or active_source.is_symlink():
                from domino_sources import _check_tree
                _check_tree(active_source)
                shutil.rmtree(active_source)
            if (cached / 'source').is_dir():
                shutil.copytree(cached / 'source', active_source)
            for name in ['Country.mmdb', 'geoip.metadb', 'geoip.dat', 'geosite.dat', 'ASN.mmdb']:
                if (cached / name).is_file():
                    self.ctx.write_private(self.data / name, (cached / name).read_bytes())
            pending = self.data / ('.subscription-' + revision + '.json')
            self.ctx.write_private(pending, json.dumps(candidate, ensure_ascii=False))
            self.ctx.run([str(self.app / 'mihomo'), '-t', '-d', str(self.data), '-f', str(pending)],
                         capture_output=True, text=True, timeout=90)
            self.ctx.write_private(self.data / 'config.json', pending.read_bytes())
            pending.unlink()
            live_dirty = True
            self.ctx.api_json('/configs?force=true', {'path': str(self.data / 'config.json')}, method='PUT', timeout=45)
            fallback = ([g['name'] for g in candidate.get('proxy-groups', [])] +
                        [n['name'] for n in candidate.get('proxies', [])]) if candidate['mode'] == 'global' else ()
            self.restore_selections(selections, fallback)
            self.ctx.write_private(self.data / 'rules-base.json', json.dumps(base, ensure_ascii=False))
            self.ctx.write_private(self.data / 'subscription.json', json.dumps({'id': item['id']}))
            self.replace(item)
            self.save()
            for name in ('config.json', 'subscription.json', 'rules-base.json'):
                if name in file_modes:
                    (self.data / name).chmod(file_modes[name])
            if index_mode is not None:
                self.index.chmod(index_mode)
        except BaseException:
            try:
                # Restore only files changed by this transaction. Never truncate
                # the running kernel's memory-mapped cache.db (or Geo databases).
                for name in ['config.json', 'subscription.json', 'rules-base.json', 'Country.mmdb', 'geoip.metadb', 'geoip.dat', 'geosite.dat', 'ASN.mmdb']:
                    saved = backup / 'data' / name
                    if saved.is_file():
                        self.ctx.write_private(self.data / name, saved.read_bytes())
                        (self.data / name).chmod(stat.S_IMODE(saved.stat().st_mode))
                    elif name in ['subscription.json', 'rules-base.json'] or (cached / name).is_file():
                        (self.data / name).unlink(missing_ok=True)
                active_source = self.data / 'source'
                if active_source.exists() or active_source.is_symlink():
                    from domino_sources import _check_tree
                    _check_tree(active_source)
                    shutil.rmtree(active_source)
                if (backup / 'data/source').is_dir():
                    shutil.copytree(backup / 'data/source', active_source)
                if index_before is None:
                    self.index.unlink(missing_ok=True)
                else:
                    self.ctx.write_private(self.index, index_before)
                    self.index.chmod(index_mode)
                self.registry = json.loads(index_before) if index_before is not None else {'schema': 1, 'items': []}
                if live_dirty:
                    self.ctx.api_json('/configs?force=true', {'path': str(self.data / 'config.json')}, method='PUT', timeout=45)
                    self.restore_selections(old_selections)
                shutil.rmtree(resources, ignore_errors=True)
                (self.data / ('.subscription-' + revision + '.json')).unlink(missing_ok=True)
            except BaseException as recovery_error:
                raise RecoveryError(_t('订阅应用失败且恢复未完成；备份：') + str(backup)) from recovery_error
            raise self.ctx.InstallError(_t('订阅未应用，已恢复原配置；备份：') + str(backup),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
        # Keep only the active resource copy; the previous one is in the backup.
        for path in resources.parent.iterdir():
            if path != resources and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)

    def import_current(self, name):
        self.available_name(name)
        previous_registry = copy.deepcopy(self.registry)
        index_before = self.index.read_bytes() if self.index.exists() else None
        index_mode = stat.S_IMODE(self.index.stat().st_mode) if self.index.exists() else None
        marker = self.data / 'subscription.json'
        marker_before = marker.read_bytes() if marker.exists() else None
        bind = self.active_id() is None
        item = self.fetch({'id': uuid.uuid4().hex, 'name': name, 'kind': 'snapshot'}, snapshot=True)
        try:
            item['selections'] = self.selections()
        except (OSError, ValueError, self.ctx.InstallError):
            item['selections'] = {}
        source = self.data / 'source'
        with tempfile.TemporaryDirectory(prefix='.import-current-', dir=self.root) as directory:
            saved_source = Path(directory) / 'source'
            if bind and source.exists():
                from domino_sources import _check_tree
                _check_tree(source)
                shutil.copytree(source, saved_source)
            try:
                self.registry['items'].append(item)
                self.save()
                if bind:
                    if source.exists():
                        shutil.rmtree(source)
                    shutil.copytree(self.cached(item) / 'source', source)
                    self.ctx.write_private(marker, json.dumps({'id': item['id']}))
            except BaseException:
                try:
                    self.registry = previous_registry
                    if index_before is None:
                        self.index.unlink(missing_ok=True)
                    else:
                        self.ctx.write_private(self.index, index_before)
                        self.index.chmod(index_mode)
                    if bind:
                        if source.exists():
                            shutil.rmtree(source)
                        if saved_source.exists():
                            shutil.copytree(saved_source, source)
                        if marker_before is None:
                            marker.unlink(missing_ok=True)
                        else:
                            self.ctx.write_private(marker, marker_before)
                    shutil.rmtree(self.cached(item), ignore_errors=True)
                except BaseException as error:
                    raise RecoveryError(_t('当前配置快照登记失败且恢复未完成。')) from error
                raise

    def source_subscription_url(self, item):
        """Recover only the captured Clash profile's explicitly recorded subscription."""
        import domino_cli as tool
        from domino_sources import read_source
        message = _t('本地快照没有可用订阅地址；请在“修改地址”中填写 HTTPS 订阅地址后更新配置。')
        try:
            _, origin = read_source(self.cached(item) / 'source')
            kind = origin.get('capture_kind')
            if kind not in ('verge-profile', 'verge-runtime') or not origin.get('profile_id'):
                raise ValueError()
            original = Path(origin['original_path'])
            if not original.is_absolute():
                raise ValueError()
            root = original.parent.parent if kind == 'verge-profile' else original.parent
            index = _safe_path(root / 'profiles.yaml')
            if index.stat().st_size > 2 * 1024 * 1024:
                raise ValueError()
            entries = tool.load_yaml(index)['items']
            matches = [entry for entry in entries if isinstance(entry, dict) and entry.get('uid') == origin['profile_id']]
            if len(matches) != 1 or matches[0].get('type') != 'remote':
                raise ValueError()
            entry = matches[0]
            if not isinstance(entry.get('url'), str) or not isinstance(entry.get('file'), str) or not entry['file']:
                raise ValueError()
            filename = Path(entry['file'])
            if filename.is_absolute() or '..' in filename.parts or '\\' in str(filename):
                raise ValueError()
            if kind == 'verge-profile' and (root / 'profiles' / filename).resolve() != original.resolve():
                raise ValueError()
            return self.url(entry['url'])
        except (DomainError, OSError, ValueError, TypeError, KeyError, RuntimeError):
            raise self.ctx.InstallError(message, code='SUBSCRIPTION_URL_REQUIRED') from None

    def update(self, item):
        candidate = copy.deepcopy(item)
        if not candidate.get('url'):
            candidate.update(url=self.source_subscription_url(item), kind='subscription')
            for key in ('source_identity', 'source_digest'):
                candidate.pop(key, None)
        updated = self.fetch(candidate)
        try:
            if self.active_id() == item['id']:
                self.apply(updated)
            else:
                self.replace(updated)
                self.save()
        except BaseException:
            shutil.rmtree(self.cached(updated), ignore_errors=True)
            raise

    def execute(self, args, *, render=True):
        if args.url is not None and not (args.add or args.set_url):
            raise self.ctx.InstallError(_t('--url 需用于 domino add 或 domino set-url。'))
        if args.new_name is not None and not args.rename:
            raise self.ctx.InstallError(_t('--new-name 需与 --rename 配合使用。'))
        if args.add:
            self.available_name(args.add)
            self.registry['items'].append({'id': uuid.uuid4().hex, 'name': args.add, 'kind': 'subscription', 'url': self.url(args.url)})
            self.save()
        elif args.import_current:
            self.import_current(args.import_current)
        elif args.remove:
            item = self.find(args.remove)
            if item['id'] == self.active_id():
                raise self.ctx.InstallError(_t('不能删除当前正在使用的配置，请先切换到其他配置。'))
            self.registry['items'].remove(item)
            self.save()
            if item.get('revision'):
                shutil.rmtree(self.cached(item), ignore_errors=True)
        elif args.rename:
            item = self.find(args.rename)
            self.available_name(args.new_name)
            item['name'] = args.new_name
            self.save()
        elif args.set_url:
            item = self.find(args.set_url)
            item.update(url=self.url(args.url), kind='subscription')
            item.pop('revision', None)
            item.pop('updated_at', None)
            item.pop('node_count', None)
            item.pop('group_count', None)
            for key in ('usage', 'usage_checked_at', 'usage_error'):
                item.pop(key, None)
            self.save()
        elif getattr(args, 'refresh_usage', False):
            self.refresh_usage()
        elif args.use:
            item = self.find(args.use)
            fetched = not item.get('revision')
            if fetched:
                item = self.fetch(item)
            try:
                self.apply(item)
            except BaseException:
                if fetched:
                    shutil.rmtree(self.cached(item), ignore_errors=True)
                raise
        elif args.update:
            self.update(self.find(args.update))
        elif args.update_all:
            failed = []
            for item in list(self.registry['items']):
                if item.get('url'):
                    try:
                        self.update(item)
                    except RecoveryError:
                        raise
                    except (RuntimeError, OSError, ValueError, KeyError):
                        self.registry = json.loads(self.index.read_text())
                        failed.append(item['name'])
            if failed:
                raise self.ctx.InstallError(_t('部分订阅更新失败，保留各自旧配置：') + '、'.join(failed))
        if render:
            if not args.json and (args.use or args.update or args.update_all):
                print(_t('配置操作已完成；配置应用不代表出网通过，使用 domino status 检查。'))
            self.show(args.json)
        return self.listing()


def run(ctx, args):
    Manager(ctx).execute(args)
