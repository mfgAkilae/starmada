"""UI action-sequence regression checks; never submit OS or game input."""
import unittest
from unittest.mock import patch

from play_input import Input, KEY, BUTTON, MOVE
from ui_player import UIPlayer


class MovePath(unittest.TestCase):
    def player(self):
        player = object.__new__(UIPlayer)
        player.note = lambda **values: None
        player._game_key = lambda vk: vk
        return player

    def test_native_waypoints_hold_tab_across_right_clicks_then_release(self):
        events = []
        player = self.player()
        with patch.object(Input, 'event', lambda self, msg, value: events.append((msg, value))):
            player.move_path([(430, 250), (570, 225)])
        self.assertEqual(events[:3], [(KEY, ord('S')), (KEY, ord('S') | 0x10000), (KEY, 9)])
        self.assertEqual(events[3:-1], [(MOVE, 250 << 16 | 430), (BUTTON, 3), (BUTTON, 4),
                                       (MOVE, 225 << 16 | 570), (BUTTON, 3), (BUTTON, 4)])
        self.assertEqual(events[-1], (KEY, 9 | 0x10000))

    def test_error_still_releases_virtual_waypoint_modifier(self):
        events = []
        player = self.player()
        with patch.object(Input, 'event', lambda self, msg, value: events.append((msg, value))), \
                patch.object(player, 'click', side_effect=OSError('bridge failed')):
            with self.assertRaisesRegex(OSError, 'bridge failed'):
                player.move_path([(430, 250), (570, 225)])
        self.assertEqual(events[-1], (KEY, 9 | 0x10000))

    def test_rejects_hud_edges_and_malformed_paths_before_any_input(self):
        player = self.player()
        invalid = ([], [(50, 50)], [(50, 50)] * 9, [(0, 100), (50, 50)],
                   [(50, 350), (50, 50)], [(50, 10), (50, 50)],
                   [(50.0, 50), (50, 50)], [(True, 50), (50, 50)], [(50,), (50, 50)])
        with patch.object(Input, 'event') as event:
            for path in invalid:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    player.move_path(path)
            event.assert_not_called()


if __name__ == '__main__':
    unittest.main()
