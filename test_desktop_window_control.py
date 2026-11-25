import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))


class PlacementTests(unittest.TestCase):
    def test_fit_rect_to_work_area_keeps_window_inside_target_display(self):
        from desktop_window_control import Rect, fit_rect_to_work_area

        result = fit_rect_to_work_area(
            Rect(left=0, top=0, right=1800, bottom=1100),
            Rect(left=1707, top=0, right=2787, bottom=1920),
        )

        self.assertEqual(result, Rect(left=1707, top=0, right=2787, bottom=1100))

    def test_vertical_stack_bounds_splits_a_display_without_overlap(self):
        from desktop_window_control import Rect, vertical_stack_bounds

        top, bottom = vertical_stack_bounds(
            Rect(left=2560, top=104, right=3640, bottom=2024),
            top_fraction=0.72,
        )

        self.assertEqual(top, Rect(left=2560, top=104, right=3640, bottom=1486))
        self.assertEqual(bottom, Rect(left=2560, top=1486, right=3640, bottom=2024))

    def test_region_bounds_uses_fractions_of_the_display_work_area(self):
        from desktop_window_control import Rect, region_bounds

        result = region_bounds(
            Rect(left=2560, top=104, right=3640, bottom=2024),
            left_fraction=0,
            top_fraction=0.65,
            width_fraction=1,
            height_fraction=0.35,
        )

        self.assertEqual(result, Rect(left=2560, top=1352, right=3640, bottom=2024))

    def test_fancyzones_drag_points_hold_the_title_bar_and_release_in_the_zone(self):
        from desktop_window_control import Rect, fancyzones_drag_points

        start, end = fancyzones_drag_points(
            Rect(left=2560, top=104, right=3640, bottom=1352),
            Rect(left=2560, top=104, right=3640, bottom=1352),
        )

        self.assertEqual(start, (3100, 120))
        self.assertEqual(end, (3100, 728))


class BridgeTests(unittest.TestCase):
    def test_read_response_accepts_only_the_matching_command_id(self):
        from bridge import read_response

        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime = Path(temporary_directory)
            (runtime / "response.json").write_text('{"id":"other","ok":true}', encoding="utf-8")
            self.assertIsNone(read_response(runtime, "expected"))
            (runtime / "response.json").write_text('{"id":"expected","ok":true,"result":{"value":1}}', encoding="utf-8")
            self.assertEqual(read_response(runtime, "expected"), {"value": 1})


class InteractiveAgentTests(unittest.TestCase):
    def test_vertical_stack_dispatch_does_not_require_single_window_handle(self):
        import interactive_agent
        from desktop_window_control import Rect

        with patch.object(interactive_agent.importlib, "reload", side_effect=lambda module: module), patch.object(
            interactive_agent.windows,
            "arrange_vertical_stack",
            return_value=(Rect(0, 0, 100, 70), Rect(0, 70, 100, 100)),
        ):
            result = interactive_agent.dispatch(
                "arrange_vertical_stack",
                {"top_handle": 1, "bottom_handle": 2, "display_id": "DISPLAY3", "top_fraction": 0.7},
            )

        self.assertEqual(result["action"], "arranged_vertical_stack")

    def test_fancyzones_dispatch_sends_one_window_to_one_region(self):
        import interactive_agent
        from desktop_window_control import Rect

        with patch.object(interactive_agent.importlib, "reload", side_effect=lambda module: module), patch.object(
            interactive_agent.windows,
            "snap_window_to_fancyzones_region",
            return_value=Rect(0, 0, 100, 70),
        ):
            result = interactive_agent.dispatch(
                "snap_window_to_fancyzones_region",
                {
                    "handle": 1,
                    "display_id": "DISPLAY3",
                    "left_fraction": 0,
                    "top_fraction": 0,
                    "width_fraction": 1,
                    "height_fraction": 0.65,
                },
            )

        self.assertEqual(result["action"], "fancyzones_snapped")

    def test_previous_agent_pid_reads_status_file(self):
        import interactive_agent

        with tempfile.TemporaryDirectory() as temporary_directory:
            status_path = Path(temporary_directory) / "status.json"
            status_path.write_text('{"pid": 12345}', encoding="utf-8")
            self.assertEqual(interactive_agent.previous_agent_pid(status_path), 12345)


if __name__ == "__main__":
    unittest.main()
