import tempfile
import unittest
from pathlib import Path

from scripts.tls_finalize import read_env, update_env


class TLSFinalizeTests(unittest.TestCase):
    def test_update_env_preserves_unrelated_settings_and_removes_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                'TG_BOT_TOKEN="keep-me"\nLEGACY_NODE_BRIDGE="true"\nLEGACY_NODE_BRIDGE="true"\n',
                encoding="utf-8",
            )

            update_env(env_file, {"LEGACY_NODE_BRIDGE": "false", "WEB_SERVER_HOST": "127.0.0.1"})

            lines = env_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines.count('LEGACY_NODE_BRIDGE="false"'), 1)
            self.assertEqual(lines.count('WEB_SERVER_HOST="127.0.0.1"'), 1)
            self.assertIn('TG_BOT_TOKEN="keep-me"', lines)
            self.assertEqual(read_env(env_file)[1]["LEGACY_NODE_BRIDGE"], "false")


if __name__ == "__main__":
    unittest.main()