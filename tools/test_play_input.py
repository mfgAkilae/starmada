"""Regression for distinct commands collected within one Windows clock tick."""
from contextlib import redirect_stdout
import ctypes
from ctypes import wintypes as wt
import io
import struct
import unittest
from unittest.mock import patch

import play_input


class NetworkCommands(unittest.TestCase):
    def exercise(self):
        class CopyData(ctypes.Structure):
            _fields_ = [('dwData', ctypes.c_size_t), ('cbData', wt.DWORD), ('lpData', ctypes.c_void_p)]
        queued, last = [], 0

        def native_send(hwnd, message, wp, lp, flags, timeout, result):
            nonlocal last
            data = ctypes.cast(lp, ctypes.POINTER(CopyData)).contents
            seq, action, actor = struct.unpack('<III', ctypes.string_at(data.lpData, 12))
            if seq != last:
                queued.append((seq, action, actor))
                last = seq
            result._obj.value = 1  # Native proxy acknowledges retries without re-queuing.
            return 1

        device = play_input.Input.__new__(play_input.Input)
        device.hwnd = 123
        with patch.object(play_input.probe.user32, 'SendMessageTimeoutW', native_send), \
             patch.object(play_input.time, 'time_ns', return_value=123_000_000), redirect_stdout(io.StringIO()):
            device.command(1, 7, name='ffreight')
            device.command(1, 8, name='fdestroy')
        return queued

    def test_different_commands_in_same_clock_tick_both_reach_queue(self):
        queued = self.exercise()
        self.assertEqual([entry[2] for entry in queued], [7, 8])
        self.assertEqual(len({entry[0] for entry in queued}), 2)
        self.assertNotIn(0, [entry[0] for entry in queued])


if __name__ == '__main__':
    unittest.main(verbosity=2)
