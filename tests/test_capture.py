import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from screen_recorder.capture import (
    CaptureError, Recorder, build_ffmpeg_args, concat_list_content, save_screenshot, unique_path,
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
                self.assertEqual("-movflags" in args, suffix == "mp4")
                if suffix == "mp4":
                    self.assertEqual(args[args.index("-movflags") + 1], "+frag_keyframe+empty_moov")

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


if __name__ == "__main__":
    unittest.main()
