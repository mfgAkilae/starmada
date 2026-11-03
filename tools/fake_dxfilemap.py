"""Hold a named file mapping "dxfilemap" with a bogus device pointer (simulates another
process that uses the GOG DirectX wrapper) for N seconds."""
import ctypes
import struct
import sys
import time

k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateFileMappingA.restype = ctypes.c_void_p
k.MapViewOfFile.restype = ctypes.c_void_p
k.CreateFileMappingA.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.c_uint32, ctypes.c_char_p]
k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
name = (sys.argv[2] if len(sys.argv) > 2 else 'dxfilemap').encode()
h = k.CreateFileMappingA(ctypes.c_void_p(-1), None, 0x04, 0, 4096, name)
v = k.MapViewOfFile(h, 0x000F001F, 0, 0, 0)
ctypes.memmove(v, struct.pack('<6I', 1, 0x0BADF00C, 640, 480, 32, 0), 24)
print('holding', name, hex(h), flush=True)
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 40)
