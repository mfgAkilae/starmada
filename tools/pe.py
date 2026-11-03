"""Small static-analysis helpers for Armada.exe (x86 PE): VA mapping, disassembly, call-site scans."""
import struct
import sys

import capstone
import pefile


class Image:
    def __init__(self, path):
        self.path = path
        self.pe = pefile.PE(path, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.data = bytearray(open(path, 'rb').read())
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.md.detail = False
        text = [s for s in self.pe.sections if s.Name.startswith(b'.text')][0]
        self.text_va = self.base + text.VirtualAddress
        self.text_off = text.PointerToRawData
        self.text_size = min(text.Misc_VirtualSize, text.SizeOfRawData)

    def off(self, va):
        return self.pe.get_offset_from_rva(va - self.base)

    def va(self, off):
        return self.base + self.pe.get_rva_from_offset(off)

    def read(self, va, n):
        o = self.off(va)
        return bytes(self.data[o:o + n])

    def u32(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def dis(self, va, n=64, count=0):
        return list(self.md.disasm(self.read(va, n), va, count))

    def calls_to(self, target):
        """Return VAs of E8/E9 rel32 instructions in .text that branch to target."""
        res = []
        d = self.data
        start, end = self.text_off, self.text_off + self.text_size - 5
        for op in (0xE8, 0xE9):
            i = d.find(bytes([op]), start, end)
            while i != -1:
                rel = struct.unpack_from('<i', d, i + 1)[0]
                src = self.text_va + (i - self.text_off)
                if (src + 5 + rel) & 0xFFFFFFFF == target:
                    res.append((src, 'call' if op == 0xE8 else 'jmp'))
                i = d.find(bytes([op]), i + 1, end)
        return sorted(res)

    def dword_refs(self, value):
        """Return file-wide VAs where the little-endian dword equals value (pointers, immediates)."""
        pat = struct.pack('<I', value)
        res = []
        i = self.data.find(pat)
        while i != -1:
            try:
                res.append(self.va(i))
            except Exception:
                res.append(('off', i))
            i = self.data.find(pat, i + 1)
        return res


def fmt(insns):
    return '\n'.join(f'{i.address:08x}: {i.bytes.hex():<20} {i.mnemonic} {i.op_str}' for i in insns)


if __name__ == '__main__':
    img = Image(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'dis':
        print(fmt(img.dis(int(sys.argv[3], 16), int(sys.argv[4], 0) if len(sys.argv) > 4 else 64)))
    elif cmd == 'calls':
        for t in sys.argv[3:]:
            t = int(t, 16)
            print(f'{t:08x}:', ' '.join(f'{a:08x}{"" if k == "call" else "(jmp)"}' for a, k in img.calls_to(t)))
    elif cmd == 'refs':
        for t in sys.argv[3:]:
            t = int(t, 16)
            print(f'{t:08x}:', ' '.join(f'{a:08x}' if isinstance(a, int) else str(a) for a in img.dword_refs(t)))
