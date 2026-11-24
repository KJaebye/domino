# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""User-owned launchd installation and lifecycle; no administrator password required."""
from __future__ import annotations
from domino_i18n import tr as _t

import copy
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import socket
import subprocess
import time
import uuid
from domino_model import DomainError

LABEL = 'local.domino.mihomo'


def paths(home):
    return home / 'Library/LaunchAgents' / (LABEL + '.plist'), home / 'Library/Logs/domino'


def domain():
    return f'gui/{os.getuid()}'


def launch(*arguments, check=True):
    result = subprocess.run(['launchctl', *arguments], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(_t('launchctl 操作失败；请确认当前用户已登录 macOS 图形会话。'))
    return result


def state(home):
    plist, _ = paths(home)
    result = launch('print', domain() + '/' + LABEL, check=False)
    active = result.returncode == 0 and 'state = running' in result.stdout
    disabled = launch('print-disabled', domain(), check=False)
    enabled = plist.is_file() and not re.search(r'"' + re.escape(LABEL) + r'"\s*=>\s*true', disabled.stdout)
    return active, bool(enabled)


def owned(ctx):
    plist, _ = paths(ctx.HOME)
    if plist.is_symlink() or ctx.APP.is_symlink():
        raise ctx.InstallError(_t('Domino 安装路径不能是符号链接。'))
    if plist.exists():
        value = plistlib.loads(plist.read_bytes())
        if value.get('Label') != LABEL or value.get('DominoManaged') != 1:
            raise ctx.InstallError(_t('同名 LaunchAgent 不属于 Domino，未覆盖。'))


def stop(home):
    result = launch('bootout', domain() + '/' + LABEL, check=False)
    if result.returncode:
        if launch('print', domain() + '/' + LABEL, check=False).returncode == 0:
            raise RuntimeError(_t('Domino LaunchAgent 未能停止。'))
        return
    # bootout can return while the supervisor is still reaping its child. A
    # subsequent start must bootstrap a new job, not kickstart the departing one.
    deadline = time.monotonic() + 30
    while launch('print', domain() + '/' + LABEL, check=False).returncode == 0:
        if time.monotonic() >= deadline:
            raise RuntimeError(_t('等待 Domino LaunchAgent 退出超时；请检查服务状态后重试。'))
        time.sleep(.1)


def start(home):
    plist, _ = paths(home)
    result = launch('print', domain() + '/' + LABEL, check=False)
    if result.returncode:
        launch('enable', domain() + '/' + LABEL)
        launch('bootstrap', domain(), str(plist))
    else:
        launch('kickstart', domain() + '/' + LABEL)


def snapshot(ctx, kind='deploy', *, preserve_cli=False):
    ctx.BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = ctx.BACKUPS / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir(mode=0o700)
    active, _ = state(ctx.HOME)
    files = ['Library/LaunchAgents/' + LABEL + '.plist', '.local/bin/domino',
             '.zshrc', '.bashrc', '.config/domino/proxy.env']
    meta = {'schema': 'macos-1', 'kind': kind, 'created_ns': time.time_ns(),
            'active': active, 'had_app': ctx.APP.exists(), 'files': {}}
    if ctx.APP.exists():
        shutil.copytree(ctx.APP, backup / 'app', symlinks=True)
    for index, name in enumerate(files):
        path = ctx.HOME / name
        if preserve_cli and name == '.local/bin/domino':
            meta['files'][name] = {'preserved': True}
            continue
        if path.is_symlink():
            raise ctx.InstallError(_t('受管理的文件不能是符号链接。'))
        item = {'exists': path.exists(), 'index': index}
        if path.exists():
            item['mode'] = path.stat().st_mode & 0o777
            ctx.write_private(backup / f'file-{index}', path.read_bytes(), item['mode'])
        meta['files'][name] = item
    import domino_subscriptions
    domino_subscriptions.snapshot_registry(ctx, backup)
    ctx.write_private(backup / 'snapshot.json', json.dumps(meta))
    return backup


def restore(ctx, backup):
    # Restore registry even when launchd/app recovery fails, and conversely.
    failures = []
    try:
        _restore_installation(ctx, backup)
    except BaseException as exc:
        failures.append(exc)
    try:
        import domino_subscriptions
        domino_subscriptions.restore_registry(ctx, backup)
    except BaseException as exc:
        failures.append(exc)
    if failures:
        raise ctx.InstallError(_t('恢复未完成；备份：') + str(backup),
                               code='RECOVERY_INCOMPLETE', effect='unknown') from None


def _restore_installation(ctx, backup):
    import domino_macos_app as native
    owned(ctx)
    meta = json.loads((backup / 'snapshot.json').read_text())
    expected = {'Library/LaunchAgents/' + LABEL + '.plist', '.local/bin/domino',
                '.zshrc', '.bashrc', '.config/domino/proxy.env'}
    if meta.get('schema') != 'macos-1' or set(meta['files']) != expected:
        raise ctx.InstallError(_t('不是 macOS Domino 备份，未恢复。'))
    stop(ctx.HOME)
    if ctx.APP.exists():
        native.register(ctx, ctx.APP, remove=True)
        shutil.rmtree(ctx.APP)
    if meta['had_app']:
        shutil.copytree(backup / 'app', ctx.APP, symlinks=True)
    for name, item in meta['files'].items():
        if item.get('preserved'):
            continue
        path = ctx.HOME / name
        if path.is_symlink():
            raise ctx.InstallError(_t('受管理的文件不能是符号链接。'))
        if item['exists']:
            ctx.write_private(path, (backup / f"file-{item['index']}").read_bytes(), item['mode'])
        else:
            path.unlink(missing_ok=True)
    native.register(ctx, ctx.APP)
    if meta['active']:
        start(ctx.HOME)


def configure_environment(ctx, *, legacy_port=None):
    ctx.configure_shell_environment(ctx.APP, ctx.HOME, legacy_port=legacy_port)


def install(ctx, bundle):
    from domino_macos_app_build import install as apply
    return apply(ctx, bundle)


def setup_network_app(ctx):
    from domino_macos_app_build import setup_network_app as setup
    return setup(ctx)


def service_action(ctx, action, lines=100, follow=False, *, batch=False):
    owned(ctx)
    if not 1 <= lines <= 10000:
        raise ctx.InstallError(_t('日志行数必须在 1–10000 之间。'))
    plist, logs = paths(ctx.HOME)
    if not plist.exists():
        raise ctx.InstallError(_t('尚未安装本机 Domino 运行环境，请先运行安装程序。'))
    if action == 'logs':
        path = logs / 'mihomo.log'
        if not path.exists():
            print(_t('暂无日志。'))
            return
        arguments = ['tail', '-n', str(lines)]
        if follow:
            arguments += ['-f']
        ctx.run(arguments + [str(path)])
    elif action == 'stop':
        system_proxy(ctx, 'off',batch=batch,render=False)
        stop(ctx.HOME)
        ctx.human_header(_t('运行状态'),_t('● 已关闭'),'31')
        if getattr(ctx,'OUTPUT_VERBOSE',False):ctx.human_row(_t('服务'),_t('已停止'))
        ctx.human_row(_t('系统代理'),_t('已解除 Domino 接管（恢复原设置，保留其他程序的修改）') if getattr(ctx,'OUTPUT_VERBOSE',False) else _t('已解除 Domino 接管'))
        if getattr(ctx,'OUTPUT_VERBOSE',False):print(_t('  开启 Domino：domino start'))
    else:
        if action == 'restart':
            stop(ctx.HOME)
        start(ctx.HOME)
        try:
            for attempt in range(20):
                try:
                    ctx.controller(ctx.APP / 'data', '/version', timeout=1)
                    break
                except (OSError, ctx.InstallError):
                    if attempt == 19:
                        raise ctx.InstallError(_t('控制接口未就绪，请用 domino logs 查看日志。')) from None
                    time.sleep(.25)
            proxy_result = system_proxy(ctx, 'on', batch=batch, render=False)
        except DomainError as error:
            raise ctx.InstallError(_t('服务已启动，但系统代理未接通：') + str(error),
                                   code=error.code, exit_code=error.exit_code, effect='unknown') from None
        except (OSError, RuntimeError):
            raise ctx.InstallError(_t('服务已启动，但系统代理未接通；请运行 domino status 检查。'),
                                   effect='unknown') from None
        ctx.human_header(_t('运行状态'),_t('● 已重启 · 系统代理已接通') if action == 'restart' else _t('● 已开启 · 系统代理已接通'))
        if getattr(ctx,'OUTPUT_VERBOSE',False):ctx.human_row(_t('服务'),_t('运行中'))
        number = proxy_result['proxies']['web']['port']
        if getattr(ctx,'OUTPUT_VERBOSE',False):ctx.human_row(_t('系统代理'),_t('已开启（HTTP / HTTPS / SOCKS）'))
        ctx.human_row(_t('代理目标'),f'127.0.0.1:{number}（Domino）')


def rollback(ctx, name=None):
    backup = ctx.select_backup(name)
    safety = snapshot(ctx, 'rollback-safety')
    try:
        restore(ctx, backup)
    except BaseException:
        try: restore(ctx, safety)
        except BaseException:
            raise ctx.InstallError(_t('回滚和自动恢复未完成；当前状态备份：')+safety.name,code='RECOVERY_INCOMPLETE',effect='unknown') from None
        raise ctx.InstallError(_t('回滚未完成，已恢复操作前状态。'),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
    finally:
        vars(ctx).pop('_domino_registry_backup', None)
    print(_t('已恢复：') + backup.name)


def network(*arguments, write=False, batch=False):
    result = subprocess.run(['/usr/sbin/networksetup', *arguments], capture_output=True, text=True)
    failed = result.returncode != 0 or result.stdout.startswith('** Error')
    if failed and write:
        if batch:
            authorization=subprocess.run(['sudo','-n','-v'],capture_output=True,text=True)
            if authorization.returncode:
                raise DomainError(_t('系统代理修改需要预先授权 sudo；机器接口不会询问密码。'),code='AUTH_REQUIRED',exit_code=4)
        result = subprocess.run(['sudo', *(['-n'] if batch else []), '/usr/sbin/networksetup', *arguments],
                                capture_output=False, text=True)
    if result.returncode or (result.stdout or '').startswith('** Error'):
        raise DomainError(_t('无法读取或修改系统代理；请检查网络服务名称和管理员权限。'),code='SYSTEM_PROXY_FAILED',exit_code=8 if write else 5,effect='unknown' if write else 'none')
    return result.stdout or ''


def network_service(requested=None):
    names = network('-listallnetworkservices').splitlines()[1:]
    names = [name for name in names if name and not name.startswith('*')]
    if requested:
        if requested not in names:
            raise RuntimeError(_t('网络服务不存在；可用：') + ', '.join(names))
        return requested
    route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True, text=True)
    match = re.search(r'interface:\s*(\S+)', route.stdout)
    device = match.group(1) if match else None
    order = network('-listnetworkserviceorder')
    current = None
    for line in order.splitlines():
        item = re.match(r'\(\d+\) (.+)', line)
        if item:
            current = item.group(1)
        if device and f'Device: {device})' in line and current in names:
            return current
    raise RuntimeError(_t('无法确定当前网络服务，请用 --service 指定；可用：') + ', '.join(names))


def proxy_settings(service):
    values = {}
    for kind in ['web', 'secureweb', 'socksfirewall']:
        text = network('-get' + kind + 'proxy', service)
        fields = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line)
        values[kind] = {'enabled': fields.get('Enabled') == 'Yes', 'server': fields.get('Server', ''),
                        'port': int(fields.get('Port') or 0),
                        'authenticated': fields.get('Authenticated Proxy Enabled') in ['1', 'Yes']}
    return values


def system_proxy_overview(number):
    """Read effective system proxy routing without admin access or environment overrides."""
    try:
        result = subprocess.run(['/usr/sbin/scutil','--proxy'],capture_output=True,text=True,timeout=2)
        if result.returncode:
            return {'routing':'unknown','ports':[]}
    except (OSError,subprocess.SubprocessError):
        return {'routing':'unknown','ports':[]}
    fields = {key:value.strip() for key,value in re.findall(r'^\s*(HTTPEnable|HTTPPort|HTTPProxy|HTTPSEnable|HTTPSPort|HTTPSProxy|SOCKSEnable|SOCKSPort|SOCKSProxy|ProxyAutoConfigEnable|ProxyAutoDiscoveryEnable)\s*:\s*([^\r\n]+)',result.stdout,re.M)}
    if any(fields.get(name)=='1' for name in ['ProxyAutoConfigEnable','ProxyAutoDiscoveryEnable']):
        return {'routing':'pac','ports':[]}
    enabled=[]
    for prefix in ['HTTP','HTTPS','SOCKS']:
        if fields.get(prefix+'Enable')=='1':
            try:
                port=int(fields.get(prefix+'Port','0'))
            except ValueError:
                return {'routing':'unknown','ports':[]}
            local=fields.get(prefix+'Proxy','').lower() in ['127.0.0.1','localhost','::1']
            enabled.append((local and port==number,port))
    matching=sum(1 for matches,_ in enabled if matches)
    routing=('off' if not enabled else 'domino' if matching==len(enabled)
             else 'mixed' if matching else 'other')
    return {'routing':routing,'ports':sorted({port for _,port in enabled})}


def owns_system_proxy(value, number):
    return (value['enabled'] and value['server'].lower() in ['127.0.0.1','localhost','::1']
            and value['port'] == number)


def restored_system_proxy(value, target):
    # networksetup cannot replay an unconfigured endpoint; its disabled state is sufficient.
    return value == target or (not target['enabled'] and not (target['server'] and target['port']) and not value['enabled'])


def pending_system_proxy(previous, kind, value):
    pending = previous.get('pending', {}).get(kind) if previous else None
    return pending if pending and value in pending['expected'] and not restored_system_proxy(value, pending['target']) else None


def restore_proxy_targets(ctx, path, record, current, targets, batch=False, *, expected=None):
    pending = {}
    for kind, target in targets.items():
        states = list(expected[kind] if expected else [current[kind]])
        # Endpoint setters can enable a proxy before the explicit state command runs.
        if target['server'] and target['port']:
            states.extend([dict(target, enabled=True), dict(target, enabled=current[kind]['enabled'])])
        states.append(target)
        pending[kind] = {'target': target, 'expected': states}
    record['pending'] = pending
    ctx.write_private(path, json.dumps(record))
    for kind, item in list(pending.items()):
        value = proxy_settings(record['service'])[kind]
        if value in item['expected'] and not restored_system_proxy(value, item['target']):
            restore_system_proxy({'service': record['service'], 'proxies': {kind: item['target']}}, batch,
                                 current={kind: value})
            value = proxy_settings(record['service'])[kind]
            if not restored_system_proxy(value, item['target']):
                raise ctx.InstallError(_t('系统代理恢复读回不一致，恢复记录已保留。'),code='RECOVERY_INCOMPLETE',effect='unknown')
        # Unknown live states belong to a later owner, not to this pending operation.
        del pending[kind]
        if not pending:
            record.pop('pending')
        ctx.write_private(path, json.dumps(record))
    return proxy_settings(record['service'])


def show_system_proxy(ctx, service, current, previous, as_json=False, message=None, *, render=True):
    available = bool(previous and previous['service'] == service and any(
        owns_system_proxy(value, previous['domino_port']) or pending_system_proxy(previous, kind, value)
        for kind, value in current.items()))
    result={'service':service,'proxies':current,'restore_available':available}
    if not render: return result
    if as_json:
        ctx.show(result,True)
        return result
    app,_ = ctx.current_installation()
    config_path = app / 'data/config.json'
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    enabled=[value for value in current.values() if value['enabled']]
    matching=sum(owns_system_proxy(value, config.get('mixed-port')) for value in enabled)
    automatic = 'Enabled: Yes' in network('-getautoproxyurl',service) or ': On' in network('-getproxyautodiscovery',service)
    directed = bool(enabled) and matching == len(enabled) and not automatic
    summary = _t('● 使用 PAC / 自动代理配置') if automatic else _t('● 已指向 Domino') if directed else _t('● 未指向 Domino')
    ctx.human_header(_t('系统代理'), summary, '32' if directed else '33' if automatic else '31')
    verbose=getattr(ctx,'OUTPUT_VERBOSE',False)
    if verbose:ctx.human_row(_t('网络服务'),service)
    from install_domino import human_proxy_rows
    human_proxy_rows(current,[('web','HTTP'),('secureweb','HTTPS'),('socksfirewall','SOCKS')],row=ctx.human_row,verbose=verbose)
    if verbose or previous and not available:
        ctx.human_row(_t('恢复记录'),_t('可用 domino proxy off 恢复仍由 Domino 管理的项目') if available else _t('历史记录已失效，现有设置保持不变') if previous else _t('无'))
    if message and (verbose or not directed):ctx.human_row(_t('操作'),message)
    return result


def system_proxy(ctx, action=None, service=None, as_json=False, batch=False, *, render=True):
    record = ctx.HOME / '.config/domino/system-proxy.json'
    previous = json.loads(record.read_text()) if record.is_file() else None
    service = service or (previous['service'] if previous else network_service())
    service = network_service(service)
    current = proxy_settings(service)
    if not action:
        return show_system_proxy(ctx,service,current,previous if not previous or previous['service'] == service else None,as_json,render=render)
    if previous and previous['service'] != service:
        raise ctx.InstallError(_t('另一网络服务已有代理备份，请先使用 domino proxy off 恢复。'))
    app, _ = ctx.current_installation()
    config = json.loads((app / 'data/config.json').read_text())
    number = config['mixed-port']
    if action == 'on':
        manifest_path = app / 'manifest.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        if manifest.get('awaiting_subscription') and not (config.get('proxies') or config.get('proxy-providers')):
            raise ctx.InstallError(_t('请先用 domino add / domino switch 配好订阅，再运行 domino start。'))
        if not state(ctx.HOME)[0]:
            raise ctx.InstallError(_t('请先启动 Domino，再开启系统代理。'))
        ctx.controller(app / 'data', '/version')
        if any(value['authenticated'] for value in current.values()):
            raise ctx.InstallError(_t('当前网络使用需要认证的系统代理，无法完整备份其密码；请先手动处理该代理。'))
        pac = network('-getautoproxyurl', service)
        discovery = network('-getproxyautodiscovery', service)
        if 'Enabled: Yes' in pac or ': On' in discovery:
            raise ctx.InstallError(_t('当前网络启用了 PAC/自动发现，请先手动关闭或选择其他网络服务。'))
        if previous and (previous.get('pending') or 'rollback_record' in previous):
            raise ctx.InstallError(_t('系统代理有未完成的恢复，请先使用 domino proxy off 处理。'),code='RECOVERY_INCOMPLETE')
        entry = copy.deepcopy(current)
        saved = copy.deepcopy(previous)
        baseline = {kind: copy.deepcopy(previous['proxies'][kind] if previous and owns_system_proxy(value, previous['domino_port']) else value)
                    for kind, value in current.items()}
        previous = {'service': service, 'proxies': baseline, 'domino_port': number, 'rollback_record': saved}
        expected = {kind: [value, dict(value, server='127.0.0.1', port=number, authenticated=False),
                           dict(value, server='127.0.0.1', port=number, authenticated=False, enabled=True)]
                    for kind, value in entry.items()}
        previous['pending'] = {kind: {'target': value, 'expected': expected[kind]} for kind, value in entry.items()}
        ctx.write_private(record, json.dumps(previous))
        try:
            for kind in current:
                network('-set' + kind + 'proxy', service, '127.0.0.1', str(number), write=True, batch=batch)
                network('-set' + kind + 'proxystate', service, 'on', write=True, batch=batch)
            observed = proxy_settings(service)
            if any(not owns_system_proxy(value, number) or value['authenticated'] for value in observed.values()):
                raise RuntimeError(_t('系统代理设置读回不一致，正在恢复原设置。'))
            previous.pop('pending')
            previous.pop('rollback_record')
            ctx.write_private(record, json.dumps(previous))
        except BaseException:
            try:
                previous['rollback_record'] = saved
                restored = restore_proxy_targets(ctx, record, previous, entry, entry, batch, expected=expected)
                if any(not restored_system_proxy(restored[kind], value) for kind, value in entry.items()):
                    raise RuntimeError(_t('系统代理回滚读回不一致。'))
                if saved:
                    ctx.write_private(record, json.dumps(saved))
                else:
                    record.unlink(missing_ok=True)
            except BaseException:
                raise ctx.InstallError(_t('系统代理修改失败且恢复未完成，恢复记录已保留。'),code='RECOVERY_INCOMPLETE',effect='unknown') from None
            raise ctx.InstallError(_t('系统代理未应用，已恢复本次操作前设置。'),code='APPLY_ROLLED_BACK',effect='rolled_back') from None
        return show_system_proxy(ctx,service,observed,previous,as_json,_t('已开启 Domino 系统代理'),render=render)
    else:
        if previous and previous.get('pending'):
            targets = {kind: item['target'] for kind, item in previous['pending'].items()}
            expected = {kind: item['expected'] for kind, item in previous['pending'].items()}
            current = restore_proxy_targets(ctx, record, previous, current, targets, batch, expected=expected)
        if previous and 'rollback_record' in previous:
            previous = previous['rollback_record']
            if previous:
                ctx.write_private(record, json.dumps(previous))
            else:
                record.unlink(missing_ok=True)
        targets = {}
        for kind, value in current.items():
            original = previous['proxies'].get(kind) if previous else None
            if previous and owns_system_proxy(value, previous['domino_port']):
                target = copy.deepcopy(original) if original else dict(value, enabled=False)
            elif owns_system_proxy(value, number):
                target = dict(value, enabled=False)
            else:
                continue
            if owns_system_proxy(target, number) or (previous and owns_system_proxy(target, previous['domino_port'])):
                target = dict(target, enabled=False)
            targets[kind] = target
        if targets:
            recovery = previous or {'service': service, 'proxies': {}, 'domino_port': number}
            current = restore_proxy_targets(ctx, record, recovery, current, targets, batch)
        if any(owns_system_proxy(value, number) or (previous and owns_system_proxy(value, previous['domino_port'])) for value in current.values()):
            raise ctx.InstallError(_t('仍有生效代理指向 Domino，恢复记录已保留。'),code='RECOVERY_INCOMPLETE',effect='unknown')
        record.unlink(missing_ok=True)
        message=_t('已解除 Domino 系统代理；已关闭或由其他程序管理的设置保持不变')
        return show_system_proxy(ctx,service,current,None,as_json,message,render=render)


def restore_system_proxy(record, batch=False, *, current=None):
    for kind, value in record['proxies'].items():
        live = current.get(kind) if current else None
        if value['server'] and value['port'] and (not live or any(live[key] != value[key] for key in ['server','port','authenticated'])):
            network('-set' + kind + 'proxy', record['service'], value['server'], str(value['port']), write=True, batch=batch)
        network('-set' + kind + 'proxystate', record['service'], 'on' if value['enabled'] else 'off', write=True, batch=batch)
