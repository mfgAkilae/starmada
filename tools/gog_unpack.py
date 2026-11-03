"""Reassemble files from an innounp-extracted GOG installer (chunked {tmp} format).

Usage: py -I gog_unpack.py <innounp_extract_dir> <output_dir>
"""
import hashlib
import lzma
import os
import re
import sys
import zlib

BS = chr(92)

src, out = sys.argv[1], sys.argv[2]
iss = open(os.path.join(src, 'install_script.iss'), encoding='utf-8-sig').read()
pat = re.compile(
    r'Source: "\{tmp\}\\([0-9a-f]{2})\\([0-9a-f]{2})\\([0-9a-f]{32})";.*?'
    r"BeforeInstall: \"before_install(_dependency)?\('([0-9a-f]{32})', '(.*?)', (\d+)\)\";\s*"
    r"AfterInstall: \"after_install(?:_dependency)?\('([0-9a-f]{32})', (\d+), (\d+)\)\"")
files = {}
order = []
for m in pat.finditer(iss):
    a, b, chunk, dep, fmd5, name, cnt, fmd5b, csize, usize = m.groups()
    key = (fmd5, name)
    if key not in files:
        files[key] = []
        order.append(key)
    files[key].append(os.path.join(src, '{tmp}', a, b, chunk))


def decomp(data):
    for f in (zlib.decompress, lambda d: zlib.decompress(d, -15), lzma.decompress):
        try:
            return f(data)
        except Exception:
            pass
    return data


ok = bad = 0
for key in order:
    fmd5, name = key
    buf = b''.join(decomp(open(p, 'rb').read()) for p in files[key])
    good = hashlib.md5(buf).hexdigest() == fmd5
    dest = os.path.join(out, name.replace(BS, os.sep))
    os.makedirs(os.path.dirname(dest) or out, exist_ok=True)
    with open(dest, 'wb') as fh:
        fh.write(buf)
    ok += good
    bad += not good
    if not good:
        print('MD5 MISMATCH', name, len(buf))
# [Dirs] entries (the game needs e.g. Logs\ and save\; fopen on a missing Logs\ dir hits int3)
sec = iss.find('[Dirs]')
if sec >= 0:
    for m in re.finditer(r'Name: "\{app\}[/\\]?(.*?)";', iss[sec:iss.find('\n[', sec + 1)]):
        os.makedirs(os.path.join(out, m.group(1).replace(BS, os.sep)), exist_ok=True)
print('files', len(order), 'ok', ok, 'bad', bad)
