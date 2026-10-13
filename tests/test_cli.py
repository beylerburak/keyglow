import os
import tempfile
import unittest

from keyglow import cli, settings
from keyglow.settings import Settings


class LatestUserSettingsTest(unittest.TestCase):
    def _home(self, root, name, s, mtime):
        home = os.path.join(root, name)
        path = os.path.join(home, ".config", "keyglow", "settings.json")
        settings.save(s, path)
        os.utime(path, (mtime, mtime))
        return home

    def test_newest_wins(self):
        with tempfile.TemporaryDirectory() as root:
            old = self._home(root, "ada", Settings(effect="static", color="#ff0000"), 1000)
            new = self._home(root, "bob", Settings(effect="rainbow"), 2000)
            empty = os.path.join(root, "carol")
            os.makedirs(empty)
            self.assertEqual(cli.latest_user_settings([old, new, empty]).effect, "rainbow")

    def test_nobody(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(cli.latest_user_settings([root, os.path.join(root, "missing")]))


if __name__ == "__main__":
    unittest.main()
