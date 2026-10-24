import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from term_fixer import fix_text

ROOT = Path(__file__).resolve().parents[1]


class DictationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = os.path.join(self.temp_dir.name, "history")
        self.warnings = []

    def make_history(self, enabled: bool = True) -> main.DictationHistory:
        history = main.DictationHistory(
            self.directory,
            enabled=enabled,
            on_warning=self.warnings.append,
        )
        self.addCleanup(history.close)
        return history

    def test_disabled_history_creates_nothing(self):
        history = self.make_history(enabled=False)
        history.record("Сырой текст", "Итоговый текст ")
        history.close()

        self.assertFalse(os.path.exists(self.directory))
        self.assertIsNone(history.path)
        self.assertEqual(self.warnings, [])

    def test_jsonl_records_and_flush(self):
        history = self.make_history()
        soda_one = "Запусти докер кампоуз Up."
        final_one = fix_text(main.process_text(soda_one)) + " "
        soda_two = "Питон - это змея."
        final_two = soda_two + " "

        history.record(soda_one, final_one)
        history.record(soda_two, final_two)

        with open(history.path, encoding="utf-8") as file:
            content = file.read()
        self.assertIn("Запусти", content)
        self.assertNotIn("\\u0417", content)
        records = [json.loads(line) for line in content.splitlines()]

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["type"], "session_start")
        self.assertEqual(records[0]["pid"], os.getpid())
        self.assertTrue(records[0]["timestamp"])
        self.assertEqual(records[1]["type"], "segment")
        self.assertEqual(records[1]["soda"], soda_one)
        self.assertEqual(records[1]["final"], final_one)
        self.assertEqual(records[1]["final"], "Запусти docker compose up. ")
        self.assertEqual(records[2]["soda"], soda_two)
        self.assertEqual(records[2]["final"], final_two)

        history.close()
        history.close()
        self.assertFalse(history.enabled)

    def test_each_instance_creates_new_session(self):
        first = self.make_history()
        second = self.make_history()
        first.record("Первый", "Первый ")
        second.record("Второй", "Второй ")
        first.close()
        second.close()

        self.assertNotEqual(first.path, second.path)
        files = list(Path(self.directory).glob("session-*.jsonl"))
        self.assertEqual(len(files), 2)

    def test_create_failure_warns_once_and_disables(self):
        with mock.patch.object(
            main.tempfile,
            "NamedTemporaryFile",
            side_effect=OSError("disk full"),
        ):
            history = self.make_history()

        history.record("Текст", "Текст ")
        history.close()

        self.assertFalse(history.enabled)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("disk full", self.warnings[0])

    def test_write_failure_warns_once_and_disables(self):
        failing_file = mock.Mock()
        failing_file.name = os.path.join(self.directory, "session-test.jsonl")
        failing_file.write.side_effect = [None, OSError("disk full")]
        with mock.patch.object(
            main.tempfile,
            "NamedTemporaryFile",
            return_value=failing_file,
        ):
            history = self.make_history()

        history.record("Текст", "Текст ")
        history.record("Ещё текст", "Ещё текст ")

        self.assertFalse(history.enabled)
        self.assertEqual(failing_file.write.call_count, 2)
        failing_file.close.assert_called_once_with()
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("disk full", self.warnings[0])

    def test_main_logs_same_text_it_pastes(self):
        gasr = mock.Mock()
        gasr.poll.return_value = 0
        gasr_out = mock.Mock()
        gasr_out.readline.side_effect = [
            "* неполный\r* Запусти докер кампоуз Up.\n",
            "",
        ]

        def cleanup_main_history():
            if main._history is not None:
                main._history.close()
            main._history = None

        self.addCleanup(cleanup_main_history)
        main._history = None
        with (
            mock.patch.object(main, "_parse_args", return_value=mock.Mock(no_history=False)),
            mock.patch.object(main, "HISTORY_DIR", self.directory),
            mock.patch.object(main, "PID_FILE", os.path.join(self.temp_dir.name, "test.pid")),
            mock.patch.object(main, "GASR_PY", "/unused/gasr.py"),
            mock.patch.object(main.os.path, "isfile", return_value=True),
            mock.patch.object(main.subprocess, "run", return_value=mock.Mock(returncode=0)),
            mock.patch.object(main.signal, "signal"),
            mock.patch.object(main.sys, "stdout", mock.Mock()),
            mock.patch.object(main, "_start_pipeline", return_value=(gasr, gasr_out)),
            mock.patch.object(main, "_watch_stderr"),
            mock.patch.object(main, "paste_text") as paste_mock,
        ):
            main.main()

        paste_mock.assert_called_once_with("Запусти docker compose up. ")
        history_path = main._history.path
        main._history.close()
        with open(history_path, encoding="utf-8") as file:
            records = [json.loads(line) for line in file]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["soda"], "Запусти докер кампоуз Up.")
        self.assertEqual(records[1]["final"], "Запусти docker compose up. ")

    def test_no_history_argument(self):
        with mock.patch.object(sys, "argv", ["main.py"]):
            self.assertFalse(main._parse_args().no_history)
        with mock.patch.object(sys, "argv", ["main.py", "--no-history"]):
            self.assertTrue(main._parse_args().no_history)

    def test_help_exits_before_pipeline(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--help"],
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
            cwd=ROOT / "tests",
        )
        self.assertIn("--no-history", result.stdout)


if __name__ == "__main__":
    unittest.main()
