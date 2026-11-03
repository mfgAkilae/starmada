"""Regression checks for false-green multiplayer dump comparisons."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import cmpdumps


class CompareDumps(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / 'A', self.root / 'B'
        self.a.mkdir()
        self.b.mkdir()

    def dump(self, folder, body='health 100', step=50, end=True):
        text = f'step {step} synced_rng 123 table_index 1\n{body}\n'
        if end:
            text += f'END step {step}\n'
        (folder / f'step_{step:06d}.txt').write_text(text)

    def compare(self, *options):
        with redirect_stdout(io.StringIO()):
            return cmpdumps.main([str(self.a), str(self.b), *options])

    def test_no_pairs_is_failure(self):
        self.assertEqual(self.compare(), 2)

    def test_only_local_fields_are_ignored(self):
        self.dump(self.a, 'isVisible 2 seen 2\nlocal state local_rng aa')
        self.dump(self.b, 'isVisible 4 seen 4\nlocal state local_rng bb')
        self.assertEqual(self.compare(), 0)

    def test_divergence_is_failure(self):
        self.dump(self.a)
        self.dump(self.b, 'health 99')
        self.assertEqual(self.compare(), 1)

    def test_extra_lines_are_divergence(self):
        self.dump(self.a)
        self.dump(self.b, 'health 100\nextra object')
        self.assertEqual(self.compare(), 1)

    def test_missing_end_marker_is_failure(self):
        self.dump(self.a, end=False)
        self.dump(self.b, end=False)
        self.assertEqual(self.compare(), 2)
        self.assertEqual(self.compare('--legacy'), 2)  # still too short

    def test_synchronized_rng_is_compared(self):
        for folder in (self.a, self.b):
            self.dump(folder)
        path = self.b / 'step_000050.txt'
        path.write_text(path.read_text().replace('synced_rng 123', 'synced_rng 456'))
        self.assertEqual(self.compare(), 1)

    def test_old_cache_never_hides_reused_run(self):
        state = self.root / 'equal.txt'
        self.dump(self.a)
        self.dump(self.b)
        self.assertEqual(self.compare('--state', str(state)), 0)
        self.dump(self.b, 'health 99')
        self.assertEqual(self.compare('--state', str(state)), 1)

    def test_expected_step_and_pair_count(self):
        self.dump(self.a)
        self.dump(self.b)
        self.assertEqual(self.compare('--min-step', '100'), 2)
        self.assertEqual(self.compare('--min-pairs', '2'), 2)
        self.assertEqual(self.compare('--min-step', '50', '--min-pairs', '1'), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
