"""Guard tokenization must preserve shlex decisions without per-character concatenation."""
import itertools
import shlex
import unittest

from gravityguard_engine.shell_tokens import split_command


class TestShellTokens(unittest.TestCase):
    def test_matches_legacy_tokenization(self):
        alphabet = ('a', ' ', '\t', '\n', '\r', "'", '"', '\\', '#', ';', '\v')
        for length in range(5):
            for parts in itertools.product(alphabet, repeat=length):
                command = ''.join(parts)
                try:
                    expected = shlex.split(command, posix=False)
                except ValueError:
                    expected = command.split()
                self.assertEqual(split_command(command), expected, repr(command))

    def test_long_quoted_arguments_and_windows_paths(self):
        command = 'python "' + 'x ' * 60_000 + '" C:\\tools\\check.py'
        self.assertEqual(split_command(command), shlex.split(command, posix=False))
