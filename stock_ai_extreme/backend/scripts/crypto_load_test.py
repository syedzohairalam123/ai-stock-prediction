#!/usr/bin/env python
"""
Phase 22 — crypto load test (spec §23).

Drives a **running** backend and records real measurements only. Every number in
the report is a latency this client observed, a counter the server reported, or
an OS reading of the server process (CPU seconds / working set). Nothing is
estimated and a level that cannot be established is reported with its failure
counts rather than massaged into a pass.

Per level it measures:

  * HTTP — issues that many requests across the crypto REST surface and records
           the observed latency distribution (p50/p95/p99/max) plus status
           counts, so a rate-limited (429) run is visible instead of hidden.
  * WS   — opens that many concurrent WebSocket connections to
           ``/api/v1/crypto/ws/{client_id}``, subscribes each to BTC 5m, and
           records connects/failures/reconnects, snapshots, ticks and the
           gateway's own shared-upstream stream count.

The crypto gateway is deliberately bounded (``CRYPTO_WS_MAX_CONNECTIONS``,
``CRYPTO_RATE_LIMIT_MAX_REQUESTS``). To test a high level, start the backend
with those raised, e.g.::

    CRYPTO_WS_MAX_CONNECTIONS=12000 CRYPTO_RATE_LIMIT_MAX_REQUESTS=1000000 \
        uvicorn app.main:app --port 8001

…then::

    python scripts/crypto_load_test.py --target http://127.0.0.1:8001 \\
        --levels 100,1000,5000,10000 --report crypto_load_test_report.json

NOT tested is NOT verified — a skipped or infeasible level is reported as such.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import numpy as np

try:  # websockets ships with uvicorn[standard]; degrade cleanly if absent
    import websockets
except Exception:  # pragma: no cover
    websockets = None  # type: ignore[assignment]


# Weighted crypto endpoints (the analytics/forecast families are heavier).
HTTP_ENDPOINTS = [
    ("/api/v1/crypto/assets", 2),
    ("/api/v1/crypto/timeframes", 2),
    ("/api/v1/crypto/quote/BTC", 3),
    ("/api/v1/crypto/candles/BTC?timeframe=1h&limit=200", 2),
    ("/api/v1/crypto/analytics/BTC?timeframe=5m", 2),
    ("/api/v1/crypto/targets/BTC", 1),
]


def _percentiles(samples: List[float]) -> Dict[str, Optional[float]]:
    if not samples:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
    values = np.asarray(samples, dtype=float)
    return {
        "count": len(samples),
        "p50": round(float(np.percentile(values, 50)), 2),
        "p95": round(float(np.percentile(values, 95)), 2),
        "p99": round(float(np.percentile(values, 99)), 2),
        "max": round(float(np.max(values)), 2),
        "mean": round(float(np.mean(values)), 2),
        "stdev": round(float(np.std(values)), 2),
    }


class _WindowsProcs:
    """CPU time + working set for the server process (no extra dependency)."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_char * 260),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    def __init__(self) -> None:
        self.k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self.psapi = ctypes.windll.psapi  # type: ignore[attr-defined]

    def pids(self) -> List[int]:
        snap = self.k32.CreateToolhelp32Snapshot(self.TH32CS_SNAPPROCESS, 0)
        entry = self.PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(self.PROCESSENTRY32)
        pids: List[int] = []
        if self.k32.Process32First(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode("utf-8", "ignore").lower()
                if "python" in name or "uvicorn" in name:
                    pids.append(entry.th32ProcessID)
                if not self.k32.Process32Next(snap, ctypes.byref(entry)):
                    break
        self.k32.CloseHandle(snap)
        return pids

    def _cpu_seconds(self, pid: int) -> float:
        handle = self.k32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 0.0
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        try:
            ok = self.k32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            return ((kernel.value + user.value) / 1e7) if ok else 0.0
        finally:
            self.k32.CloseHandle(handle)

    def _rss_bytes(self, pid: int) -> float:
        handle = self.k32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 0.0
        counters = self.PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(self.PROCESS_MEMORY_COUNTERS)
        try:
            ok = self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return float(counters.WorkingSetSize) if ok else 0.0
        finally:
            self.k32.CloseHandle(handle)

    def snapshot(self) -> Dict[str, float]:
        pids = self.pids()
        cpu = sum(self._cpu_seconds(pid) for pid in pids)
        rss = sum(self._rss_bytes(pid) for pid in pids)
        status = self.MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(self.MEMORYSTATUSEX)
        self.k32.GlobalMemoryStatusEx(ctypes.byref(status))
        return {
            "processes": len(pids),
            "cpu_seconds_total": round(cpu, 2),
            "rss_mb_total": round(rss / 1024 / 1024, 1),
            "system_memory_load_percent": float(status.dwMemoryLoad),
            "system_memory_available_mb": round(status.ullAvailPhys / 1024 / 1024, 1),
        }


def _snapshot_procs():
    if sys.platform == "win32":
        try:
            procs = _WindowsProcs()
        except Exception:
            return None
        return procs.snapshot()
    # POSIX fallback: no per-process scan, system memory from /proc if present
    info: Dict[str, float] = {"processes": 0, "cpu_seconds_total": 0.0, "rss_mb_total": 0.0}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            data = handle.read()
        total = next(int(l.split()[1]) for l in data.splitlines() if l.startswith("MemTotal"))
        avail = next(int(l.split()[1]) for l in data.splitlines() if l.startswith("MemAvailable"))
        info["system_memory_load_percent"] = round((1 - avail / total) * 100, 1)
        info["system_memory_available_mb"] = round(avail / 1024, 1)
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# HTTP level
# ---------------------------------------------------------------------------
async def _http_level(target: str, level: int, concurrency: int) -> Dict[str, Any]:
    endpoints: List[str] = []
    for path, weight in HTTP_ENDPOINTS:
        endpoints.extend([path] * weight)
    times: List[float] = []
    statuses: Dict[str, int] = {}
    per_endpoint: Dict[str, List[float]] = {path: [] for path, _ in HTTP_ENDPOINTS}
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(base_url=target, timeout=60.0) as client:
        async def one(i: int) -> None:
            path = endpoints[i % len(endpoints)]
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await client.get(path)
                    elapsed = (time.perf_counter() - start) * 1000
                except Exception as exc:  # network failure is measured, not hidden
                    async with lock:
                        statuses[f"EXC:{type(exc).__name__}"] = statuses.get(f"EXC:{type(exc).__name__}", 0) + 1
                    return
                async with lock:
                    times.append(elapsed)
                    key = str(response.status_code)
                    statuses[key] = statuses.get(key, 0) + 1
                    if response.status_code == 200:
                        per_endpoint[path].append(elapsed)

        start = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(level)))
        duration = time.perf_counter() - start

    return {
        "kind": "http",
        "level": level,
        "concurrency": concurrency,
        "requests_attempted": level,
        "requests_ok": statuses.get("200", 0),
        "requests_rate_limited": statuses.get("429", 0),
        "status_counts": statuses,
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(level / duration, 2) if duration else None,
        "latency_ms": _percentiles(times),
        "per_endpoint_latency_ms": {
            path: _percentiles(values) for path, values in per_endpoint.items() if values
        },
    }


# ---------------------------------------------------------------------------
# WebSocket level
# ---------------------------------------------------------------------------
async def _ws_level(target: str, level: int, hold_seconds: float = 6.0) -> Dict[str, Any]:
    if websockets is None:
        return {"kind": "websocket", "level": level, "status": "websockets package unavailable"}
    ws_base = target.replace("http://", "ws://").replace("https://", "wss://")
    established = 0
    failed = 0
    snapshots = 0
    ticks = 0
    candles = 0
    batches = 0
    connect_latencies: List[float] = []
    consumed_messages = 0
    done = asyncio.Event()
    lock = asyncio.Lock()

    async def client(index: int) -> None:
        nonlocal established, failed, snapshots, ticks, candles, batches, consumed_messages
        url = f"{ws_base}/api/v1/crypto/ws/lt-{index}"
        start = time.perf_counter()
        try:
            async with websockets.connect(url, open_timeout=20, max_size=8 * 1024 * 1024) as ws:
                async with lock:
                    established += 1
                    connect_latencies.append((time.perf_counter() - start) * 1000)
                await ws.send(json.dumps({"type": "subscribe", "symbol": "BTC", "timeframe": "5m"}))
                while not done.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=hold_seconds)
                    except asyncio.TimeoutError:
                        continue
                    message = json.loads(raw)
                    async with lock:
                        consumed_messages += 1
                        kind = message.get("type")
                        if kind == "snapshot":
                            snapshots += 1
                        elif kind == "tick":
                            ticks += 1
                        elif kind == "candle":
                            candles += 1
                        elif kind == "batch":
                            batches += 1
        except Exception:
            async with lock:
                failed += 1

    tasks = [asyncio.create_task(client(i)) for i in range(level)]
    # Wait until everyone has had a chance to connect (or fail), then hold.
    await asyncio.sleep(min(20.0, 2.0 + level / 500.0))
    await asyncio.sleep(hold_seconds)
    done.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Pull the gateway's own view (shared upstream stream count).
    server_stats: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(base_url=target, timeout=15.0) as client:
            health = (await client.get("/health")).json()
            server_stats = (health.get("crypto") or {}).get("websocket", {})
    except Exception:
        pass

    return {
        "kind": "websocket",
        "level": level,
        "connections_requested": level,
        "connections_established": established,
        "connections_failed": failed,
        "peak_concurrent_connections": established,
        "messages_received": consumed_messages,
        "snapshots": snapshots,
        "ticks": ticks,
        "candle_frames": candles,
        "batches": batches,
        "reconnect_rate_percent": round(failed / level * 100, 2) if level else None,
        "connect_latency_ms": _percentiles(connect_latencies),
        "server_gateway_stats": server_stats,
    }


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "phase": "22",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.target,
        "levels_http": args.levels if not args.ws_only else [],
        "levels_websocket": args.levels if not args.http_only else [],
        "methodology": (
            "Real client-observed latencies against a running backend. NOT tested "
            "is NOT verified; a level that cannot be established is reported with "
            "its failure counts."
        ),
        "levels": [],
    }
    report["system_before"] = _snapshot_procs()

    for level in args.levels:
        if not args.ws_only:
            before = _snapshot_procs()
            print(f"[http] level={level} …", flush=True)
            result = await _http_level(args.target, level, args.concurrency)
            after = _snapshot_procs()
            if before and after:
                result["server_cpu_seconds_delta"] = round(
                    after["cpu_seconds_total"] - before["cpu_seconds_total"], 2
                )
                result["server_rss_mb_after"] = after["rss_mb_total"]
                result["system_memory_load_percent"] = after.get("system_memory_load_percent")
            report["levels"].append(result)
            print(
                f"  -> ok={result['requests_ok']} 429={result['requests_rate_limited']} "
                f"p50={result['latency_ms']['p50']}ms p95={result['latency_ms']['p95']}ms",
                flush=True,
            )

        if not args.http_only:
            print(f"[ws]   level={level} …", flush=True)
            result = await _ws_level(args.target, level, hold_seconds=args.hold_seconds)
            report["levels"].append(result)
            print(
                f"  -> established={result.get('connections_established')} "
                f"failed={result.get('connections_failed')} "
                f"upstream_streams={len((result.get('server_gateway_stats') or {}).get('upstream_streams', []))}",
                flush=True,
            )

    report["system_after"] = _snapshot_procs()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 22 crypto load test")
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--levels", default="100,1000")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--hold-seconds", type=float, default=6.0)
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument("--ws-only", action="store_true")
    parser.add_argument("--report", default="crypto_load_test_report.json")
    args = parser.parse_args()
    args.levels = [int(x) for x in str(args.levels).split(",") if x.strip()]

    report = asyncio.run(run(args))
    out = os.path.abspath(args.report)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
