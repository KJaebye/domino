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


def prepare_geo(profile,data,download,proxy=None):
    base=resource_base()
    if not base: return
    text=json.dumps(profile,ensure_ascii=False).upper()
    providers=data/'providers'
    if providers.is_dir():
        text+=' '.join(path.read_text(errors='ignore').upper() for path in providers.rglob('*') if path.is_file() and path.stat().st_size<8388608)
    needed=set()
    if 'GEOIP' in text: needed.add('geoip.dat' if profile.get('geodata-mode') else 'Country.mmdb')
    if 'GEOSITE' in text: needed.add('geosite.dat')
    if 'IP-ASN' in text or 'SRC-IP-ASN' in text: needed.add('ASN.mmdb')
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
