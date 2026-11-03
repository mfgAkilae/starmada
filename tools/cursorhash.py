"""Print a hash of the current system arrow cursor (OCR_NORMAL) image."""
import ctypes
import ctypes.wintypes as wt
import hashlib

user32 = ctypes.WinDLL('user32')
gdi32 = ctypes.WinDLL('gdi32')


class ICONINFO(ctypes.Structure):
    _fields_ = [('fIcon', wt.BOOL), ('xHotspot', wt.DWORD), ('yHotspot', wt.DWORD),
                ('hbmMask', wt.HBITMAP), ('hbmColor', wt.HBITMAP)]


user32.LoadCursorW.restype = wt.HANDLE
user32.CopyImage.restype = wt.HANDLE
h = user32.CopyImage(user32.LoadCursorW(None, 32512), 2, 0, 0, 0)  # IMAGE_CURSOR copy of current IDC_ARROW
ii = ICONINFO()
user32.GetIconInfo(wt.HANDLE(h), ctypes.byref(ii))
digest = hashlib.sha256()
for bm in (ii.hbmMask, ii.hbmColor):
    if bm:
        buf = ctypes.create_string_buffer(64 * 64 * 4)
        n = gdi32.GetBitmapBits(wt.HBITMAP(bm), len(buf), buf)
        digest.update(buf.raw[:n])
print('arrow', digest.hexdigest()[:16], 'hotspot', ii.xHotspot, ii.yHotspot)
