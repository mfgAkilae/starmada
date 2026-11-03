"""mouse_watchdog.py [minutes] [log]: guard the user's mouse during test runs.

Polls the system cursor clip rectangle every 50 ms. When a test instance confines the
cursor (a clip inside an Armada window) or an Armada window becomes the foreground
window, all Armada.exe processes are killed, the clip is released and the event is
logged. Other clips (e.g. Windows while the user drags a window) are only logged. Ends after the given minutes (default 120) or 60 s after the last
Armada.exe process ended.
"""
import ctypes
import ctypes.wintypes as w
import subprocess
import sys
import time

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 120
log = open(sys.argv[2] if len(sys.argv) > 2 else r'E:\dev\starmada\work\mouse_watchdog.log', 'a')


def clip():
    r = w.RECT()
    user32.GetClipCursor(ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def armada_pids():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Armada.exe', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    return {int(l.split('","')[1]) for l in out.splitlines() if l.startswith('"Armada.exe"')}


def fg_pid():
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def fg_desc():
    h = user32.GetForegroundWindow()
    cls, title = ctypes.create_unicode_buffer(128), ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(h, cls, 128)
    user32.GetWindowTextW(h, title, 128)
    return f'hwnd {h:#x} class {cls.value!r} title {title.value!r}'


def armada_rects(pids):
    rects = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(h, _):
        pid = w.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(h):
            r = w.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            rects.append((r.left, r.top, r.right, r.bottom))
        return True
    user32.EnumWindows(cb, 0)
    return rects


def inside(c, r, tol=4):
    return c[0] >= r[0] - tol and c[1] >= r[1] - tol and c[2] <= r[2] + tol and c[3] <= r[3] + tol


def say(msg):
    log.write(time.strftime('%H:%M:%S ') + msg + '\n')
    log.flush()
    print(msg, flush=True)


base = clip()
say(f'start clip={base}')
end = time.time() + minutes * 60
pids, last_seen, n, seen_clip = set(), time.time(), 0, None
while time.time() < end:
    if n % 20 == 0:                       # process list once a second
        pids = armada_pids()
        if pids:
            last_seen = time.time()
        elif time.time() - last_seen > 60:
            say('no Armada.exe for 60 s, done')
            break
    n += 1
    c, f = clip(), fg_pid()
    # a clip counts only when it holds the cursor inside an Armada window; Windows itself
    # clips to the work area while the user drags or resizes a window
    held = bool(pids) and c != base and any(inside(c, r) for r in armada_rects(pids))
    if c != base and c != seen_clip and not held:
        say(f'clip={c} not inside an Armada window, ignored')
    seen_clip = c
    if pids and (held or f in pids):
        why = f'clip={c}' if c != base else f'foreground pid {f} {fg_desc()}'
        subprocess.run(['taskkill', '/F', '/IM', 'Armada.exe'], capture_output=True)
        user32.ClipCursor(None)
        say(f'ALERT {why}: killed Armada.exe {sorted(pids)}')
        sys.exit(1)
    time.sleep(0.05)
say('end')
