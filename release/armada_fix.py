#!/usr/bin/env python3
r"""Star Trek: Armada (GOG "1.2 RDNA fix") - multiplayer sync fix and windowed mode.

Python 3.8+, standard library only. Double-click (or Armada_MP_fix.exe) in the game
folder, drag Armada.exe onto it, or run it against the game folder:

    python armada_fix.py status  "C:\GOG Games\Star Trek Armada"
    python armada_fix.py apply   "C:\GOG Games\Star Trek Armada" [options]
    python armada_fix.py restore "C:\GOG Games\Star Trek Armada"

apply options:
    --window WxH     window size, e.g. 1280x960 (default: auto, largest 4:3 size
                     that fits 80 % of the primary screen height)
    --window native  window in the game's own resolution (640x480 in the menus)
    --no-window      leave dxcfg.ini unchanged (fullscreen as shipped by GOG)
    --no-cursorfix   do not install the Strlkup.dll runtime proxy
    --no-label       keep the main menu label "v1.2" (default shows "v1.2s")

Components (each one is backed up as <file>.armadafix-backup before the first change):
  Armada.exe  sync fix: 3 calls of the time-seeded local RNG in simulation code now use
              the synchronized RNG; 4 stores in the ordnance render pass that cleared the
              ordnance target id depending on local visibility are removed.
              crash fix: a missing or read-only Logs folder no longer ends the game at start.
  ddraw.dll   GOG DirectX wrapper: the session-wide shared memory name "dxfilemap" becomes
              "armada1fm". Otherwise the wrapper reads the D3D device pointer of any other
              running game that uses the same GOG wrapper and crashes.
  Strlkup.dll runtime proxy (original kept as Strlkup_orig.dll): the game's cursor applies to
              the game windows only instead of the system-wide arrow cursor; the wrapper's
              shared memory name becomes unique to the process.
  dxcfg.ini   presentation=windowed, display=<size>.

All players of a multiplayer match need the identical Armada.exe (compare the sha256
that this tool prints). A patched and an unpatched client drift apart.
"""
import hashlib
import os
import re
import shutil
import struct
import sys

VERSION = '1.0.0'
BACKUP = '.armadafix-backup'
HERE = os.path.dirname(os.path.abspath(__file__))

EXE_BUILDS = {
    '1c37ee8e4a24380c950a91ce5a7f9f96c4fcf3d8ffc0cc7e58faec3835350be6': 'GOG 1.2 RDNA fix, unpatched',
}

# ---------------------------------------------------------------------------------------
# Armada.exe
# ---------------------------------------------------------------------------------------
# The game has two generators with the same code "rand(n): s = (s*0x8e1+0x1f) % 0x19981595;
# return s % n" and different state variables:
#   0x5014d0 (state 0x67dc98) seeded with the session seed -> identical on all nodes
#   0x5018c0 (state 0x67dca4) seeded with srand(time(0)) -> different on every node
RNG_MID = bytes.fromhex('33d28d0cc0c1e1032bc8c1e1058d44011fb995159819f7f18bc233d2a3')

# Every patch site is located by its code signature, not by a fixed address, so the tool
# also works on builds where the code moved (other releases, exe-based mods). Each
# signature must match exactly the expected number of times; otherwise nothing is changed.
# Addresses in the comments are those of the GOG 1.2 build.

# 1. Docking approach angle CraftProcess+0x114 = rand(4) * pi/2, drawn from the local RNG:
#      0x42a540 in 0x42a450 (CraftProcess vtable slot 23)
#      0x42b76e in 0x42b430 (CraftProcess vtable slot 27)
#      0x430296 in 0x430270 (unreferenced helper with the same code)
#    Signature: push 4; mov [esi+0x7c], eax; call rel32 (-> local or synced RNG). 3 matches.
CALL_RE = re.compile(rb'\x6a\x04\x89\x46\x7c\xe8(....)', re.S)
CALL_COUNT = 3

# 2. Ordnance render pass 0x4edaf0 (runs per rendered view and frame). Reached only when the
#    shooter is not visible to the local player; clears Ordnance+0xf8 (the target id used by
#    the simulation). The stores become a 6-byte NOP. The simulation's own check (0x4ee620,
#    ordnance vtable slots 17/19) has the same instruction but a different tail and stays.
STORE = bytes.fromhex('899ef8000000')          # mov [esi+0xf8], ebx  (ebx == 0)
NOP6 = bytes.fromhex('8d9b00000000')           # lea ebx, [ebx+0x0]
STORE_TAILS = [bytes.fromhex(x) for x in ('e9f0000000', 'e995000000', '33c9eb5c', '33ff8bcf')]
STORE_RE = re.compile(rb'\x38\x9f[\xb1\xb4]\x01\x00\x00\x74.(' + re.escape(STORE) + rb'|'
                      + re.escape(NOP6) + rb')(' + rb'|'.join(re.escape(t) for t in STORE_TAILS) + rb')', re.S)

# 3. Logging init 0x4ff6xx: if Logs\logfile.txt cannot be created, the game executes int3
#    (a debugger break) and crashes without a message. The code after it already turns file
#    logging off; the int3 becomes a NOP. Signature: ret; int3; mov byte [flag], 0; pop esi;
#    mov esp, ebp; pop ebp; ret. 1 match.
INT3_RE = re.compile(rb'\x5e\x8b\xe5\x5d\xc3([\xcc\x90])\xc6\x05....\x00\x5e\x8b\xe5\x5d\xc3', re.S)

# 4. Main menu version label "v1.2" (4 bytes of padding follow). Only the main menu draws it
#    in LAN/DirectPlay games (the other user is the dead WON login check). The menu draws it
#    into a 40 px wide box, so the marker stays short.
LABEL_OLD = b'v1.2\0\0\0\0'
LABEL_NEW = b'v1.2s\0\0\0'


class Pe:
    def __init__(self, data):
        self.data = data
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe + 4] != b'PE\0\0':
            raise ValueError('not a PE file')
        nsec = struct.unpack_from('<H', data, pe + 6)[0]
        optsz = struct.unpack_from('<H', data, pe + 20)[0]
        self.base = struct.unpack_from('<I', data, pe + 24 + 28)[0]
        self.sections = []
        off = pe + 24 + optsz
        for _ in range(nsec):
            name = bytes(data[off:off + 8]).rstrip(b'\0')
            vsize, va, rsize, raw = struct.unpack_from('<4I', data, off + 8)
            self.sections.append((name, self.base + va, rsize, raw))
            off += 40

    def off(self, va):
        for name, sva, rsize, raw in self.sections:
            if sva <= va < sva + rsize:
                return raw + (va - sva)
        raise ValueError(f'address {va:#x} not in file')

    def text(self):
        for name, sva, rsize, raw in self.sections:
            if name == b'.text':
                return sva, raw, rsize
        raise ValueError('no .text section')


def find_rngs(pe):
    """Return (synced_fn, local_fn). The local generator is the one whose state is written by
    the srand(time(0)) seeding loop "call esi; test eax,eax; mov [state],eax; je loop"."""
    tva, traw, tsize = pe.text()
    d = pe.data
    found = {}
    i = d.find(RNG_MID, traw, traw + tsize)
    while i != -1:
        start = i - 8
        state = bytes(d[start + 4:start + 8])
        full = bytes.fromhex('558beca1') + state + RNG_MID + state + bytes.fromhex('f775088bc25dc3')
        if d[start:start + len(full)] == full:
            found[state] = tva + (start - traw)
        i = d.find(RNG_MID, i + 1, traw + tsize)
    if len(found) != 2:
        raise ValueError(f'expected 2 RNG functions, found {len(found)}')
    local = [fn for st, fn in found.items()
             if d.find(b'\xff\xd6\x85\xc0\xa3' + st + b'\x74', traw, traw + tsize) != -1]
    synced = [fn for fn in found.values() if fn not in local]
    if len(local) != 1 or len(synced) != 1:
        raise ValueError('cannot tell synced and local RNG apart')
    return synced[0], local[0]


def exe_sites(data):
    """List of (name, file_offset, original, patched, state, required)."""
    pe = Pe(data)
    synced, local = find_rngs(pe)
    tva, traw, tsize = pe.text()
    d = bytes(pe.data)
    text = d[traw:traw + tsize]
    out = []

    def va(o):
        return tva + (o - traw)

    calls = []
    for m in CALL_RE.finditer(text):
        o = traw + m.start() + 5                       # offset of the call instruction
        tgt = (va(o) + 5 + struct.unpack('<i', m.group(1))[0]) & 0xFFFFFFFF
        if tgt in (local, synced):
            calls.append((o, tgt))
    if len(calls) != CALL_COUNT:
        raise ValueError(f'expected {CALL_COUNT} RNG call sites, found {len(calls)}')
    for o, tgt in calls:
        orig = b'\xe8' + struct.pack('<i', local - (va(o) + 5))
        new = b'\xe8' + struct.pack('<i', synced - (va(o) + 5))
        out.append((f'sync: rng call {va(o):#x}', o, orig, new,
                    'unpatched' if tgt == local else 'patched', True))

    stores = list(STORE_RE.finditer(text))
    tails = sorted(m.group(2) for m in stores)
    if len(stores) != len(STORE_TAILS) or tails != sorted(STORE_TAILS):
        raise ValueError(f'expected {len(STORE_TAILS)} render store sites, found {len(stores)}')
    for m in stores:
        o = traw + m.start(1)
        out.append((f'sync: render store {va(o):#x}', o, STORE, NOP6,
                    'unpatched' if m.group(1) == STORE else 'patched', True))

    hits = list(INT3_RE.finditer(text))
    if len(hits) != 1:
        raise ValueError(f'expected 1 log int3 site, found {len(hits)}')
    o = traw + hits[0].start(1)
    out.append((f'crash: log open int3 {va(o):#x}', o, b'\xcc', b'\x90',
                'unpatched' if d[o] == 0xCC else 'patched', True))

    for old_new in (LABEL_OLD, LABEL_NEW):
        if d.count(old_new) == 1:
            o = d.find(old_new)
            out.append(('menu label v1.2s', o, LABEL_OLD, LABEL_NEW,
                        'unpatched' if old_new == LABEL_OLD else 'patched', False))
            break
    return out, synced, local


# ---------------------------------------------------------------------------------------
# ddraw.dll (GOG DirectX 1-7 wrapper)
# ---------------------------------------------------------------------------------------
MAP_OLD = b'dxfilemap\0'
MAP_NEW = b'armada1fm\0'


def ddraw_state(data):
    if b'GOG.com DirectX 1-7 wrapper'.decode().encode('utf-16le') not in data:
        return 'not the GOG wrapper'
    if data.count(MAP_OLD) == 1 and MAP_NEW not in data:
        return 'unpatched'
    if data.count(MAP_NEW) == 1 and MAP_OLD not in data:
        return 'patched'
    return 'unknown layout'


# ---------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------
def sha256(b):
    return hashlib.sha256(b).hexdigest()


def find_file(game, name):
    for f in os.listdir(game):
        if f.lower() == name.lower():
            return os.path.join(game, f)
    return None


def backup(path):
    b = path + BACKUP
    if not os.path.exists(b):
        shutil.copy2(path, b)
        print('  backup', os.path.basename(b))


def write_atomic(path, data):
    tmp = path + '.armadafix-tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def proxy_dll():
    """Bytes of the Strlkup.dll proxy: the copy embedded below, or a local build when present."""
    for p in (os.path.join(HERE, 'Strlkup_cursorfix.dll'),
              os.path.join(HERE, '..', 'src', 'strlkup_proxy', 'build', 'Strlkup.dll')):
        if os.path.exists(p):
            return open(p, 'rb').read()
    if PROXY_DLL_B64:
        import base64
        return base64.b64decode(''.join(PROXY_DLL_B64.split()))
    return None


def is_proxy(path):
    return path and os.path.exists(path) and b'ArmadaCursorFix' in open(path, 'rb').read()


def auto_window():
    sizes = [(640, 480), (800, 600), (1024, 768), (1280, 960), (1600, 1200), (1920, 1440), (2560, 1920)]
    h = 1080
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
        h = user32.GetSystemMetrics(1) or h
    except Exception:
        pass
    best = sizes[0]
    for w, hh in sizes:
        if hh <= 0.8 * h:
            best = (w, hh)
    return best


def set_ini(text, key, value):
    pat = re.compile(rf'^{key}\s*=.*$', re.M | re.I)
    if pat.search(text):
        return pat.sub(f'{key}={value}', text)
    return text.rstrip('\r\n') + f'\r\n{key}={value}\r\n'


# ---------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------
def status(game):
    ok = True
    exe = find_file(game, 'Armada.exe')
    if not exe:
        print('Armada.exe not found in', game)
        return 1
    data = bytearray(open(exe, 'rb').read())
    h = sha256(data)
    print(f'Armada.exe  sha256 {h}  ({EXE_BUILDS.get(h, "patched or other build")})')
    try:
        sites, synced, local = exe_sites(data)
        for name, o, orig, new, state, req in sites:
            print(f'  {name:28s} {state}')
        req_states = {s[4] for s in sites if s[5]}
        print('  sync fix:', 'ACTIVE' if req_states == {'patched'} else
              'not applied' if req_states == {'unpatched'} else 'PARTIAL')
    except ValueError as e:
        ok = False
        print('  unsupported executable:', e)
    dd = find_file(game, 'ddraw.dll')
    print('ddraw.dll  ', ddraw_state(open(dd, 'rb').read()) if dd else 'missing')
    sl = find_file(game, 'Strlkup.dll')
    print('Strlkup.dll', 'runtime proxy installed' if is_proxy(sl) else 'original' if sl else 'missing')
    ini = find_file(game, 'dxcfg.ini')
    if ini:
        t = open(ini, encoding='latin1').read()
        m1 = re.search(r'^presentation\s*=\s*(\S+)', t, re.M | re.I)
        m2 = re.search(r'^display\s*=\s*(\S+)', t, re.M | re.I)
        print('dxcfg.ini   presentation=%s display=%s' % (m1 and m1.group(1), m2 and m2.group(1)))
    return 0 if ok else 1


def apply(game, args):
    window = 'auto'
    cursor = True
    label = True
    it = iter(args)
    for a in it:
        if a == '--window':
            window = next(it)
        elif a == '--no-window':
            window = None
        elif a == '--no-cursorfix':
            cursor = False
        elif a == '--no-label':
            label = False
        else:
            raise SystemExit(f'unknown option {a}')

    exe = find_file(game, 'Armada.exe')
    if not exe:
        raise SystemExit('Armada.exe not found in ' + game)
    data = bytearray(open(exe, 'rb').read())
    try:
        sites, synced, local = exe_sites(data)
    except ValueError as e:
        raise SystemExit(f'Armada.exe: unsupported executable ({e}); nothing changed')
    todo = [s for s in sites if s[4] == 'unpatched' and (s[5] or label)]
    print('Armada.exe')
    if todo:
        backup(exe)
        for name, o, orig, new, state, req in todo:
            data[o:o + len(new)] = new
            print('  patched', name)
        check, _, _ = exe_sites(data)
        assert all(s[4] == 'patched' for s in check if s[5])
        write_atomic(exe, data)
    else:
        print('  already patched')
    print('  sha256', sha256(data), '<- must be identical on all multiplayer PCs')

    dd = find_file(game, 'ddraw.dll')
    print('ddraw.dll')
    if dd:
        dd_data = bytearray(open(dd, 'rb').read())
        st = ddraw_state(dd_data)
        if st == 'unpatched':
            backup(dd)
            i = dd_data.find(MAP_OLD)
            dd_data[i:i + len(MAP_NEW)] = MAP_NEW
            write_atomic(dd, dd_data)
            print('  shared memory name dxfilemap -> armada1fm')
        else:
            print(' ', st)
    else:
        print('  missing (skipped)')

    if cursor:
        print('Strlkup.dll')
        src = proxy_dll()
        sl = find_file(game, 'Strlkup.dll')
        orig = os.path.join(game, 'Strlkup_orig.dll')
        if not src:
            print('  proxy DLL not found next to this script (skipped)')
        elif sl and not is_proxy(sl):
            if os.path.exists(orig):
                raise SystemExit('Strlkup_orig.dll exists already but Strlkup.dll is not the proxy; check manually')
            os.replace(sl, orig)
            write_atomic(os.path.join(game, 'Strlkup.dll'), src)
            print('  runtime proxy installed (original kept as Strlkup_orig.dll)')
        elif is_proxy(sl):
            if open(sl, 'rb').read() != src:
                write_atomic(sl, src)
                print('  runtime proxy updated')
            else:
                print('  runtime proxy up to date')
        else:
            print('  Strlkup.dll missing (skipped)')

    if window:
        ini = find_file(game, 'dxcfg.ini') or os.path.join(game, 'dxcfg.ini')
        print('dxcfg.ini')
        if os.path.exists(ini):
            backup(ini)
            text = open(ini, encoding='latin1').read()
        else:
            text = '[dxcfg]\r\n'
        if window == 'native':
            display = 'application'
        else:
            if window == 'auto':
                w, h = auto_window()
            else:
                m = re.fullmatch(r'(\d+)x(\d+)', window)
                if not m:
                    raise SystemExit('--window expects WxH, native or auto')
                w, h = int(m.group(1)), int(m.group(2))
            display = f'{w}x{h}@60'
        text = set_ini(set_ini(text, 'presentation', 'windowed'), 'display', display)
        with open(ini, 'w', encoding='latin1', newline='') as fh:
            fh.write(text.replace('\r\n', '\n').replace('\n', '\r\n'))
        print(f'  presentation=windowed display={display}')
    return 0


def restore(game):
    for name in ('Armada.exe', 'ddraw.dll', 'dxcfg.ini'):
        p = os.path.join(game, name)
        if os.path.exists(p + BACKUP):
            shutil.copy2(p + BACKUP, p)
            os.remove(p + BACKUP)
            print('restored', name)
    sl = find_file(game, 'Strlkup.dll')
    orig = os.path.join(game, 'Strlkup_orig.dll')
    if is_proxy(sl) and os.path.exists(orig):
        os.remove(sl)
        os.replace(orig, os.path.join(game, 'Strlkup.dll'))
        print('restored Strlkup.dll')
    return 0


def interactive(argv):
    """Double-click mode (no command): patch the folder that holds this tool, or the
    Armada.exe dropped onto it, then wait for Enter so the window stays readable."""
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    target = argv[1] if len(argv) > 1 else here
    if os.path.isfile(target):
        target = os.path.dirname(os.path.abspath(target))
    if not find_file(target, 'Armada.exe'):
        print(__doc__)
        print(f'Armada.exe not found in {target}.')
        print('Put this tool into the Star Trek Armada folder and start it there,')
        print('or drag Armada.exe onto it.')
        rc = 1
    else:
        try:
            rc = main([argv[0], 'apply', target])
        except SystemExit as e:
            print(e)
            rc = 1
    try:
        input('\nPress Enter to close.')
    except EOFError:
        pass
    return rc


def main(argv):
    if len(argv) < 3 or argv[1] not in ('status', 'apply', 'restore'):
        if len(argv) <= 2 and (len(argv) == 1 or argv[1] not in ('status', 'apply', 'restore', '-h', '--help')):
            return interactive(argv)
        print(__doc__)
        return 2
    game = argv[2]
    if os.path.isfile(game):
        game = os.path.dirname(os.path.abspath(game))
    print(f'Armada fix {VERSION} - {game}')
    if argv[1] == 'status':
        return status(game)
    if argv[1] == 'apply':
        rc = apply(game, argv[3:])
        print()
        status(game)
        return rc
    return restore(game)


# Strlkup.dll runtime proxy (src/strlkup_proxy), embedded so that this file works alone.
# Regenerated by tools/make_release.py.
PROXY_DLL_B64 = '''
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
JCCDwxSJXCQUg3sMAA+FZf///4tUJBhfXl2LwluDxAzDzMzMzMzMzItMJAhTi1wkCAPLVVaLdCQgM+1XiUwkFI0EMzvBD4eJAAAA
i0QkHIv7K/gPH0QAADPShfZ0EYoMBzoIdRJCQDvWcvOLTCQUhe11YYvr6wSLTCQUQ0eNBDM7wYtEJBx20IXtdEiLHRAgABCNRCQU
UGoEVlX/04XAdDOF9nQYi3wkIIvNK/2L1ooED41JAYhB/4PqAXXyjUQkFFD/dCQYVlX/019eXbgBAAAAW8NfXl0zwFvDzMzMzMzM
zMzMzMzMzFGNBCTHBCQAAAAAUP90JAz/FUQgABD/FQwgABA5BCR1EP90JAxq9P90JBD/FTwgABC4AQAAAFnCCAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAwkAAAoJAAAQCQAAFgkAABuJAAAgCQAAJwkAACwJAAAwCQAAMwkAAAAAAAA5iQAAPIkAAD+JAAADiUAACAlAAAw
JQAAPiUAAFolAAAAAAAAQXJtYWRhQ3Vyc29yRml4IDEuMSAoY3Vyc29yLCBkZHJhdyBtYXBwaW5nIGlzb2xhdGlvbikAAABkZHJh
dy5kbGwAAABkeG0lMDZsWAAAAABkeGZpbGVtYXAAAABhcm1hZGExZm0AAABTZXRTeXN0ZW1DdXJzb3IAVVNFUjMyLmRsbAAATG9h
ZExpYnJhcnlBAAAAAEtFUk5FTDMyLmRsbAAAAAAAAAAAUzfqagAAAAANAAAA3AAAAKQiAACkDAAAAAAAAP////8AAAAAdCEAAAEA
AAAGAAAABgAAADghAABQIQAAaCEAAJAhAAC+IQAA6iEAABUiAABKIgAAUCAAAG8iAACAIQAArSEAANwhAAAFIgAAMiIAAAUAAAAB
AAIAAwAEAFN0cmxrdXAuZGxsAFN0ckxvb2t1cENyZWF0ZQBTdHJsa3VwX29yaWcuU3RyTG9va3VwQ3JlYXRlAFN0ckxvb2t1cERl
c3Ryb3kAU3RybGt1cF9vcmlnLlN0ckxvb2t1cERlc3Ryb3kAU3RyTG9va3VwRmluZABTdHJsa3VwX29yaWcuU3RyTG9va3VwRmlu
ZABTdHJMb29rdXBGb3JtYXQAU3RybGt1cF9vcmlnLlN0ckxvb2t1cEZvcm1hdABTdHJMb29rdXBfR2xvYmFsX09iamVjdABTdHJs
a3VwX29yaWcuU3RyTG9va3VwX0dsb2JhbF9PYmplY3QAQXJtYWRhQ3Vyc29yRml4AAAYAAAAA4ADgJgiAAAEAAAAnCIAAAgAAAC9
EwAAABAAACoEAAAAAAAAABAAACoEAAAudGV4dCRtbgAAAAAAIAAAUAAAAC5pZGF0YSQ1AAAAAFAgAADAAAAALnJkYXRhAAAQIQAA
cAEAAC5lZGF0YQAAgCIAACQAAAAucmRhdGEkdm9sdG1kAAAApCIAANwAAAAucmRhdGEkenp6ZGJnAAAAgCMAACgAAAAuaWRhdGEk
MgAAAACoIwAAFAAAAC5pZGF0YSQzAAAAALwjAABQAAAALmlkYXRhJDQAAAAADCQAAGoBAAAuaWRhdGEkNgAAAAAAMAAAIAAAAC5i
c3MAAAAAvCMAAAAAAAAAAAAA2CQAAAAgAADoIwAAAAAAAAAAAABqJQAALCAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADCQAACgkAABA
JAAAWCQAAG4kAACAJAAAnCQAALAkAADAJAAAzCQAAAAAAADmJAAA8iQAAP4kAAAOJQAAICUAADAlAAA+JQAAWiUAAAAAAACMA0lu
aXRpYWxpemVDcml0aWNhbFNlY3Rpb24AUwFFbnRlckNyaXRpY2FsU2VjdGlvbgAA7QNMZWF2ZUNyaXRpY2FsU2VjdGlvbgAAPAJH
ZXRDdXJyZW50UHJvY2Vzc0lkAAkGVmlydHVhbFByb3RlY3QAAD4BRGlzYWJsZVRocmVhZExpYnJhcnlDYWxscwCcAkdldE1vZHVs
ZUhhbmRsZUEAAPEDTG9hZExpYnJhcnlBAABsBmxzdHJjbXBBAABvBmxzdHJjbXBpQQBLRVJORUwzMi5kbGwAAAYEd3NwcmludGZB
ADkDU2V0Q3Vyc29yAEgBR2V0Q3Vyc29yUG9zAAAABFdpbmRvd0Zyb21Qb2ludAAxA1NldENsYXNzTG9uZ0EAEQFFbnVtV2luZG93
cwACAkdldFdpbmRvd1RocmVhZFByb2Nlc3NJZAAAswBEZXN0cm95Q3Vyc29yAFVTRVIzMi5kbGwAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAABkAAAADDAYMB0wIzAoMC0wMjA9MEIwRzBp
MG4weDB+MIowkDCoMMMw0jDZMA4xLDFQMVYxkzGlMasxtTG7McExxzHSMeQx9DH6MQcyFjIbMiEyczKMMsEyljMCNAg0HTQAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
'''


if __name__ == '__main__':
    sys.exit(main(sys.argv))
