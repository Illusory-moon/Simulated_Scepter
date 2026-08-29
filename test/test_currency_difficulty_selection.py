import unittest
from unittest.mock import Mock, patch

from currency import SimulatedCurrency


class CurrencyDifficultySelectionTest(unittest.TestCase):
    @staticmethod
    def make_currency(state="difficulty_select"):
        currency = object.__new__(SimulatedCurrency)
        currency.state = state
        currency.update_state = Mock(
            side_effect=lambda next_state: setattr(currency, "state", next_state)
        )
        return currency

    @patch("currency.key_mouse_manager")
    def test_complete_selection_clears_drag_queue_and_updates_state(self, manager):
        currency = self.make_currency()

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_called_once_with()
        manager.click.assert_called_once_with(1692, 965, force=True)
        currency.update_state.assert_called_once_with("startbattle")
        self.assertEqual(currency.state, "startbattle")

    @patch("currency.key_mouse_manager")
    def test_complete_selection_is_idempotent_after_state_advanced(self, manager):
        currency = self.make_currency("startbattle")

        self.assertTrue(currency.complete_difficulty_selection())

        manager.clean.assert_not_called()
        manager.click.assert_not_called()
        currency.update_state.assert_not_called()

    @patch("currency.key_mouse_manager")
    def test_scroll_loop_stops_when_state_already_advanced(self, manager):
        currency = self.make_currency("startbattle")
        currency.get_screen = Mock()
        currency.is_one = Mock()

        self.assertTrue(currency.select_difficulty_start())

        currency.get_screen.assert_not_called()
        currency.is_one.assert_not_called()
        manager.drag.assert_not_called()

    @patch("currency.key_mouse_manager")
    def test_detected_selection_uses_shared_completion_path(self, manager):
        currency = self.make_currency()
        currency.get_screen = Mock()
        currency.is_one = Mock(return_value=True)
        currency.complete_difficulty_selection = Mock(return_value=True)

        self.assertTrue(currency.select_difficulty_start())

        currency.complete_difficulty_selection.assert_called_once_with()
        manager.drag.assert_not_called()


if __name__ == "__main__":
    unittest.main()
