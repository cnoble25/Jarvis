"""Spoken values must never break out of a command template's quoting."""
import subprocess
import unittest

from daemon.tools.execution_engine import interpolate_shell_template as fill


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


class TestTemplateEscaping(unittest.TestCase):
    def test_single_quoted_placeholder_keeps_apostrophes(self):
        self.assertEqual(run(fill("echo '{q}'", {"q": "Don't Stop Me Now"})), "Don't Stop Me Now")

    def test_double_quoted_placeholder_is_literal(self):
        self.assertEqual(run(fill('echo "{q}"', {"q": 'say "hi" $HOME `id`'})), 'say "hi" $HOME `id`')

    def test_bare_placeholder_cannot_inject(self):
        self.assertEqual(run(fill("echo {q}", {"q": "a; echo INJECTED #"})), "a; echo INJECTED #")

    def test_existing_quoted_templates_render_unchanged(self):
        self.assertEqual(fill("gtk-launch '{app_name}'", {"app_name": "VS Code"}), "gtk-launch 'VS Code'")

    def test_unknown_placeholders_are_left_for_the_caller(self):
        self.assertEqual(fill("echo {q} {missing}", {"q": "x"}), "echo x {missing}")


if __name__ == "__main__":
    unittest.main()
