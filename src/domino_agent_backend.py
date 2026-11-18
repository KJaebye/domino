# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Private process transport; protocol data never shares stdout with diagnostics."""
from domino_i18n import tr as _t
from contextlib import redirect_stdout
import json
import re
import sys
from domino_model import DomainError, Result
from domino_service import Application


def run(context):
    token='ERROR'
    result=Result(None)
    try:
        raw=sys.stdin.read(1048577)
        if len(raw.encode())>1048576: raise ValueError()
        request=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
        if not isinstance(request,dict): raise ValueError()
        token=request.get('transport_token','')
        if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token): raise ValueError()
        if not isinstance(request.get('operation'),str) or not isinstance(request.get('arguments',{}),dict): raise ValueError()
        if not isinstance(request.get('operation_id'),str) or not re.fullmatch('[a-f0-9]{32}',request['operation_id']): raise ValueError()
        result=Result(request['operation'],request.get('target','localhost'),operation_id=request['operation_id'])
        with redirect_stdout(sys.stderr):
            result=Application(context).execute(request)
    except (ValueError,TypeError):
        result.error=DomainError(_t('机器请求格式无效。'),code='INVALID_REQUEST',exit_code=2)
    except DomainError as error:
        result.error=error
        result.effect=error.effect
    except KeyboardInterrupt:
        result.error=DomainError(_t('请求已中断。'),code='CANCELLED',exit_code=7)
    except Exception:
        result.error=DomainError(_t('目标执行出现内部错误。'),code='INTERNAL_ERROR',exit_code=1)
    marker='DOMINO_RPC_'+token
    print(marker)
    print(json.dumps(result.document(),ensure_ascii=False,allow_nan=False))
    print(marker)
    return result.exit_code
