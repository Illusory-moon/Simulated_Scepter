"""倒计时 GUI 与纯后端边界及初始布局回归测试。"""

import inspect
import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication, QPlainTextEdit, QScrollArea

import countdown_backend as backend
import countdown_dp as dp
import countdown_gui as gui
import countdown_map_loader as loader


class CountdownGuiBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = gui.MainWindow()

    def tearDown(self):
        self.window.close()

    def test_gui_uses_new_backend_not_legacy_hybrid_optimizer(self):
        source = inspect.getsource(gui)
        self.assertNotIn("test_countdown_optimizer", source)
        self.assertIn("ExactCountdownDP", source)
        self.assertNotIn("future_table", source)
        self.assertNotIn("sys.stdout =", source)
        self.assertNotIn("random.Random", source)

    def test_dp_is_an_independent_side_panel_inside_the_scroll_area(self):
        backend_source = inspect.getsource(backend)
        dp_source = inspect.getsource(dp)
        self.assertNotIn("ExactCountdownDP", backend_source)
        self.assertNotIn("MonteCarloController", dp_source)
        self.assertTrue(hasattr(gui.DPAnalysisThread, "done_signal"))
        scroll = self.window.findChild(QScrollArea)
        parent = self.window.lbl_dp_max.parentWidget()
        while parent is not None and parent is not scroll:
            parent = parent.parentWidget()
        self.assertIs(parent, scroll)
        self.assertTrue(hasattr(self.window, "lbl_dp_steps"))
        self.assertIsInstance(self.window.lbl_dp_steps, QPlainTextEdit)
        self.assertTrue(self.window.lbl_dp_steps.isReadOnly())

    def test_dp_panel_renders_each_steps_action_cd_and_infection_state(self):
        nodes = [
            {"idx": 0, "name": "start", "cx": 0, "cy": 0},
            {"idx": 1, "name": "wait", "cx": 100, "cy": 0},
            {"idx": 2, "name": "boss", "cx": 200, "cy": 0},
        ]
        model = backend.CountdownMap(
            nodes, {0: [1], 1: [2], 2: []}, 0, ())
        context = backend.DecisionContext(
            backend.PHASE_EFFECT, model.initial_state(1, 0, 5),
            backend.EFFECT_NOTHING)
        self.window.prepared = SimpleNamespace(model=model)
        self.window.dp_context = context
        self.window.dp_result = dp.ExactCountdownDP(model).solve(context)
        self.window._render_dp_result()
        text = self.window.lbl_dp_steps.toPlainText()
        self.assertIn("第1步", text)
        self.assertIn("cheat→慈怀", text)
        self.assertIn("CD：5 +1 → 6", text)
        self.assertIn("效果 +0，移动 +1", text)
        self.assertIn("本步感染：wait#1", text)
        self.assertIn("后：CD=6", text)

    def test_all_gui_win_rates_show_four_decimal_places(self):
        source = inspect.getsource(gui)
        self.assertNotIn(".2f}%", source)
        self.assertGreaterEqual(source.count(".4f}%"), 4)

    def test_backend_and_lazy_loader_keep_heavy_dependencies_out_of_startup(self):
        backend_source = inspect.getsource(backend)
        loader_source = inspect.getsource(loader)
        self.assertNotIn("PyQt", backend_source)
        self.assertNotRegex(backend_source, r"(?m)^\s*(?:from|import)\s+cv2")
        self.assertNotRegex(loader_source, r"(?m)^import\s+cv2\s*$")

    def test_loader_merges_template_versions_without_duplicate_nodes(self):
        old = [{"name": "battle", "location": (100, 100), "size": (40, 40),
                "similarity": 0.7}]
        new = [
            {"name": "elite", "location": (102, 99), "size": (42, 42),
             "similarity": 0.9},
            {"name": "boss", "location": (300, 100), "size": (40, 40),
             "similarity": 0.8},
        ]
        merged = loader._merge_match_groups(old, new)
        self.assertEqual(2, len(merged))
        self.assertEqual({"elite", "boss"}, {item["name"] for item in merged})

    def test_requested_defaults_and_three_map_paths_are_visible(self):
        self.assertEqual("manual", self.window.mode_combo.currentData())
        self.assertEqual("single", self.window.scope_combo.currentData())
        self.assertEqual((2, 3), (
            self.window.spin_cheat.value(), self.window.spin_reroll.value()))
        self.assertEqual((10_000, 10_000), (
            self.window.spin_control.value(), self.window.spin_evaluation.value()))
        self.assertEqual(3, len(self.window.path_lines))
        self.assertTrue(all(line.text() for line in self.window.path_lines))

    def test_manual_controls_are_outside_the_scrolling_side_panel(self):
        scroll = self.window.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        parent = self.window.btn_keep.parentWidget()
        while parent is not None:
            self.assertIsNot(parent, scroll)
            parent = parent.parentWidget()

    def test_progress_is_structured_and_failure_has_its_own_signal(self):
        self.assertTrue(hasattr(gui.MapLoadThread, "progress_signal"))
        self.assertTrue(hasattr(gui.MapLoadThread, "failed_signal"))
        self.assertTrue(hasattr(gui.RecommendationThread, "done_signal"))
        self.assertTrue(hasattr(gui.RecommendationThread, "failed_signal"))

    def test_map_switch_defers_recommendation_until_the_old_worker_exits(self):
        source = inspect.getsource(gui.MainWindow)
        self.assertIn("pending_recommendation", source)
        self.assertIn("QTimer.singleShot(0, self._request_recommendation)", source)
        load_source = inspect.getsource(gui.MainWindow._start_map_load)
        self.assertIn("self.request_id += 1", load_source)
        self.assertIn("self.auto_pending = False", load_source)
        finished_source = inspect.getsource(gui.MainWindow._rec_thread_finished)
        self.assertIn("not (self.map_thread and self.map_thread.isRunning())",
                      finished_source)

    def test_target_changes_invalidate_the_inflight_win_rate_snapshot(self):
        source = inspect.getsource(gui.MainWindow._recommendation_settings_changed)
        self.assertIn("self.request_id += 1", source)
        self.assertIn("self.rec_thread.requestInterruption()", source)

    def test_map_change_commits_only_after_recognition_and_loader_is_cancellable(self):
        dropped = inspect.getsource(gui.MainWindow._image_dropped)
        loaded = inspect.getsource(gui.MainWindow._map_loaded)
        loader_source = inspect.getsource(loader.load_countdown_map)
        self.assertNotIn("self.map_paths[index] =", dropped)
        self.assertIn("self.map_paths[plane - 1] = prepared.image_path", loaded)
        self.assertIn("cancelled", loader_source)

    def test_candidate_labels_render_without_qpoint_type_errors(self):
        nodes = [
            {"idx": 0, "cx": 30, "cy": 50, "w": 30},
            {"idx": 1, "cx": 170, "cy": 50, "w": 30},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        state = model.initial_state(0, 0)
        context = backend.DecisionContext(
            backend.PHASE_PATH, state, locked_effect=backend.EFFECT_NOTHING)
        stats = backend.MCSampleStats()
        stats.append(12, 10)
        recommendation = backend.MCRecommendation(
            context, {1: stats}, 1, 1, 0, 1)
        canvas = gui.MapCanvas()
        canvas.resize(400, 240)
        canvas._pixmap = QPixmap(200, 100)
        canvas._pixmap.fill()
        canvas.prepared = SimpleNamespace(
            width=200, height=100, nodes=tuple(nodes), model=model,
            start_detected=False)
        canvas.set_view(state, context, recommendation)
        target = QPixmap(canvas.size())
        canvas.render(target)

    def test_mean_and_win_policy_samples_are_displayed_separately(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        context = backend.DecisionContext(
            backend.PHASE_PATH, model.initial_state(0, 0, 0),
            locked_effect=backend.EFFECT_NOTHING)
        mean_stats, win_stats = backend.MCSampleStats(), backend.MCSampleStats()
        mean_stats.append(20, 75)
        win_stats.append(80, 75)
        recommendation = backend.MCRecommendation(
            context, {1: mean_stats}, 1, 1, 1, 2, {1: win_stats})
        self.window._fill_recommendation(context, recommendation)
        self.assertIn("100.0000%", self.window.lbl_recommend.text())
        self.assertEqual("1/1", self.window.candidate_table.item(0, 3).text())
        self.assertEqual(0.0, mean_stats.win_rate)
        self.assertEqual(1.0, win_stats.win_rate)

    def test_canvas_uses_detached_nodes_and_spreads_them_across_the_view(self):
        nodes = [
            {"idx": 0, "name": "start", "cx": 900, "cy": 500, "w": 30},
            {"idx": 1, "name": "boss", "cx": 1000, "cy": 500, "w": 30},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        canvas = gui.MapCanvas()
        canvas.resize(1000, 600)
        canvas._pixmap = QPixmap(1920, 1080)
        canvas._pixmap.fill()
        canvas.prepared = SimpleNamespace(
            width=1920, height=1080, model=model, start_detected=False)
        canvas.set_view(model.initial_state(0, 0))
        target = QPixmap(canvas.size())
        canvas.render(target)
        self.assertGreater(canvas._screen_nodes[1].x() - canvas._screen_nodes[0].x(), 700)
        self.assertEqual(QColor("#10131d"), target.toImage().pixelColor(10, 10))
        self.assertFalse(hasattr(canvas, "_image_rect"))

    def test_dense_canvas_scales_nodes_instead_of_covering_neighbors(self):
        nodes = [
            {"idx": idx, "name": "battle", "cx": (idx % 7) * 100,
             "cy": (idx // 7) * 100, "w": 40}
            for idx in range(28)
        ]
        edges = {idx: [idx + 1] if idx < len(nodes) - 1 else []
                 for idx in range(len(nodes))}
        model = backend.CountdownMap(nodes, edges, 0, ())
        canvas = gui.MapCanvas()
        canvas.resize(680, 500)
        canvas._pixmap = QPixmap(400, 300)
        canvas._pixmap.fill()
        canvas.prepared = SimpleNamespace(
            width=400, height=300, model=model, start_detected=False)
        canvas.set_view(model.initial_state(0, 0))
        canvas.render(QPixmap(canvas.size()))
        self.assertEqual(len(nodes), len(canvas._screen_nodes))
        self.assertLess(canvas._node_radius, canvas.NODE_RADIUS)
        self.assertLess(canvas._icon_size, 76)

    def test_cancel_and_mode_switch_cannot_resume_stale_automatic_work(self):
        self.window.pending_load = self.window.pending_recommendation = True
        self.window.cancel_work()
        self.assertFalse(self.window.pending_load)
        self.assertFalse(self.window.pending_recommendation)
        self.window.mode_combo.setCurrentIndex(
            self.window.mode_combo.findData("mc"))
        self.window.auto_pending = True
        self.window.mode_combo.setCurrentIndex(
            self.window.mode_combo.findData("manual"))
        self.assertFalse(self.window.auto_pending)

    def test_automatic_mode_can_retry_after_a_failed_or_cancelled_recommendation(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        self.window.session = backend.CountdownSession(model, 0, 0)
        self.window.view_index = 0
        self.window.recommendation = None
        self.window.mode_combo.setCurrentIndex(
            self.window.mode_combo.findData("mc"))
        self.window._update_controls()
        self.assertTrue(self.window.btn_execute.isEnabled())
        self.window.auto_pending = True
        self.window._update_controls()
        self.assertFalse(self.window.btn_execute.isEnabled())

    def test_observed_effect_selector_tracks_the_backend_fact(self):
        nodes = [
            {"idx": 0, "cx": 0, "cy": 0},
            {"idx": 1, "cx": 100, "cy": 0},
        ]
        model = backend.CountdownMap(nodes, {0: [1], 1: []}, 0, ())
        self.window.session = backend.CountdownSession(model, 0, 0)
        self.window.session.set_observed_effect(backend.EFFECT_RANDOM_INFECT)
        self.window.view_index = 0
        self.window._refresh_view()
        self.assertEqual(backend.EFFECT_RANDOM_INFECT,
                         self.window.combo_observed.currentData())


if __name__ == "__main__":
    unittest.main(verbosity=2)
