"""Persistent slash-command terminal workspace over the regular CLI commands."""
from __future__ import annotations

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
    ('/nodes', '搜索策略组与节点，Enter 切换'), ('/mode', '规则 / 全局 / 直连模式'),
    ('/status', '检查服务和真实 HTTPS 出网'), ('/delay', '测速全部节点，或填写节点/组名'),
    ('/scan', '扫描当前目标的配置和代理入口出网'),
    ('/traffic', '实时速率和累计流量'), ('/connections', '查看或关闭连接'),
    ('/rules', '查看规则；/rules add/remove "规则" 管理自定义规则'), ('/providers', '查看或更新节点 / 规则集合'),
    ('/configs', '管理在线订阅与配置快照，更新和切换配置'),
    ('/refresh', '立即刷新状态和流量'),
    ('/logs', '最近的内核日志'), ('/log-level', '设置日志级别'),
    ('/proxy', '查看、开启或恢复系统代理'), ('/shell', '终端代理策略与原变量恢复'), ('/start', '启动 Domino'),
    ('/stop', '停止 Domino'), ('/restart', '重启 Domino'),
    ('/help', '命令与快捷键'), ('/clear', '清空本次操作记录'), ('/exit', '退出界面，也可输入 exit 或按 Ctrl+D'),
]

LOGO_LINES = (
    '█▀▄ █▀█ █▄ ▄█ █ █▄ █ █▀█',
    '█ █ █ █ █ ▀ █ █ █ ▀█ █ █',
    '▀▀  ▀▀▀ ▀   ▀ ▀ ▀  ▀ ▀▀▀',
)

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
        return f'仅统计 {scope}；系统代理仍指向其他代理' + (f' :{ports}' if ports else '')
    if state == 'mixed':
        return f'仅统计 {scope}；部分系统代理指向其他代理'
    if state == 'pac':
        return f'仅统计 {scope}；系统使用 PAC / 自动发现'
    if state == 'off':
        return f'仅统计 {scope}；系统代理未开启，应用需单独设置代理'
    return f'仅统计 {scope}，不包含其他代理或系统总流量'


def parse_command(text):
    parts = shlex.split(text.strip())
    if not parts:
        return '', []
    name = '/' + parts[0].lstrip('/')
    if name in ['/q', '/quit']:
        name = '/exit'
    if name not in dict(COMMANDS):
        raise ValueError('未知命令，输入 /help 查看可用操作。')
    if name == '/shell' and parts[1:] not in [[], ['status'], ['on'], ['off']]:
        raise ValueError('用法：/shell status，/shell on，/shell off。')
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
        if available and previous_available and self.sampled_at and elapsed > 0:
            self.up = max(0, value.get('upload_total', 0) - self.snapshot.get('upload_total', 0)) / elapsed
            self.down = max(0, value.get('download_total', 0) - self.snapshot.get('download_total', 0)) / elapsed
        else:
            self.up = self.down = None
        self.snapshot, self.sampled_at = value, now
        self.updated_at = time.time()
        self.last_error = value.get('error', '')

    def stale(self, message):
        self.last_error = message
        self.up = self.down = None
        self.sampled_at = 0


def load_toolkit():
    try:
        return importlib.import_module('prompt_toolkit')
    except ImportError:
        for path in [Path(__file__).parent / '_vendor', Path.home() / '.local/share/domino/cli/_vendor']:
            if (path / 'prompt_toolkit').is_dir():
                sys.path.insert(0, str(path))
                return importlib.import_module('prompt_toolkit')
    raise RuntimeError('交互界面需要 prompt-toolkit；请安装项目依赖，或更新带 UI 组件的 Domino 安装包。')


def make_completer():
    from prompt_toolkit.completion import Completer, Completion
    class Commands(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if text.startswith('/') and not any(c.isspace() for c in text):
                for name, description in COMMANDS:
                    if name.startswith(text):
                        yield Completion(name, start_position=-len(text), display_meta=description)
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
        self.input = TextArea(multiline=False, height=1, wrap_lines=False, history=InMemoryHistory(),
            prompt=[('class:prompt', '  ❯ ')], style='class:input',
            completer=ConditionalCompleter(make_completer(), Condition(lambda: self.state.panel is None)),
            complete_while_typing=True, accept_handler=self.accept)
        self.input.buffer.on_text_changed += self.on_text_changed
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
        composer = HSplit([Window(height=1,char='─',style='class:composer.border'), self.input,
                           Window(height=1,char='─',style='class:composer.border')])
        body = HSplit([Window(height=1),Window(FormattedTextControl(self.header),height=self.header_height),Window(height=1),transcript,
            ConditionalContainer(picker, filter=Condition(lambda: self.state.panel is not None)),
            Window(height=1), composer, Window(FormattedTextControl(self.footer),height=1)])
        root = FloatContainer(body, floats=[Float(xcursor=True, ycursor=True,
            content=CompletionsMenu(max_height=8, scroll_offset=1), z_index=10)])
        bindings, panel_open = KeyBindings(), Condition(lambda: self.state.panel is not None)

        @bindings.add('up', filter=panel_open)
        def up(event): self.state.panel.move(-1)

        @bindings.add('down', filter=panel_open)
        @bindings.add('tab', filter=panel_open)
        def down(event): self.state.panel.move(1)

        @bindings.add('escape')
        def escape(event):
            if self.input.buffer.complete_state:
                self.input.buffer.cancel_completion()
            else:
                self.close_panel()

        @bindings.add('c-c')
        def interrupt(event):
            if self.state.panel or self.input.text:
                self.close_panel()
            elif self.job and not self.job.done():
                if self.job_mutates:
                    self.state.append('pending','正在应用设置，完成后即可继续；此阶段不强行中断。')
                else:
                    self.job.cancel()
            elif time.monotonic() - self.last_interrupt < 1.5:
                event.app.exit()
            else:
                self.state.append('muted', '再次按 Ctrl+C 退出，代理服务会继续运行。')
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
        def refresh(event): self.refresh.set()

        @bindings.add('c-t', filter=Condition(lambda:self.state.panel is not None and self.state.panel.kind=='nodes'))
        def speed(event):
            panel, item = self.state.panel, self.state.panel.selected()
            if panel.kind == 'nodes' and item:
                self.queue('测试节点延迟', 'delay', '--node', item['value'], '--json', done=self.delay_result)

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
            }), full_screen=False, mouse_support=False,
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
            mode = {'rule':'规则','global':'全局','direct':'直连'}.get(data['mode'],'?')
            metadata += [('class:muted','  ·  '+mode)]
        if not data: status,style='连接中…','pending'
        elif not data.get('installed'): status,style='未初始化','pending'
        elif not data.get('reachable'): status,style='接口离线','error'
        elif data.get('awaiting_subscription'): status,style='待添加订阅','pending'
        elif self.state.last_error: status,style='状态待刷新','pending'
        else: status,style='接口在线','success'
        status_line = [('class:'+style,'● '),('class:muted',status)]
        if self.header_height() == 2:
            if data.get('proxy_port') and self.app.output.get_size().columns >= 72:
                metadata += [('class:muted',f"  ·  :{data['proxy_port']}")]
            return [('class:brand','  Domino'),('class:muted','  v'+self.version),('', '\n')] + self.footer_line(metadata,status_line,keep_right=True)
        if data.get('proxy_port'):
            status_line += [('class:muted',f"  ·  :{data['proxy_port']}")]
        if 'node_count' in data:
            counts = f"  ·  {data['node_count']} 节点"
            if isinstance(data.get('groups'),list): counts += f" / {len(data['groups'])} 组"
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
        if not values: return [('class:muted', '  没有匹配项；继续输入或按 Esc 返回。')]
        fragments = []
        for index, item in enumerate(values):
            style = 'class:selected' if index == panel.index else 'class:current' if item.get('current') else ''
            label = ('● ' if item.get('current') else '  ') + clean(item['label'])
            if panel.kind == 'nodes' and item['value'] in self.state.delays:
                number = self.state.delays[item['value']]
                label += f'  {number} ms' if number is not None else '  不可用'
            fragments.append((style, (' › ' if index == panel.index else '   ') + label + '\n'))
        return fragments

    def footer(self):
        data = self.state.snapshot
        available = data.get('stats_available',data.get('reachable',bool(data)))
        connections = str(data.get('connections',0)) if available else '—'
        stats = f"↑ {format_bytes(self.state.up,True)}  ↓ {format_bytes(self.state.down,True)}  ·  {connections} 连接"
        left, right = [('class:muted',stats)], [('class:muted','/ 命令')]
        if self.state.busy:
            left = [('class:pending','⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[int(time.monotonic()*8)%10]+' '+clean(self.state.busy))]
            right = []
        elif self.state.last_error:
            left,right = [('class:error','状态刷新失败 · /refresh 重试')],[]
        elif self.state.panel:
            hint = '↑↓ 选择 · Enter 确认 · Esc 返回' if self.app.output.get_size().columns >= 80 else '↑↓ · Enter 选择 · Esc 返回'
            if self.state.panel.kind == 'nodes': hint += ' · Ctrl+T 测速'
            left,right = [('class:muted',hint)],[('class:muted','输入筛选')]
        else:
            routing = data.get('system_proxy',{}).get('routing')
            notices = {'other':'系统代理指向其他代理 :'+('/'.join(str(v) for v in data.get('system_proxy',{}).get('ports',[])) or '?'),
                       'mixed':'系统代理混用','pac':'系统代理 PAC','off':'系统代理未开启','unknown':'系统代理未知'}
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

    def close_panel(self):
        self.state.panel = None
        self.input.buffer.reset()

    def panel(self, title, items, callback, kind=''):
        self.state.panel = Panel(title, items, callback, kind=kind)
        self.input.buffer.reset()
        self.input.buffer.cancel_completion()

    def accept(self, buffer):
        if buffer.text.strip() in ['exit','/exit']:
            self.request_exit()
            return False
        if self.state.panel:
            panel, item = self.state.panel, self.state.panel.selected()
            self.close_panel()
            if item: panel.callback(item['value'])
        elif buffer.text.strip() == '/':
            self.panel('命令', [{'label': n + '  ' + d, 'value': n} for n,d in COMMANDS], self.dispatch)
        elif buffer.text.strip(): self.dispatch(buffer.text.strip())
        return False

    async def call(self, action, *options, capture=True, timeout=75):
        if action in ['configs', 'switch', 'update'] and timeout == 75:
            timeout = 900
        if action == 'scan':
            arguments = [action, *options]
        elif action in ['proxy','shell'] and options and options[0] in ['status', 'on', 'off']:
            arguments = [action, options[0], self.state.target, *options[1:]]
        elif action == 'rules' and options and options[0] in ['add', 'remove']:
            if timeout == 75:
                timeout = 180
            arguments = [action, *options[2:], '--', options[0], options[1], self.state.target]
        elif action in ['add', 'switch', 'update', 'rename', 'remove', 'set-url']:
            count = 2 if action == 'rename' else 1
            arguments = ['configs', action, *options[count:], '--', *options[:count], self.state.target]
        elif action == 'delay' and options and not options[0].startswith('--'):
            arguments = [action, options[0], self.state.target, *options[1:]]
        else:
            arguments = [action, self.state.target, *options]
        result = self.execute(arguments, capture=capture, timeout=timeout)
        return await result if inspect.isawaitable(result) else result

    async def poll(self):
        while True:
            try: self.state.update(json.loads(await self.call('overview', timeout=8)))
            except asyncio.CancelledError: raise
            except Exception: self.state.stale('无法刷新控制接口；/refresh 重试，/logs 查看日志。')
            self.app.invalidate()
            self.refresh.clear()
            try: await asyncio.wait_for(self.refresh.wait(), 2)
            except asyncio.TimeoutError: pass

    async def animate(self):
        while True:
            await asyncio.sleep(.12 if self.state.busy else .4)
            if self.state.busy:
                self.app.invalidate()

    def queue(self, title, action, *options, done=None, foreground=False, prompt=None):
        if self.job and not self.job.done():
            self.state.append('pending', '已有任务进行中；Ctrl+C 可中断。')
            return
        self.state.busy = title
        self.job_mutates = (action in ['select','start','stop','restart','add','switch','update','rename','remove','set-url'] or '--set' in options or
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
                    self.state.append('success', title + '完成。')
                else:
                    output = await self.call(action, *options)
                    if done: done(output)
                    elif output: self.state.append('info', output.rstrip(), ansi=True)
                    else: self.state.append('success', title + '完成。')
                self.refresh.set()
            except asyncio.CancelledError: self.state.append('muted', '已中断命令；可用 /status 查看实际状态。')
            except asyncio.TimeoutError: self.state.append('error', '操作超时，请重试或使用 /logs 检查。')
            except (Exception, SystemExit) as error: self.state.append('error', clean(str(error)) or '操作失败。')
            finally:
                self.state.busy = ''
                self.job_mutates = False
                self.app.invalidate()
        self.job = self.app.create_background_task(perform())

    def groups(self, for_delay=False):
        groups = self.state.snapshot.get('groups', [])
        if groups: self.group_panel(groups, for_delay)
        else: self.queue('读取策略组', 'nodes', '--json', done=lambda s: self.group_panel(json.loads(s)['groups'],for_delay))

    def group_panel(self, groups, for_delay=False):
        def selected(group):
            if for_delay: self.queue('测试策略组延迟','delay','--group',group['name'],'--json',done=self.delay_result)
            else: self.nodes(group)
        self.panel('策略组',
            [{'label': f"{g['name']} → {g.get('current') or '自动策略'}", 'search':g['name'], 'value':g} for g in groups], selected)

    def nodes(self, group):
        def selected(name):
            if not group['selectable']:
                self.state.append('muted', '该组由策略自动选择；请在上层 Selector 策略组中切换。')
            else: self.queue('切换节点','select','--group',group['name'],'--node',name)
        self.panel(group['name'] + ('' if group['selectable'] else ' · 自动策略'),
            [{'label':n,'value':n,'current':n==group.get('current')} for n in group['choices']], selected, 'nodes')

    def delay_result(self, text):
        for item in json.loads(text):
            self.state.delays[item['name']] = item['delay_ms']
            self.state.append('success' if item['ok'] else 'muted',
                item['name'] + (f"  {item['delay_ms']} ms" if item['ok'] else '  超时 / 不可用'))

    def choices(self, title, values, action):
        self.panel(title,[{'label':label,'value':v,'current':v==self.state.snapshot.get('mode')} for v,label in values],
            lambda v:self.queue(title,action,*([v] if action=='proxy' else ['--set',v]),foreground=action=='proxy'))

    def help(self):
        self.state.append('info','\n'.join(f'{n:14} {d}' for n,d in COMMANDS))
        self.state.append('muted','/mode global · /delay 自动选择 · /rules google · /connections --close ID')
        self.state.append('muted','面板中输入筛选，↑↓ 导航，Enter 确认，Ctrl+T 测速。Ctrl+C 中断命令或清空输入。')

    def can_exit(self):
        if self.job and not self.job.done() and self.job_mutates:
            self.state.append('pending','设置尚在提交，请等操作完成后退出。')
            return False
        return True

    def request_exit(self):
        if self.can_exit():
            self.app.exit()

    def dispatch(self, text):
        try:
            name, args = parse_command(text)
            if not name: return
            if name == '/exit':
                self.request_exit()
                return
            if name == '/clear': self.state.events.clear(); self.state.scroll=0; return
            if name in ['/status','/traffic','/logs','/start','/stop','/restart','/help'] and args:
                raise ValueError(name + ' 不需要额外参数。')
            if name == '/configs':
                visible, hide_next = [], False
                for value in args:
                    visible.append('***' if hide_next else '--url=***' if value.startswith('--url=') else value)
                    hide_next = value == '--url'
                self.state.append('command', shlex.join([name, *visible]))
            else:
                self.state.append('command',text)
            if name == '/help': self.help()
            elif name == '/refresh':
                self.refresh.set()
                self.state.append('muted','已请求刷新状态和流量。')
            elif name == '/nodes':
                if args: self.queue('读取策略组','nodes','--group',' '.join(args),'--json',done=lambda s:self.nodes(json.loads(s)['groups'][0]))
                else: self.groups()
            elif name == '/configs':
                if not args or args == ['list']:
                    self.queue('读取配置', 'configs', '--json', done=lambda s:self.config_panel(json.loads(s)))
                elif args[0] in ['add', 'set-url']:
                    action = args[0]
                    title = '添加订阅' if action == 'add' else '设置订阅地址'
                    values = args[1:]
                    if len(values) == 1:
                        self.queue(title, action, *values, foreground=True)
                    elif (len(values) == 3 and values[1] == '--url') or (len(values) == 2 and values[1].startswith('--url=')):
                        self.queue(title, action, *values)
                    else:
                        raise ValueError('用法：/configs ' + action + ' "配置名称"，地址将隐藏输入；也可附加 --url "HTTPS 地址"。')
                elif args[0] in ['switch', 'update', 'rename', 'remove']:
                    action, values = args[0], args[1:]
                    required = 2 if action == 'rename' else 1
                    if len(values) != required:
                        raise ValueError('用法：/configs ' + action + (' "旧名称" "新名称"' if required == 2 else ' "配置名称"') + ('；/configs update all 更新全部在线订阅。' if action == 'update' else '。'))
                    self.queue('订阅管理', action, *values)
                else:
                    hidden = any(v in ['--add','--set-url'] or v.startswith(('--add=','--set-url=')) for v in args) and not any(v=='--url' or v.startswith('--url=') for v in args)
                    self.queue('配置管理', 'configs', *args, foreground=hidden)
            elif name == '/mode':
                if args:
                    if (len(args)!=1 and not (len(args)==2 and args[0]=='--set')) or args[-1] not in ['rule','global','direct']:
                        raise ValueError('用法：/mode，或 /mode rule|global|direct。')
                    self.queue('切换模式','mode','--set',args[-1])
                else: self.choices('选择运行模式',[('rule','规则模式  按分流规则选择出口'),('global','全局模式  使用 GLOBAL 当前选择'),('direct','直连模式  直接连接目标')],'mode')
            elif name == '/delay':
                if not args: self.queue('测试全部节点延迟','delay','--all','--json',done=self.delay_result)
                elif len(args)==1: self.queue('测试延迟','delay',args[0],'--json',done=self.delay_result)
                elif len(args)==2 and args[0] in ['--node','--group']: self.queue('测试延迟','delay',*args,'--json',done=self.delay_result)
                else: raise ValueError('用法：/delay 测全部，或 /delay "节点或组名" 测指定项。')
            elif name == '/scan':
                if args and not ((len(args)==2 and args[0]=='--source') or
                                 (len(args)==1 and args[0].startswith('--source=') and args[0]!='--source=')):
                    raise ValueError('用法：/scan，或 /scan --source "配置路径"。')
                self.queue('扫描配置与代理出网','scan',*args)
            elif name == '/status': self.queue('验证代理出网','status','--json',done=self.status_result)
            elif name == '/traffic':
                d=self.state.snapshot
                self.state.append('info',f"实时 ↑ {format_bytes(self.state.up,True)} ↓ {format_bytes(self.state.down,True)}；累计 ↑ {format_bytes(d.get('upload_total',0))} ↓ {format_bytes(d.get('download_total',0))}。")
                self.state.append('muted',traffic_notice(d))
                if d.get('system_proxy',{}).get('routing') in ['other','off','mixed']:
                    self.state.append('muted','如需让系统应用使用 Domino，可执行 /proxy on。')
                self.state.append('muted','底部每 2 秒刷新；累计值自内核启动开始计算。')
            elif name == '/connections':
                if not args: self.queue('读取连接','connections','--json',done=self.connections_result)
                elif args==['--all'] or (len(args)==2 and args[0]=='--close'): self.queue('关闭连接','connections',*args)
                else: raise ValueError('用法：/connections，/connections --close ID，/connections --all。')
            elif name == '/rules':
                if args and args[0] in ['add','remove']:
                    if len(args) != 2:
                        raise ValueError('用法：/rules ' + args[0] + ' "完整规则"。例如 /rules add "DOMAIN-SUFFIX,example.com,DIRECT"。')
                    self.queue('新增规则' if args[0]=='add' else '删除自定义规则','rules',*args)
                elif args == ['--custom']:
                    self.queue('读取自定义规则','rules','--custom')
                else:
                    self.queue('读取规则','rules','--limit','20',*(['--match',' '.join(args)] if args else []))
            elif name == '/providers':
                kind=args[0] if args else 'proxy'
                if kind not in ['proxy','rule']: raise ValueError('用法：/providers 或 /providers rule。')
                self.queue('读取集合','providers','--kind',kind,'--json',done=lambda s:self.provider_panel(json.loads(s),kind))
            elif name == '/log-level':
                if args and (len(args)==1 or (len(args)==2 and args[0]=='--set')) and args[-1] in ['debug','info','warning','error','silent']: self.queue('日志级别','log-level','--set',args[-1])
                elif not args: self.choices('日志级别',[(v,v) for v in ['debug','info','warning','error','silent']],'log-level')
                else: raise ValueError('日志级别可选 debug、info、warning、error、silent。')
            elif name == '/shell':
                if not args or args == ['status']: self.queue('终端代理策略','shell','status')
                elif len(args)==1 and args[0] in ['on','off']: self.queue('终端代理策略','shell',args[0])
                else: raise ValueError('用法：/shell status，/shell on，/shell off。')
            elif name == '/proxy':
                if not args: self.choices('macOS 系统代理',[('on','开启 Domino 系统代理'),('off','恢复此前的系统代理设置')],'proxy')
                elif (len(args)==1 or (len(args)==2 and args[0]=='--set')) and args[-1] in ['on','off']: self.queue('系统代理','proxy',args[-1],foreground=True)
                elif args==['status']: self.queue('系统代理状态','proxy','status',foreground=True)
                else: raise ValueError('用法：/proxy，/proxy on，/proxy off，/proxy status。')
            elif name == '/logs': self.queue('查看内核日志','logs','--lines','30',foreground=True)
            elif name in ['/start','/stop','/restart']: self.queue('执行 '+name[1:],name[1:],foreground=True)
        except ValueError as error: self.state.append('error',str(error))

    def status_result(self, text):
        d=json.loads(text)
        self.state.append('success' if d.get('healthy') else 'error','HTTPS 出网验证通过' if d.get('healthy') else 'HTTPS 出网验证未通过')
        self.state.append('info',f"服务 {d.get('service')} · 模式 {d.get('mode')} · 端口 {d.get('proxy_port')} · 出口 {d.get('exit_country') or '未知'}")

    def connections_result(self, text):
        values=json.loads(text).get('connections',[])
        self.state.append('info',f'活跃连接 {len(values)} 条；显示前 20 条。')
        for v in values[:20]: self.state.append('info',f"{v['id']}  {v.get('network')}  {v.get('host')}:{v.get('port')}  {' → '.join(v.get('chains') or [])}")

    def provider_panel(self, values, kind):
        if not values: self.state.append('muted','没有可用集合。'); return
        def selected(item):
            if str(item.get('vehicleType','')).lower() not in ['http','file']:
                self.state.append('muted','这是内置节点快照；请用 /configs 管理和更新完整订阅。')
            else: self.queue('更新集合','providers','--kind',kind,'--update',item['name'])
        self.panel('订阅集合 · Enter 更新 HTTP / file 集合',
            [{'label':f"{v['name']}  [{v.get('vehicleType')}]  {v.get('count')} 项",'value':v} for v in values],selected)

    def config_panel(self, result):
        items = [{'label':f"{v['name']}  {v.get('node_count') if v.get('node_count') is not None else '—'} 节点  {v.get('updated_at') or '尚未下载'}",
                  'value':v, 'current':v['active']} for v in result['configs']]
        items.append({'label':'+ 添加订阅配置', 'value':None})
        items.append({'label':'+ 将当前配置保存为快照', 'value':'snapshot'})
        def selected(item):
            if item == 'snapshot':
                self.queue('保存当前配置', 'configs', '--import-current', foreground=True, prompt='快照名称：')
                return
            if item is None:
                self.queue('添加订阅配置', 'add', foreground=True, prompt='配置名称：')
                return
            actions = [{'label':'切换到此配置', 'value':'switch'}]
            if item['kind'] == 'subscription':
                actions.append({'label':'更新订阅' + ('并应用到当前配置' if item['active'] else '缓存'), 'value':'update'})
            actions.append({'label':'设置订阅地址', 'value':'set-url'})
            if not item['active']:
                actions.append({'label':'删除配置', 'value':'remove'})
            def operate(action):
                if action == 'update' and item['name'] == 'all':
                    self.queue('更新订阅', 'configs', '--update', 'all')
                else:
                    self.queue('配置管理', action, item['name'], foreground=action=='set-url')
            self.panel(item['name'], actions, operate, 'configs-actions')
        self.panel('配置', items, selected, 'configs')

    def run(self):
        def start():
            self.app.create_background_task(self.poll())
            self.app.create_background_task(self.animate())
        try:
            self.app.run(pre_run=start)
        except (EOFError, KeyboardInterrupt):
            pass
        print('已退出 Domino 界面；代理服务继续运行。')


def run(target, execute, version=''):
    Workspace(target,execute,version).run()
