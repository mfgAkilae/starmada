"""Reassemble an innounp-extracted GOG installer, including continuation chunks.

Usage: python gog_unpack.py <innounp_extract_dir> <output_dir>
Every chunk and complete file must match the install manifest before it is written.
"""
import hashlib
import lzma
from pathlib import Path
import re
import sys
import zlib

SOURCE = re.compile(r'Source: "\{tmp\}\\([0-9a-f]{2})\\([0-9a-f]{2})\\([0-9a-f]{32})";')
BEFORE = re.compile(r"before_install(?:_dependency)?\('([0-9a-f]{32})', '(.*?)', (\d+)\)")
AFTER = re.compile(r"after_install(?:_dependency)?\('([0-9a-f]{32})', (\d+), (\d+)\)")


def decomp(data):
    for f in (zlib.decompress, lambda d: zlib.decompress(d, -15), lzma.decompress):
        try:
            return f(data)
        except (zlib.error, lzma.LZMAError):
            pass
    return data


def manifest(iss):
    """Only the first chunk has BeforeInstall; subsequent rows have AfterInstall only."""
    entries, current = [], None
    for line in iss.splitlines():
        source, before, after = SOURCE.search(line), BEFORE.search(line), AFTER.search(line)
        if not source or not after:
            continue
        if before:
            if current is not None:
                raise ValueError('missing continuation chunks for ' + current['name'])
            current = dict(md5=before[1], name=before[2], count=int(before[3]), chunks=[])
        if current is None:
            raise ValueError('continuation chunk without BeforeInstall')
        current['chunks'].append((source.groups(), after[1], int(after[3])))
        if len(current['chunks']) == current['count']:
            entries.append(current)
            current = None
    if current is not None:
        raise ValueError('missing continuation chunks for ' + current['name'])
    if not entries:
        raise ValueError('no GOG chunk entries found in manifest')
    return entries


def unpack(src, out):
    src, out = Path(src), Path(out).resolve()
    iss = (src / 'install_script.iss').read_text(encoding='utf-8-sig')
    entries = manifest(iss)
    for entry in entries:
        pieces = []
        for parts, expected, expanded in entry['chunks']:
            chunk = decomp((src / '{tmp}' / Path(*parts)).read_bytes())
            if len(chunk) != expanded or hashlib.md5(chunk).hexdigest() != expected:
                raise ValueError('chunk length/MD5 mismatch for ' + entry['name'])
            pieces.append(chunk)
        buf = b''.join(pieces)
        if hashlib.md5(buf).hexdigest() != entry['md5']:
            raise ValueError('complete-file MD5 mismatch for ' + entry['name'])
        dest = (out / entry['name'].replace('\\', '/')).resolve()
        if out not in dest.parents:
            raise ValueError('file path escapes output directory')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(buf)
    start = iss.find('[Dirs]')
    if start >= 0:
        end = iss.find('\n[', start + 1)
        for match in re.finditer(r'Name: "\{app\}[/\\]?(.*?)";', iss[start:end if end >= 0 else None]):
            dest = (out / match[1].replace('\\', '/')).resolve()
            if dest != out and out not in dest.parents:
                raise ValueError('directory path escapes output directory')
            dest.mkdir(parents=True, exist_ok=True)
    print('files', len(entries), 'ok', len(entries), 'bad 0')
    return len(entries)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    unpack(*sys.argv[1:])
