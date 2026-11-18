"""Run real SQLite/ORM tests in a fresh Python process, apart from legacy mocks."""
import multiprocessing
import runpy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_operations_scenarios():
    # A spawned interpreter uses the active Python environment without shell commands.
    sys.argv = ["operations_scenarios.py", "-v"]
    runpy.run_path(str(ROOT / "tests" / "operations_scenarios.py"), run_name="__main__")


class OperationIntegrationTests(unittest.TestCase):
    def test_operation_delivery_and_history(self):
        process = multiprocessing.get_context("spawn").Process(target=_run_operations_scenarios)
        process.start()
        process.join(timeout=90)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            self.fail("Operations integration scenarios timed out")
        self.assertEqual(process.exitcode, 0, f"Operations scenarios exited with {process.exitcode}")


if __name__ == "__main__":
    unittest.main()
