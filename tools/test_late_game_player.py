"""Regression checks for the real-player controller's economy bootstrap."""
import unittest

from late_game_player import Player


def cost(dili, seconds):
    return dict(dilithium=dili, officers=2, crew=100, seconds=seconds)


def world_actor(identity, name, kind, x, z, team=1):
    return dict(id=identity, name=name, kind=kind, team=team, pos=[x, 38.5, z], health=100)


class Device:
    def __init__(self):
        self.commands = []

    def command(self, action, actor, **args):
        self.commands.append(dict(action=action, actor=actor, **args))


class EconomyBootstrap(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.player = Player('A', self.device, lambda _: None)
        self.world = [world_actor(1, 'fbase1', 'starbase', 1000, 1000),
                      world_actor(2, 'fconst2', 'constructionrig', 900, 1000),
                      world_actor(3, 'fconst3', 'constructionrig', 900, 1100),
                      world_actor(4, 'fscout4', 'wingman', 1000, 900),
                      world_actor(5, 'mmooninf5', 'scrap', 1500, 1000, team=0),
                      world_actor(6, 'kbase6', 'starbase', 5000, 5000, team=2)]
        self.state = dict(team=1, economy=dict(dilithium=10000, officers=999, crew=99999), actors={
            1: dict(id=1, name='fbase', builds={'fconst': cost(500, 50), 'ffreight': cost(400, 40)}),
            2: dict(id=2, name='fconst', builds={'fyard': cost(1200, 60), 'fmining': cost(1000, 50)}, active_class=0, queued=0),
            3: dict(id=3, name='fconst', builds={'fyard': cost(1200, 60), 'fmining': cost(1000, 50)}, active_class=0, queued=0),
            4: dict(id=4, name='fscout', builds={})})

    def run_player(self, seconds):
        self.player.control(seconds, self.state, self.world, {1, 3}, False)

    def test_opening_builds_mine_and_yard_with_distinct_constructors(self):
        self.run_player(0)
        commands = self.device.commands
        self.assertEqual([(c['action'], c['name']) for c in commands], [(3, 'fmining'), (3, 'fyard')])
        self.assertEqual(len({c['actor'] for c in commands}), 2)
        self.assertEqual(self.state['economy']['dilithium'], 10000)

    def test_travelling_constructor_keeps_its_order_and_funds(self):
        self.run_player(0)
        for seconds in (30, 60, 180, 300):
            self.run_player(seconds)
        self.assertEqual(len(self.device.commands), 2)
        self.assertEqual(sum(p['cost']['dilithium'] for p in self.player.pending), 2200)

    def test_scarce_resources_preserve_mining_bootstrap(self):
        self.state['economy']['dilithium'] = 1500
        self.run_player(0)
        self.assertEqual([c['name'] for c in self.device.commands], ['fmining'])

    def test_production_waits_for_observed_completed_mine(self):
        self.world.append(world_actor(7, 'fyard7', 'shipyard', 2000, 1800))
        self.state['actors'][7] = dict(id=7, name='fyard', builds={'fdestroy': cost(200, 24)})
        self.run_player(0)
        self.assertFalse(any(c['action'] == 1 for c in self.device.commands))
        self.world.append(world_actor(8, 'fmining8', 'mining', 2200, 2200))
        self.run_player(60)
        self.assertTrue(any(c['action'] == 1 and c['name'] == 'fdestroy' for c in self.device.commands))

    def test_resource_stress_still_pays_for_normal_yard_and_ship_commands(self):
        self.player.resource_stress = True
        self.state['economy']['dilithium'] = 1000000
        self.world.append(world_actor(7, 'fyard7', 'shipyard', 2000, 1800))
        self.state['actors'][7] = dict(id=7, name='fyard', builds={'fdestroy': cost(200, 24)})
        self.run_player(0)
        self.assertTrue(any(c['action'] == 3 and c['name'] == 'fyard' for c in self.device.commands))
        self.assertTrue(any(c['action'] == 1 and c['name'] == 'fdestroy' for c in self.device.commands))
        self.assertFalse(any(c['name'] == 'fmining' for c in self.device.commands))
        self.assertEqual(self.state['economy']['dilithium'], 1000000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
