# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Explicit message localization; configuration and user values are never translated."""
import json
import os
from pathlib import Path
import tempfile
from functools import lru_cache

from domino_translations import ENGLISH


def normalize(value):
    value = str(value).lower().replace('_', '-')
    if value in ('zh', 'zh-cn', 'zh-hans'):
        return 'zh'
    if value in ('en', 'en-us', 'en-gb'):
        return 'en'
    raise ValueError('Language must be zh or en / 语言必须是 zh 或 en。')


def preference_path():
    return Path.home() / '.config/domino/preferences.json'


@lru_cache(maxsize=8)
def _read_preference(path, modified, size):
    try:
        value = json.loads(Path(path).read_text())
        return normalize(value['language']) if isinstance(value, dict) else 'en'
    except (OSError, ValueError, KeyError, TypeError):
        return 'en'


def get_language():
    if os.environ.get('DOMINO_LANG'):
        try:
            return normalize(os.environ['DOMINO_LANG'])
        except ValueError:
            pass
    path = preference_path()
    try:
        if any(p.is_symlink() for p in [path, path.parent, path.parent.parent]):
            return 'en'
        info = path.stat()
        if info.st_size > 65536:
            return 'en'
        return _read_preference(str(path), info.st_mtime_ns, info.st_size)
    except OSError:
        return 'en'


def tr(message, *values):
    template = ENGLISH.get(message, message) if get_language() == 'en' else message
    return template.format(*values) if values else template


def configure(arguments):
    """Apply a one-command override before argparse or any child process runs."""
    result = []
    selected = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == '--':
            result.extend(arguments[index:])
            break
        if argument == '--lang':
            index += 1
            if index == len(arguments):
                raise ValueError('--lang requires zh or en / --lang 需要 zh 或 en。')
            selected = normalize(arguments[index])
        elif argument.startswith('--lang='):
            selected = normalize(argument.split('=', 1)[1])
        else:
            result.append(argument)
        index += 1
    os.environ['DOMINO_LANG'] = selected or get_language()
    return result


def set_language(value):
    selected = normalize(value)
    path = preference_path()
    if any(p.is_symlink() for p in [path, path.parent, path.parent.parent]):
        raise ValueError('Language preference path must not be a symlink / 语言设置路径不能是符号链接。')
    existing = {}
    if path.exists():
        if path.stat().st_size > 65536:
            raise ValueError('Invalid language preferences / 语言设置无效。')
        existing = json.loads(path.read_text())
        if not isinstance(existing, dict):
            raise ValueError('Invalid language preferences / 语言设置无效。')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.preferences-', dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(dict(existing, language=selected), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    _read_preference.cache_clear()
    os.environ['DOMINO_LANG'] = selected
    return selected
