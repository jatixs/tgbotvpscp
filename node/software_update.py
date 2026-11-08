"""Apply a confirmed client revision to a systemd-managed node."""
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

REPOSITORY = "https://github.com/jatixs/tgbotvpscp.git"
SERVICE = "tg-node.service"
COMMIT = re.compile(r"[0-9a-f]{40}")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,255}")


class ClientUpdater:
    def __init__(self, root: str):
        self.root = Path(root)
        self.commit = ""
        self.supported = False
        self.failed = None
        self.worker = None
        self.restarting = False
        self.lock = threading.Lock()
        if not (self.root / ".git").is_dir():
            return
        try:
            self.commit = self._git("rev-parse", "HEAD").decode().strip()
            if not COMMIT.fullmatch(self.commit) or not hasattr(os, "geteuid") or os.geteuid() != 0:
                return
            main_pid = self._run("systemctl", "show", "--property=MainPID", "--value", SERVICE)
            self.supported = main_pid.decode().strip() == str(os.getpid())
        except (OSError, subprocess.SubprocessError):
            logging.debug("Node client updates are unavailable", exc_info=True)

    def _run(self, *args, timeout=30):
        return subprocess.run(
            args, cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=timeout, check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        ).stdout

    def _git(self, *args, timeout=30):
        return self._run("git", *args, timeout=timeout)

    def report(self):
        return {
            "commit": self.commit,
            "supported": self.supported,
            "failed": self.failed,
            "busy": self.restarting or bool(self.worker and self.worker.is_alive()),
        }

    def offer(self, job):
        if not self.supported or not isinstance(job, dict):
            return
        job_id, branch, commit, expires = (job.get(key) for key in ("id", "branch", "commit", "expires_at"))
        if type(job_id) is not int or job_id <= 0 or not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            return
        if not isinstance(branch, str) or not BRANCH.fullmatch(branch):
            return
        if type(expires) not in (int, float) or not expires > time.time():
            return
        with self.lock:
            if self.restarting or job_id == self.failed or commit == self.commit or (self.worker and self.worker.is_alive()):
                return
            self.worker = threading.Thread(target=self._update, args=(job_id, branch, commit, expires), daemon=True)
            self.worker.start()

    def _update(self, job_id: int, branch: str, commit: str, expires: float):
        try:
            if self._git("status", "--porcelain", "--untracked-files=no"):
                raise RuntimeError("The node checkout has local changes")
            ref = f"refs/heads/{branch}"
            self._git("check-ref-format", ref)
            self._git("fetch", "--no-tags", "--no-recurse-submodules", "--depth=32", REPOSITORY, ref, timeout=240)
            self._git("merge-base", "--is-ancestor", commit, "FETCH_HEAD")
            for file in ("node/node.py", "node/software_update.py", "node/endpoint_migration.py", "network_validation.py"):
                compile(self._git("show", f"{commit}:{file}"), file, "exec")
            if time.time() >= expires:
                return
            if self._git("rev-parse", "HEAD").decode().strip() != self.commit:
                raise RuntimeError("The node revision changed during the update")
            if self._git("status", "--porcelain", "--untracked-files=no"):
                raise RuntimeError("The node checkout changed during the update")
            self._git("checkout", "--detach", "--no-overwrite-ignore", commit)
            try:
                self.restarting = True
                self._run("systemctl", "--no-block", "restart", SERVICE)
            except (OSError, subprocess.SubprocessError):
                self.restarting = False
                self._git("checkout", "--detach", "--no-overwrite-ignore", self.commit)
                raise
        except Exception:
            logging.exception("Node client update %s failed", job_id)
            self.failed = job_id
