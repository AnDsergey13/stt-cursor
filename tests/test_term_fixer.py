import subprocess
import sys
import unittest
from pathlib import Path

from main import process_text
from term_fixer import fix_text

ROOT = Path(__file__).resolve().parents[1]

FIXTURES = [
    (1, "Запусти докер кампоуз Up.", "Запусти docker compose up."),
    (2, "Запусти докер кампоусаб.", "Запусти docker compose up."),
    (3, "Открой репозитории и сделай комит.", "Открой репозитории и сделай commit."),
    (4, "Провери логи инженекс и перезапусти System D Unit.", "Провери логи nginx и перезапусти systemd unit."),
    (5, "Проверил логин genix и перезапусти System de Unit.", "Проверил логин nginx и перезапусти systemd unit."),
    (6, "Напиши функцию на Python с осинка вейт.", "Напиши функцию на python с async await."),
    (7, "Напиши функцию на пальтон с осинка вейт.", "Напиши функцию на python с async await."),
    (8, "Напиши функцию на pythonka wait.", "Напиши функцию на python с async await."),
    (9, "Обнови пакеты через пакман и яй.", "Обнови пакеты через pacman и yay."),
    (10, "Подними экзит бокс и проверить quid proxy.", "Подними exitbox и проверить squid proxy."),
    (11, "Запусти докер компост.", "Запусти docker compose."),
    (12, "Запусти докер компоус.", "Запусти docker compose."),
    (13, "Сегодня хорошая погода Я иду домой.", "Сегодня хорошая погода Я иду домой."),
    (14, "Питон - это змея, а сода стоит на кухонной полке.", "Питон - это змея, а сода стоит на кухонной полке."),
    (15, "Дока комит.", "Дока commit."),
    (16, "Run docker compose app,", "Run docker compose up,"),
    (17, "Deploy exitbox Squid proxy Wireguard and huggingface Annex.", "Deploy exitbox Squid proxy Wireguard and huggingface onnx."),
]


class TermFixerTests(unittest.TestCase):
    def test_acceptance_fixtures(self):
        for number, source, expected in FIXTURES:
            with self.subTest(fixture=number):
                self.assertEqual(fix_text(source), expected)

    def test_idempotence(self):
        for number, source, _ in FIXTURES:
            with self.subTest(fixture=number):
                fixed = fix_text(source)
                self.assertEqual(fix_text(fixed), fixed)

    def test_canonical_latin_unchanged(self):
        source = (
            "Уже верно: docker compose, commit, nginx, systemd unit, python, "
            "async await, pacman, yay, exitbox, squid proxy, onnx, huggingface."
        )
        self.assertEqual(fix_text(source), source)

    def test_remaining_docker_variants(self):
        for variant in ("компас", "компаузап"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    fix_text(f"Запусти докер {variant}."),
                    "Запусти docker compose.",
                )
        self.assertEqual(fix_text("Сделай коммит."), "Сделай commit.")

    def test_remaining_systemd_variant(self):
        self.assertEqual(
            fix_text("Перезапусти System Di Unit."),
            "Перезапусти systemd unit.",
        )

    def test_huggingface_variants(self):
        for variant in ("hugging face", "heightened face"):
            with self.subTest(variant=variant):
                self.assertEqual(fix_text(f"Deploy {variant}."), "Deploy huggingface.")

    def test_onnx_variants_require_huggingface(self):
        for variant in ("Annex", "Onyx", "unks", "songs", "onks"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    fix_text(f"Load huggingface {variant}."),
                    "Load huggingface onnx.",
                )
                self.assertEqual(fix_text(f"Load {variant}."), f"Load {variant}.")

    def test_false_positive_controls(self):
        controls = (
            "Компост стоит в саду.",
            "Скажи яй вслух.",
            "Подожди wait перед продолжением.",
            "Сода стоит на кухонной полке.",
            "Дока остаётся без изменений.",
            "В комитете обсудили яйца.",
        )
        for source in controls:
            with self.subTest(source=source):
                self.assertEqual(fix_text(source), source)

    def test_yay_requires_package_context(self):
        self.assertEqual(fix_text("Обнови пакеты и яй."), "Обнови пакеты и yay.")

    def test_piton_requires_it_context(self):
        self.assertEqual(
            fix_text("Напиши функцию на питон."),
            "Напиши функцию на python.",
        )
        self.assertEqual(fix_text("Питон бывает разных размеров."), "Питон бывает разных размеров.")

    def test_animal_veto_overrides_it_anchor(self):
        for word in ("змея", "рептилия", "террариум", "усы"):
            with self.subTest(word=word):
                source = f"Питон в коде: {word}."
                self.assertEqual(fix_text(source), source)

    def test_sentence_start_case(self):
        self.assertEqual(fix_text("Python работает."), "Python работает.")
        self.assertEqual(fix_text("После точки. Python работает."), "После точки. Python работает.")
        self.assertEqual(fix_text("Использую Python в коде."), "Использую python в коде.")

    def test_voice_punctuation_then_terms(self):
        source = (
            "Запусти докер кампоуз точка с запятой новая строка "
            "Напиши функцию на пальтон с осинка вейт точка"
        )
        expected = (
            "Запусти docker compose; \n "
            "Напиши функцию на python с async await."
        )
        self.assertEqual(fix_text(process_text(source)), expected)

    def run_cli(self, source: str) -> str:
        result = subprocess.run(
            [sys.executable, str(ROOT / "term_fixer.py")],
            input=source,
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
            cwd=ROOT / "tests",
        )
        return result.stdout

    def test_cli_filter(self):
        self.assertEqual(
            self.run_cli("Запусти докер кампоуз Up.\n"),
            "Запусти docker compose up.\n",
        )

    def test_cli_multiline_and_final_line_without_newline(self):
        source = "Запусти докер компост.\nСегодня хорошая погода Я иду домой.\nДока комит."
        expected = "Запусти docker compose.\nСегодня хорошая погода Я иду домой.\nДока commit."
        self.assertEqual(self.run_cli(source), expected)


if __name__ == "__main__":
    unittest.main()
