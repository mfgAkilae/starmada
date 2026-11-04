"""Patcher integration checks using an owned GOG install; no game is launched.

python tools/test_patcher.py work/install [--exe work/release/Armada_MP_fix.exe]
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

FILES = ('Armada.exe', 'ddraw.dll', 'Strlkup.dll', 'dxcfg.ini')
EXPECTED = '6b3676a95607e5b3b2ccc1ca7272aa9a8af2d0bffeb4da1e7b7f38ac7ff7a9d1'


class Patcher(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)
        self.originals = {name: (SOURCE / name).read_bytes() for name in FILES}
        for name in FILES:
            shutil.copy2(SOURCE / name, self.game / name)

    def run_tool(self, *args, ok=True):
        r = subprocess.run(COMMAND + [str(a) for a in args], input='\n', capture_output=True, text=True, timeout=45)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.game.iterdir()}

    def test_apply_idempotent_restore(self):
        self.run_tool('apply', self.game, '--window', 'native')
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(), EXPECTED)
        self.assertEqual((self.game / 'Strlkup_orig.dll').read_bytes(), self.originals['Strlkup.dll'])
        self.assertIn(b'presentation=windowed', (self.game / 'dxcfg.ini').read_bytes())
        first = self.snapshot()
        self.run_tool('apply', self.game, '--window', 'native')
        self.assertEqual(self.snapshot(), first)
        self.run_tool('restore', self.game)
        self.assertEqual(self.snapshot(), {name: hashlib.sha256(data).hexdigest() for name, data in self.originals.items()})

    def test_unsupported_exe_changes_nothing(self):
        (self.game / 'Armada.exe').write_bytes(b'unsupported executable')
        before = self.snapshot()
        self.run_tool('apply', self.game, '--window', 'native', ok=False)
        self.assertEqual(self.snapshot(), before)

    def test_bad_window_option_changes_nothing(self):
        before = self.snapshot()
        for options in (('--window', 'invalid'), ('--window', '0x480'), ('--window',)):
            with self.subTest(options=options):
                self.run_tool('apply', self.game, *options, ok=False)
                self.assertEqual(self.snapshot(), before)

    def test_proxy_collision_changes_nothing(self):
        (self.game / 'Strlkup_orig.dll').write_bytes(b'existing mod library')
        before = self.snapshot()
        self.run_tool('apply', self.game, '--window', 'native', ok=False)
        self.assertEqual(self.snapshot(), before)

    def test_drag_and_drop(self):
        self.run_tool(self.game / 'Armada.exe')
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(), EXPECTED)

    def test_double_click_standalone(self):
        tool = self.game / Path(COMMAND[-1]).name
        shutil.copy2(COMMAND[-1], tool)
        command = [str(tool)] if tool.suffix.lower() == '.exe' else [sys.executable, str(tool)]
        r = subprocess.run(command, input='\n', capture_output=True, text=True, timeout=45)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(), EXPECTED)

    def test_upgrade_from_v110_preserves_original_backup(self):
        root = Path(__file__).resolve().parents[1]
        old = subprocess.run(['git', 'show', 'v1.1.0:release/armada_fix.py'], cwd=root,
                             capture_output=True, check=True).stdout
        previous = self.game / 'previous_tool.py'
        previous.write_bytes(old)
        subprocess.run([sys.executable, str(previous), 'apply', str(self.game), '--window', 'native'],
                       capture_output=True, check=True, timeout=45)
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(),
                         '0d8fa21add19801926ebc95752b591a820990bbad4f0b7fb49bf8e4a0d05e76e')
        self.run_tool('apply', self.game, '--window', 'native')
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(), EXPECTED)
        self.assertEqual((self.game / 'Armada.exe.armadafix-backup').read_bytes(), self.originals['Armada.exe'])
        self.run_tool('restore', self.game)
        for name, data in self.originals.items():
            self.assertEqual(hashlib.sha256((self.game / name).read_bytes()).hexdigest(), hashlib.sha256(data).hexdigest())

    def test_upgrade_from_v130_updates_proxy_only(self):
        root = Path(__file__).resolve().parents[1]
        old = subprocess.run(['git', 'show', 'v1.3.0:release/armada_fix.py'], cwd=root,
                             capture_output=True, check=True).stdout
        previous = self.game / 'previous_tool.py'
        previous.write_bytes(old)
        subprocess.run([sys.executable, str(previous), 'apply', str(self.game), '--window', 'native'],
                       capture_output=True, check=True, timeout=45)
        old_proxy = (self.game / 'Strlkup.dll').read_bytes()
        before = {p.name: p.read_bytes() for p in self.game.iterdir() if p.name != 'Strlkup.dll'}
        self.run_tool('apply', self.game, '--window', 'native')
        self.assertNotEqual((self.game / 'Strlkup.dll').read_bytes(), old_proxy)
        self.assertEqual({p.name: p.read_bytes() for p in self.game.iterdir() if p.name != 'Strlkup.dll'}, before)
        self.assertEqual(hashlib.sha256((self.game / 'Armada.exe').read_bytes()).hexdigest(), EXPECTED)
        self.run_tool('restore', self.game)
        for name, data in self.originals.items():
            self.assertEqual((self.game / name).read_bytes(), data)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--exe', type=Path)
    args = p.parse_args()
    SOURCE = args.source.resolve()
    COMMAND = [str(args.exe.resolve())] if args.exe else [sys.executable, str(Path(__file__).resolve().parents[1] / 'release' / 'armada_fix.py')]
    unittest.main(argv=[sys.argv[0]], verbosity=2)
