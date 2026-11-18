import os
import re
import shutil
import asyncio
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
if not BASH and os.name == "nt":
    candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
    if candidate.is_file():
        BASH = str(candidate)


@unittest.skipUnless(BASH, "Bash is required for installer checks")
class InstallerCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def run_cleanup(self, root, program, saved):
        process = await asyncio.create_subprocess_exec(
            BASH, "-c", program, cwd=root,
            env={**os.environ, "BOT_INSTALL_PATH": root.as_posix()},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise
        self.assertEqual(process.returncode, 0, stdout.decode(errors="replace") + stderr.decode(errors="replace"))
        for path in saved:
            self.assertEqual(path.read_text(encoding="utf-8"), "preserve")

    async def test_node_cleanup_preserves_operation_journal_and_sqlite_sidecars(self):
        for script in ("deploy.sh", "deploy_en.sh"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                (root / ".git").mkdir()
                config_dir = root / "config"
                config_dir.mkdir()
                saved = [config_dir / f"operations-test.db{suffix}" for suffix in ("", "-wal", "-shm", "-journal")]
                for path in saved:
                    path.write_text("preserve", encoding="utf-8")
                trash = config_dir / "unused.json"
                trash.write_text("remove", encoding="utf-8")
                source = (ROOT / script).read_text(encoding="utf-8")
                function = re.search(r"^cleanup_for_node\(\) \{\n.*?^\}", source, re.M | re.S)
                self.assertIsNotNone(function)
                program = 'set -e\nsudo() { "$@"; }\nmsg_info() { :; }\n' + function.group() + '\ncleanup_for_node test\n'
                # Only a repository-defined function executes in a disposable directory; no external input.
                await self.run_cleanup(root, program, saved)
                self.assertFalse(trash.exists())

    async def test_both_installers_preserve_backup_contents_during_cleanup(self):
        for script in ("deploy.sh", "deploy_en.sh"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                saved = []
                for folder in (".backups/pre_update_test", ".backup"):
                    for name in ("local.py", "__pycache__/local.pyc"):
                        path = root / folder / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("preserve", encoding="utf-8")
                        saved.append(path)
                (root / "docs").mkdir()
                (root / "__pycache__").mkdir()
                source = (ROOT / script).read_text(encoding="utf-8")
                function = re.search(r"^cleanup_common_trash\(\) \{\n.*?^\}", source, re.M | re.S)
                self.assertIsNotNone(function)
                # Execute only the cleanup function against this disposable root.
                # No installer entry point, sudo privilege or real installation.
                program = 'set -e\nsudo() { "$@"; }\n' + function.group() + '\ncleanup_common_trash\n'
                await self.run_cleanup(root, program, saved)
                self.assertFalse((root / "docs").exists())
                self.assertFalse((root / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
