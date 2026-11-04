"""Regression checks for Late-Game validation evidence."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from late_game_metrics import Criteria, EvidenceError, RunMetrics, main, sample
import watch_late_game


SMALL_LOAD = ('--min-simulation-seconds', '1', '--min-combat-ships', '2',
              '--min-fleet-seconds', '1', '--min-battle-clusters', '1',
              '--min-parallel-seconds', '1', '--late-start-seconds', '0')


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


class PlayerScope(unittest.TestCase):
    def test_six_player_scouts_exclude_ten_map_entities(self):
        names = ('fscout', 'bscout', 'kscout', 'kscout', 'rscout', 'fscout')
        body = ''.join(actor(i, i, i * 2000).replace(f'test{i}', f'{name}{i}')
                       for i, name in enumerate(names, 1))
        body += ''.join(actor(i, 8, i * 2000, health=50).replace(f'test{i}', f'zentity{i}')
                        for i in range(100, 110))
        stats = sample(dump(body), player_teams=list(range(1, 7)))
        self.assertEqual(stats['combat_ships'], 6)
        self.assertEqual(stats['damaged_combat_ships'], 0)
        self.assertEqual(set(stats['teams']), set('123456'))
        self.assertEqual(stats['player_teams'], list(range(1, 7)))
        self.assertEqual(stats['fleet_scope'], 'declared_players')
        self.assertEqual(stats['combat_scope'], 'cross_owner')

    def test_npc_to_player_and_player_to_npc_shots_are_excluded(self):
        body = (actor(1, 1, 0, target=99, shot=100) + actor(99, 8, 100, target=1, shot=100) +
                actor(2, 2, 5000, target=98, shot=100) + actor(98, 7, 5100, target=2, shot=100))
        stats = sample(dump(body), player_teams=[1, 2])
        self.assertEqual(stats['combat_ships'], 2)
        self.assertEqual(stats['active_firing_ships'], 0)
        self.assertEqual(stats['active_battle_clusters'], 0)

    def test_foreign_race_captures_and_legitimate_team_eight_count_by_owner(self):
        body = ''.join(actor(i, 3, i * 2000).replace(f'test{i}', f'{name}{i}')
                       for i, name in enumerate(('fdestroy', 'kdestroy', 'rdestroy', 'bdestroy'), 1))
        body += actor(5, 8, 10000).replace('test5', 'bbattle5')
        body += ''.join(actor(i, 3, 0, kind=kind) for i, kind in
                        ((6, 'constructionrig'), (7, 'freighter'), (8, 'starbase')))
        body += actor(9, 7, 0) + actor(10, 3, 0, health=0)
        stats = sample(dump(body), player_teams=[3, 8])
        self.assertEqual(stats['combat_ships'], 5)
        self.assertEqual(stats['teams']['3']['objects'], 7)
        self.assertEqual(stats['teams']['8']['combat_ships'], 1)
        self.assertNotIn('7', stats['teams'])

    def test_allied_edges_are_excluded_but_hostile_edges_count(self):
        body = (actor(1, 6, 0, target=2, shot=100) + actor(2, 3, 100) +
                actor(3, 1, 5000, target=4, shot=100) + actor(4, 4, 5100) +
                actor(5, 3, 10000, target=6, shot=100) + actor(6, 4, 10100))
        teams = [1, 3, 4, 6]
        self.assertEqual(sample(dump(body), teams)['active_battle_clusters'], 3)
        stats = sample(dump(body), teams, {'1': 1, '3': 0, '4': 1, '6': 0})
        self.assertEqual(stats['combat_ships'], 6)
        self.assertEqual(stats['active_firing_ships'], 1)
        self.assertEqual(stats['active_battle_clusters'], 1)
        self.assertEqual(stats['combat_scope'], 'hostile_declared_alliances')

    def test_station_fire_on_enemy_freighter_is_combat_without_a_fleet(self):
        stats = sample(dump(actor(1, 3, 0, kind='starbase', target=2, shot=100) +
                            actor(2, 4, 100, kind='freighter')),
                       [3, 4], {'3': 0, '4': 1})
        self.assertEqual(stats['combat_ships'], 0)
        self.assertEqual(stats['active_firing_ships'], 0)
        self.assertEqual(stats['active_battle_clusters'], 1)

    def test_invalid_player_teams_are_rejected(self):
        for teams in ([], [0], [-1], [9], [True], ['1'], [1.0], [1, 1], '12', {1, 2}, {}):
            with self.subTest(teams=teams), self.assertRaises(EvidenceError) as caught:
                sample(dump(), player_teams=teams)
            self.assertEqual(caught.exception.exit_code, 2)

    def test_alliances_require_exact_string_key_coverage_and_true_int_ids(self):
        invalid = ({}, {'1': 0}, {'1': 0, '2': 1, '8': 0}, {1: 0, 2: 1},
                   {'01': 0, '2': 1}, {'1': True, '2': 1}, {'1': -1, '2': 1},
                   {'1': 8, '2': 1}, {'1': '0', '2': 1}, {'1': 0.0, '2': 1}, [0, 1])
        for alliances in invalid:
            with self.subTest(alliances=alliances), self.assertRaises(EvidenceError):
                sample(dump(), [1, 2], alliances)
        with self.assertRaises(EvidenceError):
            sample(dump(), player_alliances={'1': 0})

    def test_legacy_scope_remains_explicit_and_unfiltered(self):
        stats = sample(dump(actor(1, 1, 0) + actor(8, 8, 100)))
        self.assertEqual(stats['combat_ships'], 2)
        self.assertIsNone(stats['player_teams'])
        self.assertIsNone(stats['player_alliances'])
        self.assertEqual(stats['fleet_scope'], 'all_non_neutral')
        self.assertEqual(stats['combat_scope'], 'cross_owner')


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

    def test_player_scope_change_cannot_mix_loaded_periods(self):
        metrics = RunMetrics()
        metrics.add(dict(point(1, 100), player_teams=[1, 2]))
        with self.assertRaises(EvidenceError):
            metrics.add(dict(point(2, 160), player_teams=[1, 3]))
        self.assertEqual(metrics.summary()['pairs'], 1)
        self.assertEqual(metrics.summary()['observed_seconds'], 0)

    def test_alliance_change_cannot_mix_periods_with_the_same_scope_label(self):
        metrics = RunMetrics()
        metrics.add(dict(point(1, 100), player_teams=[1, 2], player_alliances={'1': 0, '2': 1}))
        with self.assertRaises(EvidenceError):
            metrics.add(dict(point(2, 160), player_teams=[1, 2], player_alliances={'1': 0, '2': 0}))
        self.assertEqual(metrics.summary()['pairs'], 1)

    def test_declared_and_legacy_scope_cannot_mix(self):
        metrics = RunMetrics()
        metrics.add(point(1, 100))
        with self.assertRaises(EvidenceError):
            metrics.add(dict(point(2, 160), player_teams=[1, 2]))

    def test_equivalent_scope_order_preserves_sustained_duration(self):
        metrics = RunMetrics(Criteria(min_simulation_seconds=60, late_start_seconds=0,
                                      min_combat_ships=2, min_fleet_seconds=60,
                                      min_battle_clusters=1, min_parallel_seconds=60))
        metrics.add(dict(point(1, 0, 2, 1), player_teams=[2, 1], player_alliances={'2': 1, '1': 0}))
        metrics.add(dict(point(2, 60, 2, 1), player_teams=[1, 2], player_alliances={'1': 0, '2': 1}))
        result = metrics.summary()
        self.assertTrue(result['passed'])
        self.assertEqual(result['player_teams'], [1, 2])
        self.assertEqual(result['player_alliances'], {'1': 0, '2': 1})
        self.assertEqual(result['fleet_scope'], 'declared_players')
        self.assertEqual(result['combat_scope'], 'hostile_declared_alliances')

    def test_inconsistent_scope_labels_are_invalid(self):
        for field, value in (('fleet_scope', 'declared_players'),
                             ('combat_scope', 'hostile_declared_alliances')):
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                RunMetrics().add(dict(point(1, 100), **{field: value}))

    def test_empty_summary_reports_legacy_scope(self):
        result = RunMetrics().summary()
        self.assertIsNone(result['player_teams'])
        self.assertEqual(result['fleet_scope'], 'all_non_neutral')
        self.assertEqual(result['combat_scope'], 'cross_owner')


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

    def summary(self, *options):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([str(self.run), *options])
        return code, json.loads(output.getvalue())

    def matching_steps(self, peers):
        for tag in peers:
            (self.run / tag).mkdir(exist_ok=True)
            for step, seconds in ((1000, 100), (2000, 101)):
                body = actor(1, 1, 0, target=2, shot=seconds) + actor(2, 2, 100)
                self.write(tag, dump(body, seconds, step), step)

    def manifest(self, peers, **scope):
        (self.run / 'launch.json').write_text(json.dumps(dict(peers=peers, **scope)), encoding='utf-8')

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

    def test_six_matching_peers_pass_and_report_actual_cohort(self):
        peers = list('ABCDEF')
        self.matching_steps(peers)
        self.manifest(peers)
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 0)
        self.assertEqual(result['peers'], peers)
        self.assertEqual(result['peer_count'], 6)
        self.assertEqual(result['pairs'], 2)

    def test_manifest_scope_applies_to_six_peer_metrics(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'), player_teams=[2, 1], player_alliances={'1': 0, '2': 1})
        npc = actor(99, 8, 5000, target=1, shot=100)
        for tag in 'ABCDEF':
            for step in (1000, 2000):
                path = self.run / tag / f'step_{step:06d}.txt'
                path.write_text(path.read_text().replace(f'END step {step}', npc + f'END step {step}'))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 0)
        self.assertEqual(result['peak_combat_ships'], 2)
        self.assertEqual(result['player_teams'], [1, 2])
        self.assertEqual(result['combat_scope'], 'hostile_declared_alliances')

    def test_npc_only_divergence_in_f_is_still_a_raw_state_error(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'), player_teams=[1, 2])
        npc = actor(99, 8, 5000)
        for tag in 'ABCDEF':
            path = self.run / tag / 'step_001000.txt'
            path.write_text(path.read_text().replace('END step 1000', npc + 'END step 1000'))
        path = self.run / 'F' / 'step_001000.txt'
        path.write_text(path.read_text().replace(npc, actor(99, 8, 5000, health=50)))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 1)
        self.assertIn('peer F', result['error'])

    def test_malformed_scope_metadata_never_falls_back_to_legacy(self):
        self.matching_steps('AB')
        invalid = (dict(player_teams=None), dict(player_teams=[]), dict(player_teams=[True]),
                   dict(player_teams=[0]), dict(player_teams=[9]), dict(player_teams=['1']),
                   dict(player_teams=[1, 1]), dict(player_alliances={'1': 0}),
                   dict(player_teams=[1, 2], player_alliances=None),
                   dict(player_teams=[1, 2], player_alliances={'1': 0}),
                   dict(player_teams=[1, 2], player_alliances={'1': False, '2': 1}))
        for scope in invalid:
            with self.subTest(scope=scope):
                self.manifest(['A', 'B'], **scope)
                code, result = self.summary(*SMALL_LOAD)
                self.assertEqual(code, 2)
                self.assertIn('player_', result['error'])

    def test_legacy_manifest_scope_is_reported(self):
        self.matching_steps('AB')
        self.manifest(['A', 'B'])
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 0)
        self.assertIsNone(result['player_teams'])
        self.assertEqual(result['fleet_scope'], 'all_non_neutral')
        self.assertEqual(result['combat_scope'], 'cross_owner')

    def test_manifest_scope_change_between_captures_is_rejected(self):
        import late_game_metrics
        self.matching_steps('AB')
        self.manifest(['A', 'B'], player_teams=[1, 2])
        original = late_game_metrics.compare_step

        def compare_and_change(*args, **kwargs):
            current = original(*args, **kwargs)
            self.manifest(['A', 'B'], player_teams=[1, 3])
            return current

        with patch.object(late_game_metrics, 'compare_step', side_effect=compare_and_change):
            code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 2)
        self.assertEqual(result['pairs'], 1)
        self.assertIn('scope changed', result['error'])

    def test_only_f_diverges(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        path = self.run / 'F' / 'step_001000.txt'
        path.write_text(path.read_text().replace('synced_rng abc123', 'synced_rng ffffff'))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 1)
        self.assertIn('peer F', result['error'])
        self.assertEqual(result['peer_count'], 6)

    def test_missing_f_directory_cannot_reduce_to_a_b(self):
        self.matching_steps('ABCDE')
        self.manifest(list('ABCDEF'))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 2)
        self.assertIn('peer F', result['error'])
        self.assertEqual(result['peers'], list('ABCDEF'))

    def test_empty_f_cannot_reduce_to_a_b(self):
        self.matching_steps('ABCDE')
        (self.run / 'F').mkdir()
        self.manifest(list('ABCDEF'))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 2)
        self.assertEqual(result['pairs'], 0)
        self.assertEqual(result['peer_count'], 6)

    def test_truncated_f_is_invalid(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        path = self.run / 'F' / 'step_001000.txt'
        path.write_text(path.read_text().replace('END step 1000\n', ''))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 2)
        self.assertIn('peer F incomplete', result['error'])

    def test_incomplete_group_is_not_compared_as_a_subset(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        path = self.run / 'B' / 'step_001000.txt'
        path.write_text(path.read_text().replace('synced_rng abc123', 'synced_rng ffffff'))
        path = self.run / 'F' / 'step_001000.txt'
        path.write_text(path.read_text().replace('END step 1000\n', ''))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 2)
        self.assertEqual(result['pairs'], 0)
        self.assertIn('peer F incomplete', result['error'])

    def test_six_peer_local_visibility_differences_are_ignored(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        for path in (self.run / 'F').glob('step_*.txt'):
            path.write_text(path.read_text().replace('isVisible 1 seen 1', 'isVisible 64 seen 64'))
        self.assertEqual(self.call(*SMALL_LOAD), 0)

    def test_invalid_or_duplicate_manifest_peers_fail(self):
        self.matching_steps('AB')
        for peers in (None, [], ['A'], ['A', 'A'], ['A', 'I'], ['A', 'b'],
                      ['A', 2], 'AB', list('ABCDEFGHI')):
            with self.subTest(peers=peers):
                self.manifest(peers)
                self.assertEqual(self.call(*SMALL_LOAD), 2)

    def test_invalid_manifest_cannot_fall_back_to_a_b(self):
        self.matching_steps('AB')
        for text in ('[]', '{broken'):
            with self.subTest(text=text):
                (self.run / 'launch.json').write_text(text)
                self.assertEqual(self.call(*SMALL_LOAD), 2)

    def test_manifest_subset_override_is_rejected(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        code, result = self.summary(*SMALL_LOAD, '--peers', 'A', 'B')
        self.assertEqual(code, 2)
        self.assertIn('conflicts with launch.json', result['error'])

    def test_identical_manifest_override_is_allowed(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        self.assertEqual(self.call(*SMALL_LOAD, '--peers', *'ABCDEF'), 0)

    def test_manifest_peer_order_is_binding(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        self.assertEqual(self.call(*SMALL_LOAD, '--peers', *'FEDCBA'), 2)

    def test_windows_utf8_bom_manifest_is_supported(self):
        self.matching_steps('ABCDEF')
        (self.run / 'launch.json').write_text(json.dumps(dict(peers=list('ABCDEF'))), encoding='utf-8-sig')
        self.assertEqual(self.call(*SMALL_LOAD), 0)

    def test_explicit_peers_without_manifest_do_not_assume_a_b(self):
        self.matching_steps('CD')
        code, result = self.summary(*SMALL_LOAD, '--peers', 'C', 'D')
        self.assertEqual(code, 0)
        self.assertEqual(result['peers'], ['C', 'D'])

    def test_explicit_invalid_peers_are_rejected(self):
        self.matching_steps('AB')
        for peers in (['A'], ['A', 'A'], ['A', 'I']):
            with self.subTest(peers=peers):
                self.assertEqual(self.call(*SMALL_LOAD, '--peers', *peers), 2)

    def test_legacy_manifest_without_peers_uses_a_b(self):
        self.matching_steps('AB')
        (self.run / 'launch.json').write_text('{"run": "legacy"}')
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 0)
        self.assertEqual(result['peers'], ['A', 'B'])
        self.assertEqual(self.call(*SMALL_LOAD, '--peers', 'C', 'D'), 2)

    def test_eight_peers_are_supported(self):
        self.matching_steps('ABCDEFGH')
        self.manifest(list('ABCDEFGH'))
        code, result = self.summary(*SMALL_LOAD)
        self.assertEqual(code, 0)
        self.assertEqual(result['peer_count'], 8)

    def test_output_cannot_overwrite_f_capture(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        capture = self.run / 'F' / 'step_001000.txt'
        original = capture.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([str(self.run), '--timeline', str(capture)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(capture.read_bytes(), original)

    def test_output_cannot_overwrite_manifest(self):
        self.matching_steps('ABCDEF')
        self.manifest(list('ABCDEF'))
        manifest = self.run / 'launch.json'
        original = manifest.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([str(self.run), '--output', str(manifest)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(manifest.read_bytes(), original)


class ObserverPeers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'work' / 'det' / 'six'
        self.run.mkdir(parents=True)
        self.peers = list('ABCDEF')
        (self.run / 'launch.json').write_text(json.dumps(dict(peers=self.peers)))
        (self.run / 'observer.stop').touch()
        for tag in self.peers:
            (self.run / tag).mkdir()
            (self.run / tag / 'step_001000.txt').write_text(dump())

    def observe(self, *options):
        with patch.object(watch_late_game, 'BASE', self.root), redirect_stdout(io.StringIO()):
            code = watch_late_game.main(['six', '--minutes', '0.01', *options])
        result = json.loads((self.run / 'observer_status.json').read_text())
        return code, result

    def test_observer_reports_all_six_peers_with_insufficient_load(self):
        code, result = self.observe()
        self.assertEqual(code, 2)
        self.assertEqual(result['peers'], self.peers)
        self.assertEqual(result['peer_count'], 6)
        self.assertEqual(result['metrics']['pairs'], 1)
        record = json.loads((self.run / 'observer_timeline.jsonl').read_text())
        self.assertEqual(record['peer_count'], 6)

    def test_observer_detects_f_divergence(self):
        path = self.run / 'F' / 'step_001000.txt'
        path.write_text(path.read_text().replace('synced_rng abc123', 'synced_rng ffffff'))
        code, result = self.observe()
        self.assertEqual(code, 1)
        self.assertIn('peer F', result['error'])

    def test_observer_rejects_missing_f(self):
        (self.run / 'F' / 'step_001000.txt').unlink()
        (self.run / 'F').rmdir()
        code, result = self.observe()
        self.assertEqual(code, 2)
        self.assertEqual(result['peer_count'], 6)
        self.assertIn('peer F', result['error'])

    def test_observer_rejects_manifest_subset(self):
        code, result = self.observe('--peers', 'A', 'B')
        self.assertEqual(code, 2)
        self.assertIn('conflicts with launch.json', result['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
