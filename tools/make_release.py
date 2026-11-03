"""Build the release artefacts of the Armada multiplayer fix.

  python tools/make_release.py [--no-build] [--no-exe]

Steps:
  1. build src/strlkup_proxy (Visual Studio Build Tools, x86) unless --no-build
  2. embed the built Strlkup.dll into release/armada_fix.py (PROXY_DLL_B64)
  3. pack release/armada_fix.py with PyInstaller into Armada_MP_fix.exe unless --no-exe
     (python -m pip install pyinstaller)
  4. write SHA256SUMS.txt

Output folder: ARMADA_RELEASE (default: work/release).
"""
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TOOL = os.path.join(BASE, 'release', 'armada_fix.py')
PROXY_DIR = os.path.join(BASE, 'src', 'strlkup_proxy')
PROXY = os.path.join(PROXY_DIR, 'build', 'Strlkup.dll')
OUT = os.environ.get('ARMADA_RELEASE', os.path.join(BASE, 'work', 'release'))


def embed(dll):
    b64 = base64.b64encode(dll).decode()
    lines = '\n'.join(b64[i:i + 100] for i in range(0, len(b64), 100))
    src = open(TOOL, encoding='utf-8').read()
    new, n = re.subn(r"^PROXY_DLL_B64 = (None|'''[^']*''')$",
                     lambda m: "PROXY_DLL_B64 = '''\n" + lines + "\n'''", src, flags=re.M)
    if n != 1:
        raise SystemExit('PROXY_DLL_B64 not found in ' + TOOL)
    if new != src:
        with open(TOOL, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(new)
        print('embedded', len(dll), 'bytes into', TOOL)
    else:
        print('embedded proxy unchanged')


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main(args):
    if '--no-build' not in args:
        subprocess.run(['cmd', '/c', os.path.join(PROXY_DIR, 'build.cmd')], check=True)
    embed(open(PROXY, 'rb').read())
    os.makedirs(OUT, exist_ok=True)
    assets = [os.path.join(OUT, 'armada_fix.py')]
    shutil.copy2(TOOL, assets[0])
    if '--no-exe' not in args:
        work = os.path.join(BASE, 'work', 'pyinstaller')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--onefile', '--console', '--clean', '--noconfirm',
                        '--name', 'Armada_MP_fix', '--distpath', OUT, '--workpath', work,
                        '--specpath', work, TOOL], check=True)
        assets.append(os.path.join(OUT, 'Armada_MP_fix.exe'))
    with open(os.path.join(OUT, 'SHA256SUMS.txt'), 'w', newline='\n') as fh:
        for a in assets:
            fh.write(f'{sha256(a)} *{os.path.basename(a)}\n')
    for a in assets + [os.path.join(OUT, 'SHA256SUMS.txt')]:
        print(f'{os.path.getsize(a):>9}  {a}')


if __name__ == '__main__':
    main(sys.argv[1:])
