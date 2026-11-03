"""Replay actual GOG instructions for the two sync fixes, without starting the game.

Usage: python tools/test_sync_instructions.py <unmodified GOG Armada.exe>
Dependencies (tests only): pefile, unicorn. No game bytes are distributed.
Lookups/visibility use explicit fixtures. This is a bounded instruction replay,
not an end-to-end match or a cross-CPU floating point test.
API: https://www.unicorn-engine.org/docs/tutorial.html
"""
import hashlib
from pathlib import Path
import struct
import sys
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_ESI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'release'))
import armada_fix

STACK, HEAP, STUB = 0x1000000, 0x2000000, 0x3000000


class Replay:
    def __init__(self, data):
        pe = pefile.PE(data=data)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(pe.OPTIONAL_HEADER.ImageBase, (pe.OPTIONAL_HEADER.SizeOfImage + 0xfff) & ~0xfff)
        self.uc.mem_write(pe.OPTIONAL_HEADER.ImageBase, pe.get_memory_mapped_image())
        for base in (STACK, HEAP, STUB):
            self.uc.mem_map(base, 0x10000)
        self.uc.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        self.stubs = {}
        self.uc.hook_add(UC_HOOK_CODE, self.on_code)

    def put(self, addr, value):
        self.uc.mem_write(addr, struct.pack('<I', value))

    def get(self, addr):
        return struct.unpack('<I', self.uc.mem_read(addr, 4))[0]

    def on_code(self, uc, address, size, _):
        if address in self.stubs:
            sp = uc.reg_read(UC_X86_REG_ESP)
            value = self.stubs[address]()
            ret = self.get(sp)
            uc.reg_write(UC_X86_REG_EAX, value)
            uc.reg_write(UC_X86_REG_ESP, sp + 4)
            uc.reg_write(UC_X86_REG_EIP, ret)

    def run(self, entry, until):
        self.uc.emu_start(entry, until, timeout=1000000, count=10000)
        if self.uc.reg_read(UC_X86_REG_EIP) != until:
            raise AssertionError('instruction budget exhausted before the checkpoint')


def docking(data, site):
    nodes = []
    for seed in (1, 2):
        r = Replay(data)
        r.put(0x67dc98, 1234)  # same session seed
        r.put(0x67dca4, seed)  # different local presentation seeds
        r.uc.reg_write(UC_X86_REG_ESI, HEAP)
        r.run(site - 5, site + 5)  # actual push(4), call and complete RNG function
        nodes.append(r.uc.reg_read(UC_X86_REG_EAX))
    return nodes


def torpedo(data, visible, dying=True):
    r = Replay(data)
    head, node, shot, shooter, target, vtable = (HEAP + x for x in (0, 0x100, 0x1000, 0x2000, 0x3000, 0x4000))
    r.put(0x67c784, head)
    r.put(head, node)
    r.put(node, head)
    r.put(node + 8, shot)
    for obj in (shot, shooter, target):
        r.put(obj, vtable)
    r.put(vtable + 0x24, STUB)
    r.put(shot + 0xf4, 11)
    r.put(shot + 0xf8, 22)
    r.put(shooter + 0xbc, 4)
    r.put(target + 0xbc, 4)
    r.uc.mem_write(target + 0x1b1, bytes([int(dying)]))
    r.stubs[0x46cf50] = lambda: {11: shooter, 22: target}.get(r.get(r.uc.reg_read(UC_X86_REG_ESP) + 4), 0)
    r.stubs[0x430430] = lambda: shooter
    r.stubs[STUB] = lambda: int(visible)
    # Stop before rendering. Only lookup/visibility queries are fixtures; the
    # renderer's actual branches and stores execute unchanged in the emulator.
    r.run(0x4edaf0, 0x4edca4 if visible else 0x4edc99)
    return r.get(shot + 0xf8)


class SyncInstructions(unittest.TestCase):
    def test_docking_original_diverges_patched_agrees(self):
        for site in (0x42a540, 0x42b76e, 0x430296):
            with self.subTest(site=hex(site)):
                original = docking(ORIGINAL, site)
                patched = docking(PATCHED, site)
                self.assertNotEqual(*original)
                self.assertEqual(*patched)
                print(f'{site:#x}: original angle indices {original}; patched {patched}')

    def test_torpedo_visibility_cannot_change_simulation_target(self):
        original = [torpedo(ORIGINAL, visible) for visible in (True, False)]
        patched = [torpedo(PATCHED, visible) for visible in (True, False)]
        self.assertEqual(original, [22, 0])
        self.assertEqual(patched, [22, 22])
        print(f'torpedo target visible/hidden: original {original}; patched {patched}')

    def test_live_target_is_preserved(self):
        for data in (ORIGINAL, PATCHED):
            self.assertEqual([torpedo(data, visible, dying=False) for visible in (True, False)], [22, 22])


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    ORIGINAL = Path(sys.argv.pop()).read_bytes()
    if hashlib.sha256(ORIGINAL).hexdigest() != '1c37ee8e4a24380c950a91ce5a7f9f96c4fcf3d8ffc0cc7e58faec3835350be6':
        raise SystemExit('requires the unmodified GOG 1.2 RDNA fix Armada.exe')
    patched = bytearray(ORIGINAL)
    for _, offset, _, new, _, _ in armada_fix.exe_sites(patched)[0]:
        patched[offset:offset + len(new)] = new
    PATCHED = bytes(patched)
    unittest.main(verbosity=2)
