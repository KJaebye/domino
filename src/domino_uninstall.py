# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Remove an owned runtime without following user paths or removing package files."""
import configparser
import os
from pathlib import Path
import pwd
import plistlib
import shlex
import shutil
import sys


def checked_path(ctx, path):
    path = Path(path)
    path.relative_to(ctx.HOME)
    for parent in [path, *path.parents]:
        if parent == ctx.HOME:
            break
        if parent.is_symlink():
            raise ctx.InstallError('卸载路径包含符号链接，未修改：' + str(parent))
    return path


def strip_integration(ctx, text):
    markers = {ctx.BEGIN: ctx.END,
               '# >>> Domino completion >>>': '# <<< Domino completion <<<'}
    result, pending = [], None
    for line in text.splitlines(keepends=True):
        value = line.rstrip('\r\n')
        if value in markers:
            if pending is not None:
                raise ctx.InstallError('Domino 终端标记嵌套，未修改启动文件。')
            pending = markers[value]
        elif value in markers.values():
            if value != pending:
                raise ctx.InstallError('Domino 终端标记不完整，未修改启动文件。')
            pending = None
        elif pending is None:
            result.append(line)
    if pending is not None:
        raise ctx.InstallError('Domino 终端标记不完整，未修改启动文件。')
    return ''.join(result)


def plan(ctx):
    if sys.platform not in ('darwin', 'linux'):
        raise ctx.InstallError('卸载仅支持 macOS 和 Linux。')
    directories = [ctx.APP, ctx.BACKUPS, ctx.HOME / '.config/domino',
                   ctx.HOME / (('Library/Caches' if sys.platform == 'darwin' else '.cache') + '/domino')]
    for path in directories:
        checked_path(ctx, path)
        if path.exists() and not path.is_dir():
            raise ctx.InstallError('卸载目录类型异常：' + str(path))
    if sys.platform == 'darwin':
        import domino_macos
        service, logs = domino_macos.paths(ctx.HOME)
        checked_path(ctx, service)
        checked_path(ctx, logs)
        domino_macos.owned(ctx)
        if service.exists():
            arguments = plistlib.loads(service.read_bytes()).get('ProgramArguments', [])
            if not arguments or arguments[0] != str(ctx.APP / 'mihomo'):
                raise ctx.InstallError('LaunchAgent 不属于当前用户的 Domino，未卸载。')
        if logs.exists() and not logs.is_dir():
            raise ctx.InstallError('Domino 日志目录类型异常，未卸载。')
        directories.append(logs)
    else:
        service = ctx.SERVICE
        if service.is_symlink():
            raise ctx.InstallError('同名服务是符号链接，未卸载。')
        if service.exists():
            ctx.owned_service()
            try:
                unit = configparser.ConfigParser(interpolation=None)
                unit.read_string(service.read_text())
                command = shlex.split(unit.get('Service', 'ExecStart'))
                owner = unit.get('Service', 'User')
            except (configparser.Error, ValueError):
                raise ctx.InstallError('同名服务内容异常，未卸载。') from None
            if (owner != pwd.getpwuid(os.getuid()).pw_name or not command
                    or command[0] != str(ctx.APP / 'mihomo')):
                raise ctx.InstallError('同名服务不属于当前用户的 Domino，未卸载。')
    for name in ('data/config.json', 'manifest.json'):
        checked_path(ctx, ctx.APP / name)
    for name in ('system-proxy.json', 'linux-system-proxy.json'):
        checked_path(ctx, ctx.HOME / '.config/domino' / name)
    edits = []
    for name in ('.bashrc', '.zshrc', '.bash_profile', '.profile', '.zprofile',
                 '.vscode-server/server-env-setup'):
        path = checked_path(ctx, ctx.HOME / name)
        if path.exists():
            original = path.read_bytes().decode()
            updated = strip_integration(ctx, original)
            if updated != original:
                edits.append((path, original, updated, path.stat().st_mode & 0o777))
    launcher = ctx.HOME / '.local/bin/domino'
    # Package managers own their launchers. Remove only our marked standalone file.
    checked_path(ctx, launcher.parent)
    owned_launcher = (not launcher.is_symlink() and launcher.is_file()
                      and ctx.CLI_MARKER in launcher.read_text())
    return {'directories': [p for p in directories if p.exists()], 'service': service,
            'edits': edits, 'launcher': launcher if owned_launcher else None}


def uninstall(ctx, *, yes=False, non_interactive=False, dry_run=False):
    initial = plan(ctx)
    ctx.human_header('卸载 Domino', '预览（未修改）' if dry_run else '移除当前用户的运行环境')
    ctx.human_row('删除', 'Mihomo、运行配置、配置库、部署备份、默认缓存和日志', wrap=True)
    for path in initial['directories']:
        ctx.human_row('目录', str(path), wrap=True)
    if initial['service'].exists():
        ctx.human_row('服务', str(initial['service']), wrap=True)
    for path, *_ in initial['edits']:
        ctx.human_row('清理接入', str(path), wrap=True)
    ctx.human_row('保留', '项目源码、外部客户端及包管理器安装的 CLI', wrap=True)
    if dry_run:
        return
    if not yes:
        if non_interactive or not sys.stdin.isatty():
            raise ctx.InstallError('卸载会删除配置和备份；请在终端确认，或明确添加 --yes。')
        try:
            accepted = input('确认卸载并删除这些数据？[y/N] ').strip().lower() == 'y'
        except EOFError:
            accepted = False
        if not accepted:
            raise ctx.InstallError('已取消卸载，未修改。')
    with ctx.deployment_lock():
        current = plan(ctx)
        service = current['service']
        if sys.platform == 'linux' and service.exists():
            ctx.run(['sudo', *(['-n'] if non_interactive else []), '-v'])
        config = ctx.APP / 'data/config.json'
        records = ctx.HOME / '.config/domino'
        if config.exists() or any((records / n).exists() for n in ('system-proxy.json', 'linux-system-proxy.json')):
            ctx.system_proxy('off', non_interactive=non_interactive, render=False)
        if service.exists():
            if sys.platform == 'darwin':
                import domino_macos
                domino_macos.stop(ctx.HOME)
                service.unlink()
            else:
                ctx.sudo('systemctl', 'disable', '--now', service.name)
                ctx.sudo('rm', '-f', str(service))
                ctx.sudo('systemctl', 'daemon-reload')
                if service.exists():
                    raise ctx.InstallError('服务文件未移除，保留运行文件；请重试卸载。')
        for path, original, updated, mode in current['edits']:
            checked_path(ctx, path)
            if path.read_bytes().decode() != original:
                raise ctx.InstallError('终端文件在卸载期间发生变化，未覆盖：' + str(path))
            ctx.write_private(path, updated, mode)
        for path in current['directories']:
            checked_path(ctx, path)
            shutil.rmtree(path)
        if current['launcher']:
            path = checked_path(ctx, current['launcher'])
            if ctx.CLI_MARKER not in path.read_text():
                raise ctx.InstallError('命令入口在卸载期间发生变化，未删除。')
            path.unlink()
    ctx.human_header('卸载 Domino', '● 运行环境已移除', '31')
    ctx.human_row('终端接入', '已清理 Domino 管理区块；请重新打开终端或重新 SSH 登录', wrap=True)
    ctx.human_row('CLI', '包管理器入口保留；pip 安装的 CLI 可继续运行 pip uninstall domino-proxy', wrap=True)
