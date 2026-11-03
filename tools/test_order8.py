"""Replay the order 8 handler (CraftProcess slot 21, 0x42af80) with a vanished target.

Usage: python tools/test_order8.py <unmodified GOG Armada.exe>
Dependencies (tests only): pefile, unicorn. Reuses the replay harness of
test_sync_instructions.py. Lookups and timers are fixtures; the handler's own
instructions run unchanged in the emulator, original and patched.
"""
import hashlib
from pathlib import Path
import struct
import sys
import unittest

from unicorn import UcError
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'release'))
import armada_fix
from test_sync_instructions import HEAP, STACK, STUB, Replay

HANDLER, FAULT, RETURN = 0x42af80, 0x42affa, STUB + 0x800


class Order8(Replay):
    """Stubs with a callee-cleaned argument size (thiscall functions with "ret N")."""

    def __init__(self, data):
        super().__init__(data)
        self.calls = []
        self.stub_args = {}

    def on_code(self, uc, address, size, _):
        if address in self.stubs:
            sp = uc.reg_read(UC_X86_REG_ESP)
            self.calls.append(address)
            value = self.stubs[address]()
            uc.reg_write(UC_X86_REG_EAX, value)
            uc.reg_write(UC_X86_REG_ESP, sp + 4 + self.stub_args.get(address, 0))
            uc.reg_write(UC_X86_REG_EIP, self.get(sp))


def order8(data, hit_recently):
    """Run the handler for a ship whose target id no longer resolves to an object."""
    r = Order8(data)
    proc, craft, info = HEAP, HEAP + 0x1000, HEAP + 0x3000
    r.put(proc + 0x18, craft)
    r.put(proc + 0x134, 99)                      # id of the vanished target
    r.uc.mem_write(craft + 0x550, b'\x01')       # checks before the target lookup pass
    r.uc.mem_write(craft + 0x4dc, b'\x00')
    r.put(craft + 0xe0, info)
    r.uc.mem_write(info + 0x237, b'\x01')
    r.stubs[0x472100] = lambda: 1                # thiscall, no arguments
    r.stubs[0x46cf50] = lambda: 0                # object lookup: id 99 is gone (cdecl)
    r.stubs[0x46e640] = lambda: int(hit_recently)  # thiscall, ret 4
    r.stub_args[0x46e640] = 4
    r.stubs[0x5bbb88] = lambda: 0                # __RTDynamicCast(NULL, ...) is NULL (cdecl)
    r.stubs[0x46eac0] = lambda: 0                # new order for the ship (thiscall, ret 0xc)
    r.stub_args[0x46eac0] = 0xc
    sp = STACK + 0x8000
    r.put(sp, RETURN)
    r.uc.reg_write(UC_X86_REG_ESP, sp)
    r.uc.reg_write(UC_X86_REG_ECX, proc)
    try:
        r.uc.emu_start(HANDLER, RETURN, timeout=1000000, count=10000)
    except UcError:
        return 'crash', r.uc.reg_read(UC_X86_REG_EIP), r.calls
    if r.uc.reg_read(UC_X86_REG_EIP) != RETURN:
        raise AssertionError('instruction budget exhausted before the return')
    if r.uc.reg_read(UC_X86_REG_ESP) != sp + 4:
        raise AssertionError('stack not balanced at the return')
    return 'return', None, r.calls


class Order8LostTarget(unittest.TestCase):
    def test_original_crashes_patched_returns(self):
        kind, eip, _ = order8(ORIGINAL, hit_recently=False)
        self.assertEqual((kind, eip), ('crash', FAULT))
        kind, _, calls = order8(PATCHED, hit_recently=False)
        self.assertEqual(kind, 'return')
        self.assertNotIn(0x46eac0, calls)
        print(f'target gone, not hit: original crash at {FAULT:#x}; patched returns without a new order')

    def test_other_branch_unchanged(self):
        # ship hit within the last second: the original survives and does nothing;
        # the patched handler must end the same way (same simulation for old and new exe)
        original = order8(ORIGINAL, hit_recently=True)
        patched = order8(PATCHED, hit_recently=True)
        self.assertEqual(original[0], 'return')
        self.assertNotIn(0x46eac0, original[2])
        self.assertEqual(patched[0], 'return')
        self.assertNotIn(0x46eac0, patched[2])
        print('target gone, hit recently: original and patched both return without a new order')


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
