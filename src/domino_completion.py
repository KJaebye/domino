# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Shell completion using parser metadata and local JSON files, without I/O writes."""
from domino_i18n import tr as _t
import argparse
import json
from pathlib import Path
import sys

SCRIPTS = {
    'bash': r'''# Domino Bash completion (Bash 3.2+)
_domino_complete() {
    local line mode reply quoted
    COMPREPLY=()
    reply=$(command "${COMP_WORDS[0]}" completion --query -- "${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null) || return 0
    mode=${reply%%$'\n'*}
    [ "$reply" != values ] || return 0
    if [ "$mode" = files ]; then
        reply=$(compgen -f -- "${COMP_WORDS[COMP_CWORD]}")
    else
        reply=${reply#*$'\n'}
    fi
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            case "$line" in
                *[!a-zA-Z0-9_./:@%+=,-]*) quoted=${line//\'/\'\\\'\'}; quoted="'$quoted'";;
                *) quoted=$line;;
            esac
            COMPREPLY[${#COMPREPLY[@]}]=$quoted
        fi
    done <<< "$reply"
}
complete -F _domino_complete domino
''',
    'zsh': r'''#compdef domino
_domino() {
    local -a reply
    reply=("${(@f)$(command "${words[1]}" completion --query -- "${words[@]:1:$((CURRENT-1))}" 2>/dev/null)}")
    if [[ ${reply[1]} = files ]]; then
        _files
    else
        (( ${#reply} > 1 )) && compadd -- "${reply[@]:1}"
    fi
}
if [[ ${funcstack[1]} = _domino ]]; then
    _domino "$@"
elif [[ -o interactive ]]; then
    if (( ! $+functions[compdef] )); then
        autoload -Uz compinit
        compinit -D -i
    fi
    compdef _domino domino
fi
''',
}
PATH_OPTIONS = {'--source', '--bundle', '--core', '--identity', '--resource-dir',
                '--controller-socket', '--vscode-settings', '--output-dir'}


def read_json(path):
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def names(kind):
    home = Path.home()
    if kind == 'config':
        return [item.get('name') for item in read_json(home / '.config/domino/subscriptions/index.json').get('items', [])
                if isinstance(item, dict)]
    data = home / '.local/share/domino/data'
    config = read_json(data / 'config.json')
    result = [item.get('name') for item in config.get('proxy-groups', []) if isinstance(item, dict)]
    if kind != 'group':
        result += [item.get('name') for item in config.get('proxies', []) if isinstance(item, dict)]
        for provider in config.get('proxy-providers', {}).values():
            if isinstance(provider, dict):
                result += [item.get('name') for item in provider.get('payload', []) if isinstance(item, dict)]
                if provider.get('path'):
                    try:
                        path = (data / provider['path']).resolve()
                        path.relative_to(data.resolve())
                        if path.stat().st_size <= 16 * 1024 * 1024:
                            from domino_cli import load_yaml
                            cached = load_yaml(path)
                            result += [item.get('name') for item in cached.get('proxies', []) if isinstance(item, dict)]
                    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
                        pass
    return result


def subcommands(parser):
    action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    return ({a.dest: action.choices[a.dest] for a in action._choices_actions
             if a.help != argparse.SUPPRESS} if action else {})


def candidates(words):
    import domino_cli
    parser = domino_cli.build_parser(advanced_delay_help=True)
    words = list(words) or ['']
    prefix, previous = words[-1], words[:-1]
    root = subcommands(parser)
    remote = bool(previous and previous[0] not in root and not previous[0].startswith('-'))
    if remote:
        previous.pop(0)
    command, positionals, pending = '', [], None
    for value in previous:
        if pending is not None:
            pending = None
        elif value.startswith('-'):
            option = parser._option_string_actions.get(value.split('=', 1)[0])
            if option and option.nargs != 0 and '=' not in value:
                pending = option
        elif value in subcommands(parser) and not positionals:
            parser = subcommands(parser)[value]
            command = value
        else:
            positionals.append(value)
    if pending:
        if pending.option_strings and pending.option_strings[0] in PATH_OPTIONS:
            return 'files', []
        choices = list(pending.choices or [])
        if not remote and pending.dest in ['config', 'group', 'node']:
            choices += names({'config': 'config', 'group': 'group', 'node': 'node'}[pending.dest])
    elif prefix.startswith('-'):
        choices = [flag for action in parser._actions if action.help != argparse.SUPPRESS
                   for flag in action.option_strings]
    elif subcommands(parser):
        choices = list(subcommands(parser))
    else:
        choices = []
        actions = [a for a in parser._actions if not a.option_strings and a.help != argparse.SUPPRESS]
        if len(positionals) < len(actions):
            choices += list(actions[len(positionals)].choices or [])
        if not remote and not positionals:
            if command in ['switch', 'update', 'remove', 'rename', 'set-url', 'test']:
                choices += names('config')
            if command in ['select', 'test']:
                choices += names('node')
        if command in ['update', 'test'] and not positionals:
            choices.append('all')
        if command == 'rules' and not positionals:
            choices += ['add', 'remove']
    return 'values', sorted({v for v in choices if isinstance(v, str) and v.startswith(prefix)
                             and v and all(c.isprintable() for c in v)})


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == ['--query', '--']:
        try:
            mode, values = candidates(argv[2:])
        except (OSError, ValueError, TypeError, AttributeError):
            mode, values = 'values', []
        print(mode + '\n' + '\n'.join(values))
        return 0
    parser = argparse.ArgumentParser(prog='domino completion', description=_t('输出 Tab 补全脚本；source 后在当前 shell 生效。'))
    parser.add_argument('shell', choices=['zsh', 'bash'])
    args = parser.parse_args(argv)
    print(SCRIPTS[args.shell], end='')
    return 0
