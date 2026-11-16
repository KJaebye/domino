# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Bounded owned-service logs with URL and known credential redaction."""
import json
import platform
import re
import subprocess
from urllib.parse import parse_qs,urlsplit
from domino_model import DomainError


def redactor(ctx):
    secrets=set()
    def collect(value,key=''):
        if isinstance(value,dict):
            for name,item in value.items(): collect(item,str(name).lower())
        elif isinstance(value,list):
            for item in value: collect(item,key)
        elif isinstance(value,str):
            if key in ['secret','password','uuid','private-key','token','authorization'] and len(value)>=4: secrets.add(value)
            if key in ['url','subscription']:
                secrets.add(value)
                try:
                    for items in parse_qs(urlsplit(value).query).values():
                        secrets.update(item for item in items if len(item)>=4)
                except ValueError: pass
    app,_=ctx.current_installation()
    for path in [app/'data/config.json',ctx.HOME/'.config/domino/subscriptions/index.json']:
        if path.is_file(): collect(json.loads(path.read_text()))
    def redact(message):
        for secret in sorted(secrets,key=len,reverse=True): message=message.replace(secret,'[redacted]')
        message=re.sub(r'(?i)\b(?:https?|ss|ssr|vmess|vless|trojan|hysteria2?)://[^\s"<>]+','[redacted-url]',message)
        message=re.sub(r'(?i)((?:password|secret|token|authorization|uuid)["\s]*[:=]["\s]*)[^\s",;]+',r'\1[redacted]',message)
        return ''.join(char for char in message if char.isprintable() or char=='\t')[:4096]
    return redact


def read_logs(ctx,limit=100):
    redact=redactor(ctx)
    truncated=False
    if platform.system().lower()=='darwin':
        path=ctx.HOME/'Library/Logs/domino/mihomo.log'
        if not path.exists(): return {'lines':[],'limit':limit,'truncated':False}
        with path.open('rb') as handle:
            size=path.stat().st_size
            offset=max(0,size-1048576)
            handle.seek(offset)
            raw=handle.read(1048576).decode(errors='replace')
            if offset: raw=raw.partition('\n')[2]; truncated=True
        lines=[{'message':redact(line)} for line in raw.splitlines()[-limit:]]
    else:
        _,service=ctx.current_installation()
        process=subprocess.run(['journalctl','-u',service.name,'-n',str(limit),'--no-pager','--output=json'],capture_output=True,text=True,timeout=15)
        if process.returncode:
            raise DomainError('无法读取服务日志，请检查当前用户的日志权限。',code='LOG_ACCESS_DENIED',exit_code=4)
        raw=process.stdout[-1048576:]
        if len(process.stdout)>1048576: raw=raw.partition('\n')[2]; truncated=True
        lines=[]
        for line in raw.splitlines()[-limit:]:
            entry=json.loads(line)
            message=entry.get('MESSAGE','')
            if not isinstance(message,str): message='[non-text log message]'
            lines.append({'message':redact(message),'timestamp_us':entry.get('__REALTIME_TIMESTAMP')})
    return {'lines':lines,'limit':limit,'truncated':truncated}
