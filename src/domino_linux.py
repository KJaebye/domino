"""GNOME desktop proxy integration for the current Linux user; no sudo or shell exports."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
from domino_model import DomainError

SCHEMA = 'org.gnome.system.proxy'
KINDS = ('http', 'https', 'socks')
KEYS = {'mode': (SCHEMA, 'mode'), 'same': (SCHEMA, 'use-same-proxy'),
        'auth': (SCHEMA + '.http', 'use-authentication')}
for _kind in (*KINDS, 'ftp'):
    for _key in ('host', 'port'):
        KEYS[_kind + '.' + _key] = (SCHEMA + '.' + _kind, _key)
MANAGED = ['same', *(kind + '.' + key for kind in KINDS for key in ('host', 'port')), 'mode']


def desktop_environment():
    if not shutil.which('gsettings') or os.environ.get('GSETTINGS_BACKEND', 'dconf') != 'dconf':
        return None
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
    if not any(name in desktop.split(':') for name in ['gnome', 'ubuntu']):
        try:
            process = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'gnome-shell'],
                                     capture_output=True, timeout=2)
            if process.returncode: return None
        except (OSError, subprocess.TimeoutExpired): return None
    env = dict(os.environ)
    if not env.get('DBUS_SESSION_BUS_ADDRESS'):
        bus = Path('/run/user') / str(os.getuid()) / 'bus'
        try:
            info = bus.stat()
            if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode): return None
        except OSError: return None
        env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + str(bus)
    return env


class Settings:
    def __init__(self):
        self.env = desktop_environment()
        if self.env is None:
            raise DomainError('没有可用的 GNOME 桌面会话。', code='DESKTOP_UNAVAILABLE', exit_code=3)
        schemas = self.run('list-schemas').splitlines()
        if any(schema not in schemas for schema in {value[0] for value in KEYS.values()}):
            raise DomainError('桌面缺少 GNOME 系统代理设置。', code='DESKTOP_UNAVAILABLE', exit_code=3)

    def run(self, *args):
        try:
            result = subprocess.run(['gsettings', *args], env=self.env, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            raise DomainError('无法访问当前用户的桌面代理设置。', code='SYSTEM_PROXY_FAILED', exit_code=5) from None
        # dconf can report a commit failure on stderr while returning exit code zero.
        if result.returncode or (args[0] == 'set' and result.stderr.strip()):
            raise DomainError('桌面代理设置读取或写入失败。', code='SYSTEM_PROXY_FAILED', exit_code=8)
        return result.stdout.strip()

    def get(self, name): return self.run('get', *KEYS[name])
    def set(self, name, value):
        self.run('set', *KEYS[name], value)
        if self.get(name) != value:
            raise DomainError('桌面代理设置读回不一致。', code='READBACK_MISMATCH', effect='unknown')
    def state(self): return {key: self.get(key) for key in KEYS}
    def writable(self, keys):
        for key in keys:
            if self.run('writable', *KEYS[key]) != 'true':
                raise DomainError('桌面代理设置不允许当前用户修改。', code='AUTH_REQUIRED', exit_code=4)


def record_path(ctx): return ctx.HOME / '.config/domino/linux-system-proxy.json'


def valid_values(values):
    if not isinstance(values,dict) or set(values)!=set(KEYS): return False
    for key,value in values.items():
        if not isinstance(value,str): return False
        if key in ['same','auth']:
            if value not in ['true','false']: return False
            continue
        try: item=ast.literal_eval(value)
        except (ValueError,SyntaxError): return False
        if key=='mode':
            if item not in ['none','manual','auto']: return False
        elif key.endswith('.port'):
            if type(item) is not int or not 0<=item<=65535: return False
        elif not isinstance(item,str): return False
    return True


def load_record(path):
    if path.is_symlink():
        raise DomainError('桌面代理恢复记录不能为符号链接。', code='INVALID_PROXY_RECORD')
    if not path.exists(): return None
    try:
        record = json.loads(path.read_text())
        if record['schema'] != 1 or record['backend'] != 'gnome': raise ValueError()
        for name in ['original', 'applied']:
            if not valid_values(record[name]): raise ValueError()
        if record.get('restore'):
            for name in ['before','target']:
                values = record['restore'][name]
                if not valid_values(values): raise ValueError()
            previous = record['restore'].get('previous')
            if previous:
                if previous.get('schema')!=1 or previous.get('backend')!='gnome' or previous.get('restore'): raise ValueError()
                for name in ['original','applied']:
                    if not valid_values(previous[name]): raise ValueError()
        return record
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError('桌面代理恢复记录无效，未修改设置。', code='INVALID_PROXY_RECORD') from None


def decoded(value):
    if value in ['true', 'false']: return value == 'true'
    return ast.literal_eval(value)


def owns(values, kind, number):
    return decoded(values[kind+'.host']) in ['127.0.0.1', 'localhost', '::1'] and decoded(values[kind+'.port']) == number


def overview_from(values, number):
    mode = decoded(values['mode'])
    endpoints = [(decoded(values[k+'.host']), decoded(values[k+'.port'])) for k in KINDS]
    enabled = [(host, port) for host, port in endpoints if host and port]
    ports = sorted({port for _, port in enabled}) if mode == 'manual' else []
    matching = sum(host in ['127.0.0.1', 'localhost', '::1'] and port == number for host, port in enabled)
    routing = 'off' if mode == 'none' or (mode == 'manual' and not enabled) else 'pac' if mode == 'auto' else (
        'domino' if matching and matching == len(enabled) and values['auth'] == 'false' else 'mixed' if matching else 'other')
    return {'supported':True, 'routing':routing, 'ports':ports, 'backend':'gnome'}


def system_proxy_overview(number):
    try: return overview_from(Settings().state(), number)
    except DomainError as error:
        return {'supported':False, 'routing':'unsupported' if error.code == 'DESKTOP_UNAVAILABLE' else 'unknown', 'ports':[], 'backend':'gnome'}


def _recover_transaction(ctx, settings, path, record):
    """Finish a durable restore plan, retaining settings changed by another owner."""
    transaction = record.get('restore')
    if not transaction: return record
    before, target = transaction['before'], transaction['target']
    for key in MANAGED:
        current = settings.state()
        if key in ['same', 'mode'] and any(current[k] not in [before[k], target[k]] for k in KEYS if k not in ['same','mode']):
            continue
        if current[key] == before[key] and current[key] != target[key]:
            settings.set(key, target[key])
    observed = settings.state()
    if any(observed[key] == before[key] and before[key] != target[key] for key in MANAGED
           if key not in ['same','mode']):
        raise DomainError('桌面代理恢复未完成，已保留恢复记录。', code='RECOVERY_INCOMPLETE', effect='unknown')
    previous = transaction.get('previous')
    if previous:
        ctx.write_private(path, json.dumps(previous))
    else: path.unlink(missing_ok=True)
    return previous


def recover_transaction(ctx, settings, path, record):
    try:
        return _recover_transaction(ctx,settings,path,record)
    except (DomainError,OSError,ValueError,KeyError,TypeError):
        raise DomainError('桌面代理恢复未完成，恢复记录已保留；请重试 domino stop。',
                          code='RECOVERY_INCOMPLETE',effect='unknown') from None


def system_proxy(ctx, action=None, service=None, as_json=False, batch=False, *, render=True):
    if service:
        raise DomainError('GNOME 系统代理按当前用户管理，不使用 --service 网络服务名称。', code='INVALID_ARGUMENT', exit_code=2)
    path = record_path(ctx)
    previous = load_record(path)
    try: settings = Settings()
    except DomainError as error:
        if error.code != 'DESKTOP_UNAVAILABLE': raise
        if action == 'off' and previous:
            raise DomainError('桌面会话不可用，无法恢复系统代理；服务未停止。', code='RECOVERY_INCOMPLETE', effect='unknown') from None
        result = {'supported':False,'service':'无 GNOME 桌面会话','proxies':{},'restore_available':False,
                  'routing':'unsupported','ports':[]}
        return show(ctx, result, as_json, render)
    if previous and previous.get('restore'):
        if action == 'on':
            raise DomainError('桌面代理有待完成的恢复，请先运行 domino stop。', code='RECOVERY_INCOMPLETE')
        if action == 'off': previous = recover_transaction(ctx, settings, path, previous)
    current = settings.state()
    app, _ = ctx.current_installation()
    config_path = app/'data/config.json'
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    number = config.get('mixed-port')
    owned_ports = {number}
    if previous:
        owned_ports.update(decoded(previous['applied'][kind+'.port']) for kind in KINDS)
    if action == 'on':
        if type(number) is not int or not 1 <= number <= 65535:
            raise DomainError('Domino 代理端口无效。',code='INVALID_PROXY_PORT',exit_code=3)
        if ctx.subscription_pending(app, config):
            raise DomainError('请先用 domino add / domino switch 配好订阅，再运行 domino start。', exit_code=3)
        if not ctx.systemctl('is-active'):
            raise DomainError('Domino 服务尚未运行，请执行 domino start。', exit_code=3)
        for attempt in range(20):
            try:
                ctx.controller(app/'data','/version',timeout=1)
                break
            except (DomainError,OSError):
                if attempt == 19: raise DomainError('服务已启动，但控制接口未就绪，系统代理未接通。', effect='unknown') from None
                time.sleep(.25)
        if current['mode'] == "'auto'" or current['auth'] == 'true':
            raise DomainError('当前桌面使用 PAC 或认证代理，请先处理后再开启 Domino。', exit_code=3)
        settings.writable(MANAGED)
        original = dict(current)
        if previous:
            for kind in KINDS:
                if owns(current,kind,decoded(previous['applied'][kind+'.port'])) and all(current[kind+'.'+key] == previous['applied'][kind+'.'+key] for key in ['host','port']):
                    for key in ['host','port']: original[kind+'.'+key] = previous['original'][kind+'.'+key]
            if current == previous['applied']:
                original = dict(previous['original'])
        target = dict(current, mode="'manual'", same='false')
        for kind in KINDS:
            target.update({kind+'.host':"'127.0.0.1'",kind+'.port':str(number)})
        record = {'schema':1,'backend':'gnome','original':original,'applied':target}
        journal = dict(record, restore={'before':target,'target':current,'previous':previous})
        ctx.write_private(path, json.dumps(journal))
        try:
            for key in MANAGED:
                if current[key] != target[key]: settings.set(key,target[key])
            if settings.state() != target:
                raise DomainError('桌面代理读回不一致。',code='READBACK_MISMATCH')
            ctx.write_private(path, json.dumps(record))
        except BaseException:
            try: recover_transaction(ctx,settings,path,journal)
            except BaseException:
                raise DomainError('桌面代理设置失败且恢复未完成，恢复记录已保留。',code='RECOVERY_INCOMPLETE',effect='unknown') from None
            raise DomainError('桌面代理未应用，已恢复本次操作前的设置。',code='APPLY_ROLLED_BACK',effect='rolled_back') from None
        previous = record
    elif action == 'off':
        target = dict(current)
        for kind in KINDS:
            expected_port = decoded(previous['applied'][kind+'.port']) if previous else number
            if kind == 'http' and current['auth'] != (previous['applied']['auth'] if previous else 'false'):
                continue
            if owns(current,kind,expected_port):
                for key in ['host','port']:
                    target[kind+'.'+key] = previous['original'][kind+'.'+key] if previous else ("''" if key == 'host' else '0')
        if previous and current == previous['applied']:
            target = dict(previous['original'])
        for kind in KINDS:
            old_port = decoded(previous['applied'][kind+'.port']) if previous else number
            if kind == 'http' and current['auth'] != (previous['applied']['auth'] if previous else 'false'):
                continue
            if owns(target,kind,number) or owns(target,kind,old_port):
                target[kind+'.host'],target[kind+'.port'] = "''",'0'
        if target['mode'] == "'manual'" and all(not decoded(target[k+'.host']) or not decoded(target[k+'.port']) for k in (*KINDS,'ftp')):
            target['mode'] = "'none'"
        if previous or target != current:
            settings.writable([key for key in MANAGED if target[key] != current[key]])
            journal = dict(previous or {'schema':1,'backend':'gnome','original':current,'applied':current},
                           restore={'before':current,'target':target,'previous':None})
            ctx.write_private(path,json.dumps(journal))
            recover_transaction(ctx,settings,path,journal)
        previous = None
    observed = settings.state()
    if action == 'off' and observed['mode'] == "'manual'" and any(owns(observed,kind,port) for kind in (*KINDS,'ftp') for port in owned_ports):
        raise DomainError('仍有桌面代理指向 Domino；请修改该设置后重试 domino stop，服务未停止。',
                          code='RECOVERY_INCOMPLETE',effect='unknown')
    overview = overview_from(observed,number)
    result = dict(overview,service='GNOME 用户桌面',restore_available=bool(previous),proxies={
        kind:{'enabled':decoded(observed['mode'])=='manual' and bool(decoded(observed[kind+'.host'])) and bool(decoded(observed[kind+'.port'])),
              'server':decoded(observed[kind+'.host']),'port':decoded(observed[kind+'.port']),'authenticated':kind=='http' and observed['auth']=='true'} for kind in KINDS})
    return show(ctx,result,as_json,render)


def show(ctx, result, as_json, render):
    if render:
        if as_json: ctx.show(result,True)
        else:
            ctx.human_header('系统代理','● 已指向 Domino' if result['routing']=='domino' else '● 未接通桌面系统代理', '32' if result['routing']=='domino' else '33')
            ctx.human_row('桌面',result['service'])
            for kind,value in result['proxies'].items():
                ctx.human_row(kind.upper(),f"{value['server']}:{value['port']}" if value['enabled'] else '未开启')
    return result
