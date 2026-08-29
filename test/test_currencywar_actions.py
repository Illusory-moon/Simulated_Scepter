import json
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
