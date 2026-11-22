# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Persistent slash-command terminal workspace over the regular CLI commands."""
from __future__ import annotations
from domino_i18n import tr as _t

import asyncio
from dataclasses import dataclass, field
import importlib
import inspect
import json
from pathlib import Path
import re
import shlex
import sys
import time

COMMANDS = [
    ('/language', '切换中英文界面'),
    ('/nodes', '当前配置、代理链路和节点'), ('/select', '按名称或关键词选择节点'),
    ('/catch', '选择配置或捕获全部'), ('/mode', '规则 / 全局 / 直连模式'),
    ('/doctor', '诊断系统直连与代理，支持指定 HTTPS 地址'),
    ('/status', '检查服务和真实 HTTPS 出网'), ('/test', '选择全部配置、单个配置或节点检测'),
    ('/scan', '扫描当前目标的配置和代理入口出网'),
    ('/traffic', '选择内嵌或全屏动态流量面板'), ('/connections', '查看或选择关闭连接'),
    ('/rules', '查看、添加或选择删除自定义规则'), ('/providers', '选择节点 / 规则集合'),
    ('/list', '查看配置与管理面板'), ('/add', '添加配置'), ('/switch', '切换配置'),
    ('/update', '更新配置或 all'), ('/remove', '删除配置'), ('/rename', '重命名配置'), ('/set-url', '修改订阅地址'),
    ('/refresh', '立即刷新状态和流量'),
    ('/logs', '最近的内核日志'), ('/log', '查看或设置日志级别'),
    ('/shell', '终端代理：开启 / 关闭 / 状态'), ('/start', '开启 Domino，接通系统代理'),
    ('/stop', '关闭 Domino，恢复系统代理'), ('/restart', '重启并重新接通系统代理'),
    ('/uninstall', '预览或卸载运行环境，清理配置与终端接入'),
    ('/help', '命令与快捷键'), ('/clear', '清空本次操作记录'), ('/exit', '退出界面，也可输入 exit 或按 Ctrl+D'),
]

LOGO_LINES = (
    '█▀▄ █▀█ █▄ ▄█ █ █▄ █ █▀█',
    '█ █ █ █ █ ▀ █ █ █ ▀█ █ █',
    '▀▀  ▀▀▀ ▀   ▀ ▀ ▀  ▀ ▀▀▀',
)


def command_banner(data, version, *, columns=100, color=None):
    """Static CLI rendering of the workspace logo; no toolkit or network dependency."""
    from install_domino import human_style, human_width
    def text(value):
        return clean(value).replace('\n',' ').replace('\t',' ')
    def clip(value, width):
        value=text(value)
        if human_width(value)<=width: return value
        while value and human_width(value+'…')>width: value=value[:-1]
        return value+'…' if width else ''
    def style(value, code): return human_style(value,code,color=color)
    mode={'rule':_t('规则'),'global':_t('全局'),'direct':_t('直连')}.get(str(data.get('mode')),_t('模式未知'))
    metadata='localhost  ·  '+text(data.get('subscription') or (_t('未关联配置库') if data.get('installed') else _t('未初始化')))+'  ·  '+mode
    status=_t('未初始化') if not data.get('installed') else _t('接口在线 · 出网未检测') if data.get('reachable') else _t('接口离线')
    tone='33' if not data.get('installed') else '32' if data.get('reachable') else '31'
    if data.get('awaiting_subscription') and data.get('reachable'):status,tone=_t('待添加订阅'),'33'
    status_line='● '+status
    if data.get('proxy_port'):status_line+=f"  ·  :{data['proxy_port']}"
    if data.get('node_count') is not None:
        status_line+=_t('  ·  {0} 节点 / {1} 组', data['node_count'], data['group_count'])
    build=data.get('cli_build') or {}
    build_label=(' · '+text(build['build_id'])) if build.get('build_id') else ''
    rows=[('Domino  v'+text(version)+build_label,'1'),(metadata,'2'),(status_line,tone)]
    def render(index, width):
        value=clip(rows[index][0],width)
        if index==0: return style(value[:6],'1')+style(value[6:],'2')
        if index==2: return style(value[:1],tone)+style(value[1:],'2')
        return style(value,'2')
    columns=max(3,columns)
    if columns<76:
        return '\n'.join('  '+render(index,columns-2) for index in range(len(rows)))
    available=columns-6-human_width(LOGO_LINES[0])
    return '\n'.join('  '+style(logo,'1;36')+'    '+render(index,available)
                     for index,logo in enumerate(LOGO_LINES))

SGR = re.compile(r'\x1b\[[0-9;]*m')
TERMINAL_ESCAPE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]|\x1b[@-_]')


def clean(value):
    text=TERMINAL_ESCAPE.sub('',str(value))
    return ''.join(c for c in text if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


class StyledLine(str):
    """Keep readable event text alongside its presentation fragments."""
    def __new__(cls, fragments):
        value=super().__new__(cls,''.join(text for _,text in fragments))
        value.fragments=fragments
        return value


def command_lines(value):
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    # Pass only graphic rendition codes to the formatter; other controls are text-cleaned.
    text=str(value)
    parts,last=[],0
    for match in SGR.finditer(text):
        parts.extend([clean(text[last:match.start()]),match.group()])
        last=match.end()
    parts.append(clean(text[last:]))
    lines,length=[[]],0
    for style,char in to_formatted_text(ANSI(''.join(parts))):
        if char=='\n':
            if len(lines)==80: break
            lines.append([])
            length=0
        elif length<2000:
            if lines[-1] and lines[-1][-1][0]==style:
                previous=lines[-1][-1][1]
                lines[-1][-1]=(style,previous+char)
            else:
                lines[-1].append((style,char))
            length+=len(char)
    if lines and not lines[-1]: lines.pop()
    return [StyledLine(line) for line in lines]


def format_bytes(value, rate=False):
    if value is None:
        return '—'
    number = max(0, value)
    units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    index = 0
    while number >= 1024 and index < len(units)-1:
        number /= 1024
        index += 1
    amount = f'{number:.2f}' if rate and 0 < number < 1 else f'{number:.0f}' if index == 0 else f'{number:.1f}'
    return amount + ' ' + units[index] + ('/s' if rate else '')


def traffic_notice(snapshot):
    number = snapshot.get('proxy_port')
    scope = f'Domino :{number}' if number else 'Domino'
    routing = snapshot.get('system_proxy', {})
    state = routing.get('routing')
    if state == 'other':
        ports = '/'.join(str(p) for p in routing.get('ports', []))
        return _t('仅统计 {0}；系统代理仍指向其他代理', scope) + (f' :{ports}' if ports else '')
    if state == 'mixed':
        return _t('仅统计 {0}；部分系统代理指向其他代理', scope)
    if state == 'pac':
        return _t('仅统计 {0}；系统使用 PAC / 自动发现', scope)
    if state == 'off':
        return _t('仅统计 {0}；系统代理未开启，应用需单独设置代理', scope)
    return _t('仅统计 {0}，不包含其他代理或系统总流量', scope)


def parse_command(text):
    parts = shlex.split(text.strip())
    if not parts:
        return '', []
    name = '/' + parts[0].lstrip('/')
    if name in ['/q', '/quit']:
        name = '/exit'
    name = {'/delay': '/test'}.get(name, name)
    if name not in dict(COMMANDS) and name != '/proxy':
        raise ValueError(_t('未知命令，输入 /help 查看可用操作。'))
    if name == '/shell' and parts[1:] not in [[], ['status'], ['on'], ['off']]:
        raise ValueError(_t('用法：/shell status，/shell on，/shell off。'))
    return name, parts[1:]


@dataclass
class Panel:
    title: str
    items: list
    callback: object
    query: str = ''
    index: int = 0
    kind: str = ''

    def filtered(self):
        return [v for v in self.items if self.query.casefold().strip() in str(v.get('search',v['label'])).casefold()]

    def move(self, amount):
        values = self.filtered()
        self.index = (self.index + amount) % len(values) if values else 0

    def selected(self):
        values = self.filtered()
        return values[min(self.index, len(values) - 1)] if values else None


@dataclass
class State:
    target: str
    snapshot: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    panel: object = None
    delays: dict = field(default_factory=dict)
    up: object = None
    down: object = None
    sampled_at: float = 0
    updated_at: float = 0
    busy: str = ''
    last_error: str = ''
    scroll: int = 0
    traffic_open: bool = False
    traffic_history: list = field(default_factory=list)
    progress: str = ''

    def append(self, kind, text, *, ansi=False):
        lines=command_lines(text) if ansi and SGR.search(str(text)) else [line[:2000] for line in clean(text).splitlines()[:80]]
        for line in lines:
            self.events.append((kind, line))
        self.events = self.events[-400:]
        self.scroll = 0

    def update(self, value, now=None):
        now = now if now is not None else time.monotonic()
        elapsed = now - self.sampled_at
        available = value.get('stats_available',value.get('reachable',True))
        previous_available = self.snapshot.get('stats_available',self.snapshot.get('reachable',True))
        valid = (available and previous_available and self.sampled_at and elapsed > 0
                 and value.get('upload_total',0)>=self.snapshot.get('upload_total',0)
                 and value.get('download_total',0)>=self.snapshot.get('download_total',0))
        if valid:
            self.up = (value.get('upload_total', 0) - self.snapshot.get('upload_total', 0)) / elapsed
            self.down = (value.get('download_total', 0) - self.snapshot.get('download_total', 0)) / elapsed
            self.traffic_history=(self.traffic_history+[(self.up,self.down)])[-120:]
        else:
            self.up = self.down = None
            self.traffic_history.clear()
        self.snapshot, self.sampled_at = value, now
        self.updated_at = time.time()
        self.last_error = value.get('error', '')

    def stale(self, message):
        self.last_error = message
        self.up = self.down = None
        self.sampled_at = 0
        self.traffic_history.clear()


def load_toolkit():
    try:
        return importlib.import_module('prompt_toolkit')
    except ImportError:
        for path in [Path(__file__).parent / '_vendor', Path.home() / '.local/share/domino/cli/_vendor']:
            if (path / 'prompt_toolkit').is_dir():
                sys.path.insert(0, str(path))
                return importlib.import_module('prompt_toolkit')
    raise RuntimeError(_t('交互界面需要 prompt-toolkit；请安装项目依赖，或更新带 UI 组件的 Domino 安装包。'))


def make_completer():
    from prompt_toolkit.completion import Completer, Completion
    class Commands(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if text.startswith('/') and not any(c.isspace() for c in text):
                for name, description in COMMANDS:
                    if name.startswith(text):
                        yield Completion(name, start_position=-len(text), display_meta=_t(description))
    return Commands()


class Workspace:
    def __init__(self, target, execute, version='', *, input=None, output=None):
        load_toolkit()
        from prompt_toolkit import Application
        from prompt_toolkit.data_structures import Point
        from prompt_toolkit.completion import ConditionalCompleter
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window, FloatContainer, Float, ConditionalContainer
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.menus import CompletionsMenu
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import TextArea

        self.state, self.execute, self.version = State(target), execute, version
        self.job, self.last_interrupt, self.refresh = None, 0, asyncio.Event()
        self.job_mutates = False
        self.config_view,self.config_form,self.config_keep=None,None,None
        self.config_focus,self.config_index='list',0
        self.input = TextArea(multiline=False, height=1, wrap_lines=False, history=InMemoryHistory(),
            prompt=[('class:prompt', '  ❯ ')], style='class:input',
            completer=ConditionalCompleter(make_completer(), Condition(lambda: self.state.panel is None)),
            complete_while_typing=True, accept_handler=self.accept)
        self.input.buffer.on_text_changed += self.on_text_changed
        from prompt_toolkit.history import DummyHistory
        self.form_input=TextArea(multiline=False,height=1,wrap_lines=False,history=DummyHistory(),
            prompt=lambda:[('class:prompt','  '+self.config_form['fields'][0][1]+'： ')] if self.config_form else [],
            password=Condition(lambda:bool(self.config_form and self.config_form['fields'][0][0]=='url')),
            accept_handler=self.accept_config_form)
        transcript = Window(FormattedTextControl(self.transcript_text,
            get_cursor_position=lambda:Point(x=0,y=max(0,len(self.state.events)-1-self.state.scroll))),
            height=Dimension(min=1), wrap_lines=True, always_hide_cursor=True,
            get_vertical_scroll=lambda window: max(0, len(self.state.events) -
                (window.render_info.window_height if window.render_info else 8) - self.state.scroll))
        self.picker_window = Window(FormattedTextControl(self.panel_text,
            get_cursor_position=lambda:Point(x=0,y=self.state.panel.index if self.state.panel else 0)),
            height=lambda: min(7, max(2, len(self.state.panel.filtered()) if self.state.panel else 0)),
            get_vertical_scroll=lambda _: max(0, (self.state.panel.index if self.state.panel else 0) - 4),
            always_hide_cursor=True)
        picker = HSplit([Window(FormattedTextControl(lambda:[('class:muted','  '+self.state.panel.title)] if self.state.panel else []),height=1),
                         self.picker_window])
        composer = HSplit([Window(height=1,char='─',style='class:composer.border'),
                           ConditionalContainer(self.input,filter=Condition(lambda:self.config_form is None)),
                           ConditionalContainer(self.form_input,filter=Condition(lambda:self.config_form is not None)),
                           Window(height=1,char='─',style='class:composer.border')])
        traffic=ConditionalContainer(Window(FormattedTextControl(self.traffic_text),height=self.traffic_height,
                                            always_hide_cursor=True,wrap_lines=False),
                                     filter=Condition(lambda:self.state.traffic_open))
        body = HSplit([Window(height=1),Window(FormattedTextControl(self.header),height=self.header_height),Window(height=1),traffic,transcript,
            ConditionalContainer(picker, filter=Condition(lambda: self.state.panel is not None)),
            ConditionalContainer(Window(FormattedTextControl(self.config_toolbar),height=lambda:3 if self.app.output.get_size().columns>=80 else 5,wrap_lines=True,always_hide_cursor=True),
                                 filter=Condition(self.config_open)),
            Window(height=1), composer, Window(FormattedTextControl(self.footer),height=1)])
        root = FloatContainer(body, floats=[Float(xcursor=True, ycursor=True,
            content=CompletionsMenu(max_height=8, scroll_offset=1), z_index=10)])
        bindings, panel_open = KeyBindings(), Condition(lambda: self.state.panel is not None and self.config_form is None)

        @bindings.add('up', filter=panel_open)
        def up(event):
            self.config_focus='list'
            self.state.panel.move(-1)

        @bindings.add('down', filter=panel_open)
        def down(event):
            self.config_focus='list'
            self.state.panel.move(1)

        @bindings.add('tab',filter=panel_open)
        def tab(event):
            if self.config_open():self.config_focus='list' if self.config_focus=='actions' else 'actions'
            else:self.state.panel.move(1)

        @bindings.add('left',filter=Condition(lambda:self.config_open() and self.config_form is None and self.config_focus=='actions'))
        @bindings.add('right',filter=Condition(lambda:self.config_open() and self.config_form is None and self.config_focus=='actions'))
        def action_move(event):
            self.config_index=(self.config_index+(-1 if event.key_sequence[0].key=='left' else 1))%len(self.config_actions())

        @bindings.add('escape')
        def escape(event):
            if self.config_form:self.cancel_config_form()
            elif self.config_open() and self.config_focus=='actions':self.config_focus='list'
            elif self.input.buffer.complete_state:
                self.input.buffer.cancel_completion()
            elif self.state.traffic_open and self.state.panel is None:
                self.state.traffic_open=False
            else:
                self.close_panel()

        @bindings.add('c-c')
        def interrupt(event):
            if self.config_form:self.cancel_config_form()
            elif self.state.panel or self.input.text:
                self.close_panel()
            elif self.job and not self.job.done():
                if self.job_mutates:
                    self.state.append('pending',_t('正在应用设置，完成后即可继续；此阶段不强行中断。'))
                else:
                    self.job.cancel()
            elif time.monotonic() - self.last_interrupt < 1.5:
                event.app.exit()
            else:
                self.state.append('muted', _t('再次按 Ctrl+C 退出，代理服务会继续运行。'))
                self.last_interrupt = time.monotonic()

        @bindings.add('c-d')
        def exit_app(event):
            self.request_exit()

        @bindings.add('c-l')
        def clear(event):
            self.state.events.clear()
            self.state.scroll = 0

        @bindings.add('pageup')
        def pageup(event): self.state.scroll = min(max(0, len(self.state.events) - 2), self.state.scroll + 6)

        @bindings.add('pagedown')
        def pagedown(event): self.state.scroll = max(0, self.state.scroll - 6)

        @bindings.add('f5')
        def refresh(event):
            self.refresh.set()
            if self.config_open() and not self.config_form:self.queue(_t('刷新配置'),'configs','--json',done=self.config_panel)

        @bindings.add('c-t', filter=Condition(lambda:self.state.panel is not None and self.state.panel.kind=='nodes'))
        def speed(event):
            panel, item = self.state.panel, self.state.panel.selected()
            if panel.kind == 'nodes' and item:
                self.queue(_t('测试节点延迟'), 'test', '--node', item['value'], '--json', done=self.delay_result)

        self.app = Application(layout=Layout(root, focused_element=self.input), key_bindings=bindings,
            style=Style.from_dict({
                'brand': '#58bda6 bold', 'title': 'bold', 'muted': '#8a8f98', 'info': '', 'command': '#78b4ed bold',
                'success': '#67c5a4', 'error': '#ed8274', 'prompt': '#58bda6 bold',
                'composer.border': '#68717d', 'selected': 'bg:#284b47 #f3fff9 bold',
                'current': '#67c5a4', 'pending': '#d4b77c',
                'completion-menu.completion': 'bg:#252b32 #dce4eb',
                'completion-menu.completion.current': 'bg:#31564e #ffffff',
                'completion-menu.meta.completion': 'bg:#252b32 #9faab5',
                'completion-menu.meta.completion.current': 'bg:#31564e #c8e5dc',
            }), full_screen=False, mouse_support=Condition(lambda:self.state.panel is not None),
            min_redraw_interval=.05, input=input, output=output)

    def header_height(self):
        size = self.app.output.get_size()
        return 3 if size.columns >= 76 and size.rows >= 16 else 2

    def header(self):
        data = self.state.snapshot
        metadata = [('class:muted',clean(self.state.target).replace('\n',' ').replace('\t',' '))]
        if data.get('subscription'):
            metadata += [('class:muted', '  ·  ' + clean(data['subscription']).replace('\n',' ').replace('\t',' '))]
        if data.get('mode'):
            mode = {'rule':_t('规则'),'global':_t('全局'),'direct':_t('直连')}.get(data['mode'],'?')
            metadata += [('class:muted','  ·  '+mode)]
        if not data: status,style=_t('连接中…'),'pending'
        elif not data.get('installed'): status,style=_t('未初始化'),'pending'
        elif not data.get('active',data.get('reachable')): status,style=_t('服务已停止'),'error'
        elif not data.get('reachable'): status,style=_t('接口离线'),'error'
        elif data.get('awaiting_subscription'): status,style=_t('待添加订阅'),'pending'
        elif self.state.last_error: status,style=_t('状态待刷新'),'pending'
        else: status,style=_t('接口在线 · 出网未检测'),'success'
        status_line = [('class:'+style,'● '),('class:muted',status)]
        if self.header_height() == 2:
            if data.get('proxy_port') and self.app.output.get_size().columns >= 72:
                metadata += [('class:muted',f"  ·  :{data['proxy_port']}")]
            return [('class:brand','  Domino'),('class:muted','  v'+self.version),('', '\n')] + self.footer_line(metadata,status_line,keep_right=True)
        if data.get('proxy_port'):
            status_line += [('class:muted',f"  ·  :{data['proxy_port']}")]
        if data.get('node_count') is not None:
            counts = _t('  ·  {0} 节点', data['node_count'])
            if isinstance(data.get('groups'),list): counts += _t(' / {0} 组', len(data['groups']))
            status_line += [('class:muted',counts)]
        rows = [[('class:title','Domino'),('class:muted','  v'+self.version)],metadata,status_line]
        from prompt_toolkit.utils import get_cwidth
        available = self.app.output.get_size().columns - get_cwidth(LOGO_LINES[0]) - 8
        text = []
        for index,(logo,row) in enumerate(zip(LOGO_LINES,rows)):
            text += [('class:brand','  '+logo),('','    ')]
            text += self.clip_header(row,available)
            if index < 2: text += [('', '\n')]
        return text

    @staticmethod
    def clip_header(parts, width):
        from prompt_toolkit.utils import get_cwidth
        if sum(get_cwidth(text) for _,text in parts) <= width:
            return parts
        result,used = [],0
        for style,text in parts:
            clipped = ''
            for char in text:
                if used + get_cwidth(char) > width-1: break
                clipped += char
                used += get_cwidth(char)
            result.append((style,clipped))
            if len(clipped) < len(text): break
        return result + [('class:muted','…')]

    def transcript_text(self):
        fragments=[]
        for kind,text in self.state.events:
            base='class:'+kind
            fragments.append((base,'  ❯ ' if kind=='command' else '  '))
            if isinstance(text,StyledLine):
                fragments.extend(((base+' '+style).strip(),value) for style,value in text.fragments)
            else:
                fragments.append((base,text))
            fragments.append((base,'\n'))
        return fragments

    def panel_text(self):
        panel = self.state.panel
        if not panel: return []
        values = panel.filtered()
        if not values: return [('class:muted', _t('  配置库为空，可在下方添加配置。') if self.config_open() and not self.config_view['configs'] else _t('  没有匹配项；继续输入或按 Esc 返回。'))]
        fragments = []
        for index, item in enumerate(values):
            style = 'class:selected' if index == panel.index else 'class:current' if item.get('current') else ''
            label = ('● ' if item.get('current') else '  ') + clean(item['label'])
            if panel.kind == 'nodes' and item['value'] in self.state.delays:
                number = self.state.delays[item['value']]
                label += f'  {number} ms' if number is not None else _t('  不可用')
            def clicked(event, item=item):
                from prompt_toolkit.mouse_events import MouseButton, MouseEventType
                if event.event_type!=MouseEventType.MOUSE_UP or event.button!=MouseButton.LEFT:return NotImplemented
                if self.state.panel is panel:
                    if self.config_open():
                        if self.config_form or self.state.busy:return
                        panel.index=values.index(item)
                        self.config_focus='actions'
                        self.app.invalidate()
                        return
                    self.close_panel()
                    panel.callback(item['value'])
                    self.app.invalidate()
            fragments.append((style, (' › ' if index == panel.index else '   ') + label + '\n',clicked))
        return fragments

    def traffic_height(self):
        return min(16,max(3,self.app.output.get_size().rows-11))

    def traffic_text(self):
        from install_domino import traffic_frame
        data=self.state.snapshot
        available=data.get('stats_available',data.get('reachable',False)) and not self.state.last_error
        sample={'upload_bytes_per_second':self.state.up,'download_bytes_per_second':self.state.down,
                'upload_total':data.get('upload_total',0),'download_total':data.get('download_total',0),
                'connections':data.get('connections',0),'memory':data.get('memory')} if available else None
        error=None if available else _t('控制接口不可用，正在重试…')
        rows=traffic_frame(sample,error,self.state.traffic_history,2,self.app.output.get_size().columns-4)
        rows[-1]=(_t('Esc / /traffic 关闭面板 · 底部每 2 秒刷新'),'muted')
        if len(rows)>self.traffic_height():rows=[row for row in rows if row[1]!='space']
        if len(rows)>self.traffic_height():rows=rows[:self.traffic_height()-1]+rows[-1:]
        styles={'title':'class:title','up':'class:success','down':'class:brand','error':'class:error','muted':'class:muted'}
        result=[]
        for index,(text,role) in enumerate(rows):
            if index:result.append(('','\n'))
            result.append((styles.get(role,''),'  '+clean(text)))
        return result

    def footer(self):
        data = self.state.snapshot
        available = data.get('stats_available',data.get('reachable',bool(data)))
        connections = str(data.get('connections',0)) if available else '—'
        stats = _t('↑ {0}  ↓ {1}  ·  {2} 连接', format_bytes(self.state.up, True), format_bytes(self.state.down, True), connections)
        left, right = [('class:muted',stats)], [('class:muted',_t('/ 命令'))]
        if self.state.busy:
            left = [('class:pending','⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[int(time.monotonic()*8)%10]+' '+clean(self.state.progress or self.state.busy))]
            right = []
        elif self.state.last_error:
            left,right = [('class:error',_t('状态刷新失败 · /refresh 重试'))],[]
        elif self.state.panel:
            hint = (_t('Enter 提交 · Esc 取消输入') if self.config_form else _t('↑↓ 选配置 · Tab 操作栏 · ←→ 选操作 · Enter 执行 · Esc 返回')) if self.config_open() else _t('↑↓ / 点击选择 · Enter 确认 · Esc 取消')
            if self.app.output.get_size().columns<80:hint=_t('Tab 操作 · Enter 确认 · Esc 返回')
            if self.state.panel.kind == 'nodes': hint += _t(' · Ctrl+T 测速')
            left,right = [('class:muted',hint)],[('class:muted',_t('输入筛选'))]
        else:
            routing = data.get('system_proxy',{}).get('routing')
            notices = {'other':_t('系统代理指向其他代理 :')+('/'.join(str(v) for v in data.get('system_proxy',{}).get('ports',[])) or '?'),
                       'mixed':_t('系统代理混用'),'pac':_t('系统代理 PAC'),'off':_t('系统代理未开启'),'unknown':_t('系统代理未知'),'unsupported':_t('无桌面系统代理')}
            if routing in notices:
                left = [('class:pending' if routing in ['other','mixed','pac'] else 'class:muted',notices[routing])]
                right = [('class:muted',stats)]
        return self.footer_line(left,right)

    def footer_line(self, left, right, keep_right=False):
        from prompt_toolkit.utils import get_cwidth
        width = max(1,self.app.output.get_size().columns-4)
        size = lambda parts:sum(get_cwidth(text) for _,text in parts)
        if size(left)+size(right)+2 > width and not keep_right:
            right = []
        left_width = max(0,width-size(right)-2) if right else width
        result,used = [],0
        for style,text in left:
            clipped = ''
            for char in text:
                if used+get_cwidth(char) > left_width: break
                clipped += char
                used += get_cwidth(char)
            result.append((style,clipped))
        gap = max(2,width-used-size(right)) if right else 0
        return [('class:muted','  '),*result,('',' '*gap),*right]

    def on_text_changed(self, buffer):
        if self.state.panel:
            self.state.panel.query, self.state.panel.index = buffer.text, 0
            self.config_focus,self.config_index='list',0

    def close_panel(self):
        if self.config_form:self.cancel_config_form()
        self.config_view=None
        self.state.panel = None
        self.input.buffer.reset()

    def panel(self, title, items, callback, kind=''):
        if kind!='configs':self.config_view=None
        self.state.panel = Panel(title, items, callback, kind=kind)
        self.input.buffer.reset()
        self.input.buffer.cancel_completion()

    def accept(self, buffer):
        if buffer.text.strip() in ['exit','/exit']:
            self.request_exit()
            return False
        if self.state.panel:
            panel, item = self.state.panel, self.state.panel.selected()
            if self.config_open():
                if self.config_focus=='actions':self.config_manage(self.config_actions()[self.config_index%len(self.config_actions())][0])
                else:self.config_focus='actions'
                return True
            self.close_panel()
            if item: panel.callback(item['value'])
        elif buffer.text.strip() == '/':
            self.panel(_t('命令'), [{'label': n + '  ' + d, 'value': n} for n,d in COMMANDS], self.dispatch)
        elif buffer.text.strip(): self.dispatch(buffer.text.strip())
        return False

    async def call(self, action, *options, capture=True, timeout=75, on_progress=None):
        if action in ['configs', 'switch', 'update', 'test','catch'] and timeout == 75:
            timeout = 900
        if action=='traffic' and '--full' in options and not capture:timeout=None
        if action in ['overview','catch-options']:
            arguments = [action, self.state.target]  # Internal snapshot, not a public CLI command.
        else:
            public = 'list' if action == 'configs' else action
            if action == 'rules' and options and options[0] in ['add', 'remove']:
                if timeout == 75:
                    timeout = 180
                arguments = [self.state.target, action, *options[2:], '--', options[0], options[1]]
            elif action in ['add', 'switch', 'update', 'rename', 'remove', 'set-url']:
                count = 2 if action == 'rename' else 1
                arguments = [self.state.target, public, *options[count:], '--', *options[:count]]
            else:
                arguments = [self.state.target, public, *options]
        kwargs={'capture':capture,'timeout':timeout}
        if on_progress is not None and 'on_progress' in inspect.signature(self.execute).parameters:
            kwargs['on_progress']=on_progress
        result = self.execute(arguments, **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def poll(self):
        while True:
            try: self.state.update(json.loads(await self.call('overview', timeout=8)))
            except asyncio.CancelledError: raise
            except Exception: self.state.stale(_t('无法刷新控制接口；/refresh 重试，/logs 查看日志。'))
            self.app.invalidate()
            self.refresh.clear()
            try: await asyncio.wait_for(self.refresh.wait(), 2)
            except asyncio.TimeoutError: pass

    async def animate(self):
        while True:
            await asyncio.sleep(.12 if self.state.busy else .4)
            if self.state.busy:
                self.app.invalidate()

    def queue(self, title, action, *options, done=None, foreground=False, prompt=None, reload_configs=False):
        if self.job and not self.job.done():
            self.state.append('pending', _t('已有任务进行中；Ctrl+C 可中断。'))
            return
        self.state.busy = title
        self.state.progress = ''
        self.job_mutates = (action in ['catch','select','start','stop','restart','uninstall','add','switch','update','rename','remove','set-url'] or '--set' in options or
            (action=='connections' and any(v=='--all' or v.startswith('--close') for v in options)) or
            (action=='providers' and any(v.startswith('--update') for v in options)) or
            (action=='rules' and bool(options) and options[0] in ['add','remove']) or
            (action in ['proxy','shell'] and bool(options) and options[0] in ['on','off']) or
            (action=='configs' and any(v.startswith('--') and v!='--json' for v in options)))
        async def perform():
            try:
                if foreground:
                    from prompt_toolkit.application import in_terminal
                    async with in_terminal():
                        arguments = options
                        if prompt:
                            from prompt_toolkit import PromptSession
                            value = (await PromptSession().prompt_async(prompt)).strip()
                            if not value:
                                return
                            arguments = (*options, value)
                        await self.call(action, *arguments, capture=False)
                    self.state.append('muted' if action=='catch' else 'success',
                                      _t('捕获流程已结束，使用 /list 查看配置。') if action=='catch' else title+_t('完成。'))
                    if action in ['start','stop','restart','uninstall']:
                        try:
                            self.state.update(json.loads(await self.call('overview',timeout=8)))
                            self.runtime_result()
                        except Exception:
                            self.state.stale(_t('操作已完成，但状态刷新失败；使用 /refresh 重试。'))
                            self.state.append('pending',self.state.last_error)
                else:
                    def progress(value):
                        self.state.progress=clean(value).strip()[:500]
                        self.app.invalidate()
                    output = await self.call(action, *options,on_progress=progress if action=='test' else None)
                    if done: done(output)
                    elif output: self.state.append('info', output.rstrip(), ansi=True)
                    else: self.state.append('success', title + _t('完成。'))
                self.refresh.set()
            except asyncio.CancelledError: self.state.append('muted', _t('已中断命令；可用 /status 查看实际状态。'))
            except (EOFError,KeyboardInterrupt):self.state.append('muted',_t('已取消操作；未继续提交。'))
            except asyncio.TimeoutError: self.state.append('error', _t('操作超时，请重试或使用 /logs 检查。'))
            except (Exception, SystemExit) as error: self.state.append('error', clean(str(error)) or _t('操作失败。'))
            finally:
                if reload_configs and self.config_open():
                    try:self.config_panel(await self.call('configs','--json'))
                    except Exception:self.state.append('pending',_t('配置列表刷新失败；按 F5 重试。'))
                self.state.busy = ''
                self.state.progress = ''
                self.job_mutates = False
                self.app.invalidate()
        self.job = self.app.create_background_task(perform())

    def groups(self, for_delay=False):
        groups = self.state.snapshot.get('groups', [])
        if groups:
            if not for_delay:self.describe_nodes()
            self.group_panel(groups, for_delay)
        else:
            def loaded(text):
                result=json.loads(text)
                self.state.snapshot.update(groups=result['groups'],mode=result.get('mode',self.state.snapshot.get('mode','rule')))
                if not for_delay:self.describe_nodes()
                self.group_panel(result['groups'],for_delay)
            self.queue(_t('读取策略组'),'nodes','--json',done=loaded)

    def selection_paths(self):
        from install_domino import current_proxy_paths
        groups=self.state.snapshot.get('groups',[])
        live={g['name']:{'type':g.get('type','Selector' if g.get('selectable') else 'URLTest'),
                         'now':g.get('current'),'all':g.get('choices',[])} for g in groups}
        for group in groups:
            for name in group.get('choices',[]):live.setdefault(name,{'type':'node'})
        return current_proxy_paths(self.state.snapshot.get('mode','rule'),live)

    def describe_nodes(self):
        self.state.append('info',_t('当前配置  ')+(self.state.snapshot.get('subscription') or _t('未关联配置库的配置')))
        for path in self.selection_paths():self.state.append('success',_t('当前代理  ')+path)
        if self.state.snapshot.get('mode')=='rule':self.state.append('muted',_t('当前选择按规则分流，不代表所有请求都使用同一节点。'))

    def choose_node(self, query=None, group_name=None):
        import domino_cli
        groups=[g for g in self.state.snapshot.get('groups',[]) if g.get('selectable') and g.get('choices')]
        if not groups:
            def loaded(text):
                result=json.loads(text)
                self.state.snapshot.update(groups=result['groups'],mode=result.get('mode',self.state.snapshot.get('mode','rule')))
                if any(g.get('selectable') for g in self.state.snapshot['groups']):self.choose_node(query,group_name)
                else:self.state.append('error',_t('没有可手动选择的策略组。'))
            self.queue(_t('读取可选节点'),'nodes','--json',done=loaded)
            return
        if group_name:
            matches=domino_cli.select_matches(group_name,[g['name'] for g in groups])
            if len(matches)!=1:raise ValueError(_t('请填写唯一的手动策略组名称。'))
            groups=[g for g in groups if g['name']==matches[0]]
        elif self.state.snapshot.get('mode')=='global' and any(g['name']=='GLOBAL' for g in groups):
            groups=[g for g in groups if g['name']=='GLOBAL']
        def commit(node):
            eligible=[g for g in groups if node in g['choices']]
            def apply(group):self.queue(_t('切换节点'),'select','--group',group['name'],'--node',node)
            if len(eligible)==1:apply(eligible[0])
            else:self.panel(_t('选择策略组'),[{'label':g['name'],'value':g} for g in eligible],apply,'select-group')
        if query is None:
            self.describe_nodes()
            if len(groups)==1:self.nodes(groups[0])
            else:self.group_panel(groups)
            return
        matches=domino_cli.select_matches(query,list(dict.fromkeys(name for g in groups for name in g['choices'])))
        if not matches:raise ValueError(_t('没有匹配的节点；使用 /nodes 查看名称。'))
        if len(matches)==1:commit(matches[0])
        else:self.panel(_t('选择匹配节点'),[{'label':name,'value':name,'current':any(g.get('current')==name for g in groups)} for name in matches],commit,'select-matches')

    def runtime_result(self):
        d=self.state.snapshot
        self.state.append('success' if d.get('active') else 'error',_t('● 已开启') if d.get('active') else _t('● 已关闭'))
        self.state.append('info',_t('当前配置  ')+(d.get('subscription') or _t('未关联配置库')))
        routing=d.get('system_proxy',{}).get('routing')
        if routing=='domino':self.state.append('success',_t('系统代理已开启 → Domino 127.0.0.1:{0}', d.get('proxy_port')))
        elif routing=='unsupported':self.state.append('muted',_t('无桌面系统代理；终端使用 /shell on/off/status。'))
        elif not d.get('active'):self.state.append('muted',_t('服务已停止，Domino 系统代理接管已解除。'))
        else:self.state.append('pending',_t('系统代理尚未接通；/status 查看详情。'))

    def group_panel(self, groups, for_delay=False):
        def selected(group):
            if for_delay: self.queue(_t('测试策略组延迟'),'test','--group',group['name'],'--json',done=self.delay_result)
            else: self.nodes(group)
        self.panel(_t('策略组 · ')+(self.state.snapshot.get('subscription') or _t('未关联配置库')),
            [{'label': _t('{0} → {1}', g['name'], g.get('current') or _t('自动策略')), 'search':g['name'], 'value':g} for g in groups], selected)

    def nodes(self, group, for_delay=False):
        def selected(name):
            if for_delay:self.queue(_t('测试节点延迟'),'test','--node',name,'--json',done=self.delay_result)
            elif not group['selectable']:
                self.state.append('muted', _t('该组由策略自动选择；请在上层 Selector 策略组中切换。'))
            else: self.queue(_t('切换节点'),'select','--group',group['name'],'--node',name)
        self.panel((self.state.snapshot.get('subscription') or _t('未关联配置库'))+' · '+group['name'] + ('' if group['selectable'] else _t(' · 自动策略')),
            [{'label':n,'value':n,'current':n==group.get('current')} for n in group['choices']], selected, 'nodes')

    def menu(self, title, choices):
        self.panel(title,[{'label':label,'value':command} for label,command in choices],self.dispatch,'actions')

    def catch_panel(self, text):
        values=json.loads(text)
        items=[{'label':v['name']+' · '+v['path'],'value':v['path']} for v in values]
        if not items:
            self.state.append('muted',_t('没有发现兼容外部配置；可使用 /catch --source "配置路径"。'))
            return
        self.panel(_t('选择捕获的外部配置'),items,
                   lambda path:self.queue(_t('捕获外部配置'),'catch','--source',path,foreground=True),'catch-sources')

    def configuration_picker(self, action):
        def loaded(text):
            if action=='test':self.configuration_choices(json.loads(text),action)
            else:
                self.config_panel(text)
                if action=='add':self.config_manage('add')
        self.queue(_t('读取配置'),'configs','--json',done=loaded)

    def configuration_choices(self, result, action):
        items=[{'label':_t('全部配置 · 汇总可用/不可用节点'),'value':None}]
        for item in result['configs']:
            items.append({'label':item['name'],'value':item,'current':item['active']})
        items.extend([{'label':_t('当前配置 · 选择策略组检测'),'value':'group'},
                      {'label':_t('当前配置 · 选择单个节点检测'),'value':'node'}])
        def selected(item):
            if item is None:
                self.queue(_t('检测全部配置'),'test','--all','--json',done=self.delay_result)
            elif isinstance(item,str):
                if item=='group':self.groups(for_delay=True)
                else:self.test_node_picker()
            else:self.queue(_t('检测配置节点'),'test','--config',item['name'],'--json',done=self.delay_result)
        self.panel(_t('检测配置节点 · 选择配置'),items,selected,'config-test')

    def test_node_picker(self):
        def loaded(groups):
            self.panel(_t('选择节点所在策略组'),[{'label':g['name'],'value':g} for g in groups],
                       lambda g:self.nodes(g,for_delay=True),'test-group')
        groups=self.state.snapshot.get('groups',[])
        if groups:loaded(groups)
        else:self.queue(_t('读取策略组'),'nodes','--json',done=lambda s:loaded(json.loads(s)['groups']))

    def traffic_toggle(self):
        self.state.traffic_open=not self.state.traffic_open
        if self.state.traffic_open:
            d=self.state.snapshot
            self.state.append('muted',traffic_notice(d))
            if d.get('system_proxy',{}).get('routing') in ['other','off','mixed']:
                self.state.append('muted',_t('执行 /start 开启 Domino 并接通系统代理。'))
            self.state.append('muted',_t('动态面板已打开；底部每 2 秒刷新；Esc 或 /traffic 关闭。'))
        else:self.state.append('muted',_t('动态流量面板已关闭。'))

    def delay_result(self, text):
        data=json.loads(text)
        usage=data.get('usage',{}) if isinstance(data,dict) else {}
        current=set(usage.get('nodes',[]))
        if isinstance(data,dict):
            configuration=data.get('configuration')
            if configuration:self.state.append('success' if usage.get('active') else 'muted',(_t('● 当前配置  ') if usage.get('active') else _t('测试配置  '))+configuration)
            if usage.get('active') is False:self.state.append('muted',_t('未启用 · 当前使用 ')+(usage.get('current') or _t('未关联配置库的配置')))
            for path in usage.get('paths',[]):self.state.append('success',_t('当前代理  ')+path)
            if usage.get('active') and not usage.get('known'):self.state.append('pending',_t('运行选择无法读取，本次不标记当前节点。'))
        for item in data.get('results',[]) if isinstance(data,dict) else data:
            if 'status' in item and 'total' in item:
                counts = _t('{0} 节点 · {1} 可用 · {2} 超时/不可用', item['total'], item['available'], item['unavailable']) if item['status']=='tested' else item['message']
                self.state.append('success' if item.get('available') else 'muted',('● ' if item.get('active') else '')+item['name'] + '  ' + counts)
                continue
            self.state.delays[item['name']] = item['delay_ms']
            self.state.append('success' if item['ok'] else 'error',
                ('● ' if item['name'] in current else '')+item['name'] + (f"  {item['delay_ms']} ms" if item['ok'] else _t('  超时 / 不可用'))+
                (_t('  · 当前选中') if item['name'] in current else ''))

    def choices(self, title, values, action):
        self.panel(title,[{'label':label,'value':v,'current':v==self.state.snapshot.get('log_level' if action=='log' else 'mode')} for v,label in values],
            lambda v:self.queue(title,action,*([v] if action=='proxy' else ['--set',v]),foreground=action=='proxy'))

    def help(self):
        self.state.append('info','\n'.join(f'\033[1;36m{n:14}\033[0m {_t(d)}' for n,d in COMMANDS),ansi=True)
        self.state.append('muted',_t('直接输入命令并回车进入选择面板，↑↓ 选择、Enter 确认；也可输入参数作为快捷操作。'))
        self.state.append('muted',_t('/shell 只管理终端代理策略；UI 不修改父 shell，退出后由已加载的 shell 集成同步。'))
        self.state.append('muted',_t('面板中输入筛选，↑↓ 导航，Enter 确认，Ctrl+T 测速。Ctrl+C 中断命令或清空输入。'))

    def can_exit(self):
        if self.job and not self.job.done() and self.job_mutates:
            self.state.append('pending',_t('设置尚在提交，请等操作完成后退出。'))
            return False
        return True

    def request_exit(self):
        if self.can_exit():
            self.app.exit()

    def dispatch(self, text):
        try:
            name, args = parse_command(text)
            if not name: return
            public_name = name
            if name == '/list':
                name = '/configs'
            elif name in ['/add','/switch','/update','/remove','/rename','/set-url']:
                args = [name[1:], *args]
                name = '/configs'
            if name == '/exit':
                self.request_exit()
                return
            if name == '/clear': self.state.events.clear(); self.state.scroll=0; return
            if name in ['/status','/logs','/start','/stop','/restart','/help'] and args:
                raise ValueError(name + _t(' 不需要额外参数。'))
            if name == '/doctor':
                if len(args) > 1:
                    raise ValueError(_t('用法：/doctor，或 /doctor https://example.com/。'))
                if args:
                    from domino_doctor import validate_url
                    validate_url(args[0])
            if name in ['/configs','/catch']:
                visible, hide_next = [], False
                for value in args:
                    secret_flags=['--url','--local-proxy','--controller','--subscription']
                    visible.append('***' if hide_next else value.split('=',1)[0]+'=***' if any(value.startswith(flag+'=') for flag in secret_flags) else value)
                    hide_next = value in secret_flags
                self.state.append('command', shlex.join([public_name, *visible[1:]]) if name=='/configs' and public_name not in ['/configs','/list'] else shlex.join([public_name, *visible]))
            else:
                self.state.append('command',text)
            if name == '/help': self.help()
            elif name == '/language':
                if not args:
                    self.menu(_t('界面语言'), [('English (en)', '/language en'), ('简体中文 (zh)', '/language zh')])
                elif len(args) == 1:
                    from domino_i18n import set_language
                    selected = set_language(args[0])
                    self.state.append('info', _t('界面语言：{0}', 'English (en)' if selected == 'en' else '简体中文 (zh)'))
                    self.refresh.set()
                    self.app.invalidate()
                else:
                    raise ValueError(_t('用法：/language，或 /language zh / en。'))
            elif name == '/refresh':
                self.refresh.set()
                self.state.append('muted',_t('已请求刷新状态和流量。'))
            elif name == '/nodes':
                if args: self.queue(_t('读取策略组'),'nodes','--group',' '.join(args),'--json',done=lambda s:self.nodes(json.loads(s)['groups'][0]))
                else: self.groups()
            elif name == '/select':
                import domino_cli,io
                from contextlib import redirect_stderr
                try:
                    with redirect_stderr(io.StringIO()):selection=domino_cli.build_parser().parse_args(['select',*args])
                except SystemExit:raise ValueError(_t('用法：/select，/select "节点名或关键词"，可附加 --group "策略组"。')) from None
                self.choose_node(selection.name or selection.node,selection.group)
            elif name == '/catch':
                if not args:self.menu(_t('捕获外部配置'),[(_t('选择一个外部配置'),'/catch --choose'),(_t('全部配置 · 重复项自动跳过'),'/catch all')])
                elif args==['--choose']:self.queue(_t('读取外部配置'),'catch-options',done=self.catch_panel)
                else:self.queue(_t('捕获外部配置'),'catch',*args,foreground=True)
            elif name == '/configs':
                if not args or args == ['list']:
                    self.queue(_t('读取配置'), 'configs', '--json', done=lambda s:self.config_panel(json.loads(s)))
                elif len(args)==1 and args[0]=='add':
                    self.configuration_picker('add')
                elif len(args)==1 and args[0] in ['switch','update','remove','rename','set-url']:
                    self.configuration_picker(args[0])
                elif args[0] in ['add', 'set-url']:
                    action = args[0]
                    title = _t('添加订阅') if action == 'add' else _t('设置订阅地址')
                    values = args[1:]
                    if len(values) == 1:
                        self.queue(title, action, *values, foreground=True)
                    elif (len(values) == 3 and values[1] == '--url') or (len(values) == 2 and values[1].startswith('--url=')):
                        self.queue(title, action, *values)
                    else:
                        raise ValueError(_t('用法：/') + action + _t(' "配置名称"，地址将隐藏输入；也可附加 --url "HTTPS 地址"。'))
                elif args[0] in ['switch', 'update', 'rename', 'remove']:
                    action, values = args[0], args[1:]
                    if action=='rename' and len(values)==1:
                        self.queue(_t('重命名配置'),'rename',*values,foreground=True,prompt=_t('新配置名称：'))
                        return
                    required = 2 if action == 'rename' else 1
                    if len(values) != required:
                        raise ValueError(_t('用法：/') + action + (_t(' "旧名称" "新名称"') if required == 2 else _t(' "配置名称"')) + (_t('；/update all 更新全部在线订阅。') if action == 'update' else '。'))
                    self.queue(_t('订阅管理'), action, *values)
                else:
                    hidden = any(v in ['--add','--set-url'] or v.startswith(('--add=','--set-url=')) for v in args) and not any(v=='--url' or v.startswith('--url=') for v in args)
                    self.queue(_t('配置管理'), 'configs', *args, foreground=hidden)
            elif name == '/mode':
                if args:
                    if (len(args)!=1 and not (len(args)==2 and args[0]=='--set')) or args[-1] not in ['rule','global','direct']:
                        raise ValueError(_t('用法：/mode，或 /mode rule|global|direct。'))
                    self.queue(_t('切换模式'),'mode','--set',args[-1])
                else: self.choices(_t('选择运行模式'),[('rule',_t('规则模式  按分流规则选择出口')),('global',_t('全局模式  使用 GLOBAL 当前选择')),('direct',_t('直连模式  直接连接目标'))],'mode')
            elif name in ['/test', '/delay']:
                if not args or args==['--config']:self.configuration_picker('test')
                elif args==['--group']:self.groups(for_delay=True)
                elif args==['--node']:self.test_node_picker()
                elif args==['--all']:self.queue(_t('检测全部配置'),'test','--all','--json',done=self.delay_result)
                elif len(args)==1: self.queue(_t('测试延迟'),'test',args[0],'--json',done=self.delay_result)
                elif len(args)==2 and args[0] in ['--node','--group','--config']: self.queue(_t('测试延迟'),'test',*args,'--json',done=self.delay_result)
                else: raise ValueError(_t('用法：/test 汇总所有配置，或 /test "配置名" 查看节点明细。'))
            elif name == '/scan':
                if not args:
                    self.menu(_t('扫描配置'),[(_t('扫描全部外部配置与 Domino 配置'),'/scan --all'),(_t('指定配置文件路径'),'/scan --source')])
                    return
                if args==['--all']:args=[]
                elif args==['--source']:
                    self.queue(_t('扫描指定配置'),'scan','--source',foreground=True,prompt=_t('配置文件路径：'))
                    return
                if args and not ((len(args)==2 and args[0]=='--source') or
                                 (len(args)==1 and args[0].startswith('--source=') and args[0]!='--source=')):
                    raise ValueError(_t('用法：/scan，或 /scan --source "配置路径"。'))
                self.queue(_t('扫描配置与代理出网'),'scan',*args)
            elif name == '/doctor': self.queue(_t('连接诊断'), 'doctor', *(['--url', args[0]] if args else []))
            elif name == '/status': self.queue(_t('运行状态'),'status')
            elif name == '/traffic':
                if not args:
                    self.menu(_t('动态流量面板'),[
                        (_t('关闭内嵌面板') if self.state.traffic_open else _t('打开内嵌动态面板'),'/traffic --inline'),
                        (_t('打开独立全屏面板 · q 返回'),'/traffic --full')])
                    return
                if args==['--full']:
                    self.state.traffic_open=False
                    self.queue(_t('流量监控'),'traffic','--full',foreground=True)
                    return
                if args!=['--inline']:raise ValueError(_t('用法：/traffic 选择面板，/traffic --inline，/traffic --full。'))
                self.traffic_toggle()
            elif name == '/connections':
                if not args:self.menu(_t('连接管理'),[(_t('查看活跃连接'),'/connections --list'),(_t('选择关闭一个连接'),'/connections --choose'),(_t('关闭全部活跃连接'),'/connections --all')])
                elif args==['--list']:self.queue(_t('读取连接'),'connections','--json',done=self.connections_result)
                elif args==['--choose']:self.queue(_t('读取连接'),'connections','--json',done=lambda s:self.connection_panel(json.loads(s)))
                elif args==['--all'] or (len(args)==2 and args[0]=='--close'): self.queue(_t('关闭连接'),'connections',*args)
                else: raise ValueError(_t('用法：/connections，/connections --close ID，/connections --all。'))
            elif name == '/rules':
                if not args:
                    self.menu(_t('分流规则'),[(_t('查看运行规则'),'/rules --list'),(_t('查看自定义规则'),'/rules --custom'),
                        (_t('搜索运行规则'),'/rules --search'),(_t('添加自定义规则'),'/rules add'),(_t('选择删除自定义规则'),'/rules remove')])
                elif args==['add']:self.queue(_t('新增规则'),'rules','add',foreground=True,prompt=_t('完整规则（如 DOMAIN-SUFFIX,example.com,DIRECT）：'))
                elif args==['remove']:self.queue(_t('读取自定义规则'),'rules','--custom','--limit','100000','--json',done=lambda s:self.rule_panel(json.loads(s)))
                elif args==['--search']:self.queue(_t('搜索规则'),'rules','--limit','20','--match',foreground=True,prompt=_t('搜索关键词：'))
                elif args==['--list']:self.queue(_t('读取规则'),'rules','--limit','20')
                elif args[0] in ['add','remove']:
                    if len(args) != 2:
                        raise ValueError(_t('用法：/rules ') + args[0] + _t(' "完整规则"。例如 /rules add "DOMAIN-SUFFIX,example.com,DIRECT"。'))
                    self.queue(_t('新增规则') if args[0]=='add' else _t('删除自定义规则'),'rules',*args)
                elif args == ['--custom']:
                    self.queue(_t('读取自定义规则'),'rules','--custom')
                else:
                    self.queue(_t('读取规则'),'rules','--limit','20',*(['--match',' '.join(args)] if args else []))
            elif name == '/providers':
                if not args:
                    self.menu(_t('选择集合类型'),[(_t('节点集合 · proxy'),'/providers proxy'),(_t('规则集合 · rule'),'/providers rule')])
                    return
                kind=args[0]
                if kind not in ['proxy','rule']: raise ValueError(_t('用法：/providers 或 /providers rule。'))
                self.queue(_t('读取集合'),'providers','--kind',kind,'--json',done=lambda s:self.provider_panel(json.loads(s),kind))
            elif name == '/log':
                if args and (len(args)==1 or (len(args)==2 and args[0]=='--set')) and args[-1] in ['debug','info','warning','error','silent']: self.queue(_t('日志级别'),'log','--set',args[-1])
                elif not args:self.choices(_t('日志级别'),[('debug',_t('调试  debug')),('info',_t('信息  info')),('warning',_t('警告  warning')),('error',_t('错误  error')),('silent',_t('静默  silent'))],'log')
                else: raise ValueError(_t('日志级别可选 debug、info、warning、error、silent。'))
            elif name == '/shell':
                if not args:
                    self.menu(_t('终端代理'),[(_t('on · 在终端中使用 Domino 代理'),'/shell on'),(_t('off · 恢复原代理设置'),'/shell off'),(_t('status · 查看端口和环境变量'),'/shell status')])
                elif args == ['status']: self.queue(_t('终端代理策略'),'shell','status')
                elif len(args)==1 and args[0] in ['on','off']: self.queue(_t('终端代理策略'),'shell',args[0])
                else: raise ValueError(_t('用法：/shell status，/shell on，/shell off。'))
            elif name == '/proxy':
                if not args: self.choices(_t('系统代理'),[('on',_t('开启 Domino 系统代理')),('off',_t('恢复此前的系统代理设置'))],'proxy')
                elif (len(args)==1 or (len(args)==2 and args[0]=='--set')) and args[-1] in ['on','off']: self.queue(_t('系统代理'),'proxy',args[-1],foreground=True)
                elif args==['status']: self.queue(_t('系统代理状态'),'proxy','status',foreground=True)
                else: raise ValueError(_t('用法：/proxy，/proxy on，/proxy off，/proxy status。'))
            elif name == '/logs': self.queue(_t('查看内核日志'),'logs','--lines','30',foreground=True)
            elif name == '/uninstall':
                if not args:
                    self.menu(_t('卸载 Domino'),[(_t('预览清理范围（不修改）'),'/uninstall --dry-run'),
                        (_t('卸载运行环境并删除配置、备份（需确认）'),'/uninstall --confirm')])
                elif args == ['--dry-run']: self.queue(_t('卸载预览'),'uninstall','--dry-run')
                elif args == ['--confirm']: self.queue(_t('卸载 Domino'),'uninstall',foreground=True)
                else: raise ValueError(_t('使用 /uninstall 选择预览或卸载。'))
            elif name in ['/start','/stop','/restart']: self.queue(_t('执行 ')+name[1:],name[1:],foreground=True)
        except ValueError as error: self.state.append('error',str(error))

    def connections_result(self, text):
        values=json.loads(text).get('connections',[])
        self.state.append('info',_t('活跃连接 {0} 条；显示前 20 条。', len(values)))
        for v in values[:20]: self.state.append('info',f"{v['id']}  {v.get('network')}  {v.get('host')}:{v.get('port')}  {' → '.join(v.get('chains') or [])}")

    def connection_panel(self, result):
        values=result.get('connections',[])
        if not values:
            self.state.append('muted',_t('没有活跃连接。'))
            return
        self.panel(_t('选择关闭的连接'),[{'label':f"{v.get('network')} {v.get('host')}:{v.get('port')} · {v['id']}",'value':v['id']} for v in values],
                   lambda value:self.queue(_t('关闭连接'),'connections','--close',value),'connections')

    def rule_panel(self, result):
        values=result.get('rules',[])
        if not values:
            self.state.append('muted',_t('没有自定义规则。'))
            return
        self.panel(_t('选择删除的自定义规则'),[{'label':v,'value':v} for v in values],
                   lambda value:self.queue(_t('删除自定义规则'),'rules','remove',value),'rules-remove')

    def provider_panel(self, values, kind):
        if not values: self.state.append('muted',_t('没有可用集合。')); return
        def selected(item):
            if str(item.get('vehicleType','')).lower() not in ['http','file']:
                self.state.append('muted',_t('这是内置节点快照；请用 /list 管理和更新完整订阅。'))
            else: self.queue(_t('更新集合'),'providers','--kind',kind,'--update',item['name'])
        self.panel(_t('订阅集合 · Enter 更新 HTTP / file 集合'),
            [{'label':_t('{0}  [{1}]  {2} 项', v['name'], v.get('vehicleType'), v.get('count')),'value':v} for v in values],selected)

    def config_open(self):
        return self.config_view is not None and self.state.panel is not None and self.state.panel.kind=='configs'

    def config_actions(self):
        item=self.state.panel.selected() if self.config_open() else None
        item=item['value'] if item else None
        actions=[]
        if item:
            actions=[('switch',_t('切换'))]
            actions.extend([('rename',_t('重命名')),('set-url',_t('修改地址')),('test',_t('检测'))])
            if not item['active']:actions.append(('remove',_t('删除')))
        actions.extend([('add',_t('添加')),('catch',_t('捕获')),('snapshot',_t('保存快照'))])
        if any(v['kind']=='subscription' for v in self.config_view['configs']):actions.append(('update-all',_t('全部更新')))
        return actions+([('update',_t('更新配置'))] if item else [])

    def config_toolbar(self):
        if not self.config_open():return []
        item=self.state.panel.selected()
        label=item['value']['name'] if item else _t('未选择配置')
        fragments=[('class:muted',_t('  操作对象：')+clean(label)+'\n  ')]
        for index,(action,title) in enumerate(self.config_actions()):
            def clicked(event,action=action):
                from prompt_toolkit.mouse_events import MouseButton,MouseEventType
                if event.event_type==MouseEventType.MOUSE_UP and event.button==MouseButton.LEFT:self.config_manage(action)
            style='class:muted' if self.state.busy or self.config_form else 'class:selected' if self.config_focus=='actions' and index==self.config_index else 'class:command'
            fragments.append((style,'[ '+title+' ] ',clicked))
        return fragments

    def config_panel(self, result):
        if isinstance(result,str):result=json.loads(result)
        previous=self.state.panel.selected() if self.config_open() else None
        focus,index=(self.config_focus,self.config_index) if self.config_open() else ('list',0)
        keep=self.config_keep or (previous['value'].get('id',previous['value']['name']) if previous else None)
        query=self.state.panel.query if self.config_open() else ''
        self.config_view=result
        from install_domino import human_width
        width=min(28,max([8]+[human_width(v['name']) for v in result['configs']]))
        def row(v):
            name=clean(v['name'])
            while human_width(name)>width:name=name[:-1]
            from domino_subscriptions import usage_cell
            import install_domino
            quota = usage_cell(install_domino, v)[0]
            cache='' if v.get('cached') else '  '+_t('未缓存')
            return name+' '*max(2,width-human_width(name)+2)+(_t('在线订阅') if v['kind']=='subscription' else _t('配置快照'))+'  '+str(v.get('node_count') if v.get('node_count') is not None else '—')+_t(' 节点  ')+quota+cache
        self.panel(_t('配置管理 · ')+str(len(result['configs']))+_t(' 个配置 · 当前：')+str(result.get('active') or result.get('current_source') or _t('未关联配置库')),
            [{'label':row(v),'search':v['name'],'value':v,'current':v['active']} for v in result['configs']],lambda _:None,'configs')
        panel=self.state.panel
        panel.query=query
        if keep and not any(v['value'].get('id',v['value']['name'])==keep or v['value']['name']==keep for v in panel.filtered()):
            panel.query='';self.input.buffer.reset()
        self.config_keep=None
        self.input.buffer.text=panel.query
        panel.index=next((i for i,v in enumerate(panel.filtered()) if v['value'].get('id',v['value']['name'])==keep or v['value']['name']==keep),0)
        self.config_focus,self.config_index=focus,min(index,len(self.config_actions())-1)

    def config_manage(self, action):
        if not self.config_open() or self.state.busy or self.config_form:return
        selected=self.state.panel.selected();item=selected['value'] if selected else None
        if action not in dict(self.config_actions()):return
        self.config_keep=item.get('id',item['name']) if item else None
        if action in ['add','rename','set-url','snapshot']:
            fields=[('name',_t('配置名称')),('url',_t('HTTPS 订阅地址（隐藏输入）'))] if action=='add' else [('url',_t('HTTPS 订阅地址（隐藏输入）'))] if action=='set-url' else [('name',_t('新配置名称') if action=='rename' else _t('快照名称'))]
            self.config_form={'action':action,'item':item,'fields':fields,'values':{}}
            self.form_input.buffer.reset();self.app.layout.focus(self.form_input)
        elif action=='catch':self.queue(_t('捕获外部配置'),'catch',foreground=True,reload_configs=True)
        elif action=='update-all':self.queue(_t('更新全部在线订阅'),'update','all',reload_configs=True)
        elif action=='update':
            command = ('configs','--update','all') if item['name']=='all' else ('update',item['name'])
            self.queue(_t('更新配置'),*command,done=lambda _:self.state.append('success',_t('配置已更新：')+item['name']),reload_configs=True)
        elif action=='test':self.queue(_t('检测配置节点'),'test','--config',item['name'],'--json',done=self.delay_result,reload_configs=True)
        else:self.queue(_t('配置管理'),action,item['name'],reload_configs=True)

    def cancel_config_form(self):
        self.config_form=None;self.form_input.buffer.reset()
        self.app.layout.focus(self.input)

    def accept_config_form(self, buffer):
        form=self.config_form
        if not form:return False
        value=buffer.text.strip();field=form['fields'][0][0]
        if not value:
            self.cancel_config_form()
            return False
        if field=='url':
            from urllib.parse import urlsplit
            try:url=urlsplit(value)
            except ValueError:
                self.state.append('error',_t('请输入有效的 HTTPS 订阅地址。'))
                return False
            if url.scheme!='https' or not url.hostname or url.username or url.password or any(c.isspace() for c in value):
                self.state.append('error',_t('请输入有效的 HTTPS 订阅地址。'))
                return False
        form['values'][field]=value;form['fields'].pop(0)
        if form['fields']:return False
        action,item,values=form['action'],form['item'],form['values']
        self.cancel_config_form()
        if action in ['add','rename','snapshot']:self.config_keep=values['name']
        options=([values['name'],'--url',values['url']] if action=='add' else
                 [item['name'],values['name']] if action=='rename' else
                 [item['name'],'--url',values['url']] if action=='set-url' else ['--import-current',values['name']])
        self.queue(_t('保存配置'),'configs' if action=='snapshot' else action,*options,reload_configs=True)
        return False

    def run(self):
        def start():
            self.app.create_background_task(self.poll())
            self.app.create_background_task(self.animate())
        try:
            self.app.run(pre_run=start)
        except (EOFError, KeyboardInterrupt):
            pass
        print(_t('已退出 Domino 界面；代理服务继续运行。'))


def run(target, execute, version=''):
    Workspace(target,execute,version).run()
