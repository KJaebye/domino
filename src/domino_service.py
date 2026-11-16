# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Application services: structured domain data, without terminal rendering."""
from __future__ import annotations

import hashlib
import json
import platform
import math
import re
import tempfile
import os
from pathlib import Path
from types import SimpleNamespace
from domino_model import DomainError, Result, RESULT_SCHEMA, operation_id


def obj(properties=None, required=(), extra=False):
    return {'type':'object','properties':properties or {},'required':list(required),'additionalProperties':extra}


STRING={'type':'string','minLength':1}
BOOLEAN={'type':'boolean'}
OBJECT=obj(extra=True)
ARRAY={'type':'array','items':OBJECT}


def spec(description, parameters=None, result=None, *, installed=True, platforms=None, write=False):
    return {'description':description,'write':write,'parameters':parameters or obj(),
            'result':result or OBJECT,'requires_installation':installed,
            'platforms':platforms or ['darwin','linux']}


OPERATIONS={
    'capabilities':spec('Discover protocol, operations, schemas and platform capabilities',installed=False),
    'status.get':spec('Read service state and proxy health',obj({'check_exit':BOOLEAN}),installed=False),
    'source.inspect':spec('Inspect a transferable source configuration',obj({'path':STRING}),installed=False),
    'source.list':spec('List runtime, external saved and Domino-managed configurations; probe runtime endpoints only',installed=False),
    'nodes.list':spec('List proxy groups and nodes',obj({'group':STRING})),
    'configs.list':spec('List saved configurations with stable IDs',installed=False),
    'mode.get':spec('Read proxy mode'),
    'log-level.get':spec('Read log level'),
    'connections.list':spec('List credential-free connection details'),
    'traffic.sample':spec('Take one bounded traffic sample',obj({'interval':{'type':'number','minimum':.2,'maximum':60}})),
    'rules.list':spec('Read active or custom rules',obj({'match':STRING,'limit':{'type':'integer','minimum':1,'maximum':100000},'custom':BOOLEAN})),
    'providers.list':spec('List proxy or rule providers',obj({'kind':{'type':'string','enum':['proxy','rule']}}),{'type':'array','items':OBJECT}),
    'proxy.status':spec('Read system proxy settings or report an unavailable desktop session',obj({'service':STRING}),installed=False),
    'delay.summary':spec('Summarize HTTPS node reachability for all saved configurations', obj({'url':STRING,'timeout':{'type':'integer','minimum':100,'maximum':60000}}), installed=False),
    'delay.test':spec('Measure configuration, node or group HTTPS delay',obj({'config':STRING,'name':STRING,'node':STRING,'group':STRING,
        'url':STRING,'timeout':{'type':'integer','minimum':100,'maximum':60000}}),{'type':'array','items':OBJECT}),
}

ID={'type':'string','pattern':'[a-f0-9]{32}'}
SELECTOR={'name':STRING,'id':ID}
def subscription_parameters(extra=None, required=()):
    schema=obj(dict(SELECTOR,**(extra or {})),required)
    schema['oneOf']=[{'required':['name']},{'required':['id']}]
    return schema


OPERATIONS.update({
    'logs.read':spec('Read a bounded set of redacted owned-service log messages',obj({'lines':{'type':'integer','minimum':1,'maximum':1000}})),
    'service.rollback':spec('Restore a previous owned deployment with a safety backup',obj({'backup':{'type':'string','pattern':'[A-Za-z0-9_.-]+'}}),installed=False,write=True),
    'bundle.export':spec('Build a private independent deployment archive',obj({'output':STRING,
        'arch':{'type':'string','enum':['arm64','amd64']},'system':{'type':'string','enum':['linux','darwin']},
        'source':STRING,'subscription':STRING,'local_proxy':STRING,
        'mihomo_version':{'type':'string','pattern':'latest|v[0-9]+\\.[0-9]+\\.[0-9]+'},
        'proxy_port':{'type':'integer','minimum':1024,'maximum':65535},'api_port':{'type':'integer','minimum':1024,'maximum':65535}},['output','arch']),installed=False,write=True),
    'deployment.apply':spec('Upload a caller-local private archive and install it independently',obj({'bundle':STRING,'bundle_sha256':{'type':'string','pattern':'[a-f0-9]{64}'}},['bundle','bundle_sha256']),installed=False,write=True),
    'service.install':spec('Install a private exported bundle on the selected target',obj({'bundle':STRING,'bundle_sha256':{'type':'string','pattern':'[a-f0-9]{64}'}},['bundle','bundle_sha256']),installed=False,write=True),
    'operations.get':spec('Read a durable operation record by operation ID or request key',dict(obj({'id':ID,'request_id':dict(STRING,maxLength=200)}),oneOf=[{'required':['id']},{'required':['request_id']}]),installed=False),
    'operations.list':spec('List recent durable operations',obj({'limit':{'type':'integer','minimum':1,'maximum':100}}),installed=False),
    'configs.add':spec('Save a subscription without activating it',obj({'name':STRING,'url':STRING},['name','url']),installed=False,write=True),
    'configs.switch':spec('Activate a saved configuration locally',subscription_parameters(),write=True),
    'configs.update':spec('Update one subscription',subscription_parameters(),write=True),
    'configs.update_all':spec('Update online subscriptions with per-item outcomes',write=True),
    'configs.rename':spec('Rename while retaining the stable ID',subscription_parameters({'new_name':STRING},['new_name']),installed=False,write=True),
    'configs.remove':spec('Remove an inactive configuration',subscription_parameters(),installed=False,write=True),
    'configs.set-url':spec('Replace the private subscription URL',subscription_parameters({'url':STRING},['url']),installed=False,write=True),
    'rules.add':spec('Validate and prepend a custom rule',obj({'rule':dict(STRING,maxLength=8192)},['rule']),write=True),
    'rules.remove':spec('Remove a custom rule',obj({'rule':dict(STRING,maxLength=8192)},['rule']),write=True),
    'nodes.select':spec('Select a member of a manual group',obj({'group':STRING,'node':STRING},['group','node']),write=True),
    'mode.set':spec('Persist proxy mode',obj({'value':{'type':'string','enum':['rule','global','direct']}},['value']),write=True),
    'log-level.set':spec('Persist log level',obj({'value':{'type':'string','enum':['debug','info','warning','error','silent']}},['value']),write=True),
    'shell.status':spec('Read terminal proxy policy (not parent-shell environment)',installed=False),
    'shell.on':spec('Enable terminal proxy policy',write=True),
    'shell.off':spec('Disable terminal proxy policy',write=True),
    'proxy.on':spec('Enable the supported desktop system proxy with a backup',obj({'service':STRING}),write=True),
    'proxy.off':spec('Restore the preceding desktop system proxy',obj({'service':STRING}),write=True),
    'service.start':spec('Start the owned service and connect the available desktop system proxy without prompting',write=True),
    'service.stop':spec('Restore the desktop system proxy, then stop the owned service without prompting',write=True),
    'service.restart':spec('Restart the owned service and connect the available desktop system proxy without prompting',write=True),
    'connections.close':spec('Close a connection by ID',obj({'id':STRING},['id']),write=True),
    'connections.clear':spec('Close all current connections',write=True),
    'providers.update':spec('Refresh one HTTP or file provider',obj({'kind':{'type':'string','enum':['proxy','rule']},'name':STRING},['name']),write=True),
})

# Schemas describe domain payloads; the common result envelope is published once.
NULL_STRING={'type':['string','null']}
INTEGER={'type':'integer'}
NUMBER={'type':'number'}
STRINGS={'type':'array','items':{'type':'string'}}
SUBSCRIPTION=obj({'id':ID,'name':STRING,'kind':STRING,'updated_at':NULL_STRING,
    'node_count':{'type':['integer','null']},'group_count':{'type':['integer','null']},
    'active':BOOLEAN,'cached':BOOLEAN,'host':NULL_STRING},['id','name','kind','active','cached'],extra=True)
CONFIGS=obj({'active':NULL_STRING,'active_id':dict(ID,type=['string','null']),
    'current_source':STRING,'configs':{'type':'array','items':SUBSCRIPTION}},['active','active_id','configs'],extra=True)
STATUS=obj({**{key:BOOLEAN for key in ['installed','active','enabled','healthy','awaiting_subscription','requires_source_online','controller_reachable','exit_checked']},
    **{key:NULL_STRING for key in ['service','version','arch','subscription','mode','exit_country','deployment_method','autostart_scope']},
    'proxy_port':INTEGER,'system_proxy':OBJECT},['installed','active','enabled','healthy'],extra=True)
NODES=obj({'mode':STRING,'groups':{'type':'array','items':obj({'name':STRING,'type':STRING,'current':NULL_STRING,'choices':STRINGS,'selectable':BOOLEAN},extra=True)},
    'nodes':{'type':'array','items':obj({'name':STRING,'type':STRING},['name','type'])}},extra=True)
PROVIDERS={'type':'array','items':obj({'name':STRING,'type':NULL_STRING,'vehicleType':NULL_STRING,
    'updatedAt':NULL_STRING,'count':{'type':['integer','null']}},['name','vehicleType'],extra=True)}
IMPORT_SOURCE=obj({'status':{'type':'string','enum':['known','unknown','invalid']},
    **{key:STRING for key in ['snapshot_path','capture_kind','label','captured_at','profile_name','association',
                             'import_content_sha256','snapshot_sha256']}},['status'])
PROFILE_SOURCE={'source_kind':{'type':'string','enum':['profile','import-snapshot']},'profile_id':STRING,'profile_name':STRING,
    'client_current':{'type':['boolean','null']},'check_note':STRING,
    'import_source':IMPORT_SOURCE,'current_config':STRING}
SCAN_CONFIGS=obj({'active':NULL_STRING,'current_source':STRING,'error':STRING,
    'configs':{'type':'array','items':obj({key:value for key,value in SUBSCRIPTION['properties'].items() if key!='id'},
        ['name','kind','active','cached'],extra=True)}},['configs'],extra=True)
RESULT_SCHEMAS={
    'bundle.export':obj({'output':STRING,'bundle_sha256':{'type':'string','pattern':'[a-f0-9]{64}'},'version':STRING,'arch':STRING,'system':STRING},['output','bundle_sha256','version','arch','system']),
    'deployment.apply':STATUS,
    'logs.read':obj({'lines':{'type':'array','items':obj({'message':{'type':'string'},'timestamp_us':NULL_STRING},['message'])},'limit':INTEGER,'truncated':BOOLEAN},['lines','limit','truncated']),
    'status.get':STATUS,'nodes.list':NODES,'configs.list':CONFIGS,
    'source.inspect':obj({'source':STRING,'config':NULL_STRING,'compatible_config_found':BOOLEAN,'healthy':BOOLEAN,'proxy':NULL_STRING,
        'exit_checked':BOOLEAN,**PROFILE_SOURCE},extra=True),
    'source.list':obj({'sources':{'type':'array','items':obj({'name':STRING,'source':STRING,'config':STRING,
        'compatible_config_found':BOOLEAN,'proxy':NULL_STRING,'default':BOOLEAN,'config_error':STRING,
        'healthy':BOOLEAN,'exit_checked':BOOLEAN,'check_error':STRING,
        'check_code':STRING,'check_stage':STRING,'check_hint':STRING,'check_details':OBJECT,**PROFILE_SOURCE},
        ['name','source','config','compatible_config_found','proxy','default','healthy','exit_checked'])},
        'managed_configs':SCAN_CONFIGS,'warnings':STRINGS},['sources']),
    'rules.list':obj({'total':INTEGER,'source':STRING,'rules':{'type':'array','items':{'oneOf':[{'type':'string'},OBJECT]}}},['total','rules']),
    'providers.list':PROVIDERS,'providers.update':PROVIDERS,
    'delay.summary':{'type':'array','items':obj({'name':STRING,'active':BOOLEAN,'total':{'type':['integer','null']},'available':{'type':['integer','null']},'unavailable':{'type':['integer','null']},'status':{'type':'string','enum':['tested','uncached','error']},'message':STRING,'error_code':STRING},['name','active','total','available','unavailable','status'])},
    'delay.test':{'type':'array','items':obj({'name':STRING,'delay_ms':{'type':['number','null']},'ok':BOOLEAN},['name','delay_ms','ok'])},
    'traffic.sample':obj({**{key:NUMBER for key in ['upload_bytes_per_second','download_bytes_per_second','upload_total','download_total','connections']},'memory':{'type':['number','null']}},extra=True),
    'connections.list':obj({'uploadTotal':{'type':['number','null']},'downloadTotal':{'type':['number','null']},'connections':{'type':'array','items':obj({'id':NULL_STRING,'host':NULL_STRING,'port':{'type':['string','integer','null']},'network':NULL_STRING,'process':NULL_STRING,'rule':NULL_STRING,'chains':STRINGS,'upload':NUMBER,'download':NUMBER},extra=True)}},extra=True),
    'nodes.select':obj({'group':STRING,'node':STRING,'changed':BOOLEAN},['group','node','changed']),
    'shell.status':obj({'enabled':BOOLEAN,'policy_only':BOOLEAN,'current_shell_applied':BOOLEAN},['enabled','policy_only','current_shell_applied'],extra=True),
    'proxy.status':obj({'service':STRING,'proxies':OBJECT,'restore_available':BOOLEAN},extra=True),
    'connections.close':obj({'closed':STRING},extra=True),'connections.clear':obj({'closed':STRING},extra=True),
    'operations.get':obj({'schema_version':INTEGER,'operation_id':ID,'operation':STRING,'target':STRING,
        'state':{'type':'string','enum':['applying','complete']},'created_at':STRING,'result':{'type':['object','null']}},extra=True),
    'operations.list':obj({'operations':{'type':'array','items':obj({'operation_id':ID,'operation':STRING,'target':STRING,'state':STRING,'created_at':STRING},extra=True)}},['operations']),
    'configs.update_all':obj({'results':{'type':'array','items':obj({'id':ID,'name':STRING,'ok':BOOLEAN,'effect':STRING,'error':OBJECT},extra=True)}},['results']),
}
for name in OPERATIONS:
    if name.startswith('configs.') and name!='configs.update_all': RESULT_SCHEMAS[name]=CONFIGS
    if name.startswith('mode.'): RESULT_SCHEMAS[name]=obj({'mode':STRING,'persisted':BOOLEAN},['mode'],extra=True)
    if name.startswith('log-level.'): RESULT_SCHEMAS[name]=obj({'log-level':STRING,'persisted':BOOLEAN},['log-level'],extra=True)
    if name.startswith('rules.') and name!='rules.list': RESULT_SCHEMAS[name]=obj({'changed':BOOLEAN,'rule':STRING,'action':STRING,'backup':STRING,'mode':STRING,'message':STRING},['changed','rule'],extra=True)
    if name.startswith('service.'): RESULT_SCHEMAS[name]=STATUS
    if name in ['shell.on','shell.off']: RESULT_SCHEMAS[name]=RESULT_SCHEMAS['shell.status']
    if name in ['proxy.on','proxy.off']: RESULT_SCHEMAS[name]=RESULT_SCHEMAS['proxy.status']
    if name in RESULT_SCHEMAS: OPERATIONS[name]['result']=RESULT_SCHEMAS[name]


def validate(value, schema, field='arguments'):
    if 'oneOf' in schema:
        matches=0
        for branch in schema['oneOf']:
            try: validate(value,branch,field); matches+=1
            except DomainError: pass
        if matches!=1: raise DomainError('需要唯一的资源选择条件。',code='INVALID_ARGUMENT',exit_code=2)
    kind=schema.get('type')
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
           'boolean':type(value) is bool,'integer':type(value) is int,'number':type(value) in (int,float)}
    if kind and not valid.get(kind,False):
        raise DomainError('参数类型不符合接口定义。',code='INVALID_ARGUMENT',exit_code=2,details={'field':field})
    if 'enum' in schema and value not in schema['enum']:
        raise DomainError('参数取值不符合接口定义。',code='INVALID_ARGUMENT',exit_code=2,details={'field':field})
    if kind in ['integer','number'] and (not math.isfinite(value) or value < schema.get('minimum',value) or value > schema.get('maximum',value)):
        raise DomainError('参数超出允许范围。',code='INVALID_ARGUMENT',exit_code=2,details={'field':field})
    if kind=='string' and len(value)<schema.get('minLength',0):
        raise DomainError('参数不能为空。',code='INVALID_ARGUMENT',exit_code=2,details={'field':field})
    if kind=='string' and (len(value)>schema.get('maxLength',len(value)) or ('pattern' in schema and not re.fullmatch(schema['pattern'],value))):
        raise DomainError('参数格式不符合接口定义。',code='INVALID_ARGUMENT',exit_code=2,details={'field':field})
    if kind=='object' or 'required' in schema:
        if not isinstance(value,dict): raise DomainError('需要参数对象。',code='INVALID_ARGUMENT',exit_code=2)
        properties=schema.get('properties',{})
        if any(key not in value for key in schema.get('required',[])):
            raise DomainError('缺少必填参数。',code='MISSING_ARGUMENT',exit_code=2)
        if not schema.get('additionalProperties',True) and any(key not in properties for key in value):
            raise DomainError('包含未支持的参数。',code='INVALID_ARGUMENT',exit_code=2)
        for key,item in value.items():
            if key in properties: validate(item,properties[key],key)


class Application:
    def __init__(self, context):
        self.ctx=context

    def runtime_available(self):
        app,_=self.ctx.current_installation()
        return (app/'data/config.json').is_file() and (app/'mihomo').is_file()

    def revision(self):
        app,_=self.ctx.current_installation()
        digest=hashlib.sha256()
        for path in [app/'shell-policy.json',app/'data/config.json',app/'data/subscription.json',
                     app/'data/source/metadata.json',app/'data/source/config.json',
                     self.ctx.HOME/'.config/domino/subscriptions/index.json',
                     self.ctx.HOME/'.config/domino/rules.json',self.ctx.HOME/'.config/domino/system-proxy.json',
                     self.ctx.HOME/'.config/domino/linux-system-proxy.json']:
            digest.update(str(path.relative_to(self.ctx.HOME)).encode())
            content=path.read_bytes() if path.is_file() else b'<absent>'
            try: content=json.dumps(json.loads(content),sort_keys=True,separators=(',',':')).encode()
            except ValueError: pass
            digest.update(content)
        if (app/'data/config.json').is_file() and (app/'mihomo').is_file():
            try:
                config=self.ctx.api_json('/configs')
                proxies=self.ctx.api_json('/proxies')['proxies']
                live={'mode':config.get('mode'),'log-level':config.get('log-level'),
                      'selections':{key:value.get('now') for key,value in proxies.items() if str(value.get('type','')).lower() in ['selector','select']}}
            except (OSError,ValueError,KeyError,RuntimeError):
                live={'controller_available':False}
            digest.update(json.dumps(live,sort_keys=True).encode())
            if platform.system().lower()=='darwin':
                try:
                    import domino_macos
                    service=domino_macos.network_service()
                    routing={'service':service,'proxies':domino_macos.proxy_settings(service),
                        'pac':domino_macos.network('-getautoproxyurl',service),
                        'discovery':domino_macos.network('-getproxyautodiscovery',service)}
                except (DomainError,RuntimeError,OSError): routing={'available':False}
                digest.update(json.dumps(routing,sort_keys=True).encode())
            elif platform.system().lower()=='linux':
                import domino_linux
                try: routing=domino_linux.Settings().state()
                except DomainError: routing={'available':False}
                digest.update(json.dumps(routing,sort_keys=True).encode())
        return digest.hexdigest()

    def capabilities(self):
        from domino_cli import VERSION
        app,_=self.ctx.current_installation()
        installed=self.runtime_available()
        system=platform.system().lower()
        operations=[]
        for name,definition in OPERATIONS.items():
            available=system in definition['platforms'] and (installed or not definition['requires_installation'])
            operations.append(dict(definition,operation=name,available=available,
                invocation=['domino','--output','json','--input','-','call',name]))
            if definition['write']:
                operations[-1]['dry_run_result']=obj({'operation':STRING,'would_change':BOOLEAN,'dry_run':BOOLEAN},['operation','would_change','dry_run'],extra=True)
        return {'protocol_versions':[1],'application_version':VERSION,'result_envelope':RESULT_SCHEMA,'platform':system,'client':'domino','installed':installed,
                'availability_scope':'platform and installation support; controller reachability and authorization are checked when executing',
                'revision_scope':'managed configuration and manual runtime selections',
                'controls':{'input':'stdin or private JSON file','if_revision':'sha256','request_id':'1-200 characters','dry_run':True},
                'effects':['none','applied','rolled_back','unknown'],'operations':operations}

    def configs(self):
        import domino_subscriptions
        manager=domino_subscriptions.Manager(self.ctx)
        result=manager.listing()
        identifiers={item['name']:item['id'] for item in manager.registry['items']}
        for item in result['configs']: item['id']=identifiers[item['name']]
        result['active_id']=manager.active_id()
        return result

    def read(self, operation, arguments):
        ctx=self.ctx
        if operation in ['operations.get','operations.list']:
            from domino_store import OperationStore
            store=OperationStore(ctx)
            if operation.endswith('.get'): return store.load(arguments['id']) if 'id' in arguments else store.find(arguments['request_id'])
            return store.listing(arguments.get('limit',20))
        if operation=='capabilities': return self.capabilities()
        if operation=='status.get': return ctx.collect_status(arguments.get('check_exit',True))
        if operation=='source.inspect':
            import domino_cli
            return domino_cli.collect_source(SimpleNamespace(source=arguments.get('path')))
        if operation=='source.list':
            import domino_cli
            return domino_cli.collect_sources()
        if operation=='nodes.list': return ctx.collect_nodes(arguments.get('group'))
        if operation=='configs.list': return self.configs()
        if operation in ['mode.get','log-level.get']:
            return ctx.set_option(operation.split('.')[0],render=False)
        if operation=='connections.list': return ctx.collect_connections()
        if operation=='rules.list': return ctx.collect_rules(arguments.get('match'),arguments.get('limit',50),arguments.get('custom',False))
        if operation=='providers.list': return ctx.collect_providers(arguments.get('kind','proxy'))
        if operation=='traffic.sample': return next(ctx.traffic_samples(interval=arguments.get('interval',1)))
        if operation=='logs.read':
            from domino_logs import read_logs
            return read_logs(ctx,arguments.get('lines',100))
        if operation=='shell.status': return ctx.shell_proxy(render=False)
        if operation=='proxy.status':
            return ctx.system_proxy(service=arguments.get('service'),render=False)
        if operation=='delay.summary':
            return ctx.delay_summary(url=arguments.get('url','https://www.gstatic.com/generate_204'),
                timeout_ms=arguments.get('timeout',5000),render=False)
        if operation=='delay.test':
            if sum(key in arguments for key in ['node','name','group','config'])>1:
                raise DomainError('只能指定一种测速对象。',code='INVALID_ARGUMENT',exit_code=2)
            return ctx.delay(node=arguments.get('node'),group=arguments.get('group'),name=arguments.get('name'),config=arguments.get('config'),
                url=arguments.get('url','https://www.gstatic.com/generate_204'),timeout_ms=arguments.get('timeout',5000),render=False)
        raise DomainError('未支持的操作。',code='UNSUPPORTED_OPERATION',exit_code=3)

    def manager(self):
        import domino_subscriptions
        return domino_subscriptions.Manager(self.ctx)

    def subscription(self, manager, arguments):
        if 'id' in arguments:
            item=next((value for value in manager.registry['items'] if value['id']==arguments['id']),None)
            if not item: raise DomainError('未找到订阅。',code='SUBSCRIPTION_NOT_FOUND',exit_code=3)
            return item
        return manager.find(arguments['name'])

    def plan(self, operation, arguments):
        result={'operation':operation,'would_change':True}
        if operation=='bundle.export':
            import domino_cli
            args=self.export_arguments(arguments)
            output=Path(arguments['output']).expanduser()
            if output.exists() or output.is_symlink():
                raise DomainError('导出文件已存在，请使用新的输出路径。',code='OUTPUT_EXISTS',exit_code=6)
            with domino_cli.source_input(args) as prepared:
                source,raw,_=domino_cli.source_config(prepared)
                selections=domino_cli.live_selections(prepared,raw,source)
                domino_cli.sanitize_profile(raw,selections,args.proxy_port,args.api_port)
            return dict(result,output=str(output),arch=args.arch,system=args.target_system,changes=['private archive'])
        if operation in ['service.install','deployment.apply']:
            with self.bundle(arguments) as directory:
                manifest=json.loads((directory/'manifest.json').read_text())
                if manifest.get('platform','linux')!=platform.system().lower():
                    raise DomainError('安装包平台与目标不符。',code='BUNDLE_PLATFORM_MISMATCH',exit_code=3)
                import domino_cli
                if manifest.get('arch')!=domino_cli.normalize_arch(platform.machine()):
                    raise DomainError('安装包架构与目标不符。',code='BUNDLE_ARCH_MISMATCH',exit_code=3)
                config=json.loads((directory/'data/config.json').read_text())
                if config.get('external-controller')!=f"127.0.0.1:{manifest.get('api_port')}" or config.get('mixed-port')!=manifest.get('proxy_port'):
                    raise DomainError('安装包端口与配置不一致。',code='INVALID_BUNDLE',exit_code=2)
                self.ctx.run([str(directory/'mihomo'),'-t','-d',str(directory/'data'),'-f',str(directory/'data/config.json')],capture_output=True,text=True,timeout=60)
                result.update(version=manifest.get('version'),arch=manifest.get('arch'),proxy_port=manifest.get('proxy_port'),
                    changes=['kernel','configuration','background service','management CLI'],requires_sudo=platform.system().lower()=='linux')
            return result
        if operation in ['service.start', 'service.stop']:
            active=self.ctx.systemctl('is-active')
            result['would_change']=bool(active)!=(operation=='service.start')
            if platform.system().lower() == 'darwin':
                import domino_macos
                app,_=self.ctx.current_installation()
                config=json.loads((app/'data/config.json').read_text())
                routing=domino_macos.system_proxy_overview(config['mixed-port'])['routing']
                proxy_change=(routing!='domino' if operation=='service.start' else
                              routing not in ['off','other','pac'] or (self.ctx.HOME/'.config/domino/system-proxy.json').exists())
                result['would_change'] = result['would_change'] or proxy_change
                result['changes'] = ['owned service', 'system proxy']
            elif platform.system().lower() == 'linux':
                import domino_linux
                app,_=self.ctx.current_installation()
                config=json.loads((app/'data/config.json').read_text())
                routing=domino_linux.system_proxy_overview(config['mixed-port'])['routing']
                record=domino_linux.record_path(self.ctx).exists()
                proxy_change=(routing not in ['domino','unsupported'] if operation=='service.start' else routing in ['domino','mixed','unknown'] or record)
                result['would_change'] = result['would_change'] or proxy_change
                result['changes'] = ['owned service'] + (['system proxy'] if routing!='unsupported' or record else [])
        if operation=='service.rollback':
            backup=self.ctx.select_backup(arguments.get('backup'))
            return dict(result,backup=backup.name,would_change=True,changes=['owned service','configuration','environment files'])
        if operation in ['shell.on','shell.off']:
            current=self.ctx.shell_proxy(render=False)
            if operation=='shell.on':
                import domino_shell
                app,_=self.ctx.current_installation()
                try: domino_shell.proxy_port(app)
                except ValueError as error:
                    raise self.ctx.InstallError('终端代理端口无效；请检查安装配置。',code='SHELL_POLICY_INVALID') from error
            return dict(result,would_change=current['enabled']!=(operation=='shell.on'),policy_only=True,current_shell_applied=False)
        if operation.startswith('configs.'):
            manager=self.manager()
            if operation=='configs.add':
                manager.available_name(arguments['name'])
                manager.url(arguments['url'])
                result['name']=arguments['name']
            elif operation=='configs.update_all':
                result['configs']=[{'id':item['id'],'name':item['name']} for item in manager.registry['items'] if item.get('url')]
            else:
                item=self.subscription(manager,arguments)
                result.update(id=item['id'],name=item['name'])
                if operation=='configs.rename':
                    result['would_change']=item['name']!=arguments['new_name']
                    if result['would_change']: manager.available_name(arguments['new_name'])
                    result['new_name']=arguments['new_name']
                if operation=='configs.remove' and item['id']==manager.active_id():
                    raise DomainError('请先切换订阅，再删除当前订阅。',code='ACTIVE_SUBSCRIPTION',exit_code=3)
                if operation=='configs.set-url': manager.url(arguments['url'])
                if operation=='configs.update' and not item.get('url'):
                    raise DomainError('本地快照没有在线订阅地址。',code='SUBSCRIPTION_URL_REQUIRED',exit_code=3)
                if operation=='configs.switch': self.ctx.api_json('/configs')
        elif operation.startswith('rules.'):
            preview=self.ctx.edit_rule(arguments['rule'],remove=operation.endswith('remove'),render=False,validate_only=True)
            result.update(rule=arguments['rule'],would_change=preview.get('would_change',preview.get('changed',False)))
        elif operation=='nodes.select':
            _,live=self.ctx.proxy_state()
            group=live.get(arguments['group'],{})
            if str(group.get('type','')).lower() not in ['selector','select'] or arguments['node'] not in group.get('all',[]):
                raise DomainError('需要手动策略组及其中有效的节点。',code='INVALID_SELECTION',exit_code=2)
            result.update(group=arguments['group'],node=arguments['node'],would_change=group.get('now')!=arguments['node'])
        elif operation in ['mode.set','log-level.set']:
            key=operation.split('.')[0]
            result.update(value=arguments['value'],would_change=self.ctx.api_json('/configs').get(key)!=arguments['value'])
        elif operation.startswith('connections.'):
            values=self.ctx.collect_connections()['connections']
            if operation=='connections.close' and arguments['id'] not in [item['id'] for item in values]:
                raise DomainError('未找到连接。',code='CONNECTION_NOT_FOUND',exit_code=3)
            result['would_change']=bool(values)
            result['ids']=[item['id'] for item in values if operation=='connections.clear' or item['id']==arguments.get('id')]
        elif operation=='providers.update':
            route='/providers/'+('proxies' if arguments.get('kind','proxy')=='proxy' else 'rules')
            provider=self.ctx.api_json(route)['providers'].get(arguments['name'])
            if not provider or str(provider.get('vehicleType','')).lower() not in ['http','file']:
                raise DomainError('需要可更新的 HTTP 或文件集合。',code='PROVIDER_NOT_UPDATABLE',exit_code=3)
            result.update(name=arguments['name'],kind=arguments.get('kind','proxy'))
        return result

    def bundle(self,arguments):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            import domino_cli
            path=Path(arguments['bundle']).expanduser()
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise DomainError('安装包需为权限 600 的普通文件。',code='INVALID_BUNDLE',exit_code=2)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=arguments['bundle_sha256']:
                raise DomainError('安装包摘要不一致。',code='BUNDLE_DIGEST_MISMATCH',exit_code=2)
            with tempfile.TemporaryDirectory(prefix='domino-agent-install-') as work:
                directory=Path(work)
                domino_cli.unpack_bundle(path,directory)
                manifest=json.loads((directory/'manifest.json').read_text())
                manifest['non_interactive']=True
                self.ctx.write_private(directory/'manifest.json',json.dumps(manifest))
                yield directory
        return opened()

    def export_arguments(self,arguments):
        import domino_cli
        selectors=[name for name in ['source','subscription'] if name in arguments]
        if len(selectors)>1: raise DomainError('只能选择一种配置来源。',code='INVALID_ARGUMENT',exit_code=2)
        args=domino_cli.build_parser().parse_args(['export','--arch',arguments['arch'],'--output',arguments['output']])
        for field in ['source','subscription','local_proxy','mihomo_version','proxy_port','api_port']:
            if field in arguments: setattr(args,field,arguments[field])
        args.target_system=arguments.get('system','linux')
        args.batch=True
        if args.proxy_port==args.api_port: raise DomainError('代理和控制端口不能相同。',code='INVALID_ARGUMENT',exit_code=2)
        if args.subscription: self.manager().url(args.subscription)
        return args

    def write(self, operation, arguments, plan):
        ctx=self.ctx
        if operation=='bundle.export':
            import domino_cli
            with tempfile.TemporaryDirectory(prefix='domino-agent-export-') as work:
                package,manifest=domino_cli.prepare(self.export_arguments(arguments),arguments['arch'],Path(work))
                output=Path(arguments['output']).expanduser()
                if output.exists() or output.is_symlink(): raise DomainError('导出路径已被占用。',code='OUTPUT_EXISTS',exit_code=6)
                output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                descriptor,temporary=tempfile.mkstemp(dir=output.parent)
                try:
                    with os.fdopen(descriptor,'wb') as handle: handle.write(package.read_bytes())
                    try: os.link(temporary,output)
                    except FileExistsError: raise DomainError('导出路径已被占用。',code='OUTPUT_EXISTS',exit_code=6) from None
                finally: Path(temporary).unlink(missing_ok=True)
                digest=hashlib.sha256(output.read_bytes()).hexdigest()
            return {'output':str(output),'bundle_sha256':digest,'version':manifest['version'],'arch':manifest['arch'],'system':manifest['platform']}
        if operation in ['service.install','deployment.apply']:
            with self.bundle(arguments) as directory:
                if platform.system().lower()=='darwin':
                    import domino_macos
                    domino_macos.install(ctx,directory)
                else: ctx.install(directory)
            return ctx.collect_status(check_exit=False)
        if operation.startswith('configs.'):
            manager=self.manager()
            if operation=='configs.update_all':
                outcomes=[]
                uncertain=False
                for item in list(manager.registry['items']):
                    if not item.get('url'): continue
                    entry={'id':item['id'],'name':item['name']}
                    if uncertain:
                        outcomes.append(dict(entry,ok=False,effect='none',error={'code':'NOT_ATTEMPTED','message':'前一项结果未确认，尚未尝试。','retryable':False}))
                        continue
                    try: manager.update(item); entry.update(ok=True,effect='applied')
                    except DomainError as error: entry.update(ok=False,effect=error.effect,error=error.document())
                    except (OSError,ValueError,KeyError): entry.update(ok=False,effect='none',error={'code':'SUBSCRIPTION_UPDATE_FAILED','message':'订阅更新未完成。','retryable':True})
                    outcomes.append(entry)
                    uncertain=entry['effect']=='unknown'
                    manager=self.manager()
                if any(not entry['ok'] for entry in outcomes):
                    raise DomainError('部分订阅更新未完成。',code='PARTIAL_FAILURE',exit_code=9,
                        effect='unknown' if any(item['effect']=='unknown' for item in outcomes) else 'applied' if any(item['ok'] for item in outcomes) else 'none',
                        details={'results':outcomes})
                return {'results':outcomes}
            fields={key:None for key in ['add','use','update','rename','remove','set_url','import_current','new_name','url']}
            fields.update(update_all=False,json=True)
            action=operation.split('.')[1]
            if action=='add': fields.update(add=arguments['name'],url=arguments['url'])
            else:
                item=self.subscription(manager,arguments)
                if action=='rename' and not plan['would_change']: return self.configs()
                fields[{'switch':'use','set-url':'set_url'}.get(action,action)]=item['name']
                fields.update(new_name=arguments.get('new_name'),url=arguments.get('url'))
            manager.execute(SimpleNamespace(**fields),render=False)
            return self.configs()
        if operation.startswith('rules.'):
            return ctx.edit_rule(arguments['rule'],remove=operation.endswith('remove'),render=False)
        if operation=='nodes.select': return ctx.select_node(arguments['group'],arguments['node'],render=False)
        if operation in ['mode.set','log-level.set']: return ctx.set_option(operation.split('.')[0],arguments['value'],render=False)
        if operation in ['shell.on','shell.off']:
            return ctx.shell_proxy(operation.split('.')[1],render=False)
        if operation.startswith('proxy.'):
            return ctx.system_proxy(operation.split('.')[1],service=arguments.get('service'),non_interactive=True,render=False)
        if operation.startswith('service.'):
            if operation=='service.rollback':
                if platform.system().lower()=='darwin':
                    import domino_macos
                    domino_macos.rollback(ctx,plan['backup'])
                else: ctx.rollback(plan['backup'],non_interactive=True)
                return ctx.collect_status(check_exit=False)
            try: ctx.service_action(operation.split('.')[1],non_interactive=True)
            except DomainError as error:
                if error.code!='AUTH_REQUIRED': error.effect='unknown'
                raise
            return ctx.collect_status(check_exit=False)
        if operation.startswith('connections.'):
            if not plan['would_change']: return {'closed':'all','changed':False}
            result=ctx.connections(close=arguments.get('id'),close_all=operation.endswith('clear'),render=False)
            remaining={item['id'] for item in ctx.collect_connections()['connections']}
            if remaining.intersection(plan['ids']):
                raise DomainError('关闭连接后读回结果尚未一致。',code='READBACK_MISMATCH',effect='unknown')
            return result
        if operation=='providers.update': return ctx.collect_providers(arguments.get('kind','proxy'),arguments['name'])
        raise DomainError('未支持的写操作。',code='UNSUPPORTED_OPERATION',exit_code=3)

    def mutate(self, request, result):
        from domino_store import OperationStore
        operation,arguments=request['operation'],request.get('arguments',{})
        store=OperationStore(self.ctx)
        semantic_arguments={key:value for key,value in arguments.items() if operation not in ['service.install','deployment.apply'] or key!='bundle'}
        fingerprint=hashlib.sha256(json.dumps([operation,result.target,request.get('client','domino'),semantic_arguments],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.ctx.deployment_lock():
            if not request.get('dry_run'):
                cached=store.lookup(request.get('request_id') or result.operation_id,fingerprint)
                if cached: return cached
            before=self.revision()
            if request.get('if_revision') is not None and request['if_revision']!=before:
                raise DomainError('配置已变化，请重新读取状态。',code='REVISION_CONFLICT',exit_code=6,details={'current_revision':before})
            plan=self.plan(operation,arguments)
            if request.get('dry_run'):
                result.data=dict(plan,dry_run=True)
                result.revision=before
                return result
            record=store.begin(request,fingerprint,before)
            try:
                result.data=self.write(operation,arguments,plan)
                result.revision=self.revision()
                result.changed=result.revision!=before
                if operation.startswith(('service.','connections.','providers.')) or operation in ['bundle.export','deployment.apply']:
                    result.changed=plan['would_change']
                result.effect='applied' if result.changed else 'none'
            except DomainError as error:
                result.error=error
                result.effect=error.effect
                result.changed=None if error.effect=='unknown' else error.effect=='applied'
                if error.details and 'results' in error.details: result.data={'results':error.details['results']}
            except (OSError,ValueError,KeyError,RuntimeError,KeyboardInterrupt) as failure:
                effect=getattr(failure,'domino_effect','unknown')
                result.error=DomainError('操作已取消并恢复。' if effect=='rolled_back' else '写操作未获得已确认结果，请查询操作记录。',code='CANCELLED' if isinstance(failure,KeyboardInterrupt) else 'APPLY_UNCERTAIN',exit_code=7 if isinstance(failure,KeyboardInterrupt) else 8,effect=effect)
                result.effect,result.changed=effect,None if effect=='unknown' else False
            try: store.finish(record,result)
            except OSError:
                result.error=DomainError('无法确认操作记录已落盘。',code='OPERATION_RECORD_FAILED',exit_code=1,effect='unknown')
                result.effect,result.changed='unknown',None
            return result

    def execute(self, request):
        operation=request.get('operation')
        target=request.get('target','localhost')
        identifier=request.get('operation_id') or operation_id()
        result=Result(operation,target,operation_id=identifier)
        try:
            if request.get('client','domino') != 'domino':
                raise DomainError('只支持 Domino 自有服务。',code='INVALID_ARGUMENT',exit_code=2)
            if request.get('schema_version') != 1:
                raise DomainError('不支持的协议版本。',code='UNSUPPORTED_PROTOCOL',exit_code=2)
            definition=OPERATIONS.get(operation)
            if not definition: raise DomainError('未支持的操作。',code='UNSUPPORTED_OPERATION',exit_code=3)
            arguments=request.get('arguments',{})
            validate(arguments,definition['parameters'])
            if request.get('if_revision') is not None: validate(request['if_revision'],{'type':'string','pattern':'[a-f0-9]{64}'})
            if request.get('request_id') is not None: validate(request['request_id'],dict(STRING,maxLength=200))
            if 'dry_run' in request: validate(request['dry_run'],BOOLEAN)
            if request.get('dry_run') and request.get('request_id'):
                raise DomainError('预览不接受请求去重键。',code='INVALID_ARGUMENT',exit_code=2)
            request=dict(request,operation_id=identifier)
            if platform.system().lower() not in definition['platforms']:
                raise DomainError('目标平台不支持该操作。',code='UNSUPPORTED_PLATFORM',exit_code=3)
            app,_=self.ctx.current_installation()
            if definition['requires_installation'] and not self.runtime_available():
                raise DomainError('目标尚未安装 Domino 运行环境。',code='NOT_INSTALLED',exit_code=3)
            if definition['write']: return self.mutate(request,result)
            if request.get('dry_run') or request.get('if_revision') is not None or request.get('request_id') is not None:
                raise DomainError('只读操作不接受写操作控制参数。',code='INVALID_ARGUMENT',exit_code=2)
            result.data=self.read(operation,arguments)
            result.revision=self.revision()
        except DomainError as error:
            result.error=error
            result.effect=error.effect
            if error.effect=='unknown':
                result.changed=None
                if error.details and error.details.get('operation_id'): result.operation_id=error.details['operation_id']
        except TimeoutError:
            result.error=DomainError('目标请求超时。',code='TIMEOUT',exit_code=7,retryable=True)
        except OSError:
            result.error=DomainError('无法读取目标服务或配置。',code='TARGET_UNREACHABLE',exit_code=5,retryable=True)
        except (ValueError,KeyError,TypeError):
            result.error=DomainError('目标返回的数据不符合接口定义。',code='INVALID_TARGET_RESPONSE',exit_code=1)
        return result
