# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Give the user LaunchAgent a responsible app without modifying the core."""
from domino_i18n import tr as _t
from pathlib import Path
import plistlib
import subprocess

BUNDLE_ID = 'io.github.kjaebye.domino'
APP_NAME = 'Domino.app'
EXECUTABLE = Path('Contents/MacOS/Domino')
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def app_path(runtime):
    return runtime / APP_NAME


def command(runtime, data=None):
    data = data or runtime / 'data'
    return [str(app_path(runtime) / EXECUTABLE), str(runtime / 'mihomo'),
            '-d', str(data), '-f', str(data / 'config.json')]


def register(ctx, runtime, *, remove=False):
    app = app_path(runtime)
    if not app.exists():
        return
    # Only touch the app in our private runtime, never a similarly named user app.
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != BUNDLE_ID or info.get('DominoManaged') != 1:
        raise ctx.InstallError(_t('Domino 应用身份不匹配，未修改注册。'))
    try:
        subprocess.run([LSREGISTER, '-u' if remove else '-f', str(app)],
                       capture_output=True, check=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise ctx.InstallError(_t('无法注册 Domino 本地网络应用身份。')) from None


def prepared(ctx):
    from domino_macos_app_build import prepared as build
    return build(ctx)
