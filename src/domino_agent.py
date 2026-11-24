# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Versioned noninteractive CLI adapter for external agents."""
from __future__ import annotations
from domino_i18n import tr as _t

import argparse
import json
import re
import subprocess
import sys
import hashlib
import shlex
from contextlib import contextmanager
from pathlib import Path
from domino_model import DomainError, Result, operation_id


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DomainError(_t('机器接口参数无效。'),code='INVALID_ARGUMENT',exit_code=2)


def command_request(args):
    command=args.command
    if command=='call': return args.operation,{}
    if command=='capabilities': return command,{}
    if command=='status': return 'status.get',{}
    if command=='scan':
        if args.source: return 'source.inspect',{'path':args.source}
        return 'source.list',{}
    if command=='nodes': return 'nodes.list',({'group':args.group} if args.group else {})
    if command=='select': return 'nodes.select',{'group':args.group,'node':args.node}
    if command in ['start','stop','restart']: return 'service.'+command,{}
    if command=='rollback': return 'service.rollback',({'backup':args.backup} if args.backup else {})
    if command=='logs':
        if args.follow: raise DomainError(_t('JSON 日志请求需为有界读取。'),code='INVALID_ARGUMENT',exit_code=2)
        return 'logs.read',{'lines':args.lines}
    if command in ['mode','log']:
        operation = 'log-level' if command == 'log' else command
        return operation+('.set' if args.set else '.get'),({'value':args.set} if args.set else {})
    if command=='configs':
        action=next((name for name in ['add','use','update','update_all','rename','remove','set_url','import_current'] if getattr(args,name,None)),None)
        if action:
            parameters={} if action=='update_all' else {'name':getattr(args,action)}
            parameters.update({key:getattr(args,key) for key in ['new_name','url'] if getattr(args,key,None) is not None})
            return 'configs.'+{'use':'switch','set_url':'set-url','import_current':'snapshot'}.get(action,action),parameters
        return 'configs.list',{}
    if command=='shell': return 'shell.'+(args.set or 'status'),{}
    if command=='proxy': return 'proxy.'+(args.set or 'status'),({'service':args.service} if args.service else {})
    if command=='connections':
        return ('connections.close',{'id':args.close}) if args.close else ('connections.clear',{}) if args.all else ('connections.list',{})
    if command=='rules':
        if args.add_rule is not None or args.remove_rule is not None: return 'rules.'+('add' if args.add_rule is not None else 'remove'),{'rule':args.add_rule if args.add_rule is not None else args.remove_rule}
        return 'rules.list',{key:getattr(args,key) for key in ['match','limit','custom'] if getattr(args,key,None) is not None}
    if command=='providers':
        return 'providers.'+('update' if args.update else 'list'),dict(kind=args.kind,**({'name':args.update} if args.update else {}))
    if command=='test':
        if not any(getattr(args,key,None) for key in ['name','config','node','group']):
            return 'delay.summary',{key:getattr(args,key) for key in ['url','timeout']}
        return 'delay.test',{key:getattr(args,key) for key in ['name','config','node','group','url','timeout'] if getattr(args,key,None) is not None}
    if command=='traffic':
        if args.watch or getattr(args,'full',False):
            raise DomainError(_t('机器请求仅支持单次流量采样，不支持 --watch 或 --full。'),code='INVALID_ARGUMENT',exit_code=2)
        return 'traffic.sample',{'interval':args.interval}
    raise DomainError(_t('该操作尚未接入机器协议。'),code='UNSUPPORTED_OPERATION',exit_code=3)


def decode_response(stdout, token):
    marker='DOMINO_RPC_'+token
    lines=stdout.splitlines()
    matches=[index for index,line in enumerate(lines) if line==marker]
    if len(matches)!=2 or matches[1]!=matches[0]+2:
        raise DomainError(_t('目标没有返回有效的机器协议结果。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
    try: result=json.loads(lines[matches[0]+1])
    except ValueError: raise DomainError(_t('目标结果无法解析。'),code='INVALID_REMOTE_RESPONSE',exit_code=5) from None
    valid=isinstance(result,dict) and result.get('schema_version')==1 and type(result.get('ok')) is bool
    valid=valid and all(key in result for key in ['operation','target','operation_id','revision','changed','effect','replayed','data','error'])
    valid=valid and isinstance(result.get('operation_id'),str) and bool(re.fullmatch('[a-f0-9]{32}',result['operation_id']))
    valid=valid and result.get('effect') in ['none','applied','rolled_back','unknown'] and type(result.get('replayed')) is bool
    valid=valid and (result.get('changed') is None or type(result.get('changed')) is bool)
    error=result.get('error') if isinstance(result,dict) else None
    valid=valid and ((result['ok'] and error is None) or (not result['ok'] and isinstance(error,dict) and
        isinstance(error.get('code'),str) and isinstance(error.get('message'),str) and type(error.get('retryable')) is bool))
    if not valid:
        raise DomainError(_t('目标结果版本或结构无效。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
    return result


@contextmanager
def uploaded_bundle(ssh,parameters):
    path=Path(parameters['bundle']).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise DomainError(_t('安装包需为权限 600 的普通文件。'),code='INVALID_BUNDLE',exit_code=2)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=parameters['bundle_sha256']:
        raise DomainError(_t('安装包摘要不一致。'),code='BUNDLE_DIGEST_MISMATCH',exit_code=2)
    marker=operation_id()
    code='import pathlib,tempfile,json;print('+repr(marker)+'+json.dumps(tempfile.mkdtemp(prefix=".domino-deploy.",dir=pathlib.Path.home())))'
    response=ssh.call('python3 -c '+shlex.quote(code),capture_output=True,text=True,timeout=30)
    lines=[line[len(marker):] for line in response.stdout.splitlines() if line.startswith(marker)]
    if len(lines)!=1: raise DomainError(_t('目标暂存响应无效。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
    stage=Path(json.loads(lines[0]))
    if not stage.is_absolute() or not re.fullmatch(r'\.domino-deploy\.[A-Za-z0-9_-]+',stage.name):
        raise DomainError(_t('目标暂存路径无效。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
    try:
        destination=str(stage/'bundle.tar.gz')
        with path.open('rb') as source:
            ssh.call('umask 077; cat > '+shlex.quote(destination),stdin=source,capture_output=True,timeout=900)
        yield destination
    finally:
        try: ssh.call('rm -rf -- '+shlex.quote(str(stage)),capture_output=True,timeout=20)
        except Exception: pass


def main(arguments, cli):
    identifier=operation_id()
    result=Result(None,operation_id=identifier)
    exit_code=1
    dispatched=False
    writing=False
    try:
        parser=Parser(add_help=False,allow_abbrev=False)
        parser.add_argument('--output',choices=['json'],default='json')
        parser.add_argument('--protocol-version',type=int,default=1)
        parser.add_argument('--non-interactive',action='store_true')
        parser.add_argument('--input')
        parser.add_argument('--if-revision')
        parser.add_argument('--request-id')
        parser.add_argument('--dry-run',action='store_true')
        options,remaining=parser.parse_known_args(arguments)
        if any(value.split('=',1)[0]=='--client' for value in remaining):
            raise DomainError(_t('机器接口参数无效。'),code='INVALID_ARGUMENT',exit_code=2)
        if options.protocol_version!=1:
            raise DomainError(_t('不支持的协议版本。'),code='UNSUPPORTED_PROTOCOL',exit_code=2)
        if any(value in remaining for value in ['-h','--help','--version']): remaining=['capabilities']
        args=cli.normalize_command(cli.build_parser(machine_mode=True).parse_args(remaining))
        args.batch=True
        args.machine_mode=True
        operation,parameters=command_request(args)
        from domino_service import OPERATIONS
        writing=OPERATIONS.get(operation,{}).get('write',False)
        result.operation=operation
        if options.input:
            if options.input=='-': raw=sys.stdin.read(1048577)
            else:
                path=Path(options.input).expanduser()
                if path.stat().st_mode & 0o077: raise DomainError(_t('输入文件权限应为 600 或更严格。'),code='INVALID_INPUT_FILE',exit_code=2)
                raw=path.read_text()
            if len(raw.encode())>1048576: raise DomainError(_t('输入内容过大。'),code='INVALID_INPUT',exit_code=2)
            try: extra=json.loads(raw)
            except ValueError: raise DomainError(_t('输入必须是 JSON 对象。'),code='INVALID_INPUT',exit_code=2) from None
            if not isinstance(extra,dict): raise DomainError(_t('输入必须是 JSON 对象。'),code='INVALID_INPUT',exit_code=2)
            parameters.update(extra)
        if options.if_revision is not None and not re.fullmatch('[a-f0-9]{64}',options.if_revision):
            raise DomainError(_t('修订标识格式无效。'),code='INVALID_ARGUMENT',exit_code=2)
        if options.request_id is not None and not 1<=len(options.request_id)<=200:
            raise DomainError(_t('请求去重键长度需为 1–200 个字符。'),code='INVALID_ARGUMENT',exit_code=2)
        target=getattr(args,'target',None)
        local=cli.is_local_target(target)
        try: result.target='localhost' if local else cli.destination(target,getattr(args,'user',None))
        except cli.ToolError:
            raise DomainError(_t('目标地址或用户格式无效。'),code='INVALID_ARGUMENT',exit_code=2) from None
        if local and any(getattr(args,name,None) for name in ['user','ssh_port','identity']):
            raise DomainError(_t('本机请求不能附加 SSH 认证选项。'),code='INVALID_ARGUMENT',exit_code=2)
        from domino_service import validate
        if operation not in OPERATIONS: raise DomainError(_t('未支持的操作。'),code='UNSUPPORTED_OPERATION',exit_code=3)
        validate(parameters,OPERATIONS[operation]['parameters'])
        token=operation_id()
        request={'schema_version':1,'operation':operation,'arguments':parameters,'operation_id':identifier,
                 'target':result.target,'transport_token':token,'non_interactive':True}
        request['client']='domino'
        request.update({key:getattr(options,key) for key in ['if_revision','request_id','dry_run'] if getattr(options,key) is not None})
        payload=json.dumps(request,ensure_ascii=False,allow_nan=False)
        deadline=900 if writing or operation in ['delay.test','delay.summary'] else 90
        if local:
            dispatched=True
            process=subprocess.run([sys.executable,str(cli.REMOTE_SCRIPT),'agent'],input=payload,capture_output=True,text=True,timeout=deadline)
        else:
            try:
                with cli.SSH(args) as ssh:
                    if operation=='deployment.apply':
                        with uploaded_bundle(ssh,parameters) as destination:
                            request['arguments']=dict(parameters,bundle=destination)
                            payload=json.dumps(request,ensure_ascii=False,allow_nan=False)
                            dispatched=True
                            process=subprocess.run(ssh.action_argv('agent'),input=payload,capture_output=True,text=True,timeout=deadline)
                    else:
                        dispatched=True
                        process=subprocess.run(ssh.action_argv('agent'),input=payload,capture_output=True,text=True,timeout=deadline)
            except cli.ToolError:
                raise DomainError(_t('SSH 连接未建立，请检查网络和认证配置。'),code='SSH_UNAVAILABLE',exit_code=5) from None
        document=decode_response(process.stdout,token)
        valid_id=document.get('operation_id')==identifier or (options.request_id is not None and (document.get('replayed') or document.get('effect')=='unknown'))
        if not valid_id or document.get('operation')!=operation or document.get('target')!=result.target or document.get('client')!='domino':
            raise DomainError(_t('目标结果与请求不一致。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
        exit_code=process.returncode
        if (document['ok'] and exit_code!=0) or (not document['ok'] and exit_code==0):
            raise DomainError(_t('目标退出码与结果不一致。'),code='INVALID_REMOTE_RESPONSE',exit_code=5)
        print(json.dumps(document,ensure_ascii=False,indent=2))
        return exit_code
    except DomainError as error: result.error=error
    except subprocess.TimeoutExpired: result.error=DomainError(_t('请求超时。'),code='TIMEOUT',exit_code=7,retryable=True)
    except (OSError,ValueError): result.error=DomainError(_t('无法读取输入或执行目标请求。'),code='INVALID_INPUT',exit_code=2)
    except KeyboardInterrupt: result.error=DomainError(_t('请求已中断。'),code='CANCELLED',exit_code=7)
    except Exception: result.error=DomainError(_t('机器接口发生内部错误。'),code='INTERNAL_ERROR',exit_code=1)
    if dispatched and writing and not options.dry_run:
        result.error.effect='unknown'
        result.effect,result.changed='unknown',None
    print(json.dumps(result.document(),ensure_ascii=False,indent=2))
    return result.exit_code
