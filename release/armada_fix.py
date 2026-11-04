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
              crash fix: a ship whose target of order 8 no longer exists no longer crashes
              every node of a match at the same moment.
  ddraw.dll   GOG DirectX wrapper: the session-wide shared memory name "dxfilemap" becomes
              "armada1fm". Otherwise the wrapper reads the D3D device pointer of any other
              running game that uses the same GOG wrapper and crashes.
  Strlkup.dll runtime proxy (original kept as Strlkup_orig.dll): the game's cursor applies to
              the game windows only instead of the system-wide arrow cursor; the wrapper's
              shared memory name becomes unique to the process; a destroyed light leaves
              the render engine's light list (the loading screen left dead lights there);
              closing the game window ends the game instead of leaving it running unseen;
              the game and the GOG wrapper move or confine the mouse only while the game
              window is in the foreground; the game's two graphics Mutexes are isolated
              per process and failed acquisition paths release acquired graphics Locks;
              the known GOG wrapper checks GetRenderTarget in its five color-fill
              routines, so a lost device (screen off, locked PC) no longer crashes it.
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

VERSION = '1.3.1'
BACKUP = '.armadafix-backup'
HERE = os.path.dirname(os.path.abspath(__file__))

EXE_BUILDS = {
    '1c37ee8e4a24380c950a91ce5a7f9f96c4fcf3d8ffc0cc7e58faec3835350be6': 'GOG 1.2 RDNA fix, unpatched',
    '0d8fa21add19801926ebc95752b591a820990bbad4f0b7fb49bf8e4a0d05e76e': 'GOG 1.2 RDNA fix + armada_fix 1.0.0 / 1.1.0',
    '6b3676a95607e5b3b2ccc1ca7272aa9a8af2d0bffeb4da1e7b7f38ac7ff7a9d1': 'GOG 1.2 RDNA fix + armada_fix 1.2.0 / 1.3.x',
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

# 5. CraftProcess vtable slot 21 (0x42af80, order 8): when the ship's target (id at +0x134)
#    no longer exists, the code sets edi = 0 ("xor edi, edi" at 0x42afe7) and, unless the ship
#    was hit within the last second, reads [edi+0x1c]: access violation on every node at the
#    same simulation step. The patch jumps from there to the function's return (0x42b034),
#    which is what the original does for a missing target when the other branch is taken.
#    Signature: test byte [eax+0xbc],4; je; mov edi,[esi+0x138]; jmp +2; (xor edi,edi | jmp short).
GUARD_RE = re.compile(rb'\xf6\x80\xbc\x00\x00\x00\x04\x74\x08\x8b\xbe\x38\x01\x00\x00\xeb\x02'
                      rb'(\x33\xff|\xeb\x4b)\x8b\x4e\x18\x68\x00\x00\x80\x3f\xe8....\x84\xc0\x75\x11'
                      rb'\x8b\x4f\x1c', re.S)

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

    hits = list(GUARD_RE.finditer(text))
    if len(hits) != 1:
        raise ValueError(f'expected 1 order-8 target site, found {len(hits)}')
    o = traw + hits[0].start(1)
    if d[o + 2 + 0x4b:o + 2 + 0x4b + 3] != b'\x5f\x5e\xc3':      # pop edi; pop esi; ret
        raise ValueError('order-8 site: unexpected return block')
    out.append((f'crash: order 8 lost target {va(o):#x}', o, b'\x33\xff', b'\xeb\x4b',
                'unpatched' if d[o:o + 2] == b'\x33\xff' else 'patched', True))

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
            window = next(it, None)
            if window is None:
                raise SystemExit('--window expects WxH, native or auto')
        elif a == '--no-window':
            window = None
        elif a == '--no-cursorfix':
            cursor = False
        elif a == '--no-label':
            label = False
        else:
            raise SystemExit(f'unknown option {a}')

    # Reject invalid options and an existing mod-library collision before any write.
    # Otherwise a failed installation could leave only part of the fix installed.
    display = None
    if window:
        if window == 'native':
            display = 'application'
        else:
            if window == 'auto':
                w, h = auto_window()
            else:
                m = re.fullmatch(r'(\d+)x(\d+)', window)
                if not m or min(int(m[1]), int(m[2])) <= 0:
                    raise SystemExit('--window expects a positive WxH, native or auto')
                w, h = int(m[1]), int(m[2])
            display = f'{w}x{h}@60'
    if cursor:
        src = proxy_dll()
        sl = find_file(game, 'Strlkup.dll')
        proxy_original = os.path.join(game, 'Strlkup_orig.dll')
        if src and sl and not is_proxy(sl) and os.path.exists(proxy_original):
            raise SystemExit('Strlkup_orig.dll exists already but Strlkup.dll is not the proxy; check manually; nothing changed')

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
        if not src:
            print('  proxy DLL not found next to this script (skipped)')
        elif sl and not is_proxy(sl):
            os.replace(sl, proxy_original)
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
bQCLPWR7bQBo6AMAAIuRpAAAAFL/14XAdAxfXrgBAAAAW4vlXcOhoEptAGjoAwAAi4ioAAAAUf/XhcB0DF9euAEAAABbi+VdwwAA
AKt7AgBsfAIA3uMCAJ/kAgBOEAMADxEDAB49AwDfPQMAtpgDABWZAwCLEY1EJEhQagBR/5KYAAAAi0QkSFCLCP9RCAAAi5Qk4AEA
AItcJCiLdCQ0AItEJAzHAAAAAAD/dCQM/3QkDP90JAz/kpgAAACFwHgJi0wkDIM5AHUHgQQkAAAAAMIMAAA2twIAMK4CANK/AgAs
AgAAQAIAAEwCAACgAAAAmAgAAEwAAAA/bQMAEGUDAOd1AwAwAgAARAIAAFACAACkAAAAjAgAAFQAAACNTCRMUVaLEFD/kpgAAACL
RCRMUIsQ/1IIAAAAAAAAAIuEJKAAAACLlCRMAgAAXzvGiZ2MCAAAiZWQCAAAXl1bdQXoZlD9/zPAgcQsAgAAwhQAi4QkpAAAAIuM
JFACAACJnYAIAABfO8aJjYQIAABeXVt1BehRmvz/M8CBxDACAADCFACLRCQMxwAAAAAA/3QkDP90JAz/dCQM/5KYAAAAhcB4CYtM
JAyDOQB1B4EEJAAAAADCDAAAi4QkAAAAAMeAAAAAAAEAAACDvCQAAAAAAHUF6AAAAABfXl1buMIBdoiBxAAAAADCFAAAAGbnWACm
51gABuhYAEboWADHAahAXQAAAAAAAABBcm1hZGFDdXJzb3JGaXggMS4zLjEgKGN1cnNvciwgZGRyYXcgbWFwcGluZyBhbmQgZ3Jh
cGhpY3MgTXV0ZXggaXNvbGF0aW9uLCBsaWdodCBsaWZldGltZSwgd2luZG93IGNsb3NlLCBtb3VzZSBhbmQgZm9jdXMgZ3VhcmRz
LCBsb3N0LWRldmljZSBjb2xvci1maWxsIGFuZCBkZXB0aC1yZWFkYmFjayBndWFyZHMpAABtX211dGV4X2RyYXdfY3Vyc29yX29m
ZnNjcmVlbgAAAG1fbXV0ZXhfZHJhd19jdXJzb3Jfb25zY3JlZW4AAAAAJXMuYXJtYWRhLiVsdQAAAFdhaXRGb3JTaW5nbGVPYmpl
Y3QAS0VSTkVMMzIuZGxsAAAAAGRkcmF3LmRsbAAAAGR4bSUwNmxYAAAAAGR4ZmlsZW1hcAAAAGFybWFkYTFmbQAAAFNVVlcAAAAA
i4QkACUAAAAQiYQkAAAAAP8VAABTZXRDdXJzb3JQb3MAAAAAVVNFUjMyLmRsbAAAQ2xpcEN1cnNvcgAAU2V0Rm9yZWdyb3VuZFdp
bmRvdwBTZXRGb2N1cwAAAABBcm1hZGEAAHVzZXIzMi5kbGwAAFNldFN5c3RlbUN1cnNvcgBMb2FkTGlicmFyeUEAAAAAQ3JlYXRl
TXV0ZXhBAAAAAFJlZ2lzdGVyQ2xhc3NBAAAAAAAA8rjragAAAAANAAAA3AAAAIQ2AACEHgAAAAAAAAAAAAD/////AAAAAFQ1AAAB
AAAABgAAAAYAAAAYNQAAMDUAAEg1AABwNQAAnjUAAMo1AAD1NQAAKjYAAMAyAABPNgAAYDUAAI01AAC8NQAA5TUAABI2AAAFAAAA
AQACAAMABABTdHJsa3VwLmRsbABTdHJMb29rdXBDcmVhdGUAU3RybGt1cF9vcmlnLlN0ckxvb2t1cENyZWF0ZQBTdHJMb29rdXBE
ZXN0cm95AFN0cmxrdXBfb3JpZy5TdHJMb29rdXBEZXN0cm95AFN0ckxvb2t1cEZpbmQAU3RybGt1cF9vcmlnLlN0ckxvb2t1cEZp
bmQAU3RyTG9va3VwRm9ybWF0AFN0cmxrdXBfb3JpZy5TdHJMb29rdXBGb3JtYXQAU3RyTG9va3VwX0dsb2JhbF9PYmplY3QAU3Ry
bGt1cF9vcmlnLlN0ckxvb2t1cF9HbG9iYWxfT2JqZWN0AEFybWFkYUN1cnNvckZpeAAAGAAAAAOAA4B4NgAABAAAAHw2AAAIAAAA
nSIAAAAQAAAKEwAAAAAAAAAQAAAKEwAALnRleHQkbW4AAAAAADAAAJgAAAAuaWRhdGEkNQAAAACYMAAAWAQAAC5yZGF0YQAA8DQA
AHABAAAuZWRhdGEAAGA2AAAkAAAALnJkYXRhJHZvbHRtZAAAAIQ2AADcAAAALnJkYXRhJHp6emRiZwAAAGA3AAAoAAAALmlkYXRh
JDIAAAAAiDcAABQAAAAuaWRhdGEkMwAAAACcNwAAlAAAAC5pZGF0YSQ0AAAAADA4AACgAgAALmlkYXRhJDYAAAAAAEAAAGAAAAAu
YnNzAAAAAJw3AAAAAAAAAAAAAPg5AAAAMAAAADgAAAAAAAAAAAAAxDoAAGQwAAAAAAAAAAAAAAAAAAAAAAAAAAAAADA4AABAOAAA
UDgAAGw4AACEOAAAnDgAAKw4AADCOAAA0jgAAOY4AAD8OAAAEDkAACY5AAA+OQAATjkAAGA5AABuOQAAfjkAAJo5AACuOQAAwDkA
ANA5AADcOQAA6DkAAAAAAAAGOgAAEjoAACQ6AAA2OgAATDoAAFg6AABoOgAAejoAAIo6AACYOgAAtDoAAAAAAACHAkdldExhc3RF
cnJvcgAAaQVTZXRMYXN0RXJyb3IAAIwDSW5pdGlhbGl6ZUNyaXRpY2FsU2VjdGlvbgBTAUVudGVyQ3JpdGljYWxTZWN0aW9uAADt
A0xlYXZlQ3JpdGljYWxTZWN0aW9uAADiBFJlbGVhc2VNdXRleAAAFAZXYWl0Rm9yU2luZ2xlT2JqZWN0APMAQ3JlYXRlTXV0ZXhB
AAA7AkdldEN1cnJlbnRQcm9jZXNzADwCR2V0Q3VycmVudFByb2Nlc3NJZADIBVRlcm1pbmF0ZVByb2Nlc3MAAEACR2V0Q3VycmVu
dFRocmVhZElkAADDAUZsdXNoSW5zdHJ1Y3Rpb25DYWNoZQADBlZpcnR1YWxBbGxvYwAACQZWaXJ0dWFsUHJvdGVjdAAABgZWaXJ0
dWFsRnJlZQALBlZpcnR1YWxRdWVyeQAAPgFEaXNhYmxlVGhyZWFkTGlicmFyeUNhbGxzAJwCR2V0TW9kdWxlSGFuZGxlQQAA1gJH
ZXRQcm9jQWRkcmVzcwAA8QNMb2FkTGlicmFyeUEAAGwGbHN0cmNtcEEAAG8GbHN0cmNtcGlBAKQDSXNCYWRSZWFkUHRyAABLRVJO
RUwzMi5kbGwAAAYEd3NwcmludGZBACEAQ2FsbFdpbmRvd1Byb2NBAOgCUmVnaXN0ZXJDbGFzc0EAAGABR2V0Rm9yZWdyb3VuZFdp
bmRvdwA5A1NldEN1cnNvcgBIAUdldEN1cnNvclBvcwAAAARXaW5kb3dGcm9tUG9pbnQAMQNTZXRDbGFzc0xvbmdBABEBRW51bVdp
bmRvd3MAAgJHZXRXaW5kb3dUaHJlYWRQcm9jZXNzSWQAALMARGVzdHJveUN1cnNvcgBVU0VSMzIuZGxsAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAJgBAAAS
MBwwLDAyMDcwPzBFMEwwUjBZMF8wZjBrMHEwdjB7MIAwizCQMJUwoDClMKowxTAdMSQxKjE3MTwxQTFUMV0xYjFnMXIxdzF8MYsx
kTGWMZsxxjHmMfEx+TH+MRUyNDJAMkcyfjKFMqwyujLKMtAyTDNUM6gzrTMGNBw0IzQpNFY0rDQJNUg1XTVnNW41dzV+NYU1jDWT
NaE15DX1NQE2CjYfNkU2XjZlNng2szbfNuY2DjcTNy43WjfpN/s3Bzj1OAQ5GzmgObU5vjnEOc051Dn3Of05IjozOkk6UDpiOnQ6
oTqqOrE6xzrMOvs6EjsfOy47NDtMO1g7bDt1O4w7qDuzO7o70DvdO+Y7CzwSPBw8IjwoPDM8TTxnPHY8fTyxPM889Tz7PAM9Ej0m
PSs9MD07PUA9RT1QPVU9Wj1lPWo9bz19PYM9vT3EPdU94D3yPQw+Gj46Pkk+Tz5rPoo+mT6fPrQ+yj7ZPt8+9z4jPzU/Oz9FP0s/
UT9XP2I/dD+EP4o/lz+mP6s/sT/eP+U/ACAAACwAAAACMAowFjApMDMwOjBFME8wkzCsMOEwcjHuMXYy4jLoMv0yAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
'''


if __name__ == '__main__':
    sys.exit(main(sys.argv))
