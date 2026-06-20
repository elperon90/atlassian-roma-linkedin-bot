"""Test unitari per scripts/generate_post.py.

Non chiamano nessuna API reale: Anthropic, Telegram e Unsplash non vengono
mai contattati durante l'esecuzione di questi test.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_post as gp  # noqa: E402 (import dopo sys.path.insert, necessario)


class SlugifyTests(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(gp.slugify("Novità Atlassian!"), "novita-atlassian")

    def test_empty_falls_back_to_default(self) -> None:
        self.assertEqual(gp.slugify("***"), "post")


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_missing_required_vars_raises_config_error(self) -> None:
        for key in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(key, None)
        with self.assertRaises(gp.ConfigError):
            gp.load_config()

    def test_valid_config_is_loaded(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
        os.environ["TELEGRAM_CHAT_ID"] = "12345"
        os.environ.pop("UNSPLASH_ACCESS_KEY", None)

        config = gp.load_config()

        self.assertEqual(config.telegram_chat_id, "12345")
        self.assertIsNone(config.unsplash_access_key)


class ExtractTextTests(unittest.TestCase):
    def test_concatenates_text_blocks_and_ignores_tool_blocks(self) -> None:
        message = SimpleNamespace(
            content=[
                SimpleNamespace(type="server_tool_use", text=None),
                SimpleNamespace(type="text", text='{"a": 1}'),
            ]
        )
        self.assertEqual(gp.extract_text(message), '{"a": 1}')


class BuildUserMessageTests(unittest.TestCase):
    def test_mentions_recent_themes_to_avoid(self) -> None:
        message = gp.build_user_message(["novita", "guida"])
        self.assertIn("novita, guida", message)

    def test_handles_no_recent_themes(self) -> None:
        message = gp.build_user_message([])
        self.assertIn("nessuno (prima pubblicazione)", message)


class GetRecentThemesTests(unittest.TestCase):
    def test_reads_theme_front_matter(self) -> None:
        original_posts_dir = gp.POSTS_DIR
        tmp_dir = Path(__file__).resolve().parent / "_tmp_posts_for_test"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "2026-01-05-novita.md").write_text(
            "---\ndate: 2026-01-05\ntheme: novita\n---\n\ntesto", encoding="utf-8"
        )
        try:
            gp.POSTS_DIR = tmp_dir
            themes = gp.get_recent_themes(limit=4)
            self.assertEqual(themes, ["novita"])
        finally:
            gp.POSTS_DIR = original_posts_dir
            for f in tmp_dir.glob("*"):
                f.unlink()
            tmp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
