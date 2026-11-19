"""Run cache policy tests apart from legacy tests that replace aiohttp globally."""
import multiprocessing
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def _run_cache_scenarios():
    sys.argv = ["web_cache_scenarios.py", "-v"]
    runpy.run_path(str(ROOT / "tests" / "web_cache_scenarios.py"), run_name="__main__")


class CachePolicyIsolationTests(unittest.TestCase):
    def test_cache_policy_with_legacy_aiohttp_mocks(self):
        # Reproduce discovery pollution: only the child may import real aiohttp.
        with patch.dict(sys.modules, {"aiohttp": MagicMock(), "aiohttp.web": MagicMock()}):
            process = multiprocessing.get_context("spawn").Process(target=_run_cache_scenarios)
            process.start()
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                self.fail("Cache policy scenarios timed out")
            self.assertEqual(process.exitcode, 0, f"Cache policy scenarios exited with {process.exitcode}")


if __name__ == "__main__":
    unittest.main()
