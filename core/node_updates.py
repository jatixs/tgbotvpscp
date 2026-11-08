"""Confirmation and heartbeat delivery for node client updates."""
import asyncio
import re
import secrets
import time
from dataclasses import dataclass

from tortoise.transactions import in_transaction

from . import config
from .models import Node, NodeClientUpdate

COMMIT = re.compile(r"[0-9a-f]{40}")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,255}")
PLAN_TTL = 600
UPDATE_TTL = 1800
agent_update_lock = asyncio.Lock()
running_commit = ""


@dataclass(frozen=True)
class UpdatePlan:
    user_id: int
    branch: str
    nodes: tuple[int, ...]
    expires_at: float


_plans: dict[str, UpdatePlan] = {}


async def read_agent_commit() -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", config.BASE_DIR, "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        commit = stdout.decode().strip()
        if proc.returncode == 0 and COMMIT.fullmatch(commit):
            return commit
    except OSError:
        pass
    return ""


async def initialize():
    global running_commit
    running_commit = await read_agent_commit()


def normalize_report(report) -> dict:
    if not isinstance(report, dict):
        return {}
    commit = report.get("commit")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        return {}
    normalized = {
        "commit": commit,
        "supported": report.get("supported") is True,
        "busy": report.get("busy") is True,
    }
    failed = report.get("failed")
    if type(failed) is int and 0 < failed <= 2**31 - 1:
        normalized["failed"] = failed
    return normalized


def _is_eligible(node, now: float) -> bool:
    report = normalize_report((node.stats or {}).get("client_update"))
    return report.get("supported") is True and not report["busy"] and now - node.last_seen < config.NODE_OFFLINE_TIMEOUT


async def eligible_nodes():
    now = time.time()
    nodes = await Node.all().order_by("id")
    eligible = [{"id": node.id, "name": node.name} for node in nodes if _is_eligible(node, now)]
    return eligible, len(nodes) - len(eligible)


async def prepare(user_id: int, branch: str):
    eligible, skipped = await eligible_nodes()
    now = time.monotonic()
    for key, plan in list(_plans.items()):
        if plan.expires_at <= now or plan.user_id == user_id:
            del _plans[key]
    if not eligible:
        return {"nodes": [], "skipped": skipped}
    token = secrets.token_urlsafe(16)
    _plans[token] = UpdatePlan(user_id, branch, tuple(node["id"] for node in eligible), now + PLAN_TTL)
    return {"token": token, "nodes": eligible, "skipped": skipped}


def consume(token: str, user_id: int, branch: str | None = None) -> UpdatePlan | None:
    plan = _plans.get(token)
    if not plan or plan.user_id != user_id or plan.expires_at <= time.monotonic():
        return None
    if branch is not None and plan.branch != branch:
        return None
    return _plans.pop(token)


async def queue_updates(node_ids: tuple[int, ...], branch: str, commit: str, user_id: int) -> int:
    if not node_ids:
        return 0
    if not COMMIT.fullmatch(commit) or not BRANCH.fullmatch(branch):
        raise ValueError("Invalid node update revision")
    now = time.time()
    rollout = secrets.token_hex(16)
    async with in_transaction() as conn:
        nodes = await Node.filter(id__in=node_ids).using_db(conn)
        jobs = [
            NodeClientUpdate(
                node_id=node.id, rollout=rollout, requested_by=user_id, branch=branch, commit=commit,
                expires_at=now + UPDATE_TTL,
                status="current" if node.stats["client_update"]["commit"] == commit else "pending",
            )
            for node in nodes if _is_eligible(node, now)
        ]
        if jobs:
            await NodeClientUpdate.filter(
                node_id__in=[job.node_id for job in jobs], status="pending",
            ).using_db(conn).update(status="superseded")
            await NodeClientUpdate.bulk_create(jobs, using_db=conn)
    return sum(job.status == "pending" for job in jobs)


async def heartbeat_task(node_id: int, report: dict):
    if not running_commit or not report.get("supported"):
        return None, None
    job = await NodeClientUpdate.filter(
        node_id=node_id, commit=running_commit, status="pending", expires_at__gt=time.time(),
    ).order_by("-id").first()
    if not job:
        return None, None
    if report["commit"] == job.commit:
        status = "updated"
    elif report.get("failed") == job.id:
        status = "failed"
    else:
        return {"id": job.id, "branch": job.branch, "commit": job.commit, "expires_at": job.expires_at}, None
    changed = await NodeClientUpdate.filter(id=job.id, status="pending").update(status=status)
    return None, (job.requested_by, status) if changed else None


async def latest_results(user_id: int) -> list[dict]:
    latest = await NodeClientUpdate.filter(requested_by=user_id).order_by("-id").first()
    if not latest:
        return []
    now = time.time()
    jobs = await NodeClientUpdate.filter(rollout=latest.rollout).prefetch_related("node").order_by("node_id")
    return [
        {
            "name": job.node.name,
            "status": "expired" if job.status == "pending" and job.expires_at <= now else job.status,
        }
        for job in jobs
    ]
