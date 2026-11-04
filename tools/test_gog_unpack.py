"""Regression checks for continuation chunks in the GOG installer manifest."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zlib

import gog_unpack


class GogChunks(unittest.TestCase):
    def fixture(self, root):
        chunks = [b'first chunk', b'continuation', b'final chunk']
        full = hashlib.md5(b''.join(chunks)).hexdigest()
        rows, paths = ['[Files]'], []
        for i, chunk in enumerate(chunks):
            name = f'{i:032x}'
            path = root / '{tmp}' / '00' / '00' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            packed = zlib.compress(chunk)
            path.write_bytes(packed)
            row = f'Source: "{{tmp}}\\00\\00\\{name}"; '
            if i == 0:
                row += f"BeforeInstall: \"before_install('{full}', 'animations\\STIntro.bik', 3)\"; "
            row += f"AfterInstall: \"after_install('{hashlib.md5(chunk).hexdigest()}', {len(packed)}, {len(chunk)})\";"
            rows.append(row)
            paths.append(path)
        (root / 'install_script.iss').write_text('\n'.join(rows))
        return chunks, paths, rows

    def test_continuation_rows_reassemble_complete_file(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td), Path(td) / 'out'
            chunks, _, _ = self.fixture(root)
            self.assertEqual(gog_unpack.unpack(root, out), 1)
            self.assertEqual((out / 'animations' / 'STIntro.bik').read_bytes(), b''.join(chunks))

    def test_missing_continuation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, rows = self.fixture(Path(td))
            with self.assertRaisesRegex(ValueError, 'missing continuation'):
                gog_unpack.manifest('\n'.join(rows[:-1]))

    def test_empty_or_unrecognized_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no GOG chunk entries'):
            gog_unpack.manifest('[Files]\nSource: "unrelated-file";')

    def test_corrupt_chunk_is_rejected_before_output_write(self):
        with tempfile.TemporaryDirectory() as td:
            root, out = Path(td), Path(td) / 'out'
            _, paths, _ = self.fixture(root)
            paths[1].write_bytes(zlib.compress(b'corrupt continuation'))
            with self.assertRaisesRegex(ValueError, 'chunk length/MD5 mismatch'):
                gog_unpack.unpack(root, out)
            self.assertFalse((out / 'animations' / 'STIntro.bik').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
