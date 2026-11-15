"""Private, standard-library-only terminal proxy policy and shell integration.

The helper only prints assignments for a fixed allowlist of variables. Parent
values travel on stdin, never command arguments or files. Ownership metadata is
inherited in the environment so nested shells do not snapshot Domino as a user
baseline. It is bookkeeping, not an authentication or security boundary.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Optional

VARIABLES = ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
             'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY')
NO_PROXY = 'localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'
STATE_VAR = '_DOMINO_SHELL_STATE'
MAX_INPUT = 4 * 1024 * 1024


def read_policy(app: Path) -> dict:
    """Missing policy means off; malformed or unsupported policy is an error."""
    path = Path(app) / 'shell-policy.json'
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {'version': 1, 'enabled': False}
    except (OSError, ValueError) as exc:
        raise ValueError('Invalid terminal proxy policy') from exc
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value['version'] != 1 or type(value.get('enabled')) is not bool
            or set(value) != {'version', 'enabled'}):
        raise ValueError('Invalid terminal proxy policy')
    return value


def proxy_port(app: Path) -> int:
    try:
        value = json.loads((Path(app) / 'data/config.json').read_text())['mixed-port']
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError('Invalid terminal proxy port')
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('Invalid terminal proxy port') from exc


def status(app: Path, home: Path) -> dict:
    """Policy-level status only: a CLI cannot inspect its parent's parameters."""
    policy = read_policy(app)
    try:
        with (Path(home) / '.config/domino/proxy.env').open() as source:
            available = source.readline() == '# Managed by Domino shell integration v1\n'
        available = available and (Path(app) / 'cli/domino_shell.py').is_file()
    except (OSError, UnicodeError):
        available = False
    return {'version': 1, 'enabled': policy['enabled'], 'scope': 'user-policy',
            'policy_only': True, 'current_shell_applied': False,
            'integration_available': available,
            'note': 'Policy only; source ~/.config/domino/proxy.env to activate integration. '
                    'Existing IDE processes retain their environment.'}


def legacy_environment_port(text: str, platform: str) -> Optional[int]:
    """Recognize only the two complete historical generated templates."""
    if platform not in ('linux', 'darwin', 'macos'):
        return None
    match = re.search(r'^export http_proxy=http://127\.0\.0\.1:(\d+)$', text, re.M)
    if not match or not 1024 <= int(match[1]) <= 65535:
        return None
    number = int(match[1])
    upper_https = '$https_proxy' if platform == 'linux' else '$http_proxy'
    expected = f'''export PATH="$HOME/.local/bin:$PATH"
export http_proxy=http://127.0.0.1:{number}
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="{upper_https}"
export all_proxy=socks5h://127.0.0.1:{number}
export ALL_PROXY="$all_proxy"
export no_proxy={NO_PROXY}
export NO_PROXY="$no_proxy"
'''
    return number if text == expected else None


def _desired(port: int) -> dict:
    return {name: (NO_PROXY if name.lower() == 'no_proxy' else
                   f'{"socks5h" if name.lower() == "all_proxy" else "http"}://127.0.0.1:{port}')
            for name in VARIABLES}


def _snapshot(value: dict) -> dict:
    return {key: value[key] for key in ('present', 'exported', 'value')}


def _valid_snapshot(value) -> bool:
    return (isinstance(value, dict) and set(value) == {'present', 'exported', 'value'}
            and type(value['present']) is bool and type(value['exported']) is bool
            and isinstance(value['value'], str) and '\0' not in value['value']
            and (value['present'] or (not value['exported'] and value['value'] == '')))


def _decode_state(encoded: str, app: Path, pid: str) -> dict:
    empty = {'version': 1, 'app': str(Path(app).absolute()), 'pid': pid,
             'owned': {}, 'detached': []}
    try:
        raw = base64.b64decode(encoded, validate=True)
        state = json.loads(raw)
        if (not isinstance(state, dict) or state.get('version') != 1
                or state.get('app') != empty['app'] or not isinstance(state.get('pid'), str)
                or not isinstance(state.get('owned'), dict)
                or not isinstance(state.get('detached'), list)
                or any(name not in VARIABLES for name in state['detached'])):
            return empty
        for name, item in state['owned'].items():
            if (name not in VARIABLES or not isinstance(item, dict)
                    or set(item) != {'baseline', 'last'}
                    or not _valid_snapshot(item['baseline'])
                    or not _valid_snapshot(item['last'])):
                return empty
        if state['pid'] != pid:
            # A real child process inherits exported values, not the parent's
            # unexported baseline. Restoring such a baseline would invent state.
            for item in state['owned'].values():
                if not item['baseline']['exported']:
                    item['baseline'] = {'present': False, 'exported': False, 'value': ''}
        state['pid'] = pid
        return state
    except (ValueError, TypeError, KeyError, UnicodeError):
        return empty


def sync_state(app: Path, current: dict, *, metadata: str = '', pid: str = '',
               mode: str = 'auto', intent: str = 'auto', legacy_port: Optional[int] = None) -> str:
    """Return trusted shell assignments from validated parent snapshots.

    Automatic sync never takes over an existing, unowned parameter. An explicit
    local on can do so, preserving its presence and export flag independently.
    """
    enabled = read_policy(app)['enabled']
    if mode == 'manual' and intent not in ('on', 'off'):
        return ''
    if intent not in ('auto', 'on', 'off'):
        raise ValueError('Invalid shell intent')
    if set(current) != set(VARIABLES):
        raise ValueError('Invalid parent shell state')
    for value in current.values():
        if not isinstance(value, dict) or type(value.get('readonly')) is not bool or not _valid_snapshot(
                {key: value.get(key) for key in ('present', 'exported', 'value')}):
            raise ValueError('Invalid parent shell state')
    state = _decode_state(metadata, app, pid)
    owned, detached = state['owned'], set(state['detached'])
    reported = {name: _snapshot(value) for name, value in current.items()}
    commands = []
    if intent in ('on', 'off'):
        commands.append('export DOMINO_SHELL_MODE=auto')
    desired = _desired(proxy_port(app)) if enabled else {}
    legacy = _desired(legacy_port) if legacy_port else {}
    legacy_count = 0
    readonly_count = 0
    for name in VARIABLES:
        actual = current[name]
        snapshot = _snapshot(actual)
        item = owned.get(name)
        if item and snapshot != item['last']:
            del owned[name]
            detached.add(name)
            item = None
        if actual['readonly']:
            readonly_count += 1
            owned.pop(name, None)
            detached.add(name)
            continue
        legacy_match = (not item and name not in detached and legacy
                        and actual['present'] and actual['value'] == legacy[name])
        if legacy_match:
            item = {'baseline': {'present': False, 'exported': False, 'value': ''},
                    'last': snapshot}
            owned[name] = item
            legacy_count += 1
        if enabled:
            if not item and (intent == 'on' or (not actual['present'] and name not in detached)):
                item = {'baseline': snapshot, 'last': snapshot}
                owned[name] = item
                detached.discard(name)
            if item:
                last = {'present': True, 'exported': True, 'value': desired[name]}
                if last != snapshot:
                    commands.append(f'export {name}={shlex.quote(last["value"])}')
                item['last'] = last
                reported[name] = last
        elif item:
            baseline = item['baseline']
            if not baseline['present']:
                commands.append(f'unset {name}')
            else:
                commands.append(f'{name}={shlex.quote(baseline["value"])}')
                commands.append(f'export {name}' if baseline['exported'] else f'_domino_shell_unexport {name}')
            reported[name] = baseline
            del owned[name]
    state['detached'] = sorted(detached)
    encoded = base64.b64encode(json.dumps(state, separators=(',', ':')).encode()).decode()
    commands.append(f'export {STATE_VAR}={shlex.quote(encoded)}')
    manual = sum(name not in owned and (reported[name]['present'] or name in detached)
                 for name in VARIABLES)
    summary = (f'policy={"on" if enabled else "off"} managed={len(owned)} '
               f'manual={manual} readonly={readonly_count} '
               f'restorable={len(owned)}')
    commands.append(f'_DOMINO_SHELL_SUMMARY={shlex.quote(summary)}')
    if intent in ('on', 'off') and readonly_count:
        commands.append("printf '%s\\n' 'Domino: readonly proxy parameters skipped; terminal application is partial.' >&2")
    if legacy_count:
        commands.append("printf '%s\\n' 'Domino: removing/adopting recognized legacy proxy values; their original baseline is unknown.' >&2")
    return '\n'.join(commands) + '\n'


def _collect_source() -> str:
    lines = ["printf '%s\\0' domino-shell-v1 \"$$\" \"${DOMINO_SHELL_MODE-auto}\" \"${1-auto}\" \"${_DOMINO_SHELL_STATE-}\""]
    for name in VARIABLES:
        lines.extend([
            '_domino_flags=',
            'if [ -n "${ZSH_VERSION-}" ]; then',
            f'  _domino_flags=${{(t){name}}}',
            f'elif [ -n "${{BASH_VERSION-}}" ]; then',
            f'  _domino_flags=$(declare -p {name} 2>/dev/null) || _domino_flags=',
            '  _domino_flags=${_domino_flags#declare }',
            '  _domino_flags=${_domino_flags%% *}',
            'else',
            # POSIX export -p uses shell quoting, but only the identifier and
            # attribute are inspected; values never become command arguments.
            f'  if export -p | grep -q "^export {name}="; then _domino_flags=-x; fi',
            'fi',
            '_domino_exported=0; _domino_readonly=0',
            'case "$_domino_flags" in *export*|-*x*) _domino_exported=1;; esac',
            'case "$_domino_flags" in *readonly*|-*r*) _domino_readonly=1;; esac',
            'if [ -n "${ZSH_VERSION-}" ]; then',
            '  case "$_domino_flags" in ""|scalar|scalar-export|scalar-readonly|scalar-export-readonly|scalar-readonly-export) ;; *) _domino_readonly=1;; esac',
            'elif [ -n "${BASH_VERSION-}" ]; then',
            '  case "$_domino_flags" in ""|--|-x|-r|-rx|-xr) ;; *) _domino_readonly=1;; esac',
            'else',
            f'  if readonly 2>/dev/null | grep -q "^readonly {name}="; then _domino_readonly=1; fi',
            'fi',
            f'printf \'%s\\0\' "${{{name}+1}}" "$_domino_exported" "$_domino_readonly" "${{{name}-}}"',
        ])
    return '\n'.join(lines)


def integration(app: Path, python: str, legacy_port: Optional[int] = None) -> str:
    """Generate a stable sourceable loader; no HOME writes or user rc edits."""
    app = Path(app).absolute()
    helper = app / 'cli/domino_shell.py'
    command = f'{shlex.quote(python)} -I {shlex.quote(str(helper))} sync --app {shlex.quote(str(app))}'
    if legacy_port is not None:
        if type(legacy_port) is not int or not 1024 <= legacy_port <= 65535:
            raise ValueError('Invalid legacy proxy port')
        command += f' --legacy-port {legacy_port}'
    header = '# Managed by Domino shell integration v1\n'
    if legacy_port is not None:
        header += f'# Legacy proxy port: {legacy_port}\n'
    return header + '''# Policy is stored only in shell-policy.json.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH";;
esac
_domino_shell_unexport() {
  if [ -n "${ZSH_VERSION-}" ]; then typeset -g +x "$1"
  elif [ -n "${BASH_VERSION-}" ]; then export -n "$1"
  else
    # POSIX sh has no unexport operation. This path only captures exported
    # baselines; bash and zsh retain their full parameter attributes.
    :
  fi
}
_domino_shell_collect() {
''' + _collect_source() + '''
}
_domino_shell_sync() {
  _domino_sync_code=$(_domino_shell_collect "${1-auto}" | ''' + command + ''' 2>/dev/null) || {
    _DOMINO_SHELL_SUMMARY=unavailable
    unset _domino_sync_code
    return 0
  }
  [ -z "$_domino_sync_code" ] || eval "$_domino_sync_code"
  unset _domino_sync_code
}
_domino_shell_sync auto
case $- in
  *i*)
    domino() {
      local _domino_rc _domino_intent=auto _domino_show_status=
      local _domino_action=status _domino_safe=1 _domino_json= _domino_target= _domino_argument
      command domino "$@"
      _domino_rc=$?
      if [ "$_domino_rc" -eq 0 ] && [ "${1-}" = shell ]; then
        shift
        case "${1-}" in on|off|status) _domino_action=$1; shift;; esac
        while [ "$#" -gt 0 ]; do
          _domino_argument=$1
          while [ "${_domino_argument%.}" != "$_domino_argument" ]; do
            _domino_argument=${_domino_argument%.}
          done
          case "$_domino_argument" in
            --json) _domino_json=1;;
            --batch) ;;
            [lL][oO][cC][aA][lL][hH][oO][sS][tT]|127.0.0.1|::1|'[::1]')
              if [ -n "$_domino_target" ]; then _domino_safe=; fi
              _domino_target=1;;
            *) _domino_safe=;;
          esac
          shift
        done
        if [ -n "$_domino_safe" ]; then
          case "$_domino_action" in
            on|off) _domino_intent=$_domino_action;;
            status) [ -n "$_domino_json" ] || _domino_show_status=1;;
          esac
        fi
      fi
      _domino_shell_sync "$_domino_intent"
      if [ "$_domino_rc" -eq 0 ] && [ -n "$_domino_show_status" ]; then
        if [ "${DOMINO_SHELL_MODE-auto}" = manual ]; then
          printf '%s\\n' 'Current shell: manual mode (policy sync paused).'
        else
          printf 'Current shell: %s\\n' "${_DOMINO_SHELL_SUMMARY-unavailable}"
        fi
      fi
      return "$_domino_rc"
    }
    _domino_shell_prompt() {
      local _domino_prompt_rc=$?
      _domino_shell_sync auto
      return "$_domino_prompt_rc"
    }
    if [ -n "${ZSH_VERSION-}" ]; then
      eval 'if (( ! ${precmd_functions[(Ie)_domino_shell_prompt]} )); then
        precmd_functions+=(_domino_shell_prompt)
      fi'
    elif [ -n "${BASH_VERSION-}" ]; then
      eval '
      case "$(declare -p PROMPT_COMMAND 2>/dev/null)" in
        "declare -a "*)
          _domino_hook_found=
          for _domino_hook in "${PROMPT_COMMAND[@]}"; do
            [ "$_domino_hook" != _domino_shell_prompt ] || _domino_hook_found=1
          done
          [ -n "$_domino_hook_found" ] || PROMPT_COMMAND=(_domino_shell_prompt "${PROMPT_COMMAND[@]}")
          unset _domino_hook _domino_hook_found
          ;;
        *)
          case ";${PROMPT_COMMAND-};" in
            *"_domino_shell_prompt;"*) ;;
            *) PROMPT_COMMAND="_domino_shell_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}";;
          esac
          ;;
      esac'
    fi
    ;;
esac
'''


def _read_parent(raw: bytes) -> tuple:
    parts = raw.decode('utf-8', 'surrogateescape').split('\0')
    if len(parts) != 5 + len(VARIABLES) * 4 + 1 or parts[-1] or parts[0] != 'domino-shell-v1':
        raise ValueError('Invalid parent shell protocol')
    current = {}
    for index, name in enumerate(VARIABLES):
        present, exported, readonly, value = parts[5 + index * 4:9 + index * 4]
        if present not in ('', '1') or exported not in ('0', '1') or readonly not in ('0', '1'):
            raise ValueError('Invalid parent shell attributes')
        current[name] = {'present': present == '1', 'exported': exported == '1',
                         'readonly': readonly == '1', 'value': value}
    return current, dict(pid=parts[1], mode=parts[2], intent=parts[3], metadata=parts[4])


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Private Domino parent-shell synchronizer')
    parser.add_argument('command', choices=['sync'])
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--legacy-port', type=int)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('Parent shell state too large')
        current, options = _read_parent(raw)
        code = sync_state(args.app, current, legacy_port=args.legacy_port, **options)
        sys.stdout.buffer.write(code.encode('utf-8', 'surrogateescape'))
    except (OSError, ValueError, TypeError):
        # Prompt synchronization fails closed: never emit partially generated code.
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
