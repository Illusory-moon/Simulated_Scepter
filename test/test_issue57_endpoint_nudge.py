"""Regression tests for the recorded endpoint interaction fix (issue #57)."""

import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory


ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

simul_utils = importlib.import_module("tool.simul.utils")
IronBloodUniverse = importlib.import_module("iron_blood").IronBloodUniverse


class FPromptDetectionTest(unittest.TestCase):
    def test_full_screen_match_updates_reverse_coordinates(self):
        universe = simul_utils.UniverseUtils.__new__(simul_utils.UniverseUtils)
        universe.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        universe.xx = 1920
        universe.yy = 1080
        universe.scx = 1.0
        universe.threshold = 0.96
        universe.last_info = None

        template = cv.imread(str(ROOT / "resource" / "imgs" / "f.jpg"))
        x, y = 1086, 601
        universe.screen[y:y + template.shape[0], x:x + template.shape[1]] = template

        with patch.object(simul_utils.config, "mapping", ["f"]):
            self.assertTrue(
                universe.check(
                    "f",
                    0.4443,
                    0.4417,
                    mask="mask_f1",
                    threshold=0.96,
                    search_all=True,
                )
            )

        expected_x = (1920 - (x + template.shape[1] / 2)) / 1920
        expected_y = (1080 - (y + template.shape[0] / 2)) / 1080
        self.assertAlmostEqual(expected_x, universe.tx, places=6)
        self.assertAlmostEqual(expected_y, universe.ty, places=6)


class EndpointControllerTest(unittest.TestCase):
    @staticmethod
    def make_universe(results):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.ang = 40.0
        universe._endpoint_heading = 40.0
        universe._endpoint_heading_target = None
        universe.is_run = Mock(return_value=True)
        universe.check = Mock(side_effect=lambda *a, **k: results.pop(0) if results else False)
        universe._match_device_label = Mock(return_value=None)
        universe.get_screen = Mock()
        universe.get_loc = Mock(return_value=True)
        universe.now_loc = (0.0, 0.0)
        universe.target_loc = (1.0, 1.0)
        universe.target_type = 3
        universe._stop = False
        universe.xx = 1920
        universe.yy = 1080
        universe.update_direction_data = Mock()
        return universe

    @staticmethod
    def manager():
        manager = Mock()
        manager.sleep = Mock()
        manager.wait = Mock()
        return manager

    def test_nudge_checks_before_and_after_each_bounded_step(self):
        universe = self.make_universe([False, False, True])
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertTrue(universe._nudge_forward_for_f(steps=3, step_seconds=0.2))

        self.assertEqual(2, manager.press.call_count)
        self.assertEqual(
            [("w", 0.2), ("w", 0.2)],
            [call.args for call in manager.press.call_args_list],
        )
        self.assertGreaterEqual(manager.keyUp.call_count, 2)
        self.assertTrue(all(call.kwargs.get("force") for call in manager.keyUp.call_args_list))

    def test_nudge_is_finite_when_prompt_never_appears(self):
        universe = self.make_universe([False] * 8)
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertFalse(universe._nudge_forward_for_f(steps=3))

        self.assertEqual(3, manager.press.call_count)
        self.assertGreaterEqual(manager.keyUp.call_count, 2)

    def test_type3_found_while_panning(self):
        # entry check (miss), pan step 1 (miss), pan step 2 (hit)
        universe = self.make_universe([False, False, True])
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertTrue(
                universe._approach_type3_endpoint(
                    max_rings=2, pan_steps=4, leg_seconds=0.3
                )
            )

        # issue #57: the endpoint search must not reuse the noise-driven
        # mode-1 steering at all.
        universe.update_direction_data.assert_not_called()
        manager.press.assert_not_called()
        self.assertGreaterEqual(manager.keyUp.call_count, 1)
        self.assertTrue(all(
            call.kwargs.get("force") for call in manager.keyUp.call_args_list
        ))

    def test_type3_search_is_finite_when_prompt_never_appears(self):
        # entry + ring0 pan(4) + ring0 leg(1) + ring1 pan(4) = 10 checks
        universe = self.make_universe([False] * 10)
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertFalse(
                universe._approach_type3_endpoint(
                    max_rings=2, pan_steps=4, leg_seconds=0.3
                )
            )

        universe.update_direction_data.assert_not_called()
        manager.press.assert_not_called()
        self.assertEqual(1, manager.keyDown.call_count)
        self.assertGreaterEqual(manager.keyUp.call_count, 2)

    def test_type3_found_immediately_does_not_move_or_pan(self):
        universe = self.make_universe([True])
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertTrue(universe._approach_type3_endpoint())

        universe.update_direction_data.assert_not_called()
        manager.keyDown.assert_not_called()
        manager.mouse_move.assert_not_called()
        manager.press.assert_not_called()
        manager.keyUp.assert_called()

    def test_type3_does_not_reuse_heading_from_another_target(self):
        # A heading captured for a different endpoint must not steer this one.
        universe = self.make_universe([False, False, True])
        universe.ang = 73.0
        universe._endpoint_heading = 211.0
        universe._endpoint_heading_target = (1.0, 1.0)
        universe._endpoint_heading_time = 0.0
        universe.target_loc = (2.0, 2.0)
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertTrue(
                universe._approach_type3_endpoint(
                    max_rings=2, pan_steps=4, leg_seconds=0.3
                )
            )

        first_move = manager.mouse_move.call_args_list[0].args[0]
        self.assertAlmostEqual(90.0, first_move, places=6)
        universe.update_direction_data.assert_not_called()

    def test_type3_visual_homing_walks_to_seen_device(self):
        # entry check (miss), pan step 1 check (miss), then the label match
        # appears, homing walks once and the second F check inside the walk
        # hits.
        universe = self.make_universe([False, False, False, True])
        universe._match_device_label = Mock(return_value=(1100.0, 500.0, 0.8))
        manager = self.manager()
        with patch("tool.simul.utils.key_mouse_manager", manager):
            self.assertTrue(
                universe._approach_type3_endpoint(
                    max_rings=2, pan_steps=4, leg_seconds=0.3
                )
            )

        universe.update_direction_data.assert_not_called()
        manager.keyDown.assert_any_call("w", force=True)
        self.assertTrue(all(
            call.kwargs.get("force") for call in manager.keyUp.call_args_list
        ))


class NavigationContractTest(unittest.TestCase):
    @staticmethod
    def make_universe(target_type):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.target = {((93.0, 93.0), target_type)}
        universe.target_loc = (93.0, 93.0)
        universe.now_loc = (93.0, 93.0)
        universe.target_type = target_type
        universe._stop = False
        universe.is_sprinting = 0
        universe.quan = False
        universe.bai_e = False
        universe.skill_num = 9
        universe.red_threshold = 4500
        universe.trust_annotated_attack_targets = True
        universe.get_screen = Mock()
        universe.get_recent_target = Mock(return_value=((93.0, 93.0), target_type))
        universe.update_direction_data = Mock(return_value=5.0)
        universe.get_loc = Mock(return_value=True)
        universe.is_run = Mock(return_value=True)
        universe.set_path_state = Mock()
        universe.ts = Mock()
        universe.ts.similar.return_value = False
        universe.good_f = Mock(return_value=(True, 0.1))
        universe.nof = Mock(return_value=True)
        return universe

    def test_type3_calls_bounded_controller_and_then_interacts(self):
        universe = self.make_universe(3)
        universe._approach_type3_endpoint = Mock(return_value=True)
        universe.check = Mock(return_value=False)
        manager = Mock()
        with (
            patch("tool.simul.utils.key_mouse_manager", manager),
            patch("tool.simul.utils.sprint"),
            patch("tool.simul.utils.match_skill_numbers_in_region", return_value=None),
        ):
            universe.get_path_with_big_map()

        universe._approach_type3_endpoint.assert_called_once_with()
        universe.nof.assert_called_once_with(must_be="tp")
        manager.press.assert_any_call("f", force=True)
        mode_calls = [
            call for call in universe.update_direction_data.call_args_list
            if call.kwargs.get("mode") == 1
        ]
        self.assertEqual([], mode_calls)

    def test_type2_uses_nudge_result_without_pressing_f_in_navigation(self):
        universe = self.make_universe(2)
        universe.check = Mock(return_value=False)
        universe._nudge_forward_for_f = Mock(return_value=True)
        manager = Mock()
        with (
            patch("tool.simul.utils.key_mouse_manager", manager),
            patch("tool.simul.utils.sprint"),
            patch("tool.simul.utils.match_skill_numbers_in_region", return_value=None),
        ):
            universe.get_path_with_big_map()

        universe._nudge_forward_for_f.assert_called_once_with()
        self.assertEqual(set(), universe.target)
        self.assertFalse(any(
            call.args and call.args[0] == "f"
            for call in manager.press.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
