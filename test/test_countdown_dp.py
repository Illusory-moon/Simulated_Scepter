"""倒计时最佳情形 DP 旁路分析的规则回归测试。"""

import random
import unittest

try:
    from . import countdown_backend as backend
    from .countdown_dp import ExactCountdownDP
    from .test_countdown_backend import linear_map, third_countdown_map
except ImportError:
    import countdown_backend as backend
    from countdown_dp import ExactCountdownDP
    from test_countdown_backend import linear_map, third_countdown_map


class CountdownDPTests(unittest.TestCase):
    def test_resource_available_makes_initial_observation_irrelevant_to_upper_bound(self):
        model = linear_map()
        for cheat, reroll in ((1, 0), (0, 1)):
            values = {
                ExactCountdownDP(model).solve(backend.DecisionContext(
                    backend.PHASE_EFFECT, model.initial_state(cheat, reroll, 0),
                    effect)).max_countdown
                for effect in backend.ALL_EFFECTS
            }
            self.assertEqual({2}, values)
        no_resource_values = {
            ExactCountdownDP(model).solve(backend.DecisionContext(
                backend.PHASE_EFFECT, model.initial_state(0, 0, 0),
                effect)).max_countdown
            for effect in backend.ALL_EFFECTS
        }
        self.assertGreater(len(no_resource_values), 1)

    def test_current_cheat_or_favorable_reroll_can_fix_a_bad_observed_effect(self):
        model = linear_map()
        no_resource = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 0, 0),
            backend.EFFECT_NOTHING)
        with_cheat = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(1, 0, 0),
            backend.EFFECT_NOTHING)
        with_reroll = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 1, 0),
            backend.EFFECT_NOTHING)
        self.assertEqual(-2, ExactCountdownDP(model).solve(no_resource).max_countdown)
        self.assertEqual(2, ExactCountdownDP(model).solve(with_cheat).max_countdown)
        self.assertEqual(2, ExactCountdownDP(model).solve(with_reroll).max_countdown)

    def test_trace_contains_each_steps_complete_before_and_after_state(self):
        model = linear_map()
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(1, 0, 5),
            backend.EFFECT_NOTHING)
        result = ExactCountdownDP(model).solve(context)
        first, second = result.steps
        self.assertEqual((5, 6, 1, 0), (
            first.countdown_before, first.countdown_after,
            first.cheat_before, first.cheat_after))
        self.assertEqual((0, 0), (first.infected_before, first.infected_after))
        self.assertEqual((1,), first.infected_added)
        self.assertEqual((0, 1), (
            first.effect_countdown_delta, first.move_countdown_delta))
        self.assertEqual((6, 7), (
            second.countdown_before, second.countdown_after))

    def test_select_upper_bound_reports_path_and_infection_points(self):
        model = linear_map()
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 0, 0),
            backend.EFFECT_SELECT)
        result = ExactCountdownDP(model).solve(context)
        self.assertEqual(2, result.max_countdown)
        self.assertEqual((0, 1, 2), result.path)
        self.assertEqual((1, 2), result.infection_nodes)

    def test_known_five_step_route_reaches_theoretical_cd_five(self):
        model = third_countdown_map()
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(2, 3, 0),
            backend.EFFECT_BONUS)
        result = ExactCountdownDP(model).solve(context)
        self.assertEqual(5, result.max_countdown)
        self.assertEqual(6, len(result.path))
        self.assertEqual((7, 0), (result.path[0], result.path[-1]))
        self.assertEqual(5, len(result.steps))

    def test_path_phase_does_not_repeat_an_already_settled_bonus(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, (1,))
        state = model.initial_state(0, 0, 7)
        settled = model.settle_effect(
            state, backend.EFFECT_BONUS, random.Random(1))
        context = backend.DecisionContext(
            backend.PHASE_PATH, settled, locked_effect=backend.EFFECT_BONUS)
        result = ExactCountdownDP(model).solve(context)
        self.assertEqual(8, settled.countdown)
        self.assertEqual(9, result.max_countdown)
        self.assertEqual((0, 1), result.path)

    def test_target_phase_chooses_the_best_remaining_target(self):
        model = linear_map()
        context = backend.DecisionContext(
            backend.PHASE_TARGET, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_SELECT)
        result = ExactCountdownDP(model).solve(context)
        self.assertEqual(2, result.max_countdown)
        self.assertEqual(1, result.infection_nodes[0])

    def test_adjacent_effect_reports_points_destroyed_on_the_same_column(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 100, "cy": 80},
        ]
        model = backend.CountdownMap(
            nodes, {0: [1], 1: [2], 2: []}, 0, ())
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(0, 0, 0),
            backend.EFFECT_ADJACENT)
        result = ExactCountdownDP(model).solve(context)
        self.assertIn(2, result.infection_nodes)

    def test_spread_projection_keeps_every_maximal_legal_outcome(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
            {"idx": 2, "cx": 200, "cy": 0},
            {"idx": 3, "cx": 200, "cy": 80},
            {"idx": 4, "cx": 300, "cy": 0},
            {"idx": 5, "cx": 300, "cy": 80},
            {"idx": 6, "cx": 300, "cy": 160},
        ]
        model = backend.CountdownMap(
            nodes,
            {0: [1], 1: [], 2: [4, 5], 3: [5, 6], 4: [], 5: [], 6: []},
            0, (2, 3))
        state = model.initial_state(0, 0, 0)
        outcomes = dict(ExactCountdownDP(model)._spread_path_outcomes(state))[1]
        added = {witness & ~state.infected for witness in outcomes.values()}
        self.assertEqual({(1 << 4) | (1 << 5),
                          (1 << 4) | (1 << 6),
                          (1 << 5) | (1 << 6)}, added)

    def test_dp_rejects_a_cyclic_map_before_expansion(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: [0]}, 0, ())
        with self.assertRaisesRegex(ValueError, "DAG"):
            ExactCountdownDP(model)

    def test_terminal_context_preserves_current_cd(self):
        model = linear_map()
        state = backend.CountdownState(2, 0, 9, 1, 2)
        result = ExactCountdownDP(model).solve(
            backend.DecisionContext(backend.PHASE_TERMINAL, state))
        self.assertEqual(9, result.max_countdown)
        self.assertEqual((2,), result.path)
        self.assertEqual((), result.infection_nodes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
