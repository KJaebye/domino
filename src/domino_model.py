# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Shared results and errors for application services and process adapters."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional
import uuid

PROTOCOL_VERSION = 1
RESULT_SCHEMA = {'type':'object','required':['schema_version','ok','operation','target','client','operation_id','revision','changed','effect','replayed','data','error'],
    'properties':{'schema_version':{'const':1},'ok':{'type':'boolean'},'operation':{'type':['string','null']},
        'target':{'type':'string'},'client':{'type':'string'},'operation_id':{'type':['string','null'],'pattern':'[a-f0-9]{32}'},
        'revision':{'type':['string','null'],'pattern':'[a-f0-9]{64}'},'changed':{'type':['boolean','null']},
        'effect':{'enum':['none','applied','rolled_back','unknown']},'replayed':{'type':'boolean'},'data':{},
        'error':{'oneOf':[{'type':'null'},{'type':'object','required':['code','message','retryable'],
            'properties':{'code':{'type':'string'},'message':{'type':'string'},'retryable':{'type':'boolean'},'details':{}}}]}},'additionalProperties':True}


class ExitCode(IntEnum):
    OK = 0
    INTERNAL = 1
    ARGUMENT = 2
    PRECONDITION = 3
    AUTH = 4
    UNREACHABLE = 5
    CONFLICT = 6
    TIMEOUT = 7
    APPLY = 8
    PARTIAL = 9


class DomainError(RuntimeError):
    def __init__(self, message, *, code='OPERATION_FAILED', exit_code=ExitCode.APPLY,
                 retryable=False, effect='none', details=None):
        super().__init__(message)
        self.code = code
        self.exit_code = int(exit_code)
        self.retryable = bool(retryable)
        self.effect = effect
        self.details = details

    def document(self):
        result = {'code':self.code, 'message':str(self), 'retryable':self.retryable}
        if self.details is not None:
            result['details'] = self.details
        return result


@dataclass
class Result:
    operation: Optional[str]
    target: str = 'localhost'
    data: Any = None
    operation_id: Optional[str] = None
    revision: Optional[str] = None
    changed: Optional[bool] = False
    effect: str = 'none'
    error: Optional[DomainError] = None
    replayed: bool = False
    client: str = 'domino'

    def document(self):
        return {'schema_version':PROTOCOL_VERSION, 'ok':self.error is None,
                'operation':self.operation, 'target':self.target,
                'operation_id':self.operation_id, 'revision':self.revision,
                'changed':self.changed, 'effect':self.effect, 'replayed':self.replayed, 'data':self.data,
                'error':self.error.document() if self.error else None,'client':self.client}

    @property
    def exit_code(self):
        return self.error.exit_code if self.error else int(ExitCode.OK)

    @classmethod
    def restore(cls, document, exit_code=0):
        error=document.get('error')
        domain=DomainError(error['message'],code=error['code'],exit_code=exit_code,
            retryable=error['retryable'],effect=document['effect'],details=error.get('details')) if error else None
        return cls(document['operation'],document['target'],document.get('data'),document['operation_id'],
                   document.get('revision'),document.get('changed'),document['effect'],domain,document.get('replayed',False),document.get('client','domino'))


def operation_id():
    return uuid.uuid4().hex
