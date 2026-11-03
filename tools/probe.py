"""Runtime probe for a running Armada.exe (32-bit, WOW64) on Windows.

  python probe.py windows <pid>                 list top-level windows of pid
  python probe.py shot <pid> <out.png>          PrintWindow screenshot of the main window
  python probe.py fpu <pid>                     x87 control word of every thread
  python probe.py pid                           pid(s) of Armada.exe
"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
# Physical pixels: per-monitor DPI aware v2 (otherwise rects and PrintWindow captures are
# virtualized to 96 DPI and a 640x480 window looks cropped at 150 % scaling).
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def pids(name='Armada.exe'):
    out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == name.lower():
            res.append(int(parts[1]))
    return res


def windows(pid):
    res = []

    def cb(hwnd, lp):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            style = user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF
            ex = user32.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF
            res.append(dict(hwnd=hwnd, title=buf.value, cls=cls.value, visible=bool(user32.IsWindowVisible(hwnd)),
                            rect=(r.left, r.top, r.right, r.bottom), style=hex(style), exstyle=hex(ex)))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def main_window(pid):
    ws = [w for w in windows(pid) if w['visible']]
    own = [w for w in ws if w['cls'] == 'Armada']
    if own:
        return own[0]
    ws.sort(key=lambda w: -(w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]))
    return ws[0] if ws else None


def shot(pid, out):
    from PIL import Image
    w = main_window(pid)
    hwnd = w['hwnd']
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    width, height = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG), ('biPlanes', wt.WORD),
                    ('biBitCount', wt.WORD), ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD),
                    ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG), ('biClrUsed', wt.DWORD),
                    ('biClrImportant', wt.DWORD)]
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = width, -height, 1, 32
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mdc, bmp, 0, height, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    Image.frombuffer('RGBA', (width, height), buf, 'raw', 'BGRA', 0, 1).convert('RGB').save(out)
    print('saved', out, width, height, 'PrintWindow ok' if ok else 'PrintWindow FAILED', w['title'])


class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [('ControlWord', wt.DWORD), ('StatusWord', wt.DWORD), ('TagWord', wt.DWORD),
                ('ErrorOffset', wt.DWORD), ('ErrorSelector', wt.DWORD), ('DataOffset', wt.DWORD),
                ('DataSelector', wt.DWORD), ('RegisterArea', ctypes.c_byte * 80), ('Cr0NpxState', wt.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [('ContextFlags', wt.DWORD), ('Dr0', wt.DWORD), ('Dr1', wt.DWORD), ('Dr2', wt.DWORD),
                ('Dr3', wt.DWORD), ('Dr6', wt.DWORD), ('Dr7', wt.DWORD), ('FloatSave', FLOATING_SAVE_AREA),
                ('SegGs', wt.DWORD), ('SegFs', wt.DWORD), ('SegEs', wt.DWORD), ('SegDs', wt.DWORD),
                ('Edi', wt.DWORD), ('Esi', wt.DWORD), ('Ebx', wt.DWORD), ('Edx', wt.DWORD), ('Ecx', wt.DWORD),
                ('Eax', wt.DWORD), ('Ebp', wt.DWORD), ('Eip', wt.DWORD), ('SegCs', wt.DWORD),
                ('EFlags', wt.DWORD), ('Esp', wt.DWORD), ('SegSs', wt.DWORD), ('ExtendedRegisters', ctypes.c_byte * 512)]


def threads(pid):
    class THREADENTRY32(ctypes.Structure):
        _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                    ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG),
                    ('dwFlags', wt.DWORD)]
    snap = k32.CreateToolhelp32Snapshot(4, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    res = []
    ok = k32.Thread32First(snap, ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            res.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    return res


def fpu(pid):
    k32.OpenThread.restype = wt.HANDLE
    for tid in threads(pid):
        h = k32.OpenThread(0x0008 | 0x0002 | 0x0040, False, tid)  # GET/SET_CONTEXT, SUSPEND, QUERY_INFO
        if not h:
            print(tid, 'open failed', ctypes.get_last_error())
            continue
        k32.Wow64SuspendThread(h)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = 0x00010000 | 0x08 | 0x01  # i386 | FLOATING_POINT | CONTROL
        ok = k32.Wow64GetThreadContext(h, ctypes.byref(ctx))
        k32.ResumeThread(h)
        k32.CloseHandle(h)
        cw = ctx.FloatSave.ControlWord & 0xFFFF
        pc = {0: '24-bit', 2: '53-bit', 3: '64-bit', 1: 'reserved'}[(cw >> 8) & 3]
        rc = ['nearest', 'down', 'up', 'chop'][(cw >> 10) & 3]
        print(f'tid {tid}: cw={cw:#06x} precision={pc} rounding={rc} eip={ctx.Eip:#x}' if ok else f'tid {tid}: ctx failed')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'pid':
        print(pids())
    elif cmd == 'windows':
        for w in windows(int(sys.argv[2])):
            print(w)
    elif cmd == 'shot':
        shot(int(sys.argv[2]), sys.argv[3])
    elif cmd == 'fpu':
        fpu(int(sys.argv[2]))


def children(hwnd):
    res = []

    def cb(h, lp):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        r = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        txt = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, txt, 64)
        res.append((h, cls.value, txt.value, (r.left, r.top, r.right, r.bottom), bool(user32.IsWindowVisible(h)),
                    user32.GetDlgCtrlID(h)))
        return True
    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return res


def click(hwnd, x, y):
    import time
    lp = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, 0x200, 0, lp)
    time.sleep(0.15)
    user32.PostMessageW(hwnd, 0x201, 1, lp)
    time.sleep(0.1)
    user32.PostMessageW(hwnd, 0x202, 0, lp)


def dialogs(pid):
    return [w for w in windows(pid) if w['cls'] == '#32770' and w['visible']]


if __name__ == '__main__' and sys.argv[1] == 'children':
    for c in children(int(sys.argv[2])):
        print(c)
if __name__ == '__main__' and sys.argv[1] == 'click':
    # click <pid> <x> <y> [dialog|main]
    pid = int(sys.argv[2])
    target = dialogs(pid)[0]['hwnd'] if (len(sys.argv) < 6 or sys.argv[5] == 'dialog') else main_window(pid)['hwnd']
    click(target, int(sys.argv[3]), int(sys.argv[4]))
    print('clicked', hex(target))


def modules(pid):
    """(base, size, name) of 32-bit modules via toolhelp."""
    class ME32(ctypes.Structure):
        _fields_ = [('dwSize', wt.DWORD), ('th32ModuleID', wt.DWORD), ('th32ProcessID', wt.DWORD),
                    ('GlblcntUsage', wt.DWORD), ('ProccntUsage', wt.DWORD), ('modBaseAddr', ctypes.c_void_p),
                    ('modBaseSize', wt.DWORD), ('hModule', wt.HMODULE), ('szModule', ctypes.c_char * 256),
                    ('szExePath', ctypes.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)
    me = ME32()
    me.dwSize = ctypes.sizeof(me)
    res = []
    ok = k32.Module32First(ctypes.c_void_p(snap), ctypes.byref(me))
    while ok:
        res.append((me.modBaseAddr or 0, me.modBaseSize, me.szModule.decode()))
        ok = k32.Module32Next(ctypes.c_void_p(snap), ctypes.byref(me))
    return res


if __name__ == '__main__' and sys.argv[1] == 'where':
    pid = int(sys.argv[2])
    mods = modules(pid)
    def name(a):
        for b, s, n in mods:
            if b <= a < b + s:
                return f'{n}+{a - b:#x}'
        return hex(a)
    k32.OpenThread.restype = wt.HANDLE
    k32.OpenProcess.restype = wt.HANDLE
    hp = k32.OpenProcess(0x10 | 0x400, False, pid)
    for tid in threads(pid):
        h = k32.OpenThread(0x0008 | 0x0002 | 0x0040, False, tid)
        k32.Wow64SuspendThread(h)
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = 0x00010000 | 0x01
        k32.Wow64GetThreadContext(h, ctypes.byref(ctx))
        stack = (ctypes.c_uint32 * 64)()
        n = ctypes.c_size_t()
        k32.ReadProcessMemory(hp, ctypes.c_void_p(ctx.Esp), stack, 256, ctypes.byref(n))
        k32.ResumeThread(h)
        k32.CloseHandle(h)
        allmods = len(sys.argv) > 3 and sys.argv[3] == 'all'
        rets = [name(v) for v in stack if any(b <= v < b + s for b, s, nn in mods
                if allmods or nn.lower() in ('armada.exe', 'ddraw.dll'))][:14]
        print(tid, 'eip', name(ctx.Eip), '| stack', ' '.join(rets))
