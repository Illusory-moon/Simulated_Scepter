import importlib
import itertools
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory
from tool.utils.tool import find_latest_modified_file

ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

iron_blood_module = importlib.import_module("iron_blood")
IronBloodUniverse = iron_blood_module.IronBloodUniverse
RECORD_STUCK_WINDOW = iron_blood_module.RECORD_STUCK_WINDOW
SimulatedUniverse = importlib.import_module("simul").SimulatedUniverse


class SpecialMapTargetParsingTest(unittest.TestCase):
    def test_special_target_parser_ignores_green_start(self):
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        cv.circle(image, (10, 10), 1, (0, 255, 0), -1)
        cv.circle(image, (35, 35), 1, (29, 230, 181), -1)
        cv.circle(image, (65, 65), 1, (0, 242, 255), -1)
        cv.circle(image, (10, 65), 1, (36, 28, 237), -1)

        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.speed = False
        with patch.object(cv, "imread", return_value=image.copy()):
            targets = universe.get_target("unused.png", 0, 0, target_mode="special")

        self.assertEqual([1, 2, 3], sorted(target_type for _, target_type in targets))


class RecordedSpecialMapNavigationTest(unittest.TestCase):
    @staticmethod
    def make_universe(targets):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.target = set(targets)
        universe.find = True
        universe.now_map = "event_map"
        universe._stop = False
        universe.target_type = 2
        universe.target_loc = next(
            (target[0] for target in targets if target[1] == 2), None
        )
        universe.last_interact_time = 0
        universe.special_interaction_failures = {}
        universe.native_special_map_root = None
        universe.loaded_map_root = None
        universe.trust_annotated_attack_targets = False
        universe.get_path_with_big_map = Mock()
        universe.do_interaction = Mock(return_value=1)
        # 逼近交互点的反馈环所需的最小表面；now_loc 与目标重合使
        # 逼近逻辑在距离检查处直接返回，不触发任何键鼠操作。
        universe.get_screen = Mock()
        universe.get_loc = Mock(return_value=True)
        universe.check = Mock(return_value=False)
        universe.now_loc = universe.target_loc
        return universe

    def test_recorded_map_tracks_and_interacts(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction, ((40, 50), 3)})
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        universe.get_path_with_big_map.assert_called_once_with()
        universe.do_interaction.assert_called_once_with()
        fallback.assert_not_called()
        self.assertNotIn(interaction, universe.target)
        self.assertGreater(universe.last_interact_time, 0)

    def test_consumed_interaction_continues_remaining_big_map_route(self):
        universe = self.make_universe({((40, 50), 3)})
        universe.get_path_with_big_map.side_effect = lambda: setattr(
            universe, "target_type", 3
        )
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        fallback.assert_not_called()
        universe.get_path_with_big_map.assert_called_once_with()
        universe.do_interaction.assert_not_called()

    def test_path_waypoint_does_not_trigger_interaction(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction})
        universe.target_type = 0
        fallback = Mock()

        universe.navigate_recorded_special_map(fallback)

        universe.do_interaction.assert_not_called()
        self.assertIn(interaction, universe.target)

    def test_special_map_trusts_annotated_red_attack_target(self):
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        red_target = ((280, 623), 1)
        universe.target = {red_target}
        universe.now_loc = (273, 640)
        universe.last = (300, 640)
        universe.trust_annotated_attack_targets = True

        self.assertEqual(red_target, universe.get_recent_target())
        self.assertIn(red_target, universe.target)

    def test_special_red_navigation_temporarily_enables_trusted_mode(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction, ((8, 10), 1)})
        universe.target_type = 1
        observed = []
        universe.get_path_with_big_map.side_effect = lambda: observed.append(
            universe.trust_annotated_attack_targets
        )

        universe.navigate_recorded_special_map(Mock())

        self.assertEqual([True], observed)
        self.assertFalse(universe.trust_annotated_attack_targets)
        universe.do_interaction.assert_not_called()

    def test_special_red_target_clicks_once_without_using_skill(self):
        red_target = ((12, 34), 1)
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.target = {red_target}
        universe.target_loc = red_target[0]
        universe.target_type = 1
        universe.now_loc = red_target[0]
        universe.last = red_target[0]
        universe._stop = False
        universe.skill_num = 1
        universe.quan = 1
        universe.bai_e = 1
        universe.trust_annotated_attack_targets = True
        universe.last_interact_time = 0
        universe.get_loc = Mock(return_value=True)
        universe.get_screen = Mock(return_value=np.zeros((1080, 1920, 3), dtype=np.uint8))
        universe.get_recent_target = Mock(return_value=red_target)
        universe.update_direction_data = Mock(return_value=1)
        universe.check = Mock(return_value=True)
        universe.use_e = Mock()
        manager = Mock()

        with (
            patch("tool.simul.utils.key_mouse_manager", manager),
            patch("tool.simul.utils.sprint"),
            patch("tool.simul.utils.match_skill_numbers_in_region", return_value=None),
        ):
            universe.get_path_with_big_map()

        manager.click.assert_called_once_with(0.5, 0.5)
        universe.use_e.assert_not_called()
        universe.check.assert_not_called()
        self.assertNotIn(red_target, universe.target)

    def test_failed_interaction_is_removed_after_retry_limit(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction})
        universe.do_interaction.return_value = None
        fallback = Mock()

        with patch("iron_blood.key_mouse_manager", Mock()):
            for _ in range(3):
                universe.navigate_recorded_special_map(fallback)

        self.assertNotIn(interaction, universe.target)
        fallback.assert_called_once_with()

    def test_shop_return_resumes_remaining_big_map_route(self):
        interaction = ((12, 34), 2)
        endpoint = ((40, 50), 3)
        universe = self.make_universe({interaction, endpoint})
        universe.do_interaction.return_value = None
        fallback = Mock()

        with patch("iron_blood.key_mouse_manager", Mock()):
            for _ in range(3):
                universe.navigate_recorded_special_map(fallback)

        self.assertNotIn(interaction, universe.target)
        self.assertIn(endpoint, universe.target)
        fallback.assert_called_once_with()

        # The native fallback opens and finishes the shop state machine.  On
        # returning to map navigation, only the remaining mapped route exists.
        universe.target_loc = endpoint[0]
        universe.get_path_with_big_map.side_effect = lambda: setattr(
            universe, "target_type", 3
        )
        with patch("iron_blood.key_mouse_manager", Mock()):
            universe.navigate_recorded_special_map(fallback)

        self.assertEqual(4, universe.get_path_with_big_map.call_count)
        fallback.assert_called_once_with()

    def test_recording_switch_off_still_uses_loaded_map(self):
        universe = self.make_universe({((12, 34), 2)})
        universe.record_event_map_enabled = False
        universe.area = "事件"
        universe.record_map_contexts = {"event": ("maps", {})}
        universe.big_map_init = True
        universe.loaded_map_root = "maps"
        universe.need_record = False
        universe.navigate_recorded_special_map = Mock()
        fallback = Mock()

        self.assertFalse(universe.record_special_map_or_navigate(fallback))

        universe.navigate_recorded_special_map.assert_called_once_with(fallback)
        fallback.assert_not_called()

    def test_second_interaction_remains_after_first_completes(self):
        first = ((12, 34), 2)
        second = ((60, 80), 2)
        universe = self.make_universe({first, second})

        universe.navigate_recorded_special_map(Mock())

        self.assertNotIn(first, universe.target)
        self.assertIn(second, universe.target)

    def test_empty_targets_search_exit_portal(self):
        universe = self.make_universe({((40, 50), 3)})
        universe.target = set()
        universe.do_interaction = Mock(return_value=1)
        universe.check = Mock(side_effect=[False, False, True])
        fallback = Mock()
        manager = Mock()

        with patch("iron_blood.key_mouse_manager", manager):
            universe.navigate_recorded_special_map(fallback)

        fallback.assert_not_called()
        self.assertTrue(manager.mouse_move.called)
        universe.do_interaction.assert_called_once()

    def test_empty_targets_without_portal_do_nothing(self):
        universe = self.make_universe({((40, 50), 3)})
        universe.target = set()
        universe.do_interaction = Mock(return_value=1)
        universe.check = Mock(return_value=False)
        fallback = Mock()

        with patch("iron_blood.key_mouse_manager", Mock()):
            universe.navigate_recorded_special_map(fallback)

        fallback.assert_not_called()
        universe.do_interaction.assert_not_called()

    def test_unknown_map_restores_and_stays_on_native_navigation(self):
        universe = self.make_universe(set())
        universe.record_event_map_enabled = False
        universe.area = "事件"
        universe.record_map_contexts = {"event": ("maps", {})}
        universe.big_map_init = False
        universe.big_map = "polluted special map"
        universe.mini_state = 9
        universe.first_mini = 0
        universe.need_record = False
        universe.map_data_load = Mock(return_value=(False, False, True))
        fallback = Mock()
        manager = Mock()

        with patch("iron_blood.key_mouse_manager", manager):
            universe.record_special_map_or_navigate(fallback)
            universe.record_special_map_or_navigate(fallback)

        universe.map_data_load.assert_called_once_with(
            create=False,
            map_root="maps",
            image_maps={},
            target_mode="special",
        )
        self.assertEqual("maps", universe.native_special_map_root)
        self.assertIsNone(universe.big_map)
        self.assertFalse(universe.big_map_init)
        self.assertEqual(1, universe.mini_state)
        self.assertEqual(1, universe.first_mini)
        self.assertEqual(2, fallback.call_count)

    def test_new_room_clears_special_map_source(self):
        universe = self.make_universe(set())
        universe.native_special_map_root = "maps"
        universe.loaded_map_root = "maps"
        universe.node_count = 0

        with patch.object(SimulatedUniverse, "init_map") as native_init:
            universe.init_map()

        native_init.assert_called_once_with()
        self.assertIsNone(universe.native_special_map_root)
        self.assertIsNone(universe.loaded_map_root)

    def test_rest_area_does_not_reuse_previous_battle_map(self):
        universe = self.make_universe({((12, 34), 1)})
        universe.record_event_map_enabled = False
        universe.area = "休整"
        universe.record_map_contexts = {"rest": ("rest_maps", {})}
        universe.big_map_init = True
        universe.loaded_map_root = "battle_maps"
        universe.need_record = False
        universe.map_data_load = Mock(return_value=(True, False, True))
        universe.navigate_recorded_special_map = Mock()

        def reset_big_map():
            universe.big_map_init = False

        with patch.object(
            SimulatedUniverse, "init_map", side_effect=reset_big_map
        ) as native_init, patch("iron_blood.key_mouse_manager", Mock()):
            universe.record_special_map_or_navigate(Mock())

        native_init.assert_called_once_with()
        universe.map_data_load.assert_called_once_with(
            create=False,
            map_root="rest_maps",
            image_maps={},
            target_mode="special",
        )

    @staticmethod
    def run_special_map_load(create, targets):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.debug = True
        universe.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        universe.first_save_map = True
        universe.pos_predictor = Mock()
        universe.pos_predictor.update_minimap_data.return_value = (0, 0)
        universe.get_blank_state = Mock(return_value=300)
        universe.get_screen = Mock(return_value=universe.screen)
        universe.click_text = Mock(return_value=False)
        universe._match_map_templates = Mock(return_value=("my_17682", 1.0))
        universe.get_target = Mock(return_value=set(targets))

        latest = ("map.jpg", 424.0, 588.8, 31, 207.0, 277.0, "target.jpg")
        with (
            patch("iron_blood.find_latest_modified_file", return_value=latest),
            patch("iron_blood.cv.imread", return_value=np.zeros((80, 98), dtype=np.uint8)),
            patch("iron_blood.key_mouse_manager", Mock()),
        ):
            return universe.map_data_load(
                create=create,
                map_root="special_maps",
                image_maps={},
                target_mode="special",
            )

    def test_my_special_map_always_remains_in_recording_mode(self):
        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=False, targets=set()),
        )
        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=True, targets=set()),
        )

    def test_annotated_my_map_still_remains_in_recording_mode(self):
        interaction = {((12, 34), 2)}

        self.assertEqual(
            (True, True, True),
            self.run_special_map_load(create=True, targets=interaction),
        )


class HertaInteractionTest(unittest.TestCase):
    @staticmethod
    def make_universe(text="黑塔", global_herta_match=False, quit_time=0):
        universe = SimulatedUniverse.__new__(SimulatedUniverse)
        universe.check = Mock(return_value=True)
        universe.get_small_interaction_img = Mock(
            return_value=np.zeros((10, 10), dtype=np.uint8)
        )
        universe.get_screen = Mock()
        universe.tk = SimpleNamespace(interacts=["黑塔", "事件"])
        universe.ts = Mock()
        universe.ts.similar_list.return_value = text
        universe.ts.similar.return_value = global_herta_match
        universe.quit = quit_time
        universe.update_state = Mock()
        return universe

    def test_herta_crop_result_sets_cooldown_even_if_global_ocr_misses(self):
        universe = self.make_universe(global_herta_match=False)
        manager = Mock()

        with patch("simul.time.time", return_value=100), patch(
            "simul.key_mouse_manager", manager
        ):
            result = universe.do_interaction()

        self.assertEqual(1, result)
        self.assertEqual(100, universe.quit)
        manager.press.assert_called_once_with("f", force=True)

    def test_herta_during_cooldown_does_not_press_again(self):
        universe = self.make_universe(quit_time=90)
        manager = Mock()

        with patch("simul.time.time", return_value=100), patch(
            "simul.key_mouse_manager", manager
        ):
            result = universe.do_interaction()

        self.assertIsNone(result)
        manager.press.assert_not_called()
        universe.update_state.assert_called_once_with("run")


class LatestMapFileSelectionTest(unittest.TestCase):
    def test_latest_map_and_target_win_over_stale_files(self):
        with tempfile.TemporaryDirectory() as folder:
            stale_map = os.path.join(folder, "map_31_(424.0,588.8).jpg")
            fresh_map = os.path.join(folder, "map_9_(100.0,200.0).jpg")
            stale_target = os.path.join(folder, "target_100_200.jpg")
            fresh_target = os.path.join(folder, "target_207_277.jpg")
            for path in (stale_map, stale_target):
                with open(path, "wb") as stream:
                    stream.write(b"stale")
                os.utime(path, (1000, 1000))
            for path in (fresh_map, fresh_target):
                with open(path, "wb") as stream:
                    stream.write(b"fresh")
                os.utime(path, (2000, 2000))

            file, x, y, map_num, upx, upy, target_path = find_latest_modified_file(folder)

            self.assertEqual(file, fresh_map)
            self.assertEqual((x, y), (100.0, 200.0))
            self.assertEqual(map_num, "9")
            self.assertEqual(target_path, fresh_target)
            self.assertEqual((upx, upy), (207.0, 277.0))

    def test_missing_files_return_none(self):
        with tempfile.TemporaryDirectory() as folder:
            file, x, y, map_num, upx, upy, target_path = find_latest_modified_file(folder)
            self.assertIsNone(file)
            self.assertIsNone(target_path)
            self.assertEqual(-1, map_num)

    def test_non_recording_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            init = os.path.join(folder, "init.jpg")
            with open(init, "wb") as stream:
                stream.write(b"x")
            file, x, y, map_num, upx, upy, target_path = find_latest_modified_file(folder)
            self.assertIsNone(file)
            self.assertIsNone(target_path)


class SpecialMapTrustThresholdTest(unittest.TestCase):
    @staticmethod
    def make_universe(sim, create, now_map="17682", map_root=None):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.debug = True
        universe.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        universe.first_save_map = True
        universe.pos_predictor = Mock()
        universe.pos_predictor.update_minimap_data.return_value = (0, 0)
        universe.pos_predictor.match_multiple_maps.return_value = {
            "position": (0.0, 0.0)
        }
        universe.get_blank_state = Mock(return_value=300)
        universe.get_screen = Mock(return_value=universe.screen)
        universe.click_text = Mock(return_value=False)
        universe._match_map_templates = Mock(return_value=(now_map, sim))
        universe.get_target = Mock(return_value=set())
        if map_root is None:
            map_root = tempfile.mkdtemp()
        return universe, map_root

    def test_special_map_below_trust_without_record_falls_back(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as map_root:
            universe, _ = self.make_universe(0.5, create=False, map_root=map_root)
            with patch("iron_blood.get_minimap", return_value=np.zeros((186, 186, 3), dtype=np.uint8)):
                find, record, state = universe.map_data_load(
                    create=False, map_root=map_root, image_maps={}, target_mode="special"
                )
            self.assertEqual((False, False, True), (find, record, state))

    def test_special_map_below_trust_with_record_creates_new_map(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as map_root:
            universe, _ = self.make_universe(0.5, create=True, map_root=map_root)
            with (
                patch("iron_blood.get_minimap", return_value=np.zeros((186, 186, 3), dtype=np.uint8)),
                patch("iron_blood.key_mouse_manager", Mock()),
            ):
                find, record, state = universe.map_data_load(
                    create=True, map_root=map_root, image_maps={}, target_mode="special"
                )
            self.assertEqual((False, True, True), (find, record, state))
            self.assertEqual(1, len(os.listdir(map_root)))
            created = os.listdir(map_root)[0]
            self.assertTrue(created.startswith("my_"))
            self.assertTrue(os.path.isfile(os.path.join(map_root, created, "init.jpg")))

    def test_unfinished_map_below_trust_keeps_recording_without_duplicate(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as map_root:
            universe, _ = self.make_universe(0.5, create=True, now_map="my_12345", map_root=map_root)
            with patch("iron_blood.key_mouse_manager", Mock()):
                find, record, state = universe.map_data_load(
                    create=True, map_root=map_root, image_maps={}, target_mode="special"
                )
            self.assertEqual((False, True, True), (find, record, state))
            self.assertEqual([], os.listdir(map_root))

    def test_special_map_above_trust_is_used(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as map_root:
            universe, _ = self.make_universe(0.7, create=False, map_root=map_root)
            latest = ("map.jpg", 424.0, 588.8, 31, 207.0, 277.0, "target.jpg")
            with (
                patch("iron_blood.find_latest_modified_file", return_value=latest),
                patch("iron_blood.cv.imread", return_value=np.zeros((80, 98), dtype=np.uint8)),
            ):
                find, record, state = universe.map_data_load(
                    create=False, map_root=map_root, image_maps={}, target_mode="special"
                )
            self.assertEqual((True, False, True), (find, record, state))


class AnnotatedInteractionApproachTest(unittest.TestCase):
    @staticmethod
    def make_universe(targets, now_loc):
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe.target = set(targets)
        universe.find = True
        universe.now_map = "event_map"
        universe._stop = False
        universe.target_type = 2
        universe.target_loc = next(
            (target[0] for target in targets if target[1] == 2), None
        )
        universe.now_loc = now_loc
        universe.last_interact_time = 0
        universe.special_interaction_failures = {}
        universe.native_special_map_root = None
        universe.loaded_map_root = None
        universe.trust_annotated_attack_targets = False
        universe.get_path_with_big_map = Mock()
        return universe

    def test_approach_advances_until_f_prompt_then_interacts(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction}, now_loc=(-5, 34))
        universe.do_interaction = Mock(side_effect=[None, 1])
        universe.check = Mock(side_effect=[False, True])
        universe.get_screen = Mock()
        universe.get_loc = Mock(return_value=True)
        universe.update_direction_data = Mock()
        fallback = Mock()

        with patch("iron_blood.key_mouse_manager", Mock()):
            universe.navigate_recorded_special_map(fallback)

        self.assertGreater(universe.last_interact_time, 0)
        self.assertNotIn(interaction, universe.target)
        fallback.assert_not_called()

    def test_approach_rotation_search_finds_interaction(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction}, now_loc=(10, 34))
        universe.do_interaction = Mock(side_effect=[None, 1])
        universe.check = Mock(side_effect=[False, False, True])
        universe.get_screen = Mock()
        universe.get_loc = Mock(return_value=True)
        universe.update_direction_data = Mock()
        fallback = Mock()
        manager = Mock()

        with patch("iron_blood.key_mouse_manager", manager):
            universe.navigate_recorded_special_map(fallback)

        self.assertGreater(universe.last_interact_time, 0)
        self.assertNotIn(interaction, universe.target)
        fallback.assert_not_called()
        self.assertTrue(manager.mouse_move.called)

    def test_approach_stops_without_progress_and_counts_failure(self):
        interaction = ((12, 34), 2)
        universe = self.make_universe({interaction}, now_loc=(8, 34))
        universe.do_interaction = Mock(return_value=None)
        universe.check = Mock(return_value=False)
        universe.get_screen = Mock()
        universe.get_loc = Mock(return_value=True)
        universe.update_direction_data = Mock()
        fallback = Mock()

        with patch("iron_blood.key_mouse_manager", Mock()):
            universe.navigate_recorded_special_map(fallback)

        self.assertEqual(
            1, universe.special_interaction_failures.get(("event_map", 12, 34))
        )
        self.assertIn(interaction, universe.target)
        fallback.assert_not_called()

    def test_approach_never_runs_for_non_interaction_targets(self):
        universe = self.make_universe({((40, 50), 3)}, now_loc=(38, 50))
        universe.target_type = 3
        universe.do_interaction = Mock(return_value=1)
        universe.check = Mock(side_effect=[True])

        with patch("iron_blood.key_mouse_manager", Mock()):
            universe.navigate_recorded_special_map(Mock())

        universe.do_interaction.assert_not_called()


class AutoRecordExploreTest(unittest.TestCase):
    @staticmethod
    def make_universe():
        universe = IronBloodUniverse.__new__(IronBloodUniverse)
        universe._stop = False
        universe.record_session = None
        universe.need_record = True
        universe.find = False
        universe.now_loc = (400.0, 140.0)
        universe.start_pos = (387.0, 141.4)
        universe.map_file = os.path.join("root", "my_12345") + os.sep
        universe.now_map = "my_12345"
        universe.target = set()
        universe.record_map_contexts = {"event": ("root", {})}
        universe.loaded_map_root = "root"
        universe.big_map_init = True
        universe.native_special_map_root = None
        universe.last_interact_time = 0
        universe.pos_predictor = Mock()
        universe.pos_predictor.map_num = 28
        universe.pos_predictor.assets_floor_feat = np.zeros(
            (400, 400), dtype=np.uint8
        )
        universe.check = Mock(return_value=False)
        universe.get_loc = Mock(return_value=True)
        universe.ts = SimpleNamespace(similar=Mock(return_value=False))
        universe._write_record_map = Mock()
        return universe

    def test_f_prompt_finishes_promotes_and_interacts(self):
        universe = self.make_universe()
        universe.check = Mock(return_value=True)
        universe.do_interaction = Mock(return_value=1)
        universe._promote_record_dir = Mock(return_value="123456")
        universe._reload_annotated_targets = Mock(
            side_effect=lambda: setattr(universe, "target", {((10, 10), 2)})
        )

        with patch("iron_blood.key_mouse_manager", Mock()):
            universe._record_explore_tick()

        self.assertFalse(universe.need_record)
        self.assertTrue(universe.find)
        universe._promote_record_dir.assert_called_once()
        universe.do_interaction.assert_called_once()
        self.assertGreater(universe.last_interact_time, 0)
        self.assertIsNone(universe.record_session)

    def test_stuck_walk_steps_back_and_rotates(self):
        universe = self.make_universe()
        manager = Mock()

        with patch("iron_blood.key_mouse_manager", manager):
            for _ in range(RECORD_STUCK_WINDOW + 1):
                universe._record_explore_tick()

        manager.press.assert_called_with("s", iron_blood_module.RECORD_BACK_SECONDS)
        manager.mouse_move.assert_called_with(
            iron_blood_module.RECORD_ROTATE_DEGREES
        )

    def test_consecutive_stuck_rotations_escalate_angle(self):
        universe = self.make_universe()
        manager = Mock()

        with patch("iron_blood.key_mouse_manager", manager):
            for _ in range(RECORD_STUCK_WINDOW + 1):
                universe._record_explore_tick()
            for _ in range(RECORD_STUCK_WINDOW):
                universe._record_explore_tick()

        angles = [call.args[0] for call in manager.mouse_move.call_args_list]
        self.assertEqual([45, -90], angles)

    def test_free_movement_resets_rotation_escalation(self):
        universe = self.make_universe()

        with patch("iron_blood.key_mouse_manager", Mock()):
            for _ in range(RECORD_STUCK_WINDOW + 1):
                universe._record_explore_tick()
            for _ in range(RECORD_STUCK_WINDOW):
                universe._record_explore_tick()
            self.assertEqual(2, universe.record_session["rotate_step"])
            universe.now_loc = (universe.now_loc[0] + 20.0, universe.now_loc[1])
            universe._record_explore_tick()
            self.assertEqual(1, universe.record_session["rotate_step"])
            self.assertFalse(universe.record_session["last_rotated"])

    def test_trace_samples_only_after_enough_movement(self):
        universe = self.make_universe()
        positions = [(0.0, 0.0), (9.0, 0.0), (9.0, 0.0), (18.0, 0.0)]

        with patch("iron_blood.key_mouse_manager", Mock()):
            for position in positions:
                universe.now_loc = position
                universe._record_explore_tick()

        self.assertEqual(3, len(universe.record_session["trace"]))

    def test_timeout_without_interaction_falls_back_without_promote(self):
        universe = self.make_universe()
        universe._promote_record_dir = Mock()
        init_map = Mock()
        times = itertools.chain([0.0], itertools.repeat(1000.0))

        with (
            patch("iron_blood.key_mouse_manager", Mock()),
            patch("iron_blood.SimulatedUniverse.init_map", init_map),
            patch("iron_blood.time.time", side_effect=lambda: next(times)),
        ):
            universe._record_explore_tick()

        self.assertFalse(universe.need_record)
        universe._promote_record_dir.assert_not_called()
        init_map.assert_called_once()
        self.assertEqual("root", universe.native_special_map_root)
        self.assertIsNone(universe.record_session)

    def test_write_record_map_draws_annotations_and_prunes_files(self):
        with tempfile.TemporaryDirectory() as folder:
            universe = self.make_universe()
            del universe._write_record_map  # 恢复真实实现（默认是 Mock）
            universe.map_file = os.path.join(folder, "my_1") + os.sep
            os.makedirs(universe.map_file, exist_ok=True)
            stale = os.path.join(universe.map_file, "map_9_(0.0,0.0).jpg")
            cv.imwrite(stale, np.zeros((10, 10), dtype=np.uint8))
            universe.cut_pos = [50, 250, 40, 240]
            universe.record_session = {
                "trace": [(100.0, 100.0)],
                "interactions": [(120.0, 120.0)],
            }

            universe._write_record_map()

            self.assertFalse(os.path.exists(stale))
            names = os.listdir(universe.map_file)
            self.assertEqual(1, sum(name.startswith("map_") for name in names))
            self.assertEqual(1, sum(name.startswith("target_") for name in names))
            target_path = os.path.join(
                universe.map_file, next(name for name in names if name.startswith("target_"))
            )
            image = cv.imread(target_path)
            self.assertTrue(np.any(np.all(np.abs(image.astype(int) - (255, 0, 0)) < 40, axis=-1)))
            self.assertTrue(np.any(np.all(np.abs(image.astype(int) - (29, 230, 181)) < 40, axis=-1)))

    def test_promote_renames_dir_and_migrates_template(self):
        with tempfile.TemporaryDirectory() as root:
            old_dir = os.path.join(root, "my_22887")
            os.makedirs(old_dir)
            templates = {"my_22887": np.zeros((10, 10), dtype=np.uint8)}
            universe = self.make_universe()
            universe.map_file = old_dir + os.sep
            universe.now_map = "my_22887"
            universe.record_map_contexts = {"event": (root, templates)}

            new_name = universe._promote_record_dir()

            self.assertNotIn("m", new_name)
            self.assertFalse(os.path.exists(old_dir))
            self.assertTrue(os.path.isdir(os.path.join(root, new_name)))
            self.assertIn(new_name, templates)
            self.assertNotIn("my_22887", templates)
            self.assertEqual(new_name, universe.now_map)


if __name__ == "__main__":
    unittest.main()
