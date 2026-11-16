# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Private, portable parsed import snapshots (not verbatim source documents)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from domino_model import DomainError

_ERROR = '导入源快照无效或资源不完整。'
_DIGEST = re.compile(r'[a-f0-9]{64}')
_KINDS = {'file', 'verge-profile', 'verge-runtime', 'subscription', 'runtime-snapshot', 'legacy-runtime-snapshot'}
_CERT_KEYS = {'certificate', 'private-key'}


def _fail():
    raise DomainError(_ERROR, code='INVALID_SOURCE_SNAPSHOT', exit_code=2) from None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _label(value, fallback):
    if not isinstance(value, str) or not value or len(value) > 100 or '://' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return fallback
    return value.strip() or fallback


def origin_info(raw, source: Path, *, subscription=None):
    """Capture identity before confirmation; never keep an online temporary path/URL."""
    try:
        digest = _digest(raw)
        source = Path(source)
        info = {'version': 1, 'capture_kind': 'subscription' if subscription else 'file',
                'origin_label': '在线订阅' if subscription else '配置文件',
                'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'parsed_digest': digest}
        identity = {'kind': info['capture_kind'], 'digest': digest}
        if not subscription:
            info['original_path'] = str(source.resolve())
            identity = {'kind': 'file', 'path': str(source.resolve())}
            if source.name == 'config.json' and source.parent.name == 'data' and source.parent.parent.name in ('domino', 'robot-clash'):
                info.update(capture_kind='legacy-runtime-snapshot', origin_label='旧版运行配置快照')
                identity = {'kind': 'legacy-runtime-snapshot', 'digest': digest}
            import domino_cli as tool
            verge_root = (Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev').resolve()
            resolved = source.resolve()
            profiles = {}
            runtime = resolved == verge_root / 'clash-verge.yaml'
            if runtime or resolved.is_relative_to(verge_root / 'profiles'):
                profiles, _ = tool.read_verge_profiles()
            profiles = {Path(p).resolve(): v for p, v in profiles.items()}
            selected = profiles.get(resolved)
            if runtime:
                matches = [v for p, v in profiles.items() if v.get('client_current') is True and p.parent.parent == resolved.parent]
                selected = matches[0] if len(matches) == 1 else None
                info.update(capture_kind='verge-runtime', origin_label='Clash Verge 运行配置')
            elif selected:
                info.update(capture_kind='verge-profile', origin_label='Clash Verge 保存配置')
            if selected and isinstance(selected.get('profile_id'), str):
                info.update(profile_id=_label(selected['profile_id'], 'unknown'),
                            profile_name=_label(selected.get('profile_name'), '未命名配置'),
                            association='index' if runtime else 'selected-profile')
                identity = {'kind': info['capture_kind'], 'profile_id': info['profile_id'],
                            'client_root': str(resolved.parent if runtime else resolved.parent.parent)}
            elif runtime:
                identity = {'kind': 'verge-runtime', 'digest': digest}
        info['identity'] = _digest(identity)
        return info
    except (OSError, ValueError, TypeError, RuntimeError):
        _fail()


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        _fail()
    path.write_bytes(payload if isinstance(payload, bytes) else payload.encode())
    path.chmod(0o600)


def _unsafe_parents(path):
    # macOS exposes its system temporary directories through these fixed aliases.
    return any(parent.is_symlink() for parent in Path(path).parents
               if str(parent) not in ('/var', '/tmp', '/etc'))


def _check_tree(root):
    root = Path(root)
    if root.is_symlink() or _unsafe_parents(root):
        _fail()
    if not root.is_dir():
        _fail()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            _fail()


def _relative(root, value):
    if not isinstance(value, str) or not value or '\\' in value:
        _fail()
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or path == Path('.'):
        _fail()
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink() or not target.is_file():
        _fail()
    return target


def _walk_certs(value):
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key in _CERT_KEYS and isinstance(child, str) and child and '-----BEGIN' not in child:
                yield value, key, child
            elif isinstance(child, (dict, list)):
                yield from _walk_certs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_certs(child)


def _manifest(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and path != root / 'metadata.json'}


def _validate_profile(raw):
    if not isinstance(raw, dict):
        _fail()
    for key in ('proxies', 'proxy-groups'):
        values = raw.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            _fail()
    if any(not isinstance(v.get('name'), str) for v in raw.get('proxy-groups', [])):
        _fail()
    for key in ('proxy-providers', 'rule-providers'):
        values = raw.get(key, {})
        if not isinstance(values, dict) or any(not isinstance(v, dict) for v in values.values()):
            _fail()
    for provider in raw.get('proxy-providers', {}).values():
        if provider.get('type') == 'inline':
            nodes = provider.get('payload', [])
            if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
                _fail()


class ResourceResolver:
    """Resolve explicit references in deterministic, source-specific directories."""
    def __init__(self, source, directories=()):
        source = Path(source).expanduser().absolute()
        roots = [source.parent]
        verge = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        if (source.resolve().is_relative_to((verge / 'profiles').resolve())
                or source.resolve() == (verge / 'clash-verge.yaml').resolve()):
            roots.append(verge)
        roots.extend(Path(path).expanduser().absolute() for path in directories)
        self.roots = list(dict.fromkeys(roots))

    def find(self, value, *, relative_to=()):
        if not isinstance(value, str) or not value or '\\' in value or '\0' in value or '://' in value:
            raise DomainError('本地资源引用路径无效。', code='INVALID_RESOURCE_PATH', exit_code=2)
        path = Path(value).expanduser()
        candidates = [path] if path.is_absolute() else [root / path for root in (*relative_to, *self.roots)]
        for candidate in candidates:
            if candidate.is_symlink() or _unsafe_parents(candidate):
                raise DomainError('本地资源引用包含符号链接，未读取。', code='INVALID_RESOURCE_PATH', exit_code=2)
            if candidate.is_file():
                return candidate.resolve()
        return None

    def require(self, value, kind, *, relative_to=()):
        path = self.find(value, relative_to=relative_to)
        if path is None:
            raise DomainError('缺少' + kind + '文件；请检查配置引用，或使用 --resource-dir 指定资源目录。',
                              code='SOURCE_RESOURCE_MISSING', exit_code=3)
        return path


def create_source(raw, source: Path, destination: Path, *, proxy=None, metadata=None, online=False, _offline=False, geo_dirs=(), require_geo=False, resource_dirs=()):
    """Materialize dependencies once, retaining the parsed pre-sanitize configuration."""
    import domino_cli as tool
    from domino_resources import geo_requirements, prepare_geo
    destination, source = Path(destination), Path(source)
    created = False
    try:
        _validate_profile(raw)
        if destination.exists() or destination.is_symlink():
            _fail()
        if _unsafe_parents(destination):
            _fail()
        destination.mkdir(parents=True, mode=0o700)
        created = True
        profile = copy.deepcopy(raw)
        info = copy.deepcopy(metadata) if metadata is not None else origin_info(raw, source, subscription=True if online else None)
        if online:
            for kind in ('proxy-providers', 'rule-providers'):
                for provider in profile.get(kind, {}).values():
                    if provider.get('type') == 'file':
                        _fail()
                    if provider.get('type') == 'http':
                        provider.pop('path', None)
        resolver = ResourceResolver(source, resource_dirs)
        # Source/client caches are permitted only for explicit local imports.
        if _offline:
            for kind in ('proxy-providers', 'rule-providers'):
                for provider in profile.get(kind, {}).values():
                    if provider.get('type') in ('http', 'file'):
                        value = provider.get('path')
                        resolver.require(value, 'provider 缓存')
        origins = tool.provider_resources(profile, source.parent, destination, proxy, resolver=resolver, allow_download=not _offline)

        def certificates(content, relative_to=()):
            for node, key, value in _walk_certs(content):
                if online:
                    _fail()
                original = resolver.require(value, '证书/私钥', relative_to=relative_to)
                payload = original.read_bytes()
                relative = Path('certs') / (hashlib.sha256(payload).hexdigest()[:24] + '.pem')
                _write(destination / relative, payload)
                node[key] = relative.as_posix()

        certificates(profile)
        for name, provider in profile.get('proxy-providers', {}).items():
            if not provider.get('path'):
                continue
            path = _relative(destination, provider['path'])
            if provider.get('format') == 'mrs':
                _fail()
            payload = tool.load_yaml(path)
            if not isinstance(payload, dict) or not isinstance(payload.get('proxies'), list) or any(not isinstance(n, dict) for n in payload['proxies']):
                _fail()
            tool.validate_independent_nodes(payload['proxies'])
            original = origins.get(('proxy-providers', name))
            certificates(payload, (original.parent,) if original else ())
            _write(path, _canonical(payload))
        # Reuse existing Geo snapshots without downloading when available.
        for name in ('Country.mmdb', 'geoip.metadb', 'geoip.dat', 'geosite.dat', 'ASN.mmdb'):
            if not online and (source.parent / name).is_file():
                _write(destination / name, (source.parent / name).read_bytes())
        # Geo shares the same source/client roots, plus the known installed
        # public database directory. Providers and keys never borrow runtime files.
        fallback = ([] if online else resolver.roots) + [Path(path) for path in geo_dirs]
        needed = geo_requirements(profile, destination)
        for name in sorted(needed):
            if (destination / name).is_file():
                continue
            for directory in fallback:
                candidate = directory / name
                if not candidate.is_symlink() and not _unsafe_parents(candidate) and candidate.is_file():
                    _write(destination / name, candidate.read_bytes())
                    break
        if not _offline:
            prepare_geo(profile, destination, tool.download_resource, proxy)
        missing = sorted(name for name in needed if not (destination / name).is_file())
        if require_geo and missing:
            raise DomainError('捕获缺少 Geo 数据库：' + '、'.join(missing) +
                              '。请先让来源客户端完成 Geo 数据更新，或配置 Domino 的 Geo 资源源后重试；未更改当前配置。',
                              code='GEO_RESOURCE_MISSING', exit_code=3)
        _write(destination / 'config.json', _canonical(profile))
        files = _manifest(destination)
        info.update(snapshot_digest=_digest(files), files=files)
        _write(destination / 'metadata.json', _canonical(info))
        for path in [destination, *destination.rglob('*')]:
            path.chmod(0o700 if path.is_dir() else 0o600)
        read_source(destination)
        return profile
    except BaseException as error:
        if created and destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        if isinstance(error, (KeyboardInterrupt, SystemExit)) or (isinstance(error, DomainError) and error.code in {'GEO_RESOURCE_MISSING', 'SOURCE_RESOURCE_MISSING', 'INVALID_RESOURCE_PATH'}):
            raise
        _fail()


def read_source(root):
    root = Path(root)
    if not root.exists() and not root.is_symlink():
        raise FileNotFoundError(root)
    try:
        _check_tree(root)
        if (root / 'config.json').stat().st_size > 32 * 1024 * 1024 or (root / 'metadata.json').stat().st_size > 2 * 1024 * 1024:
            _fail()
        config = json.loads((root / 'config.json').read_text())
        metadata = json.loads((root / 'metadata.json').read_text())
        _validate_profile(config)
        allowed = {'version', 'capture_kind', 'origin_label', 'captured_at', 'parsed_digest', 'snapshot_digest',
                   'identity', 'files', 'original_path', 'profile_id', 'profile_name', 'association'}
        if not isinstance(metadata, dict) or set(metadata) - allowed or type(metadata.get('version')) is not int or metadata['version'] != 1 or metadata.get('capture_kind') not in _KINDS:
            _fail()
        _canonical(config)
        for key in ('origin_label', 'profile_id', 'profile_name'):
            if key in metadata and _label(metadata[key], '') != metadata[key]:
                _fail()
        if 'association' in metadata and metadata['association'] not in ('selected-profile', 'index'):
            _fail()
        if 'original_path' in metadata and (not isinstance(metadata['original_path'], str) or '\0' in metadata['original_path'] or '://' in metadata['original_path']):
            _fail()
        if not all(isinstance(metadata.get(k), str) and _DIGEST.fullmatch(metadata[k]) for k in ('parsed_digest', 'snapshot_digest', 'identity')):
            _fail()
        if (not isinstance(metadata.get('captured_at'), str) or not 1 <= len(metadata['captured_at']) <= 40
                or any(ord(c) < 32 or ord(c) == 127 for c in metadata['captured_at'])
                or not isinstance(metadata.get('origin_label'), str)):
            _fail()
        datetime.fromisoformat(metadata['captured_at'])
        files = _manifest(root)
        if not isinstance(metadata.get('files'), dict) or metadata['files'] != files or metadata['snapshot_digest'] != _digest(files):
            _fail()
        for kind in ('proxy-providers', 'rule-providers'):
            for provider in config.get(kind, {}).values():
                if provider.get('type') in ('file', 'http'):
                    _relative(root, provider.get('path'))
                elif provider.get('type') != 'inline':
                    _fail()
        for _, _, value in _walk_certs(config):
            _relative(root, value)
        import domino_cli as tool
        for provider in config.get('proxy-providers', {}).values():
            if provider.get('path'):
                payload = tool.load_yaml(_relative(root, provider['path']))
                if (not isinstance(payload, dict) or not isinstance(payload.get('proxies'), list)
                        or any(not isinstance(node, dict) for node in payload['proxies'])):
                    _fail()
                for _, _, value in _walk_certs(payload):
                    _relative(root, value)
        return config, metadata
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        _fail()


def derive_runtime(source_root: Path, data_dir: Path, selections, proxy_port, api_port):
    import domino_cli as tool
    config, metadata = read_source(source_root)
    source_root, data_dir = Path(source_root), Path(data_dir)
    if data_dir.is_symlink() or _unsafe_parents(data_dir):
        _fail()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in metadata['files']:
        if name != 'config.json':
            target = data_dir / name
            if _unsafe_parents(target):
                _fail()
            _write(target, _relative(source_root, name).read_bytes())
    candidate = copy.deepcopy(config)
    # Subscription refresh historically accepts a direct-mode upstream but keeps
    # Domino usable in rule mode; retain the original mode in the source snapshot.
    if candidate.get('mode') == 'direct':
        candidate['mode'] = 'rule'
    return tool.sanitize_profile(candidate, selections, proxy_port, api_port)


def public_info(data_dir):
    root = Path(data_dir) / 'source'
    result = {'status': 'unknown', 'snapshot_path': str(root / 'config.json')}
    try:
        _, metadata = read_source(root)
    except FileNotFoundError:
        return result
    except DomainError:
        result['status'] = 'invalid'
        return result
    result['status'] = 'known'
    projection = {'capture_kind': 'capture_kind', 'origin_label': 'label', 'captured_at': 'captured_at',
                  'parsed_digest': 'import_content_sha256', 'snapshot_digest': 'snapshot_sha256',
                  'profile_name': 'profile_name', 'association': 'association'}
    for key, public_key in projection.items():
        if key in metadata:
            value = metadata[key]
            if key in ('profile_name', 'origin_label'):
                value = _label(value, '未知来源')
            result[public_key] = value
    return result


def is_managed_snapshot(path):
    path = Path(path)
    if path.name != 'config.json' or path.parent.name != 'source':
        return False
    if (path.parent / 'metadata.json').exists() or (path.parent / 'metadata.json').is_symlink():
        return True
    parent = path.parent.parent
    if parent.name == 'data' and parent.parent.name in ('domino', 'robot-clash'):
        return True
    return (bool(re.fullmatch(r'[a-f0-9]{32}', parent.name)) and parent.parent.name == 'cache'
            and parent.parent.parent.name == 'subscriptions')
