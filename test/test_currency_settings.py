import tempfile
import unittest
from pathlib import Path

import yaml

from tool.currency.settings import (
    DEFAULT_EXIT_PLANE,
    EXIT_PLANES,
    load_currency_settings,
    save_currency_settings,
)


class CurrencySettingsTests(unittest.TestCase):
    def test_exit_plane_choices_are_fixed(self):
        self.assertEqual(EXIT_PLANES, (1, 2, 3))

    def test_missing_config_uses_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_currency_settings(Path(temp_dir) / "missing.yml")

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_loads_supported_exit_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("exit_after_plane: 3\n", encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], 3)

    def test_invalid_exit_plane_falls_back_to_first_plane(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("exit_after_plane: 9\n", encoding="utf-8")

            settings = load_currency_settings(path)

        self.assertEqual(settings["exit_after_plane"], DEFAULT_EXIT_PLANE)

    def test_save_preserves_other_currency_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency.yml"
            path.write_text("future_setting: true\n", encoding="utf-8")

            saved = save_currency_settings({"exit_after_plane": 2}, path)
            values = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["exit_after_plane"], 2)
        self.assertEqual(values, {"future_setting": True, "exit_after_plane": 2})


if __name__ == "__main__":
    unittest.main()
