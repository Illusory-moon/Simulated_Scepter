import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from currency import SimulatedCurrency
from tool.currency.run_history import RUN_END_ACTION, RUN_START_ACTION


class CurrencyWarActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config_path = Path(__file__).resolve().parents[1] / "actions" / "currencywar.json"
        with config_path.open(encoding="utf-8") as config_file:
            cls.actions = json.load(config_file)

    def test_chalice_trial_popup_selects_left_trial_and_confirms(self):
        matches = [
            action
            for action in self.actions
            if action.get("name") == "命运圣杯祈愿试炼"
        ]

        self.assertEqual(len(matches), 1)
        self.assertEqual(
            matches[0],
            {
                "name": "命运圣杯祈愿试炼",
                "trigger": {
                    "text": "请选择一个祈愿试炼",
                    "box": [1400, 1595, 572, 599],
                    "interval": 2,
                    "redundancy": 30,
                },
                "actions": [
                    {"position": [684, 398]},
                    {"sleep": 0.5},
                    {"position": [1495, 639]},
                ],
            },
        )

    def test_run_history_actions_keep_expected_names(self):
        action_names = {action.get("name") for action in self.actions}

        self.assertIn(RUN_START_ACTION, action_names)
        self.assertIn(RUN_END_ACTION, action_names)

    def test_selected_difficulty_uses_state_completing_action(self):
        action = next(
            action
            for action in self.actions
            if action.get("name") == RUN_START_ACTION
        )

        self.assertEqual(action["actions"], ["complete_difficulty_selection"])

    def test_environment_state_advances_only_inside_selection_action(self):
        action = next(
            action
            for action in self.actions
            if action.get("name") == "选择投资环境"
        )

        self.assertEqual(action["actions"], ["select_envir"])

    def test_peace_token_skip_action_handles_both_remaining_counts(self):
        skip_action = next(
            action for action in self.actions if action.get("name") == "跳过战斗"
        )
        battle_index = next(
            index
            for index, action in enumerate(self.actions)
            if action.get("name") == "出战"
        )
        skip_index = self.actions.index(skip_action)

        self.assertLess(skip_index, battle_index)
        self.assertEqual(skip_action["trigger"]["text"], "跳过")
        self.assertEqual(skip_action["trigger"]["condition"], "startbattle")
        self.assertEqual(skip_action["actions"], [{"position": [1818, 750]}])
        self.assertIn(skip_action["trigger"]["text"], "跳过(2/2)")
        self.assertIn(skip_action["trigger"]["text"], "跳过(1/2)")

    def test_run_static_executes_peace_token_skip_before_battle(self):
        skip_action = next(
            action for action in self.actions if action.get("name") == "跳过战斗"
        )
        battle_action = next(
            action for action in self.actions if action.get("name") == "出战"
        )
        currency = object.__new__(SimulatedCurrency)
        currency.state = "startbattle"
        currency.get_screen = Mock(return_value=255)
        currency.ts = Mock()
        currency.ts.find_with_box.return_value = [
            {
                "raw_text": "跳过(2/2)",
                "box": [1784, 1852, 730, 770],
            }
        ]
        currency.action_history = []
        currency.action_time = 0
        currency.do_action = Mock(return_value=1)
        currency._on_static_action_completed = Mock()

        result = currency.run_static(
            json_file={
                "跳过战斗": [skip_action],
                "出战": [battle_action],
            }
        )

        self.assertEqual(result, ("跳过战斗", 1))
        currency.ts.find_with_box.assert_called_once_with(
            [1784, 1852, 730, 770],
            redundancy=60,
        )
        currency.do_action.assert_called_once_with({"position": [1818, 750]})


if __name__ == "__main__":
    unittest.main()
