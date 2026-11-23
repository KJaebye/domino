"""Live traffic refresh, terminal routing and machine-output compatibility."""
from contextlib import redirect_stdout
import io
import json
import os
import time
import unittest
from unittest.mock import Mock, patch

import domino_agent
import domino_cli as cli
import install_domino as control

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class TrafficTests(unittest.TestCase):
    def test_first_sample_and_counter_reset_do_not_claim_zero_rates(self):
        first = {'uploadTotal': 100, 'downloadTotal': 200, 'connections': [{}]}
        self.assertIsNone(control.traffic_reading(first)['upload_bytes_per_second'])
        result = control.traffic_reading(dict(first, uploadTotal=200, downloadTotal=600), first, 2)
        self.assertEqual((result['upload_bytes_per_second'], result['download_bytes_per_second']), (50, 200))
        reset = control.traffic_reading({'uploadTotal': 1, 'downloadTotal': 2}, first, 1)
        self.assertIsNone(reset['upload_bytes_per_second'])
        self.assertIsNone(reset['download_bytes_per_second'])
        self.assertEqual(reset['upload_total'], 1)

    def test_controller_failure_clears_stale_data_and_recovery_takes_a_new_baseline(self):
        monitor = control._TrafficMonitor(.2)
        frames = []
        class Stop:
            def is_set(self): return False
            def wait(self, interval):
                frames.append(monitor.snapshot())
                return len(frames) == 4
        monitor.stop = Stop()
        readings = [{'uploadTotal': 100, 'downloadTotal': 200}, control.InstallError('PRIVATE detail'),
                    {'uploadTotal': 500, 'downloadTotal': 800}, {'uploadTotal': 600, 'downloadTotal': 1000}]
        with patch.object(control, 'api_json', side_effect=readings) as api, \
                patch.object(control.time, 'monotonic', side_effect=[1, 2, 3]):
            monitor._run()
        self.assertIsNone(frames[0][0]['upload_bytes_per_second'])
        self.assertIsNone(frames[1][0])
        self.assertIn('正在重试', frames[1][1])
        self.assertIsNone(frames[2][0]['upload_bytes_per_second'])
        self.assertEqual(frames[3][0]['upload_bytes_per_second'], 100)
        self.assertEqual(frames[3][0]['download_bytes_per_second'], 200)
        self.assertEqual(frames[3][3], 3)
        self.assertNotIn('PRIVATE', str(frames))
        self.assertTrue(all(call.args == ('/connections',) and 'method' not in call.kwargs for call in api.call_args_list))

    def test_quit_wakes_an_idle_sampler_without_another_request(self):
        from threading import Event
        ready = Event()
        def api(*args, **kwargs):
            ready.set()
            return {'uploadTotal': 1, 'downloadTotal': 2}
        monitor = control._TrafficMonitor(60)
        with patch.object(control, 'api_json', side_effect=api) as request:
            monitor.start()
            self.assertTrue(ready.wait(2))
            start = time.monotonic()
            monitor.close()
            self.assertFalse(monitor.thread.is_alive())
            self.assertLess(time.monotonic()-start, 1)
            self.assertEqual(request.call_count, 1)

    def test_live_modes_only_use_a_real_terminal_and_remote_pty(self):
        for target in [None, 'user@host']:
            for full in [False, True]:
                for terminal, as_json, capture, term in [(True, False, False, 'xterm'), (False, False, False, 'xterm'),
                        (True, True, False, 'xterm'), (True, False, True, 'xterm'), (True, False, False, 'dumb')]:
                    args = cli.build_parser().parse_args(([target] if target else []) + ['traffic']
                        + (['--json'] if as_json else []) + (['--full'] if full else []))
                    ssh = Mock() if target else None
                    live = terminal and not as_json and not capture and term != 'dumb'
                    with patch.object(cli.sys.stdin, 'isatty', return_value=terminal), \
                            patch.object(cli.sys.stdout, 'isatty', return_value=terminal), patch.dict(os.environ, TERM=term), \
                            patch.object(cli, 'run') as run:
                        if full and not live:
                            with self.assertRaises(cli.ToolError): cli.manage(args, ssh, capture=capture)
                            run.assert_not_called()
                            if ssh: ssh.action.assert_not_called()
                            continue
                        cli.manage(args, ssh, capture=capture)
                    call = ssh.action.call_args if ssh else run.call_args
                    arguments = call.args if ssh else call.args[0]
                    self.assertEqual('--compact' in arguments, live and not full)
                    self.assertEqual('--dashboard' in arguments, live and full)
                    if ssh and live: self.assertTrue(call.kwargs['tty'])
        args = cli.normalize_command(cli.build_parser(machine_mode=True).parse_args(['traffic']))
        self.assertEqual(domino_agent.command_request(args), ('traffic.sample', {'interval': 1}))
        args = cli.normalize_command(cli.build_parser(machine_mode=True).parse_args(['traffic', '--full']))
        with self.assertRaises(domino_agent.DomainError): domino_agent.command_request(args)

    def test_bounded_json_stream_stays_plain_and_has_no_dashboard(self):
        output = io.StringIO()
        readings = [{'uploadTotal': 0, 'downloadTotal': 0}, {'uploadTotal': 10, 'downloadTotal': 20},
                    {'uploadTotal': 30, 'downloadTotal': 50}]
        with patch.object(control, 'api_json', side_effect=readings), patch.object(control.time, 'sleep'), \
                patch.object(control.time, 'monotonic', side_effect=[0, 1, 2]), \
                patch.object(control, 'traffic_dashboard') as dashboard, \
                patch.object(control, 'traffic_compact') as compact, redirect_stdout(output):
            control.traffic(watch=True, count=2, as_json=True, dashboard=True, compact=True)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['upload_bytes_per_second'] for row in rows], [10, 20])
        self.assertNotIn('\x1b', output.getvalue())
        dashboard.assert_not_called()
        compact.assert_not_called()

    def test_caller_restores_terminal_when_the_display_subprocess_is_interrupted(self):
        import termios
        for full in [False, True]:
            saved = [1, 2, 3, 4, 5, 6, []]
            terminal = Mock(); terminal.fileno.return_value = 7
            output = io.StringIO()
            with patch.object(cli.sys, 'stdin', terminal), redirect_stdout(output), \
                    patch.object(termios, 'tcgetattr', return_value=saved), patch.object(termios, 'tcsetattr') as restore:
                with self.assertRaises(KeyboardInterrupt):
                    with cli.traffic_terminal(full): raise KeyboardInterrupt()
            restore.assert_called_once_with(7, termios.TCSANOW, saved)
            self.assertIn('\x1b[?25h', output.getvalue())
            self.assertIn('\x1b[?2004l', output.getvalue())
            self.assertEqual('\x1b[?1049l' in output.getvalue(), full)

    def test_inline_contains_full_metrics_and_trends_and_keeps_final_panel(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        sample = control.traffic_reading({'uploadTotal': 2048, 'downloadTotal': 8192, 'connections': [{}], 'memory': 1048576},
                                         {'uploadTotal': 1024, 'downloadTotal': 4096}, 1)
        history = [(100, 200), (1024, 4096)]
        for key in ['q', '\x1b', '\x03']:
            output = io.StringIO()
            monitor = Mock(); monitor.snapshot.return_value = (sample, None, history, 0)
            terminal = Vt100_Output(output, lambda: Size(rows=30, columns=120), enable_cpr=False)
            with create_pipe_input() as pipe, patch.object(control, '_TrafficMonitor', return_value=monitor):
                pipe.send_text(key)
                control.traffic_compact(_input=pipe, _output=terminal)
            text = output.getvalue()
            self.assertNotIn('1049', text)
            for value in ['流量监控', '累计上传', '累计下载', '活跃连接', '内核内存', '上传近期趋势', '下载近期趋势', '峰值']:
                self.assertIn(value, text)
            self.assertIn('1.0 MiB', text)
            self.assertIn('\x1b[?25h', text)
            monitor.close.assert_called_once()

    def test_resize_and_loading_or_error_frames_do_not_display_fake_zero_rates(self):
        class Screen:
            def __init__(self, height, width): self.size, self.lines = (height, width), {}
            def getmaxyx(self): return self.size
            def erase(self): self.lines.clear()
            def addstr(self, y, x, text, style):
                self.assert_width = control.human_width(text) + x < self.size[1]
                if not self.assert_width: raise AssertionError('frame overflowed terminal')
                self.lines[y] = text
            def refresh(self): pass
        for size in [(24, 100), (12, 40), (6, 20)]:
            screen = Screen(*size)
            control.draw_traffic(screen, None, '控制接口不可用，正在重试…', [], 1, {})
            self.assertTrue(all(0 <= y < size[0] for y in screen.lines))
            self.assertIn('q / Esc', screen.lines[size[0]-1])
            self.assertNotIn('0 B/s', str(screen.lines))
        for interval, count in [(0, 0), (61, 0), (1, -1)]:
            with self.assertRaises(control.InstallError): control.traffic_dashboard(interval, count)


if __name__ == '__main__':
    unittest.main()
