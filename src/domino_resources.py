# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Configurable HTTPS resource origin with required content hashes."""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from domino_model import DomainError


def resource_base():
    path=Path.home()/'.config/domino/downloads.json'
    configured=os.environ.get('DOMINO_RESOURCE_BASE')
    if configured is None and path.is_file():
        try: configured=json.loads(path.read_text()).get('resource_base')
        except (ValueError,AttributeError): raise DomainError('资源下载配置格式无效。',code='INVALID_RESOURCE_SOURCE',exit_code=2) from None
    if not configured: return None
    if not isinstance(configured,str):
        raise DomainError('资源源必须是 HTTPS 目录地址。',code='INVALID_RESOURCE_SOURCE',exit_code=2)
    try: parsed=urlsplit(configured)
    except ValueError: parsed=None
    if not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or '..' in parsed.path.split('/'):
        raise DomainError('资源源必须是无凭据的 HTTPS 目录地址。',code='INVALID_RESOURCE_SOURCE',exit_code=2)
    return configured.rstrip('/')+'/'


def release_url(version,official):
    base=resource_base()
    if base: return base+'mihomo/'+('latest' if version=='latest' else version)+'.json'
    return official if version=='latest' else official.rsplit('/',1)[0]+'/tags/'+version


def asset_allowed(url,tag):
    base=resource_base()
    prefix=base+'mihomo/' if base else 'https://github.com/MetaCubeX/mihomo/releases/download/'+tag+'/'
    parsed=urlsplit(url)
    return url.startswith(prefix) and not (parsed.username or parsed.password or parsed.fragment or parsed.query) and '..' not in parsed.path.split('/')


def geo_requirements(profile, data):
    """Geo dependencies referenced by rules, including logical and provider rules."""
    rules = []
    def add(values):
        if isinstance(values, list):
            rules.extend(value for value in values if isinstance(value, str))
    add(profile.get('rules', []))
    for values in profile.get('sub-rules', {}).values():
        add(values)
    for provider in profile.get('rule-providers', {}).values():
        add(provider.get('payload', []))
        relative = provider.get('path')
        if not relative or provider.get('format') == 'mrs':
            continue
        path = data / relative
        if path.is_file() and path.stat().st_size < 8388608:
            if provider.get('format') == 'text':
                rules.extend(path.read_text().splitlines())
            else:
                from domino_cli import load_yaml
                payload = load_yaml(path)
                if isinstance(payload, dict):
                    add(payload.get('payload', []))
    needed = set()
    for rule in rules:
        text = rule.upper()
        if re.search(r'(?:^|\()\s*(?:SRC-)?GEOIP\s*,', text):
            needed.add('geoip.dat' if profile.get('geodata-mode') else 'Country.mmdb')
        if re.search(r'(?:^|\()\s*GEOSITE\s*,', text):
            needed.add('geosite.dat')
        if re.search(r'(?:^|\()\s*(?:SRC-)?IP-ASN\s*,', text):
            needed.add('ASN.mmdb')
    return needed


def prepare_geo(profile,data,download,proxy=None):
    base=resource_base()
    if not base: return
    needed=geo_requirements(profile, data)
    files={'geoip':'geoip.dat','mmdb':'Country.mmdb','geosite':'geosite.dat','asn':'ASN.mmdb'}
    profile['geox-url']={key:base+'geo/'+name for key,name in files.items()}
    if not needed: return
    index=data/'.geo-index.json'
    try:
        download('Geo 资源索引',base+'geo/index.json',index,proxy)
        metadata=json.loads(index.read_text())
    finally: index.unlink(missing_ok=True)
    if not isinstance(metadata,dict) or metadata.get('schema_version')!=1 or not isinstance(metadata.get('files'),dict):
        raise DomainError('Geo 资源索引格式无效。',code='INVALID_RESOURCE_INDEX',exit_code=3)
    for name in sorted(needed):
        entry=metadata['files'].get(name,{})
        digest=entry.get('sha256') if isinstance(entry,dict) else None
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise DomainError('Geo 资源缺少 SHA-256。',code='RESOURCE_DIGEST_REQUIRED',exit_code=3)
        target=data/name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==digest: continue
        download('Geo 资源',base+'geo/'+name,target,proxy)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            target.unlink(missing_ok=True)
            raise DomainError('Geo 资源 SHA-256 校验失败。',code='RESOURCE_DIGEST_MISMATCH',exit_code=3)
        target.chmod(0o600)
