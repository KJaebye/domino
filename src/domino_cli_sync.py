# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Offline CLI delivery and version negotiation for SSH deployment."""
from domino_i18n import tr as _t
import ast
import argparse
import base64
import csv
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


class SyncError(RuntimeError):
    pass


APP_RESOURCE_FILES = ('domino_assets/__init__.py', 'domino_assets/Domino.icns')


def allowed_cli_file(name):
    return isinstance(name, str) and (re.fullmatch(r'domino_[a-z][a-z0-9_]*\.py|install_domino\.py', name)
                                     or name in APP_RESOURCE_FILES)


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)', value):
        raise SyncError(_t('Domino CLI 版本格式无效。'))
    return tuple(map(int, value.split('.')))


def source_version(path):
    tree = ast.parse(path.read_text())
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets)]
    if len(values) != 1:
        raise SyncError(_t('无法确认 Domino CLI 源码版本。'))
    version_key(values[0])
    return values[0]


def module_files(root):
    tree = ast.parse((root / 'domino_cli.py').read_text())
    names = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'CLI_MODULES' for target in node.targets))
    resources = next((ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'CLI_RESOURCES' for target in node.targets)), ())
    if not isinstance(resources, (list, tuple)) or any(name not in APP_RESOURCE_FILES for name in resources):
        raise SyncError(_t('目标 CLI 应用资源清单无效。'))
    if not isinstance(names, (list, tuple)) or not names or any(
            not isinstance(name, str) or not re.fullmatch(r'domino_[a-z][a-z0-9_]*\.py|install_domino\.py', name)
            or (root / name).is_symlink() for name in names):
        raise SyncError(_t('目标 CLI 源码清单或文件类型无效。'))
    if resources and ((root / 'domino_assets').is_symlink() or any((root / name).is_symlink() for name in resources)):
        raise SyncError(_t('目标 CLI 应用资源不能是符号链接。'))
    return {name: (root / name).read_bytes() for name in (*names, *resources)}


def license_text():
    path = Path(__file__).resolve().parent.parent / 'LICENSE'
    if path.is_file():
        return path.read_bytes()
    try:
        text = importlib.metadata.distribution('domino-proxy').read_text('licenses/LICENSE')
        if text:
            return text.encode()
    except importlib.metadata.PackageNotFoundError:
        pass
    raise SyncError(_t('缺少 Domino 许可证，无法生成 CLI 同步包。'))


def make_wheel(files, output, version, license_bytes):
    """A wheel containing only explicitly supplied modules and owned app resources."""
    version_key(version)
    info = f'domino_proxy-{version}.dist-info'
    files = dict(files)
    if not files or any(not allowed_cli_file(name) for name in files):
        raise SyncError(_t('CLI 同步包源码清单无效。'))
    tree = ast.parse(files['domino_cli.py'].decode())
    declared = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets))
    if declared != version:
        raise SyncError(_t('CLI 同步包版本与源码不一致。'))
    files[info + '/METADATA'] = (f'Metadata-Version: 2.1\nName: domino-proxy\nVersion: {version}\n'
        'Summary: Domino command-line proxy management\nRequires-Python: >=3.9\n'
        'Requires-Dist: prompt-toolkit>=3.0.48,<4\nRequires-Dist: PyYAML>=6\n'
        'License: GPL-3.0-only\nLicense-File: licenses/LICENSE\n').encode()
    files[info + '/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: domino\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    files[info + '/entry_points.txt'] = b'[console_scripts]\ndomino = domino_install:package_cli\ndomino-install = domino_install:package_install\n'
    files[info + '/licenses/LICENSE'] = license_bytes
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for name, data in sorted(files.items()):
        writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='), len(data)])
    writer.writerow([info + '/RECORD', '', ''])
    files[info + '/RECORD'] = record.getvalue().encode()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return output


def checked_run(argv, *, stage, capture=True, timeout=90, env=None, output=None):
    try:
        result = subprocess.run(argv, capture_output=capture, text=True, timeout=timeout, env=env, stdout=output)
    except (OSError, subprocess.TimeoutExpired):
        raise SyncError(stage + _t('失败或超时。')) from None
    if result.returncode:
        raise SyncError(stage + _t('失败（退出码 {0}）。', result.returncode))
    return result.stdout if capture else None


def streamed_remote_argv(command_argv, code, action, options, tty):
    """Stage an oversized trusted program without consuming the request stdin."""
    import shlex
    upload = ('import os,sys,tempfile;fd,path=tempfile.mkstemp(prefix="domino-command-",suffix=".py",dir="/tmp");'
              'os.fchmod(fd,0o600);'
              'stream=os.fdopen(fd,"wb");stream.write(sys.stdin.buffer.read());stream.close();print("DOMINO_SOURCE="+path)')
    setup = {'upload': command_argv('python3 -c ' + shlex.quote(upload), False),
             'prefix': command_argv('', tty)[:-1],
             'cleanup': command_argv('', False)[:-1], 'arguments': [action, *options]}
    # The local bridge uploads code through a separate pipe. Its own stdin stays
    # attached to the final remote program for JSON requests and TTY prompts.
    bridge = _t('import json,re,shlex,subprocess,sys\nsetup=json.loads(sys.argv[1]);source="".join(sys.argv[2:]).encode()\nuploaded=subprocess.run(setup[\'upload\'],input=source,capture_output=True)\nif uploaded.returncode:\n sys.stderr.buffer.write(uploaded.stderr);raise SystemExit(uploaded.returncode)\npaths=[line[len(\'DOMINO_SOURCE=\'):] for line in uploaded.stdout.decode().splitlines() if line.startswith(\'DOMINO_SOURCE=\')]\npath=paths[0] if len(paths)==1 else \'\'\nif not re.fullmatch(r\'/tmp/domino-command-[A-Za-z0-9_-]+\\.py\',path):\n raise SystemExit(\'无法确认远端临时程序路径。\')\ntry:\n command=\'python3 \'+shlex.quote(path)+\' \'+shlex.join(setup[\'arguments\'])\n result=subprocess.run([*setup[\'prefix\'],command])\nfinally:\n try: subprocess.run([*setup[\'cleanup\'],\'rm -f -- \'+shlex.quote(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)\n except subprocess.TimeoutExpired: pass\nraise SystemExit(result.returncode)\n')
    program = 'from pathlib import Path\nPath(__file__).unlink()\n' + code
    chunks = [program[index:index+48000] for index in range(0, len(program), 48000)]
    return [sys.executable, '-I', '-c', bridge, json.dumps(setup), *chunks]


def package_cli(launcher, home):
    text = launcher.read_text()
    if '# Managed by Domino CLI' in text:
        return None
    if not any('from ' + module + ' import ' + entry in text and
               any(call + '(' + entry + '())' in text for call in ('sys.exit', 'SystemExit'))
               for module, entry in [('domino_install', 'package_cli'), ('domino_cli', 'main')]):
        raise SyncError(_t('目标 domino 入口不属于可识别的 Domino，未修改。'))
    first = text.splitlines()[0]
    python = Path(first[2:]) if first.startswith('#!/') else Path('.')
    root = python.parent.parent
    if (not re.fullmatch(r'python(?:\d+(?:\.\d+)?)?', python.name) or not python.is_absolute()
            or not root.resolve().is_relative_to(home.resolve()) or not (root / 'pyvenv.cfg').is_file()):
        raise SyncError(_t('目标 CLI 由系统包或未知环境管理；请先通过原包管理器升级，未覆盖入口。'))
    code = ('import json,domino_cli,importlib.metadata;from pathlib import Path;'
            'd=importlib.metadata.distribution("domino-proxy");'
            'print(json.dumps({"version":domino_cli.VERSION,"module":str(Path(domino_cli.__file__).resolve())}))')
    result = json.loads(checked_run([str(python), '-I', '-c', code], stage=_t('读取目标 CLI')))
    version_key(result['version'])
    if not Path(result['module']).is_relative_to(root.resolve()):
        raise SyncError(_t('目标 CLI 模块位于原虚拟环境之外，未修改。'))
    return dict(result, python=str(python))


def connect_system_proxy(python, stage, *, batch=False):
    command = [str(python), str(stage / 'cli/install_domino.py'), 'proxy', '--set', 'on', '--json']
    if batch:
        command.append('--non-interactive')
    try:
        result = json.loads(checked_run(command, stage=_t('接通目标系统代理')))
        if (not isinstance(result, dict) or type(result.get('supported')) is not bool
                or result.get('routing') != ('domino' if result['supported'] else 'unsupported')):
            raise SyncError(_t('系统代理读回状态未确认接通。'))
    except (SyncError, ValueError, TypeError) as error:
        reason = str(error) if isinstance(error, SyncError) else _t('无法读取系统代理状态。')
        raise SyncError(_t('服务已部署，但系统代理未接通：') + reason) from None
    return {'system_proxy_supported': result['supported'],
            'system_proxy_enabled': result['supported'] and result['routing'] == 'domino'}


def deploy(stage, sender_version, *, home=None, verbose=True):
    home = (Path.home() if home is None else Path(home)).resolve()
    lock = home / '.local/share/domino-cli-sync.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError(_t('已有另一个 CLI 同步操作，请稍后重试。')) from None
        return _deploy(stage, sender_version, home=home, verbose=verbose)


def _deploy(stage, sender_version, *, home, verbose):
    """Use the newest available CLI; update an older user venv offline."""
    home = (Path.home() if home is None else Path(home)).resolve()
    stage = Path(stage)
    manifest_path = stage / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if source_version(stage / 'cli/domino_cli.py') != sender_version:
        raise SyncError(_t('上传的 CLI 版本与发起端不一致，未部署。'))
    launcher = home / '.local/bin/domino'
    package = None
    if launcher.exists() or launcher.is_symlink():
        if not launcher.is_file() or launcher.stat().st_size > 64 * 1024:
            raise SyncError(_t('目标 domino 入口无效，未修改。'))
        package = package_cli(launcher, home)
    desired = sender_version
    runtime = home / '.local/share/domino/cli'
    runtime_version = source_version(runtime / 'domino_cli.py') if (runtime / 'domino_cli.py').is_file() else None
    candidates = [(sender_version, 'sender')]
    if runtime_version:
        candidates.append((runtime_version, 'runtime'))
    if package:
        candidates.append((package['version'], 'package'))
    desired, owner = max(candidates, key=lambda value: version_key(value[0]))
    if owner != 'sender':
        if verbose:
            print(_t('目标机已有较新 CLI {0}，保留新版兼容本次部署。', desired), flush=True)
        if owner == 'package':
            code = 'import domino_cli,sys;from pathlib import Path;domino_cli.copy_cli(Path(sys.argv[1]))'
            checked_run([package['python'], '-I', '-c', code, str(stage)], stage=_t('准备新版目标 CLI'))
        else:
            shutil.rmtree(stage / 'cli')
            shutil.copytree(runtime, stage / 'cli')
        shutil.copy2(stage / 'cli/install_domino.py', stage / 'install_domino.py')
    if source_version(stage / 'cli/domino_cli.py') != desired:
        raise SyncError(_t('目标新版 CLI 准备失败，未部署。'))
    wheel = stage / f'domino_proxy-{desired}-py3-none-any.whl'
    if package and version_key(package['version']) < version_key(desired):
        # Build from the negotiated source, including when the runtime is newer
        # than both the sender and the package-managed entry point.
        uploaded = stage / f'domino_proxy-{sender_version}-py3-none-any.whl'
        with zipfile.ZipFile(uploaded) as archive:
            license_bytes = archive.read(f'domino_proxy-{sender_version}.dist-info/licenses/LICENSE')
        files = module_files(stage / 'cli')
        make_wheel(files, wheel, desired, license_bytes)
        checked_run([package['python'], '-m', 'pip', '--version'], stage=_t('检查目标虚拟环境 pip'))
    manifest['cli_version'] = desired
    manifest['deployment_output'] = 'detailed' if verbose else 'compact'
    manifest_path.write_text(json.dumps(manifest))
    installer_python = package['python'] if owner == 'package' else sys.executable
    command = [installer_python, str(stage / 'install_domino.py'), 'install', str(stage)]
    install_log = ''
    if verbose:
        checked_run(command, stage=_t('目标运行环境部署'), capture=False, timeout=600)
    else:
        print(_t('  安装      服务与出网检查…'), flush=True)
        # Keep stderr and /dev/tty attached so sudo authentication and failures
        # remain visible. Only routine installer stdout is folded away.
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as log:
            try:
                checked_run(command, stage=_t('目标运行环境部署'), capture=False, timeout=600, output=log)
            except SyncError:
                log.seek(0)
                print(log.read()[-6000:], file=sys.stderr, end='')
                raise
            log.seek(0)
            install_log = log.read()
        print(_t('  同步      CLI 版本检查…'), flush=True)
    if package and version_key(package['version']) < version_key(desired):
        if verbose:
            print(_t('同步目标 CLI：{0} → {1}（原虚拟环境，离线更新）', package['version'], desired), flush=True)
        checked_run([package['python'], '-m', 'pip', 'install', '--no-index', '--no-deps',
                     '--disable-pip-version-check', '--upgrade', str(wheel)], stage=_t('目标 CLI 更新'))
    actual = checked_run([str(launcher), '--version'], stage=_t('目标 CLI 版本核验')).strip()
    if actual != desired:
        raise SyncError(_t('运行环境已部署，但目标命令仍为 {0}，预期 {1}。', actual if re.fullmatch('[0-9.]+', actual) else _t('未知版本'), desired))
    print(_t('  接通      系统代理…'), flush=True)
    proxy_state = connect_system_proxy(installer_python, stage, batch=bool(manifest.get('non_interactive')))
    report_path = stage / 'deployment-result.json'
    report = json.loads(report_path.read_text()) if report_path.is_file() else {}
    # Older compatible installers have no structured report; read public facts
    # from the deployed files and their bounded, non-secret status output.
    config_path = home / '.local/share/domino/data/config.json'
    if config_path.is_file():
        config = json.loads(config_path.read_text())
        report.setdefault('node_count', len(config.get('proxies', [])))
        report.setdefault('provider_count', len(config.get('proxy-providers', {})))
    country = re.search(r'(?:出口地区：|exit region: )([A-Z]{2})\b', install_log)
    if country:
        report.setdefault('exit_country', country[1])
    policy_path = home / '.local/share/domino/shell-policy.json'
    if policy_path.is_file():
        try:
            enabled = json.loads(policy_path.read_text()).get('enabled')
            if type(enabled) is bool:
                report.setdefault('shell_enabled', enabled)
        except (OSError, ValueError):
            pass
    report.update(schema=1, verified=True, cli_version=actual,
                  cli_before=package['version'] if package else runtime_version,
                  kept_newer=version_key(actual) > version_key(sender_version))
    report.update(proxy_state)
    (stage / 'deployment-summary.json').write_text(json.dumps(report))
    if verbose:
        print(_t('目标 CLI 已核验：{0}（{1}）', actual, launcher), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage')
    parser.add_argument('version')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    try:
        deploy(Path(args.stage).resolve(), args.version, verbose=args.verbose)
    except (SyncError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, SyncError) else type(error).__name__
        print(_t('失败：部署或 CLI 同步未完成：') + message, file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print(_t('同步已取消，请检查目标运行环境与 CLI 版本。'), file=sys.stderr)
        raise SystemExit(130)
