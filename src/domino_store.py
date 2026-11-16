# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Private operation journal and request deduplication; no raw inputs are retained."""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from domino_model import DomainError, Result


class OperationStore:
    def __init__(self, context):
        self.ctx=context
        self.root=context.HOME/'.local/state/domino/operations'
        for path in [self.root,context.HOME/'.local',context.HOME/'.local/state',self.root.parent,self.root/'requests']:
            if path.is_symlink(): raise DomainError('操作记录路径不安全。',code='UNSAFE_STORAGE',exit_code=3)

    def path(self, identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
            raise DomainError('操作 ID 无效。',code='INVALID_ARGUMENT',exit_code=2)
        path=self.root/(identifier+'.json')
        if path.is_symlink(): raise DomainError('操作记录不能是符号链接。',code='UNSAFE_STORAGE',exit_code=3)
        return path

    def load(self, identifier):
        path=self.path(identifier)
        if not path.is_file(): raise DomainError('未找到操作记录。',code='OPERATION_NOT_FOUND',exit_code=3)
        try:
            value=json.loads(path.read_text())
            if value['schema_version']!=1 or value['operation_id']!=identifier: raise ValueError()
            return value
        except (ValueError,KeyError,TypeError):
            raise DomainError('操作记录格式无效。',code='INVALID_OPERATION_RECORD',exit_code=1) from None

    def save(self, record):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.root.chmod(0o700)
        self.persist(self.path(record['operation_id']),json.dumps(record,ensure_ascii=False))

    def persist(self,path,content):
        self.ctx.write_private(path,content)
        with path.open('rb') as handle: os.fsync(handle.fileno())
        descriptor=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

    def lookup(self, key, fingerprint):
        if not isinstance(key,str) or not 1<=len(key)<=200:
            raise DomainError('请求去重键长度需为 1–200 个字符。',code='INVALID_ARGUMENT',exit_code=2)
        path=self.root/'requests'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if path.is_symlink(): raise DomainError('请求记录路径不安全。',code='UNSAFE_STORAGE',exit_code=3)
        if not path.is_file(): return None
        record=self.load(json.loads(path.read_text())['operation_id'])
        if record['fingerprint']!=fingerprint:
            raise DomainError('该请求去重键已用于不同的操作参数。',code='REQUEST_CONFLICT',exit_code=6)
        if record['state']!='complete':
            raise DomainError('该操作尚无已确认结果，请按操作 ID 查询后再处理。',code='OPERATION_UNCERTAIN',exit_code=6,
                effect='unknown',details={'operation_id':record['operation_id']})
        result=Result.restore(record['result'],record['exit_code'])
        result.replayed=True
        return result

    def find(self,key):
        if not isinstance(key,str) or not 1<=len(key)<=200:
            raise DomainError('请求去重键无效。',code='INVALID_ARGUMENT',exit_code=2)
        path=self.root/'requests'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if path.is_symlink(): raise DomainError('请求记录路径不安全。',code='UNSAFE_STORAGE',exit_code=3)
        if not path.is_file(): raise DomainError('未找到操作记录。',code='OPERATION_NOT_FOUND',exit_code=3)
        return self.load(json.loads(path.read_text())['operation_id'])

    def begin(self, request, fingerprint, revision):
        path=self.path(request['operation_id'])
        if path.exists(): raise DomainError('操作 ID 已存在。',code='OPERATION_CONFLICT',exit_code=6)
        record={'schema_version':1,'operation_id':request['operation_id'],'operation':request['operation'],
            'target':request.get('target','localhost'),'fingerprint':fingerprint,'before_revision':revision,
            'state':'applying','created_at':datetime.now(timezone.utc).isoformat(),'result':None}
        self.save(record)
        directory=self.root/'requests'
        directory.mkdir(mode=0o700,exist_ok=True)
        directory.chmod(0o700)
        key=request.get('request_id') or request['operation_id']
        self.persist(directory/(hashlib.sha256(key.encode()).hexdigest()+'.json'),
            json.dumps({'operation_id':record['operation_id']}))
        return record

    def finish(self, record, result):
        record=dict(record,state='complete',finished_at=datetime.now(timezone.utc).isoformat(),
                    result=result.document(),exit_code=result.exit_code)
        self.save(record)

    def listing(self, limit=20):
        if not self.root.exists(): return {'operations':[]}
        values=[]
        for path in sorted(self.root.glob('*.json'),key=lambda item:item.stat().st_mtime,reverse=True)[:limit]:
            record=self.load(path.stem)
            values.append({key:record.get(key) for key in ['operation_id','operation','target','state','created_at','finished_at']})
        return {'operations':values}
