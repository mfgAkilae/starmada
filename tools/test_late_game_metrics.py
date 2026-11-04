"""Regression checks for Late-Game validation evidence."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from late_game_metrics import Criteria, EvidenceError, RunMetrics, main, sample


def actor(identity, team, x, kind='wingman', target=0, shot=-10000, health=100):
    return (f'GAMEOBJECT {identity} {kind} test{identity}\n'
            f'  pos ({x}, 0, 0)\n  team {team} perceived team {team}\n'
            f'  isVisible 1 seen 1 who_shot_me 0 who_i_shot {target} when_i_shot {shot}\n'
            f'  healthration 1 curhealth {health} maxhealth 100\n\n')


def dump(body='', seconds=100, step=1000):
    return (f'step {step} synced_rng abc123 table_index 5\n'
            f'simulation_seconds {seconds} tick {step}\n{body}END step {step}\n')


def point(step, seconds, ships=200, clusters=3):
    return dict(step=step, simulation_seconds=seconds, combat_ships=ships,
                active_battle_clusters=clusters)


class SampleMetrics(unittest.TestCase):
    def test_only_live_non_neutral_wingmen_are_fleet(self):
        stats = sample(dump(actor(1, 1, 0) + actor(2, 0, 0) +
                            actor(3, 1, 0, kind='constructionrig') +
                            actor(4, 1, 0, kind='starbase') + actor(5, 1, 0, health=0)))
        self.assertEqual(stats['combat_ships'], 1)
        self.assertEqual(stats['teams']['1']['objects'], 3)

    def test_ancient_future_friendly_missing_and_dead_targets_do_not_fire(self):
        body = (actor(1, 1, 0, target=2, shot=94.99) + actor(2, 2, 100) +
                actor(3, 1, 0, target=2, shot=100.01) +
                actor(4, 1, 0, target=1, shot=100) +
                actor(5, 1, 0, target=999, shot=100) +
                actor(6, 1, 0, target=7, shot=100) + actor(7, 2, 100, health=0))
        stats = sample(dump(body))
        self.assertEqual(stats['active_firing_ships'], 0)
        self.assertEqual(stats['active_battle_clusters'], 0)

    def test_three_separate_fights_and_weapon_count(self):
        body = ''.join(actor(i * 2 + 1, 1, i * 2500, target=i * 2 + 2, shot=98) +
                       actor(i * 2 + 2, 2, i * 2500 + 100) for i in range(3))
        stats = sample(dump(body + 'Weapon cannon test.odf shot.odf\nWeapon detectcloak test NOORDNANCECLASS\n'))
        self.assertEqual(stats['active_firing_ships'], 3)
        self.assertEqual(stats['active_battle_clusters'], 3)
        self.assertEqual(stats['weapon_instances'], 2)

    def test_transitive_proximity_merges_fights(self):
        body = ''.join(actor(i * 2 + 1, 1, i * 1000, target=i * 2 + 2, shot=100) +
                       actor(i * 2 + 2, 2, i * 1000 + 100) for i in range(3))
        self.assertEqual(sample(dump(body))['active_battle_clusters'], 1)

    def test_long_range_shot_is_one_fight(self):
        self.assertEqual(sample(dump(actor(1, 1, 0, target=2, shot=100) +
                                     actor(2, 2, 2000)))['active_battle_clusters'], 1)

    def test_explicit_clock_required(self):
        with self.assertRaises(EvidenceError):
            sample(dump().replace('simulation_seconds 100 tick 1000\n', ''))

    def test_sample_rejects_truncated_dump(self):
        with self.assertRaises(EvidenceError):
            sample(dump().replace('END step 1000\n', ''))

    def test_station_fire_is_a_battle_but_not_a_firing_ship(self):
        stats = sample(dump(actor(1, 1, 0, kind='starbase', target=2, shot=100) +
                            actor(2, 2, 100)))
        self.assertEqual(stats['active_firing_ships'], 0)
        self.assertEqual(stats['active_battle_clusters'], 1)


class SustainedLoad(unittest.TestCase):
    def test_peak_alone_fails(self):
        metrics = RunMetrics(Criteria(min_simulation_seconds=120, min_fleet_seconds=60,
                                      min_parallel_seconds=60))
        for i, ships in enumerate((1, 200, 1)):
            metrics.add(point(i + 1, i * 60, ships))
        self.assertEqual(metrics.summary()['peak_combat_ships'], 200)
        self.assertEqual(metrics.summary()['longest_fleet_seconds'], 0)
        self.assertFalse(metrics.summary()['passed'])

    def test_gap_does_not_fill_sustained_duration(self):
        metrics = RunMetrics(Criteria(late_start_seconds=0))
        for i, seconds in enumerate((0, 60, 180, 240)):
            metrics.add(point(i + 1, seconds))
        stats = metrics.summary()
        self.assertEqual(stats['observed_seconds'], 120)
        self.assertEqual(stats['longest_fleet_seconds'], 60)
        self.assertEqual(stats['parallel_combat_seconds'], 120)
        self.assertEqual(stats['gaps_over_maximum'], 1)
        self.assertFalse(stats['passed'])

    def test_fleet_must_be_consecutive_but_combat_can_accumulate(self):
        criteria = Criteria(min_simulation_seconds=240, late_start_seconds=0,
                            min_fleet_seconds=120, min_parallel_seconds=120)
        metrics = RunMetrics(criteria)
        for i, (ships, fights) in enumerate(((200, 3), (200, 3), (1, 0), (200, 3), (200, 3))):
            metrics.add(point(i + 1, i * 60, ships, fights))
        self.assertEqual(metrics.summary()['parallel_combat_seconds'], 120)
        self.assertEqual(metrics.summary()['longest_fleet_seconds'], 60)
        self.assertFalse(metrics.summary()['passed'])

    def test_actual_sustained_load_passes(self):
        metrics = RunMetrics()
        for i in range(91):
            metrics.add(point(i + 1, i * 60))
        self.assertTrue(metrics.summary()['passed'])

    def test_early_combat_followed_by_long_idle_does_not_pass_late_game(self):
        metrics = RunMetrics()
        for i in range(91):
            metrics.add(point(i + 1, i * 60, 250 if i < 45 else 2, 4 if i < 45 else 0))
        self.assertFalse(metrics.summary()['passed'])

    def test_parallel_battles_need_large_fleet_at_the_same_late_time(self):
        metrics = RunMetrics()
        for i in range(91):
            metrics.add(point(i + 1, i * 60, 250 if i < 75 else 20, 0 if i < 75 else 4))
        self.assertFalse(metrics.summary()['passed'])

    def test_clock_regression_is_invalid(self):
        metrics = RunMetrics()
        metrics.add(point(1, 100))
        with self.assertRaises(EvidenceError):
            metrics.add(point(2, 99))


class PeerValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        for tag in ('A', 'B'):
            (self.run / tag).mkdir()

    def write(self, tag, text, step=1000):
        (self.run / tag / f'step_{step:06d}.txt').write_text(text, encoding='latin1')

    def call(self, *options):
        with redirect_stdout(io.StringIO()):
            return main([str(self.run), *options])

    def test_peer_divergence_fails_even_before_load_acceptance(self):
        self.write('A', dump(actor(1, 1, 0)))
        self.write('B', dump(actor(1, 1, 0, health=99)))
        self.assertEqual(self.call(), 1)

    def test_complete_matching_idle_run_is_insufficient(self):
        for tag in ('A', 'B'):
            self.write(tag, dump())
        self.assertEqual(self.call(), 2)

    def test_missing_end_is_invalid(self):
        for tag in ('A', 'B'):
            self.write(tag, dump().replace('END step 1000\n', ''))
        self.assertEqual(self.call(), 2)

    def test_only_local_fields_ignored(self):
        body = actor(1, 1, 0)
        self.write('A', dump(body))
        self.write('B', dump(body.replace('isVisible 1 seen 1', 'isVisible 4 seen 4')))
        self.assertEqual(self.call(), 2)
        self.write('B', dump(body).replace('synced_rng abc123', 'synced_rng 123abc'))
        self.assertEqual(self.call(), 1)

    def test_step_header_must_match_filename(self):
        for tag in ('A', 'B'):
            self.write(tag, dump(step=1001))
        self.assertEqual(self.call(), 2)

    def test_cli_passes_only_verified_measured_load(self):
        for tag in ('A', 'B'):
            for step, seconds in ((1000, 100), (2000, 101)):
                body = actor(1, 1, 0, target=2, shot=seconds) + actor(2, 2, 100)
                self.write(tag, dump(body, seconds, step), step)
        self.assertEqual(self.call('--min-simulation-seconds', '1', '--min-combat-ships', '2',
                                   '--min-fleet-seconds', '1', '--min-battle-clusters', '1',
                                   '--min-parallel-seconds', '1', '--late-start-seconds', '0'), 0)

    def test_output_cannot_overwrite_capture(self):
        text = dump()
        self.write('A', text)
        capture = self.run / 'A' / 'step_001000.txt'
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([str(self.run), '--timeline', str(capture)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(capture.read_text(), text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
