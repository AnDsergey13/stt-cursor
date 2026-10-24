#!/usr/bin/env python3
"""Детерминированное восстановление IT-терминов после распознавания."""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MAP_PATH = BASE_DIR / "terms_map.json"


@dataclass(frozen=True)
class _Rule:
    canonical: str
    pattern: re.Pattern
    anchors: tuple[re.Pattern, ...]
    veto: tuple[re.Pattern, ...]


def _phrase_pattern(phrase: str) -> re.Pattern:
    if not phrase:
        raise ValueError("Фразы в словаре терминов не должны быть пустыми")
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)


def _load_rules(path: Path) -> tuple[_Rule, ...]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    indexed_rules = []
    for item in data["rules"]:
        canonical = item["canonical"]
        variants = item["variants"]
        if not isinstance(variants, list) or not variants:
            raise ValueError(f"Пустой список variants в правиле {canonical!r}")
        anchors = tuple(_phrase_pattern(phrase) for phrase in item.get("anchors", []))
        veto = tuple(_phrase_pattern(phrase) for phrase in item.get("veto", []))
        for variant in variants:
            rule = _Rule(canonical, _phrase_pattern(variant), anchors, veto)
            indexed_rules.append((len(variant), rule))

    indexed_rules.sort(key=lambda indexed: indexed[0], reverse=True)
    return tuple(rule for _, rule in indexed_rules)


_DEFAULT_RULES = _load_rules(DEFAULT_MAP_PATH)


def _is_sentence_start(text: str, start: int) -> bool:
    prefix = text[:start].rstrip(" \t")
    return not prefix or prefix.endswith((".", "!", "?", "…", "\n"))


def _apply_rule(text: str, rule: _Rule) -> str:
    if any(pattern.search(text) for pattern in rule.veto):
        return text
    if rule.anchors and not any(pattern.search(text) for pattern in rule.anchors):
        return text

    def replace(match: re.Match) -> str:
        canonical = rule.canonical
        if match.group(0)[:1].isupper() and _is_sentence_start(text, match.start()):
            return canonical[:1].upper() + canonical[1:]
        return canonical

    return rule.pattern.sub(replace, text)


def fix_text(text: str, dictionary_path: str | None = None) -> str:
    """Исправить термины по точным фразам, якорям и вето из словаря."""
    rules = _DEFAULT_RULES if dictionary_path is None else _load_rules(Path(dictionary_path))
    for rule in rules:
        text = _apply_rule(text, rule)
    return text


def main() -> None:
    """Применить исправления к каждой строке stdin."""
    for line in sys.stdin:
        sys.stdout.write(fix_text(line))


if __name__ == "__main__":
    main()
