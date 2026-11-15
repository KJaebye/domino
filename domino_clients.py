"""Explicit bindings for existing Clash-compatible controllers; runtime writes only."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from domino_model import DomainError
from domino_service import Application, OPERATIONS

RUNTIME={'capabilities','status.get','source.inspect','nodes.list','nodes.select','mode.get','mode.set',
         'log-level.get','log-level.set','connections.list','connections.close','connections.clear',
         'traffic.sample','rules.list','providers.list','providers.update','delay.test','operations.get','operations.list'}


class Registry:
    def __init__(self,ctx):
        self.ctx=ctx
        self.path=ctx.HOME/'.config/domino/clients.json'
        for path in [ctx.HOME/'.config',self.path.parent,self.path]:
            if path.is_symlink(): raise DomainError('客户端绑定路径不安全。',code='UNSAFE_STORAGE',exit_code=3)
        self.items=json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.items,dict): raise DomainError('客户端绑定格式无效。',code='INVALID_CLIENT_REGISTRY',exit_code=1)

    def discover(self):
        home=self.ctx.HOME
        paths=[home/'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml',
               home/'.config/clash/config.yaml',home/'.config/mihomo/config.yaml']
        return [{'config':str(path),'type':'clash-verge' if path.name=='clash-verge.yaml' else 'clash-compatible'} for path in paths if path.is_file()]

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.ctx.write_private(self.path,json.dumps(self.items,ensure_ascii=False))

    def bind(self,name,config,controller=None,socket=None,*,persist=True):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name) or name=='domino':
            raise DomainError('客户端名称需为 1–64 位字母、数字、点、短横线或下划线。',code='INVALID_CLIENT_NAME',exit_code=2)
        if name in self.items: raise DomainError('客户端名称已绑定。',code='CLIENT_EXISTS',exit_code=6)
        item={'config':str(Path(config).expanduser().resolve())}
        if controller: item['controller']=controller
        if socket: item['socket']=socket
        client=Client(name,item,self.ctx)
        client.api('/version')
        self.items[name]=item
        if persist: self.save()
        return self.listing()

    def remove(self,name):
        if name not in self.items: raise DomainError('未找到客户端绑定。',code='CLIENT_NOT_FOUND',exit_code=3)
        del self.items[name]
        self.save()
        return self.listing()

    def listing(self):
        return {'clients':[dict(name=name,**item) for name,item in sorted(self.items.items())]}

    def client(self,name):
        if name not in self.items: raise DomainError('未找到客户端绑定，请先运行 clients bind。',code='CLIENT_NOT_FOUND',exit_code=3)
        return Client(name,self.items[name],self.ctx)


class Client:
    def __init__(self,name,item,ctx):
        import domino_cli
        self.name,self.item,self.ctx=name,item,ctx
        self.config=domino_cli.load_yaml(Path(item['config']))
        if not isinstance(self.config,dict): raise DomainError('客户端配置格式无效。',code='INVALID_CLIENT_CONFIG',exit_code=3)
        address=item.get('controller') or self.config.get('external-controller') or ''
        self.socket=item.get('socket') or self.config.get('external-controller-unix')
        if not self.socket and Path(item['config']).name=='clash-verge.yaml':
            candidate=Path('/tmp/verge/verge-mihomo.sock')
            if candidate.is_socket(): self.socket=str(candidate)
        if self.socket and not Path(self.socket).is_socket():
            raise DomainError('客户端 Unix socket 不可用。',code='CONTROLLER_UNREACHABLE',exit_code=5)
        if self.socket: address='http://127.0.0.1'
        elif '://' not in address: address='http://'+address
        parsed=urlsplit(address)
        if parsed.scheme!='http' or parsed.hostname not in ['localhost','127.0.0.1','::1'] or parsed.username or parsed.password or parsed.path not in ['','/'] or parsed.query or parsed.fragment:
            raise DomainError('客户端控制接口必须是本机回环 HTTP 地址或 Unix socket。',code='INVALID_CONTROLLER',exit_code=2)
        self.address=address.rstrip('/')

    def api(self,route,payload=None,*,method=None,timeout=3):
        method=method or ('PUT' if payload is not None else 'GET')
        config='header = '+json.dumps('Authorization: Bearer '+str(self.config.get('secret') or ''))+'\n'
        if payload is not None: config+='data = '+json.dumps(json.dumps(payload))+'\n'
        argv=['curl','--noproxy','*','--silent','--show-error','--max-time',str(timeout),'--request',method,
              '--header','Content-Type: application/json','--write-out','\n%{http_code}','--config','-']
        if self.socket: argv+=['--unix-socket',self.socket]
        writing=method not in ['GET','HEAD']
        try: process=subprocess.run([*argv,self.address+route],input=config,capture_output=True,text=True,timeout=timeout+2)
        except subprocess.TimeoutExpired:
            raise DomainError('客户端请求超时。',code='TIMEOUT',exit_code=7,retryable=True,effect='unknown' if writing else 'none') from None
        if process.returncode:
            raise DomainError('客户端控制接口不可达。',code='CONTROLLER_UNREACHABLE',exit_code=5,retryable=True,effect='unknown' if writing else 'none')
        try: body,status=process.stdout.rsplit('\n',1); status=int(status)
        except ValueError: raise DomainError('客户端控制接口响应无效。',code='INVALID_TARGET_RESPONSE',exit_code=1) from None
        if status not in range(200,300):
            code,exit_code=('AUTH_REQUIRED',4) if status in [401,403] else ('RESOURCE_NOT_FOUND',3) if status==404 else ('CONTROLLER_REJECTED',8)
            raise DomainError('客户端拒绝请求。',code=code,exit_code=exit_code,details={'http_status':status})
        try: return json.loads(body) if body else None
        except ValueError: raise DomainError('客户端响应不是 JSON。',code='INVALID_TARGET_RESPONSE',exit_code=1,effect='unknown' if writing else 'none') from None

    def option(self,key,value=None,as_json=False,*,render=True):
        if value is not None:
            self.api('/configs',{key:value},method='PATCH')
        observed=self.api('/configs').get(key)
        if value is not None and observed!=value:
            raise DomainError('客户端设置读回不一致。',code='READBACK_MISMATCH',effect='unknown')
        result={key:observed,'persisted':False,'client':self.name}
        if render:
            if as_json: self.ctx.show(result,True)
            else:
                self.ctx.show_option(key,observed)
                self.ctx.human_row('客户端',self.name)
                if value is not None: self.ctx.human_row('保存','仅当前运行时；持久配置由原客户端管理')
        return result

    def status(self,check_exit=True):
        result={'installed':True,'active':False,'enabled':False,'healthy':False,'client':self.name,
                'deployment_method':'external','persistence':'runtime-only','config':self.item['config']}
        try:
            result.update(version=self.api('/version').get('version'),mode=self.api('/configs').get('mode'),active=True)
            number=self.config.get('mixed-port') or self.config.get('port')
            if number:
                result['proxy_port']=number
                if check_exit: result.update(self.ctx.probe(number,self.ctx.DEFAULT_TEST))
        except (DomainError,OSError,ValueError): result['check_error']='客户端控制接口或出网检查失败'
        return result

    def show_status(self,as_json=False):
        result=self.status()
        if as_json: self.ctx.show(result,True)
        else:
            self.ctx.human_header('运行状态','● 代理出网正常' if result['healthy'] else '○ 未确认代理出网','32' if result['healthy'] else '33')
            self.ctx.human_row('客户端',self.name+'  ·  外部 Clash')
            self.ctx.human_row('模式',result.get('mode'))
            self.ctx.human_row('配置',self.item['config'])
            self.ctx.human_row('修改范围','运行时 API；持久配置、订阅和服务由原客户端管理')
        return 0 if result['healthy'] else 3

    def overview(self):
        result=self.status(False)
        result.update(reachable=result['active'],stats_available=False,groups=[],node_count=0,upload_total=0,download_total=0,connections=0)
        try:
            nodes=self.ctx.collect_nodes()
            stats=self.ctx.collect_connections()
            result.update(groups=nodes['groups'],node_count=len(nodes['nodes']),stats_available=True,
                connections=len(stats['connections']),upload_total=stats['uploadTotal'],download_total=stats['downloadTotal'])
        except (DomainError,OSError,ValueError): pass
        self.ctx.show(result,True)

    @contextmanager
    def session(self):
        overrides={'api_json':self.api,'proxy_state':lambda:(self.api('/configs'),self.api('/proxies')['proxies']),
                   'set_option':self.option,'collect_status':self.status,'status':self.show_status,'overview':self.overview}
        def controller(data,route,payload=None,**kwargs):
            result=self.api(route,payload,**kwargs)
            return json.dumps(result).encode() if result is not None else b''
        overrides['controller']=controller
        before={name:getattr(self.ctx,name) for name in overrides}
        try:
            for name,value in overrides.items(): setattr(self.ctx,name,value)
            yield
        finally:
            for name,value in before.items(): setattr(self.ctx,name,value)


class ExternalApplication(Application):
    def __init__(self,ctx,name):
        super().__init__(ctx)
        self.client=Registry(ctx).client(name)

    def runtime_available(self): return True

    def read(self,operation,arguments):
        if operation=='source.inspect':
            import domino_cli
            from types import SimpleNamespace
            return domino_cli.collect_source(SimpleNamespace(source=None,client=self.client.name))
        return super().read(operation,arguments)

    def revision(self):
        try:
            runtime=self.client.api('/configs')
            live=self.client.api('/proxies')['proxies']
        except DomainError: runtime,live={},{}
        value=[self.client.name,runtime.get('mode'),runtime.get('log-level'),
               {key:item.get('now') for key,item in live.items() if str(item.get('type','')).lower() in ['selector','select']}]
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

    def capabilities(self):
        result=super().capabilities()
        result.update(client=self.client.name,persistence='runtime-only')
        for item in result['operations']:
            item['available']=item['operation'] in RUNTIME
            item['invocation'][5:5]=['--client',self.client.name]
            if item['operation'] in ['mode.set','log-level.set']: item['description']+=' (runtime only)'
        return result

    def execute(self,request):
        incompatible=request.get('operation')=='rules.list' and request.get('arguments',{}).get('custom')
        incompatible=incompatible or (request.get('operation')=='source.inspect' and 'path' in request.get('arguments',{}))
        if request.get('operation') not in RUNTIME or incompatible:
            from domino_model import Result
            return Result(request.get('operation'),request.get('target','localhost'),operation_id=request.get('operation_id'),
                client=self.client.name,error=DomainError('外部客户端仅开放运行时能力；配置、订阅和服务请由原客户端管理。',code='UNSUPPORTED_CLIENT_OPERATION',exit_code=3))
        with self.client.session(): result=super().execute(request)
        result.client=self.client.name
        return result


def human_command(ctx,args):
    from domino_model import operation_id
    request={'schema_version':1,'operation':'clients.'+args.operation,'operation_id':operation_id(),
        'arguments':{key:getattr(args,key) for key in ['name','config','controller','socket'] if getattr(args,key,None) is not None}}
    result=Application(ctx).execute(request)
    if result.error: raise result.error
    if args.json: ctx.show(result.data,True)
    else:
        ctx.human_header('客户端','● 已绑定' if args.operation=='bind' else '● 已删除绑定' if args.operation=='remove' else '已有 Clash 客户端')
        if args.operation=='discover':
            ctx.human_table(['类型','配置'],[[item['type'],item['config']] for item in result.data['candidates']])
        else:
            ctx.human_table(['名称','配置'],[[item['name'],item['config']] for item in result.data['clients']])
        print('\n  使用绑定：domino --client 名称 status；domino --client 名称 ui')
    return 0
