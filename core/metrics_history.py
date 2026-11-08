"""
Metrics history (CPU/RAM/disk/network) for the agent and nodes, powering time-range charts.

Raw samples live ~1 hour, 1-minute buckets last 24 hours, and 5-minute buckets
last 1 week. Network charts use the measured RX/TX peaks in each bucket.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any, Final

from tortoise.transactions import in_transaction

from .models import MetricSample, NetworkSample, PingSample

AGENT_SOURCE: Final[str] = "agent"

RES_RAW: Final[int] = 0
RES_MINUTE: Final[int] = 60
RES_FIVE_MIN: Final[int] = 300

# range key -> (span seconds, storage tier, output step seconds; 0 = raw points as-is)
RANGES: Final[dict[str, tuple[int, int, int]]] = {
    "3m": (3 * 60, RES_RAW, 0),
    "10m": (10 * 60, RES_RAW, 0),
    "30m": (30 * 60, RES_RAW, 0),
    "1h": (60 * 60, RES_RAW, 0),
    "3h": (3 * 3600, RES_MINUTE, 60),
    "6h": (6 * 3600, RES_MINUTE, 120),
    "12h": (12 * 3600, RES_MINUTE, 180),
    "1d": (24 * 3600, RES_FIVE_MIN, 300),
    "3d": (3 * 24 * 3600, RES_FIVE_MIN, 900),
    "7d": (7 * 24 * 3600, RES_FIVE_MIN, 1800),
}
DEFAULT_RANGE: Final[str] = "3m"

# How often the SSE stream pushes new points for each range (seconds).
STREAM_INTERVALS: Final[dict[str, int]] = {
    "3m": 3,
    "10m": 3,
    "30m": 5,
    "1h": 10,
    "3h": 30,
    "6h": 30,
    "12h": 60,
    "1d": 60,
    "3d": 120,
    "7d": 300,
}

RETENTION: Final[dict[int, int]] = {
    RES_RAW: 3600 + 10 * 60,
    RES_MINUTE: 24 * 3600 + 3600,
    RES_FIVE_MIN: 7 * 24 * 3600 + 2 * 3600,
}

FLUSH_INTERVAL: Final[int] = 10
AGGREGATE_INTERVAL: Final[int] = 60
RETENTION_INTERVAL: Final[int] = 600
# Aggregation windows are re-computed idempotently, so late samples are still folded in.
MINUTE_REBUILD_WINDOW: Final[int] = 3 * 60
FIVE_MIN_REBUILD_WINDOW: Final[int] = 15 * 60

_pending: list[dict[str, Any]] = []
_pending_network: list[NetworkSample] = []
_pending_ping: list[PingSample] = []
_last_counters: dict[str, tuple[float, float, float]] = {}
_last_interfaces: dict[str, tuple[float, dict[str, tuple[int, int]]]] = {}


def node_source(node_id: int) -> str:
    return f"node:{int(node_id)}"


def _rate_from_counters(source: str, now: float, rx_bytes: float, tx_bytes: float) -> tuple[float, float] | None:
    prev = _last_counters.get(source)
    _last_counters[source] = (now, rx_bytes, tx_bytes)
    if not prev:
        return None
    prev_t, prev_rx, prev_tx = prev
    dt = now - prev_t
    if dt <= 0 or dt > 120:
        return None
    if rx_bytes < prev_rx or tx_bytes < prev_tx:
        return 0.0, 0.0
    return (rx_bytes - prev_rx) / dt, (tx_bytes - prev_tx) / dt


def _record_interfaces(source: str, now: float, counters: Any) -> None:
    current = {}
    if isinstance(counters, dict):
        for name, pair in counters.items():
            if not isinstance(name, str) or not 0 < len(name) <= 128 or "\0" in name:
                continue
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(
                type(value) is int and 0 <= value < 2**64 for value in pair
            ):
                current[name] = tuple(pair)

    previous = _last_interfaces.pop(source, None)
    if current:
        _last_interfaces[source] = (now, current)
    if not previous:
        return
    previous_t, previous_counters = previous
    dt = now - previous_t
    if not 0 < dt <= 120:
        return

    for name, (rx, tx) in current.items():
        old = previous_counters.get(name)
        if old and rx >= old[0] and tx >= old[1]:
            _pending_network.append(NetworkSample(
                source=source, interface=name, res=RES_RAW, t=int(now),
                rx=(rx - old[0]) / dt, tx=(tx - old[1]) / dt,
            ))


def record_sample(
    source: str,
    *,
    cpu: float,
    ram: float,
    disk: float,
    rx_bytes: float | None = None,
    tx_bytes: float | None = None,
    rx_rate: float | None = None,
    tx_rate: float | None = None,
    interfaces: Any = None,
    ping: Any = None,
    t: float | None = None,
) -> None:
    """Queue a raw sample with total counters or rates and optional per-interface byte counters."""
    now = float(t if t is not None else time.time())
    try:
        latency = float(ping) if not isinstance(ping, bool) else None
    except (TypeError, ValueError):
        latency = None
    if latency is not None and (not math.isfinite(latency) or latency < 0):
        latency = None
    _pending_ping.append(PingSample(source=source, t=int(now), ping=latency))
    _record_interfaces(source, now, interfaces)
    if rx_rate is None or tx_rate is None:
        if rx_bytes is None or tx_bytes is None:
            rx_rate, tx_rate = 0.0, 0.0
        else:
            rates = _rate_from_counters(source, now, float(rx_bytes), float(tx_bytes))
            if rates is None:
                return
            rx_rate, tx_rate = rates

    _pending.append(
        {
            "source": source,
            "res": RES_RAW,
            "t": int(now),
            "cpu": float(cpu or 0),
            "ram": float(ram or 0),
            "disk": float(disk or 0),
            "rx": float(rx_rate or 0),
            "tx": float(tx_rate or 0),
        }
    )


async def flush_pending() -> int:
    if not _pending and not _pending_network and not _pending_ping:
        return 0
    batch = _pending[:]
    network_batch = _pending_network[:]
    ping_batch = _pending_ping[:]
    _pending.clear()
    _pending_network.clear()
    _pending_ping.clear()
    try:
        async with in_transaction() as conn:
            if batch:
                await MetricSample.bulk_create([MetricSample(**row) for row in batch], using_db=conn)
            if network_batch:
                await NetworkSample.bulk_create(network_batch, using_db=conn)
            if ping_batch:
                await PingSample.bulk_create(ping_batch, using_db=conn)
    except Exception:
        logging.debug("Metrics flush failed, %d samples dropped", len(batch) + len(network_batch) + len(ping_batch), exc_info=True)
        return 0
    return len(batch)


def _mean_rows(rows: list[tuple[Any, ...]]) -> dict[str, float]:
    count = len(rows)
    sums = [0.0] * 5
    for row in rows:
        for idx in range(5):
            sums[idx] += float(row[idx + 1] or 0)
    return {
        "cpu": sums[0] / count,
        "ram": sums[1] / count,
        "disk": sums[2] / count,
        "rx": sums[3] / count,
        "tx": sums[4] / count,
    }


async def _rebuild_tier(target_res: int, source_res: int, now: int, window: int) -> None:
    start = (now - window) // target_res * target_res
    rows = await MetricSample.filter(res=source_res, t__gte=start).values_list(
        "source", "t", "cpu", "ram", "disk", "rx", "tx"
    )
    if not rows:
        return

    buckets: dict[tuple[str, int], list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        bucket_t = int(row[1]) // target_res * target_res
        buckets[(row[0], bucket_t)].append((row[1], *row[2:]))

    new_rows = [
        MetricSample(source=source, res=target_res, t=bucket_t, **_mean_rows(items))
        for (source, bucket_t), items in buckets.items()
    ]
    async with in_transaction():
        await MetricSample.filter(res=target_res, t__gte=start).delete()
        await MetricSample.bulk_create(new_rows)


async def _rebuild_network_tier(target_res: int, source_res: int, now: int, window: int) -> None:
    # Keep the oldest stored bucket if the source tier only contains part of it.
    start = (now - window + target_res - 1) // target_res * target_res
    async with in_transaction() as conn:
        await NetworkSample.filter(res=target_res, t__gte=start).using_db(conn).delete()
        # Raw total traffic already lives in metric_samples. Only interface rates need new raw rows.
        await conn.execute_query(
            """
            INSERT INTO network_samples (source, interface, res, t, rx, tx)
            SELECT source, interface, ?, (t / ?) * ?, MAX(rx), MAX(tx)
            FROM (
                SELECT source, interface, t, rx, tx FROM network_samples WHERE res = ? AND t >= ?
                UNION ALL
                SELECT source, '', t, rx, tx FROM metric_samples WHERE ? = 0 AND res = 0 AND t >= ?
            )
            GROUP BY source, interface, t / ?
            """,
            [target_res, target_res, target_res, source_res, start, source_res, start, target_res],
        )
        await PingSample.filter(res=target_res, t__gte=start).using_db(conn).delete()
        await conn.execute_query(
            """
            INSERT INTO ping_samples (source, res, t, ping)
            SELECT source, ?, (t / ?) * ?, MAX(ping)
            FROM ping_samples WHERE res = ? AND t >= ?
            GROUP BY source, t / ?
            """,
            [target_res, target_res, target_res, source_res, start, target_res],
        )


async def aggregate(now: float | None = None, *, full: bool = False) -> None:
    """Roll samples into 1- and 5-minute resource averages and network peaks.

    ``full`` rebuilds everything still covered by the lower tier's retention —
    used once after startup so samples left unaggregated by a shutdown are not lost.
    """
    now_i = int(now if now is not None else time.time())
    minute_window = RETENTION[RES_RAW] if full else MINUTE_REBUILD_WINDOW
    five_min_window = RETENTION[RES_MINUTE] if full else FIVE_MIN_REBUILD_WINDOW
    await _rebuild_tier(RES_MINUTE, RES_RAW, now_i, minute_window)
    await _rebuild_tier(RES_FIVE_MIN, RES_MINUTE, now_i, five_min_window)
    await _rebuild_network_tier(RES_MINUTE, RES_RAW, now_i, minute_window)
    await _rebuild_network_tier(RES_FIVE_MIN, RES_MINUTE, now_i, five_min_window)


async def apply_retention(now: float | None = None) -> None:
    now_i = int(now if now is not None else time.time())
    for res, keep in RETENTION.items():
        await MetricSample.filter(res=res, t__lt=now_i - keep).delete()
        await NetworkSample.filter(res=res, t__lt=now_i - keep).delete()
        await PingSample.filter(res=res, t__lt=now_i - keep).delete()


async def delete_source(source: str) -> None:
    _last_counters.pop(source, None)
    _last_interfaces.pop(source, None)
    _pending[:] = [row for row in _pending if row["source"] != source]
    _pending_network[:] = [row for row in _pending_network if row.source != source]
    _pending_ping[:] = [row for row in _pending_ping if row.source != source]
    async with in_transaction() as conn:
        await MetricSample.filter(source=source).using_db(conn).delete()
        await NetworkSample.filter(source=source).using_db(conn).delete()
        await PingSample.filter(source=source).using_db(conn).delete()


def _bucketize(rows: list[tuple[Any, ...]], step: int) -> list[tuple[Any, ...]]:
    buckets: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        buckets[int(row[0]) // step * step].append(row)
    result = []
    for bucket_t in sorted(buckets):
        mean = _mean_rows(buckets[bucket_t])
        result.append((bucket_t, mean["cpu"], mean["ram"], mean["disk"], mean["rx"], mean["tx"]))
    return result


async def query_series(source: str, range_key: str, since: int | None = None) -> dict[str, Any]:
    span, tier, step = RANGES.get(range_key, RANGES[DEFAULT_RANGE])
    now = int(time.time())
    start = now - span
    if since is not None:
        start = max(start, int(since))

    rows = await MetricSample.filter(source=source, res=tier, t__gte=start).order_by("t").values_list(
        "t", "cpu", "ram", "disk", "rx", "tx"
    )
    if step and step != tier:
        rows = _bucketize(list(rows), step)

    points = [
        {
            "t": int(row[0]),
            "c": round(float(row[1] or 0), 1),
            "r": round(float(row[2] or 0), 1),
            "d": round(float(row[3] or 0), 1),
            "rx": round(float(row[4] or 0)),
            "tx": round(float(row[5] or 0)),
        }
        for row in rows
    ]
    return {"range": range_key, "step": step, "span": span, "now": now, "points": points}


async def query_network_series(source: str, range_key: str, interface: str, since: int | None = None) -> dict[str, Any]:
    span, tier, _ = RANGES[range_key]
    now = int(time.time())
    start = now - span
    if span >= 3 * 86400:
        start = start // RES_FIVE_MIN * RES_FIVE_MIN
    samples = NetworkSample.filter(source=source, res=tier, t__gte=start)
    interfaces = await samples.exclude(interface="").distinct().order_by("interface").values_list("interface", flat=True)
    if since is not None:
        start = max(start, since)

    model = NetworkSample if tier or interface else MetricSample
    selected = model.filter(source=source, res=tier, t__gte=start)
    if model is NetworkSample:
        selected = selected.filter(interface=interface)
    rows = await selected.order_by("t").values_list("t", "rx", "tx")
    points = {t: {"t": t, "rx": round(rx), "tx": round(tx), "ping": None} for t, rx, tx in rows}
    ping_rows = await PingSample.filter(source=source, res=tier, t__gte=start).order_by("t").values_list("t", "ping")
    for t, ping in ping_rows:
        point = points.setdefault(t, {"t": t, "rx": None, "tx": None})
        point["ping"] = round(ping, 2) if ping is not None else None
    return {
        "range": range_key, "step": tier, "span": span, "now": now, "interfaces": interfaces,
        "points": [points[t] for t in sorted(points)],
    }


async def maintenance_loop() -> None:
    """Flush buffered samples, roll up tiers and prune old data."""
    import asyncio

    last_aggregate = 0.0
    last_retention = 0.0
    first_pass = True
    while True:
        try:
            await flush_pending()
            now = time.time()
            if now - last_aggregate >= AGGREGATE_INTERVAL:
                await aggregate(now, full=first_pass)
                first_pass = False
                last_aggregate = now
            if now - last_retention >= RETENTION_INTERVAL:
                await apply_retention(now)
                last_retention = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.debug("Metrics maintenance iteration failed", exc_info=True)
        await asyncio.sleep(FLUSH_INTERVAL)
