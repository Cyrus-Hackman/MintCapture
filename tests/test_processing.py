import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from screen_recorder.processing import (
    build_compress_args, build_gif_args, build_trim_args, parse_time_ms,
    progress_percent, validate_trim_times,
)
from screen_recorder.processing_dialog import ProcessingDialog

APP = QApplication.instance() or QApplication([])


class SignalStub:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        if self.callback:
            self.callback(*args)


class FakeProcess:
    ProcessChannelMode = QProcess.ProcessChannelMode
    ProcessState = QProcess.ProcessState
    ExitStatus = QProcess.ExitStatus

    def __init__(self, *_args):
        self.readyReadStandardOutput = SignalStub()
        self.readyReadStandardError = SignalStub()
        self.finished = SignalStub()
        self.errorOccurred = SignalStub()
        self.args = None
        self.running = False

    def setProcessChannelMode(self, _mode):
        pass

    def start(self, program, arguments):
        self.args = [program, *arguments]
        Path(arguments[-1]).write_bytes(b"partial")
        self.running = True

    def terminate(self):
        self.running = False
        self.finished.emit(1, QProcess.ExitStatus.NormalExit)

    def kill(self):
        self.running = False
        self.finished.emit(1, QProcess.ExitStatus.CrashExit)

    def state(self):
        return QProcess.ProcessState.Running if self.running else QProcess.ProcessState.NotRunning

    def readAllStandardError(self):
        return b""


class ProcessingTests(unittest.TestCase):
    def test_trim_builder_uses_input_seek_and_stream_copy(self):
        args = build_trim_args(
            "ffmpeg", Path("input.mkv"), Path("output.mkv"),
            "00:00:05.000", "00:00:10.000", True,
        )
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertLess(args.index("-i"), args.index("-t"))
        self.assertEqual(args[args.index("-t") + 1], "00:00:05.000")
        self.assertEqual(args[args.index("-c") + 1], "copy")
        self.assertEqual(args[-1], "output.mkv")

    def test_trim_builder_uses_reencode_compatibility_flags(self):
        args = build_trim_args(
            "ffmpeg", Path("input.mkv"), Path("output.mkv"),
            "00:00:05.000", "00:00:10.000", False, "Low",
        )
        self.assertIn("libx264", args)
        self.assertIn("ultrafast", args)
        self.assertIn("yuv420p", args)
        self.assertIn("scale=trunc(iw/2)*2:trunc(ih/2)*2", args)

    def test_gif_builder_uses_single_palette_filtergraph(self):
        args = build_gif_args(
            "ffmpeg", Path("input.mp4"), Path("output.gif"), "640", 15,
            "00:00:01.000", "00:00:04.000",
        )
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertLess(args.index("-i"), args.index("-t"))
        self.assertEqual(args[args.index("-t") + 1], "00:00:03.000")
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("fps=15,scale=640:-1:flags=lanczos,split", graph)
        self.assertIn("palettegen", graph)
        self.assertIn("paletteuse", graph)
        self.assertEqual(args[-1], "output.gif")

    def test_compress_builder_adds_even_scaling_pixel_format_and_codecs(self):
        for fmt, codec in (("mp4", "libx264"), ("webm", "libvpx-vp9")):
            with self.subTest(fmt=fmt):
                args = build_compress_args(
                    "ffmpeg", Path("input.mkv"), Path(f"out.{fmt}"), "Medium", fmt,
                )
                self.assertIn(codec, args)
                self.assertIn("yuv420p", args)
                self.assertIn("scale=trunc(iw/2)*2:trunc(ih/2)*2", args)

    def test_time_validation_and_duration_bound(self):
        self.assertEqual(parse_time_ms("00:00:01.5"), 1500)
        self.assertEqual(validate_trim_times("00:00:01.000", "00:00:05.000", 5), (1000, 5000))
        with self.assertRaisesRegex(ValueError, "later"):
            validate_trim_times("00:00:05.000", "00:00:05.000", None)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_trim_times("00:00:01.000", "00:00:06.000", 5)
        with self.assertRaises(ValueError):
            parse_time_ms("5 seconds")

    def test_progress_parser_converts_ffmpeg_microseconds(self):
        self.assertEqual(progress_percent("out_time_ms=5000000", 10), 50)
        self.assertIsNone(progress_percent("progress=continue", 10))
        self.assertEqual(progress_percent("out_time_ms=30000000", 10), 100)

    def test_process_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"source")
            existing = Path(directory) / "clip-trimmed.mp4"
            existing.write_bytes(b"old")
            with patch("screen_recorder.processing_dialog.video_duration", return_value="30"):
                dialog = ProcessingDialog(source)
                dialog.start_time.setText("00:00:01.000")
                dialog.end_time.setText("00:00:03.000")
                _args, output = dialog._build_command()
            self.assertNotEqual(output, existing)
            self.assertEqual(existing.read_bytes(), b"old")
            dialog.close()

    def test_cancel_terminates_process_and_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"source")
            with patch("screen_recorder.processing_dialog.video_duration", return_value="30"), \
                    patch("screen_recorder.processing_dialog.QProcess", FakeProcess):
                dialog = ProcessingDialog(source)
                dialog.start_time.setText("00:00:01.000")
                dialog.end_time.setText("00:00:03.000")
                dialog._start()
                output = dialog._output
                self.assertTrue(output.exists())
                dialog._cancel_or_close()
                self.assertFalse(output.exists())
                self.assertEqual(dialog.status.text(), "Cancelled")
                dialog.close()

    def test_processing_dialog_success_reenables_run_button(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"source")
            with patch("screen_recorder.processing_dialog.video_duration", return_value="30"), \
                    patch("screen_recorder.processing_dialog.QProcess", FakeProcess):
                dialog = ProcessingDialog(source)
                dialog.start_time.setText("00:00:01.000")
                dialog.end_time.setText("00:00:03.000")
                dialog._start()
                self.assertFalse(dialog.run_button.isEnabled())
                # Simulate successful completion
                dialog._finished(0, QProcess.ExitStatus.NormalExit)
                self.assertTrue(dialog.run_button.isEnabled())
                self.assertEqual(dialog.close_button.text(), "Close")
                dialog.close()

    def test_gif_builder_rejects_inverted_times(self):
        with self.assertRaisesRegex(ValueError, "End time must be later than start time"):
            build_gif_args(
                "ffmpeg", Path("input.mp4"), Path("output.gif"), "640", 15,
                "00:00:05.000", "00:00:02.000",
            )


if __name__ == "__main__":
    unittest.main()
