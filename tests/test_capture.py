import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPixmap

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from screen_recorder.capture import (
    ACTIVE_RECORDING_SEGMENT_DIRS, CaptureError, Recorder, build_ffmpeg_args,
    composite_screens, concat_list_content, find_orphaned_recordings,
    logical_rect_to_physical, recover_orphaned_recording,
    save_screenshot, unique_path,
)
from screen_recorder.library import captures

APP = QApplication.instance() or QApplication([])


class CaptureTests(unittest.TestCase):
    def build_args(self, suffix="mkv", **kwargs):
        return build_ffmpeg_args(
            "ffmpeg", ":0", (0, 0, 1920, 1080), Path(f"output.{suffix}"), 30, "High",
            "", False, "", **kwargs,
        )

    def test_video_and_audio_codec_selection_by_format(self):
        expected = {"mkv": ("libx264", "aac"), "mp4": ("libx264", "aac"), "webm": ("libvpx-vp9", "libopus")}
        for suffix, (video_codec, audio_codec) in expected.items():
            with self.subTest(suffix=suffix):
                no_audio = self.build_args(suffix)
                self.assertEqual(no_audio[no_audio.index("-c:v") + 1], video_codec)
                args = build_ffmpeg_args(
                    "ffmpeg", ":0", (0, 0, 1920, 1080), Path(f"output.{suffix}"),
                    30, "High", "system.monitor", False, "",
                )
                self.assertEqual(args[args.index("-c:a") + 1], audio_codec)

    def test_compatibility_flags_by_format(self):
        for suffix in ("mkv", "mp4", "webm"):
            with self.subTest(suffix=suffix):
                args = self.build_args(suffix)
                self.assertEqual(args[args.index("-vf") + 1], "scale=trunc(iw/2)*2:trunc(ih/2)*2")
                self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
                self.assertNotIn("-movflags", args)

    def test_mouse_cursor_flag(self):
        for show_cursor, expected in ((True, "1"), (False, "0")):
            with self.subTest(show_cursor=show_cursor):
                args = build_ffmpeg_args(
                    "ffmpeg", ":0", (0, 0, 1920, 1080), Path("output.mkv"),
                    30, "High", "", False, "", show_cursor=show_cursor,
                )
                self.assertEqual(args[args.index("-draw_mouse") + 1], expected)

    def test_concat_list_escapes_paths(self):
        content = concat_list_content([Path("/tmp/a'b.mkv"), Path("/tmp/second.mkv")])
        self.assertEqual(content, "file '/tmp/a\\'b.mkv'\nfile '/tmp/second.mkv'\n")

    def test_recorder_pause_resume_tracks_segments_and_finalizes(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = Mock()
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

        processes = []

        def fake_popen(args, **_kwargs):
            Path(args[-1]).write_bytes(b"segment")
            process = FakeProcess()
            processes.append(process)
            return process

        screen = Mock()
        screen.virtualGeometry.return_value.x.return_value = 0
        screen.virtualGeometry.return_value.y.return_value = 0
        screen.virtualGeometry.return_value.width.return_value = 1280
        screen.virtualGeometry.return_value.height.return_value = 720
        screen.devicePixelRatio.return_value = 1
        recorder = Recorder()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"DISPLAY": ":test", "XDG_SESSION_TYPE": "x11"}), \
                patch("screen_recorder.capture.shutil.which", return_value="/usr/bin/ffmpeg"), \
                patch("screen_recorder.capture.QGuiApplication.primaryScreen", return_value=screen), \
                patch("screen_recorder.capture.subprocess.Popen", side_effect=fake_popen), \
                patch("screen_recorder.capture.subprocess.run") as run:
            def fake_concat(args, **_kwargs):
                Path(args[-1]).write_bytes(b"final")
                return Mock(returncode=0, stderr="")

            run.side_effect = fake_concat
            output = Path(directory) / "recording.mp4"
            recorder.start(output)
            self.assertTrue(recorder.running)
            recorder.pause()
            self.assertTrue(recorder.running)
            self.assertIsNone(recorder.process)
            self.assertEqual(len(recorder.segments), 1)
            recorder.resume()
            self.assertIsNotNone(recorder.process)
            self.assertEqual(len(processes), 2)
            self.assertEqual(recorder.stop(), output)
            self.assertEqual(output.read_bytes(), b"final")
            self.assertFalse(recorder.running)
            self.assertEqual(len(recorder.segments), 0)
            concat_args = run.call_args.args[0]
            self.assertIn("-f", concat_args)
            self.assertIn("+frag_keyframe+empty_moov", concat_args)

    def test_concat_failure_preserves_segments_and_reports_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_directory = root / ".recording.segments"
            segment_directory.mkdir()
            segment = segment_directory / "segment-001.mkv"
            segment.write_bytes(b"segment")
            recorder = Recorder()
            recorder.output = root / "recording.mp4"
            recorder.segment_directory = segment_directory
            recorder.segments = [segment]
            recorder._ffmpeg = "ffmpeg"
            with patch(
                "screen_recorder.capture.subprocess.run",
                return_value=Mock(returncode=1, stderr="concat failed"),
            ):
                with self.assertRaisesRegex(CaptureError, str(segment_directory)):
                    recorder.stop()
            self.assertTrue(segment.exists())
            self.assertEqual(recorder.output, root / "recording.mp4")

    def test_orphan_detection_requires_nonempty_segment_and_excludes_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / ".valid.segments-1"
            valid.mkdir()
            (valid / "segment-001.mkv").write_bytes(b"video")
            empty = root / ".empty.segments-1"
            empty.mkdir()
            (empty / "segment-001.mkv").touch()
            active = root / ".active.segments-1"
            active.mkdir()
            (active / "segment-001.mkv").write_bytes(b"recording")
            ACTIVE_RECORDING_SEGMENT_DIRS.add(active.resolve())
            self.addCleanup(ACTIVE_RECORDING_SEGMENT_DIRS.discard, active.resolve())
            self.assertEqual(find_orphaned_recordings(root), [valid])

    def test_orphan_recovery_joins_segments_and_deletes_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            (segment_dir / "segment-001.mkv").write_bytes(b"segment")

            def run_concat(args, **_kwargs):
                Path(args[-1]).write_bytes(b"recovered")
                return Mock(returncode=0, stderr="")

            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", return_value=True), \
                    patch("screen_recorder.capture._segments_have_audio", return_value=False), \
                    patch("screen_recorder.capture._verify_recovered_output", return_value=True), \
                    patch("screen_recorder.capture.subprocess.run", side_effect=run_concat):
                output = recover_orphaned_recording(segment_dir, root, "mkv", "High")
            self.assertTrue(output.name.startswith("recovered-"))
            self.assertEqual(output.read_bytes(), b"recovered")
            self.assertFalse(segment_dir.exists())

    def test_recovery_failure_preserves_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            segment = segment_dir / "segment-001.mkv"
            segment.write_bytes(b"segment")
            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", return_value=True), \
                    patch("screen_recorder.capture._segments_have_audio", return_value=False), \
                    patch("screen_recorder.capture.subprocess.run", return_value=Mock(returncode=1, stderr="concat failed")):
                with self.assertRaisesRegex(CaptureError, "Segments were kept"):
                    recover_orphaned_recording(segment_dir, root, "mp4", "High")
            self.assertTrue(segment.exists())

    def test_recovery_moves_corrupt_trailing_segment_to_discarded_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            first = segment_dir / "segment-001.mkv"
            trailing = segment_dir / "segment-002.mkv"
            first.write_bytes(b"valid")
            trailing.write_bytes(b"truncated")

            def run_concat(args, **_kwargs):
                concat_file = Path(args[args.index("-i") + 1])
                self.assertIn(str(first.resolve()), concat_file.read_text())
                self.assertNotIn(str(trailing.resolve()), concat_file.read_text())
                Path(args[-1]).write_bytes(b"recovered")
                return Mock(returncode=0, stderr="")

            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", side_effect=[True, False]), \
                    patch("screen_recorder.capture._segments_have_audio", return_value=False), \
                    patch("screen_recorder.capture._verify_recovered_output", return_value=True), \
                    patch("screen_recorder.capture.subprocess.run", side_effect=run_concat):
                output = recover_orphaned_recording(segment_dir, root, "mkv", "High")
            self.assertTrue(output.exists())
            self.assertFalse(segment_dir.exists())
            discarded = root / f"{output.stem}.discarded" / trailing.name
            self.assertEqual(discarded.read_bytes(), b"truncated")

    def test_recovery_keeps_unknown_timeout_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            segment = segment_dir / "segment-001.mkv"
            segment.write_bytes(b"possibly good")
            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", return_value=None), \
                    patch("screen_recorder.capture._segments_have_audio", return_value=False), \
                    patch("screen_recorder.capture._verify_recovered_output", return_value=True), \
                    patch("screen_recorder.capture.subprocess.run") as run:
                def concat(args, **_kwargs):
                    concat_list = Path(args[args.index("-i") + 1])
                    self.assertIn(str(segment.resolve()), concat_list.read_text())
                    Path(args[-1]).write_bytes(b"recovered")
                    return Mock(returncode=0, stderr="")

                run.side_effect = concat
                output = recover_orphaned_recording(segment_dir, root, "mkv", "High")
            self.assertTrue(output.exists())

    def test_demux_timeout_is_unknown_not_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            segment = Path(directory) / "segment.mkv"
            segment.write_bytes(b"possibly valid")
            with patch("screen_recorder.capture.shutil.which", return_value="/usr/bin/ffprobe"), \
                    patch(
                        "screen_recorder.capture.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("ffprobe", 60),
                    ) as run:
                from screen_recorder.capture import _segment_is_readable

                self.assertIsNone(_segment_is_readable("ffmpeg", segment))
            self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_truncated_last_segment_is_corrupt_after_probe_success(self):
        with tempfile.TemporaryDirectory() as directory:
            segment = Path(directory) / "segment.mkv"
            segment.write_bytes(b"truncated")
            with patch("screen_recorder.capture.shutil.which", return_value="/usr/bin/ffprobe"), \
                    patch(
                        "screen_recorder.capture.subprocess.run",
                        side_effect=[
                            Mock(returncode=0, stdout="120.0\n", stderr=""),
                            Mock(returncode=0, stdout="", stderr="truncated packet"),
                        ],
                    ) as run:
                from screen_recorder.capture import _segment_is_readable

                self.assertFalse(_segment_is_readable("ffmpeg", segment, last_segment=True))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_last_segment_decode_timeout_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            segment = Path(directory) / "segment.mkv"
            segment.write_bytes(b"maybe good")
            with patch("screen_recorder.capture.shutil.which", return_value="/usr/bin/ffprobe"), \
                    patch(
                        "screen_recorder.capture.subprocess.run",
                        side_effect=[
                            Mock(returncode=0, stdout="120.0\n", stderr=""),
                            subprocess.TimeoutExpired("ffmpeg", 120),
                        ],
                    ):
                from screen_recorder.capture import _segment_is_readable

                self.assertIsNone(_segment_is_readable("ffmpeg", segment, last_segment=True))

    def test_corrupt_middle_segment_aborts_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            segments = [segment_dir / f"segment-{index:03d}.mkv" for index in range(1, 4)]
            for segment in segments:
                segment.write_bytes(b"data")
            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", side_effect=[True, False]), \
                    patch("screen_recorder.capture.subprocess.run") as run:
                with self.assertRaisesRegex(CaptureError, "corrupt"):
                    recover_orphaned_recording(segment_dir, root, "mkv", "High")
                run.assert_not_called()
            self.assertTrue(all(segment.exists() for segment in segments))

    def test_output_verification_failure_preserves_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            segment = segment_dir / "segment-001.mkv"
            segment.write_bytes(b"data")

            def run_concat(args, **_kwargs):
                Path(args[-1]).write_bytes(b"output")
                return Mock(returncode=0, stderr="")

            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", return_value=True), \
                    patch("screen_recorder.capture._segments_have_audio", return_value=False), \
                    patch("screen_recorder.capture._verify_recovered_output", return_value=False), \
                    patch("screen_recorder.capture.subprocess.run", side_effect=run_concat):
                with self.assertRaisesRegex(CaptureError, "could not be verified"):
                    recover_orphaned_recording(segment_dir, root, "mkv", "High")
            self.assertTrue(segment.exists())
            self.assertTrue(segment_dir.exists())

    def test_webm_recovery_preserves_audio_codec_when_audio_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segment_dir = root / ".crash.segments-1"
            segment_dir.mkdir()
            (segment_dir / "segment-001.mkv").write_bytes(b"data")

            def run_probe_and_concat(args, **_kwargs):
                if "-select_streams" in args:
                    return Mock(returncode=0, stdout="audio\n", stderr="")
                if "-f" in args and "concat" in args:
                    self.assertIn("-c:a", args)
                    self.assertIn("libopus", args)
                    Path(args[-1]).write_bytes(b"output")
                    return Mock(returncode=0, stdout="", stderr="")
                return Mock(returncode=0, stdout="1.0\n", stderr="")

            with patch("screen_recorder.capture.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \
                    patch("screen_recorder.capture._segment_is_readable", return_value=True), \
                    patch("screen_recorder.capture.subprocess.run", side_effect=run_probe_and_concat):
                output = recover_orphaned_recording(segment_dir, root, "webm", "High")
            self.assertTrue(output.exists())

    def test_each_quality_preset(self):
        expected = {
            "High": ("-preset", "veryfast", "-crf", "20"),
            "Medium": ("-preset", "veryfast", "-crf", "25"),
            "Low": ("-preset", "ultrafast", "-crf", "30"),
        }
        for quality, flags in expected.items():
            with self.subTest(quality=quality):
                args = build_ffmpeg_args(
                    "ffmpeg", ":0", (0, 0, 1920, 1080), Path("output.mkv"),
                    30, quality, "", False, "",
                )
                for flag in flags:
                    self.assertIn(flag, args)
        webm_expected = {"High": "30", "Medium": "36", "Low": "42"}
        for quality, crf in webm_expected.items():
            with self.subTest(webm_quality=quality):
                args = build_ffmpeg_args(
                    "ffmpeg", ":0", (0, 0, 1920, 1080), Path("output.webm"),
                    30, quality, "", False, "",
                )
                self.assertEqual(args[args.index("-crf") + 1], crf)

    def test_audio_input_mapping(self):
        cases = (
            ("none", "", False, "", None),
            ("system only", "system.monitor", False, "", ["0:v:0", "1:a:0"]),
            ("microphone only", "", True, "mic", ["0:v:0", "1:a:0"]),
            ("both", "system.monitor", True, "mic", ["0:v:0", "[aout]"]),
        )
        for name, system, microphone, mic_source, expected_maps in cases:
            with self.subTest(name=name):
                args = build_ffmpeg_args(
                    "ffmpeg", ":0", (0, 0, 1920, 1080), Path("output.mkv"),
                    30, "High", system, microphone, mic_source,
                )
                actual_maps = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-map"]
                self.assertEqual(actual_maps, expected_maps or [])
                self.assertEqual("-filter_complex" in args, name == "both")

    def test_unique_path_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            first = unique_path(Path(directory), "png", "test")
            first.touch()
            second = unique_path(Path(directory), "png", "test")
            self.assertNotEqual(first, second)
            self.assertEqual(second.name, "test-1.png")

    def test_library_filters_supported_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.png").touch()
            (root / "video.mkv").touch()
            (root / "notes.txt").touch()
            self.assertEqual({p.suffix for p in captures([root])}, {".png", ".mkv"})

    def test_screenshot_saves_png_and_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for image_format, suffix in (("png", ".png"), ("jpg", ".jpg")):
                path = save_screenshot(root, image_format)
                self.assertEqual(path.suffix, suffix)
                self.assertGreater(path.stat().st_size, 0)

    def test_region_screenshot_crops_composited_desktop(self):
        screen = Mock()
        screen.geometry.return_value = QRect(-100, 0, 200, 100)
        screen.devicePixelRatio.return_value = 2
        desktop = QPixmap(400, 200)
        desktop.fill(QColor("green"))
        with tempfile.TemporaryDirectory() as directory, \
                patch("screen_recorder.capture.QGuiApplication.screens", return_value=[screen]), \
                patch("screen_recorder.capture.composite_screens", return_value=desktop):
            path = save_screenshot(Path(directory), "png", region=QRect(0, 10, 50, 25))
            cropped = QPixmap(str(path))
            self.assertEqual((cropped.width(), cropped.height()), (100, 50))

    def test_composite_screens_uses_virtual_positions_and_highest_scale(self):
        first_pixmap = QPixmap(100, 50)
        first_pixmap.fill(QColor("red"))
        second_pixmap = QPixmap(400, 200)
        second_pixmap.fill(QColor("blue"))
        first = Mock()
        first.geometry.return_value = QRect(-100, 20, 100, 50)
        first.devicePixelRatio.return_value = 1.0
        first.grabWindow.return_value = first_pixmap
        second = Mock()
        second.geometry.return_value = QRect(0, 0, 200, 100)
        second.devicePixelRatio.return_value = 2.0
        second.grabWindow.return_value = second_pixmap

        result = composite_screens([first, second])
        self.assertEqual((result.width(), result.height()), (600, 200))
        image = result.toImage()
        self.assertEqual(image.pixelColor(50, 100), QColor("red"))
        self.assertEqual(image.pixelColor(300, 50), QColor("blue"))

    def test_region_coordinates_scale_by_mixed_screen_density(self):
        left = Mock()
        left.geometry.return_value = QRect(0, 0, 1000, 800)
        left.devicePixelRatio.return_value = 1
        right = Mock()
        right.geometry.return_value = QRect(1000, 0, 1000, 800)
        right.devicePixelRatio.return_value = 2
        self.assertEqual(logical_rect_to_physical(QRect(20, 30, 101, 77), [left, right]), (20, 30, 100, 76))
        self.assertEqual(logical_rect_to_physical(QRect(1200, 50, 101, 77), [left, right]), (1400, 100, 202, 154))

    def test_region_coordinates_support_left_right_and_spanning_screen_layouts(self):
        left = Mock()
        left.geometry.return_value = QRect(-1920, 0, 1920, 1080)
        left.devicePixelRatio.return_value = 1
        right = Mock()
        right.geometry.return_value = QRect(0, 0, 1280, 720)
        right.devicePixelRatio.return_value = 2
        self.assertEqual(logical_rect_to_physical(QRect(-1800, 100, 100, 100), [left, right]), (-1800, 100, 100, 100))
        self.assertEqual(logical_rect_to_physical(QRect(100, 100, 100, 100), [left, right]), (200, 200, 200, 200))
        self.assertEqual(logical_rect_to_physical(QRect(-100, 100, 200, 100), [left, right]), (1720, 200, 400, 200))

    def test_region_physical_dimensions_have_a_minimum_of_16_pixels(self):
        screen = Mock()
        screen.geometry.return_value = QRect(0, 0, 1280, 720)
        screen.devicePixelRatio.return_value = 1
        self.assertEqual(logical_rect_to_physical(QRect(4, 6, 1, 2), [screen]), (4, 6, 16, 16))

    def test_recording_uses_selected_region_geometry(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = Mock()
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

        screen = Mock()
        screen.virtualGeometry.return_value = QRect(0, 0, 1280, 720)
        screen.devicePixelRatio.return_value = 1
        region_screen = Mock()
        region_screen.geometry.return_value = QRect(0, 0, 1280, 720)
        region_screen.devicePixelRatio.return_value = 2
        region = QRect(500, 200, 321, 241)

        recorded_args = []

        def fake_popen(args, **_kwargs):
            recorded_args.append(args)
            Path(args[-1]).write_bytes(b"segment")
            return FakeProcess()

        def fake_concat(args, **_kwargs):
            Path(args[-1]).write_bytes(b"final")
            return Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"DISPLAY": ":test", "XDG_SESSION_TYPE": "x11"}), \
                patch("screen_recorder.capture.shutil.which", return_value="/usr/bin/ffmpeg"), \
                patch("screen_recorder.capture.QGuiApplication.primaryScreen", return_value=screen), \
                patch("screen_recorder.capture.QGuiApplication.screens", return_value=[region_screen]), \
                patch("screen_recorder.capture.subprocess.Popen", side_effect=fake_popen), \
                patch("screen_recorder.capture.subprocess.run") as run:
            run.side_effect = fake_concat
            recorder = Recorder()
            recorder.start(Path(directory) / "region.mkv", region=region)
            self.assertEqual(recorder._geometry, (1000, 400, 642, 482))
            recorder.pause()
            recorder.resume()
            recorder.stop()
            self.assertEqual(
                [args[args.index("-video_size") + 1] for args in recorded_args],
                ["642x482", "642x482"],
            )


if __name__ == "__main__":
    unittest.main()
