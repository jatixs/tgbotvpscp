"""Persistent node commands with capability-negotiated delivery."""
import json
import time
import uuid

from tortoise.transactions import in_transaction

from .models import Node, NodeOperation

TERMINAL_STATUSES = {"finished", "unknown", "failed", "legacy_sent"}
STATUSES = {"queued", "dispatched", "running"} | TERMINAL_STATUSES


async def enqueue(token_hash: str, task: dict, *, traffic_operation_id: int | None = None):
    node = await Node.get_or_none(token_hash=token_hash)
    if node:
        if traffic_operation_id is not None:
            if task.get("command") != "traffic" or not task.get("traffic_session"):
                raise ValueError("Only a traffic monitoring session can reuse an operation")
            async with in_transaction() as conn:
                operation = await NodeOperation.get_or_none(
                    id=traffic_operation_id, node_id=node.id, command="traffic",
                    requested_by=int(task.get("user_id") or 0),
                ).using_db(conn)
                if not operation or json.loads(operation.payload).get("traffic_session") != task["traffic_session"]:
                    raise ValueError("Traffic operation does not belong to this monitoring session")
                # Do not accumulate polls while the node is offline or a sample is in flight.
                if operation.status in TERMINAL_STATUSES:
                    operation.delivery_id = uuid.uuid4()
                    operation.status = "queued"
                    operation.updated_at = time.time()
                    await operation.save(update_fields=["delivery_id", "status", "updated_at"], using_db=conn)
                return operation
        return await NodeOperation.create(
            node_id=node.id, command=str(task.get("command", "")),
            requested_by=int(task.get("user_id") or 0), payload=json.dumps(task),
            created_at=time.time(),
        )


async def exchange(node_id: int, reports: list, *, reliable: bool, busy: bool):
    """Persist acknowledgements before returning commands. Legacy nodes remain supported."""
    notifications = []
    acknowledged = []
    async with in_transaction() as conn:
        node = await Node.get(id=node_id).using_db(conn)
        # Import queued commands from installations predating the operation table.
        for task in node.tasks or []:
            await NodeOperation.create(
                node_id=node_id, command=str(task.get("command", "")),
                requested_by=int(task.get("user_id") or 0), payload=json.dumps(task),
                created_at=time.time(), using_db=conn,
            )
        if node.tasks:
            node.tasks = []
            await node.save(update_fields=["tasks"], using_db=conn)
        if reliable:
            for report in reports[:100]:
                if not isinstance(report, dict) or not isinstance(report.get("id"), str):
                    continue
                try:
                    delivery_id = uuid.UUID(report["id"])
                except ValueError:
                    continue
                status = report.get("status")
                if not isinstance(status, str) or status not in {"running", "finished", "unknown", "failed"}:
                    continue
                operation = await NodeOperation.get_or_none(delivery_id=delivery_id, node_id=node_id).using_db(conn)
                if not operation:
                    # A reused traffic row no longer carries the preceding sample's UUID.
                    # Acknowledge stale terminal receipts so a lost ack cannot fill the node's outbox.
                    if status in TERMINAL_STATUSES and not await NodeOperation.filter(delivery_id=delivery_id).using_db(conn).exists():
                        acknowledged.append(delivery_id.hex)
                    continue
                if status in TERMINAL_STATUSES:
                    acknowledged.append(operation.delivery_id.hex)
                if operation.status in TERMINAL_STATUSES:
                    continue
                operation.status = status
                operation.updated_at = time.time()
                result = report.get("result")
                if result is not None:
                    operation.result = json.dumps(result)
                await operation.save(using_db=conn)
                if status in {"finished", "failed"} and result is not None:
                    notice = {"user_id": operation.requested_by, "command": operation.command, "result": result}
                    session = json.loads(operation.payload).get("traffic_session")
                    if operation.command == "traffic" and session:
                        notice["traffic_session"] = session
                    notifications.append(notice)
        if busy:
            return [], notifications, acknowledged
        # A downgraded client must never repeat commands already sent via the reliable protocol.
        statuses = ["queued", "dispatched"] if reliable else ["queued"]
        jobs = await NodeOperation.filter(node_id=node_id, status__in=statuses).using_db(conn).order_by("id").limit(20)
        tasks = []
        for job in jobs:
            task = json.loads(job.payload)
            if reliable:
                task["operation_id"] = job.delivery_id.hex
                if job.status == "queued":
                    job.status = "dispatched"
                    job.updated_at = time.time()
                    await job.save(update_fields=["status", "updated_at"], using_db=conn)
            else:
                job.status = "legacy_sent"
                job.updated_at = time.time()
                await job.save(update_fields=["status", "updated_at"], using_db=conn)
            tasks.append(task)
        return tasks, notifications, acknowledged


ALLOWED_PER_PAGE = [10, 20, 30, 50, 100]
DEFAULT_PER_PAGE = 20


def get_page_numbers(current_page: int, total_pages: int) -> list:
    """Returns a list of page numbers and None for ellipsis (...)."""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    if current_page <= 4:
        return [*range(1, 6), None, total_pages]
    if current_page >= total_pages - 3:
        return [1, None, *range(total_pages - 4, total_pages + 1)]
    return [1, None, current_page - 1, current_page, current_page + 1, None, total_pages]


def parse_filters(query):
    before = int(query.get("before", "0"))
    node_id = int(query.get("node_id", "0"))
    status = query.get("status", "")
    page = int(query.get("page", "1"))
    per_page = int(query.get("per_page", str(DEFAULT_PER_PAGE)))

    if page < 1 or page > 1000000:
        page = 1
    if per_page not in ALLOWED_PER_PAGE:
        if 10 <= per_page <= 100:
            pass
        else:
            per_page = DEFAULT_PER_PAGE

    if not 0 <= before < 2**63 or not 0 <= node_id < 2**63 or (status and status not in STATUSES):
        raise ValueError("Invalid filter")
    return {"before": before, "node_id": node_id, "status": status, "page": page, "per_page": per_page}


async def history(*, before=0, node_id=0, status="", page=None, per_page=None):
    if page is None and per_page is None:
        limit = 50
        query = NodeOperation.all()
        if before:
            query = query.filter(id__lt=before)
        if node_id:
            query = query.filter(node_id=node_id)
        if status:
            query = query.filter(status=status)
        rows = await query.order_by("-id").limit(limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        return rows, (rows[-1].id if more else None)

    page = page or 1
    per_page = per_page or DEFAULT_PER_PAGE
    query = NodeOperation.all()
    if node_id:
        query = query.filter(node_id=node_id)
    if status:
        query = query.filter(status=status)
    if before:
        query = query.filter(id__lt=before)

    total_count = await query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page) if total_count > 0 else 1

    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    offset = (page - 1) * per_page
    rows = await query.order_by("-id").offset(offset).limit(per_page)

    start_index = offset + 1 if total_count > 0 else 0
    end_index = min(offset + per_page, total_count)
    next_before = rows[-1].id if (len(rows) >= per_page and offset + per_page < total_count) else None

    pagination = {
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "start_index": start_index,
        "end_index": end_index,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "page_numbers": get_page_numbers(page, total_pages),
        "allowed_per_page": ALLOWED_PER_PAGE,
        "next_before": next_before,
    }
    return rows, pagination
