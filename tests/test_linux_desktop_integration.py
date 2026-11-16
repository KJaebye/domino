"""Real GSettings/dconf in a new D-Bus session and temporary user directories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform=='linux' and shutil.which('dbus-run-session') and shutil.which('gsettings'),
                     'requires Linux, dbus-run-session and GNOME schemas')
class LinuxDesktopIntegrationTests(unittest.TestCase):
    def test_real_desktop_apply_repeat_and_restore_in_an_isolated_session(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='domino-dconf-') as directory:
            home=Path(directory);runtime=home/'run';runtime.mkdir(mode=0o700)
            env={**os.environ,'HOME':str(home),'XDG_CONFIG_HOME':str(home/'config'),
                 'XDG_RUNTIME_DIR':str(runtime),'XDG_CURRENT_DESKTOP':'GNOME','GSETTINGS_BACKEND':'dconf',
                 'PYTHONPATH':str(project / 'src')}
            for name in ['DBUS_SESSION_BUS_ADDRESS','DISPLAY','WAYLAND_DISPLAY']:env.pop(name,None)
            code='''
import json
from pathlib import Path
from types import SimpleNamespace
import domino_linux as linux
import install_domino as control
home=Path.home();app=home/'app';(app/'data').mkdir(parents=True)
(app/'data/config.json').write_text('{"mixed-port":17897}')
shell=app/'shell-policy.json';shell.write_text('unchanged')
ctx=SimpleNamespace(HOME=home,current_installation=lambda:(app,None),systemctl=lambda _:True,
                    controller=lambda *a,**k:b'{}',write_private=control.write_private,
                    subscription_pending=control.subscription_pending)
settings=linux.Settings();original=settings.state()
for _ in range(2):
 result=linux.system_proxy(ctx,'on',render=False)
 assert result['routing']=='domino'
 assert all(v['port']==17897 for v in result['proxies'].values())
assert json.loads(linux.record_path(ctx).read_text())['original']==original
linux.system_proxy(ctx,'off',render=False)
assert settings.state()==original
assert not linux.record_path(ctx).exists() and shell.read_text()=='unchanged'
print(json.dumps({'real_dconf_apply_and_restore':True,'user_home_isolated':True}))
'''
            result=subprocess.run(['dbus-run-session','--',sys.executable,'-c',code],env=env,cwd=home,
                                  capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr[-2000:])
            self.assertTrue(json.loads(result.stdout)['real_dconf_apply_and_restore'])
