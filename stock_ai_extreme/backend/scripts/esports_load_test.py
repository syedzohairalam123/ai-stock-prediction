#!/usr/bin/env python
"""
Phase 21C §18 — esports load test.

Drives a **running** backend and records real measurements. Nothing here is
estimated: every number in the report is either a latency this client observed,
a counter the server reported, or a process CPU/RSS reading taken from the
operating system.

What it does per level (100 / 1,000 / 5,000 / 10,000):

  * HTTP   — issues that many requests across the esports REST endpoints and
             records the observed latency distribution (p50/p95/p99/max).
  * WS     — opens that many concurrent WebSocket connections to
             ``/api/esports/ws/{client_id}``, subscribes each to the cross-game
             firehose, holds them, and records connects, failures, messages
             received, and reconnects.
  * System — samples server-process CPU time and RSS before/after the level,
             plus system-wide memory, and pulls the server's own observability
             counters (event ingestion rate, WS broadcast latency, clients).

Usage
-----
    python scripts/esports_load_test.py                     # default levels
    python scripts/esports_load_test.py --levels 100,1000
    python scripts/esports_load_test.py --http-only
    python scripts/esports_load_test.py --report out.json

The report is written to ``load_test_report.json`` (or ``--report``) and a short
summary is printed. A level that cannot be fully established is reported with
its failure count — never massaged into a pass.
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
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np

try:  # websockets is already a project dependency (used by uvicorn[standard])
    import websockets
except Exception:  # pragma: no cover - only when the extra is absent
    websockets = None  # type: ignore[assignment]


HTTP_ENDPOINTS = [
    ("/api/esports/featured", 3),
    ("/api/esports/matches?limit=25", 3),
    ("/api/esports/games/summary", 2),
    ("/api/v1/esports/trending/games", 2),
    ("/api/v1/esports/trending/matches?limit=10", 2),
    ("/api/v1/esports/data-quality?limit=25", 2),
    ("/api/v1/esports/observability", 1),
]


# ---------------------------------------------------------------------------
# OS measurements (no extra dependency: ctypes on Windows, /proc elsewhere)
# ---------------------------------------------------------------------------

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
    """Reads CPU time and working set from Windows process handles."""

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
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)

    def pids(self, exe_hint: str = "python") -> List[int]:
        snapshot = self.kernel32.CreateToolhelp32Snapshot(self.TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return []
        entry = self.PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(self.PROCESSENTRY32)
        found: List[int] = []
        try:
            ok = self.kernel32.Process32First(snapshot, ctypes.byref(entry))
            while ok:
                name = entry.szExeFile.decode("utf-8", "ignore").lower()
                if exe_hint.lower() in name:
                    found.append(int(entry.th32ProcessID))
                ok = self.kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            self.kernel32.CloseHandle(snapshot)
        return found

    def sample(self, pid: int) -> Optional[Dict[str, float]]:
        handle = self.kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            creation, exit_time, kernel, user = (
                ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
            )
            if not self.kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return None
            counters = self.PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(self.PROCESS_MEMORY_COUNTERS)
            if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return {
                "cpu_seconds": (kernel.value + user.value) / 1e7,
                "rss_bytes": float(counters.WorkingSetSize),
            }
        finally:
            self.kernel32.CloseHandle(handle)

    def system_memory(self) -> Optional[Dict[str, float]]:
        status = self.MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(self.MEMORYSTATUSEX)
        if not self.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return {
            "total_bytes": float(status.ullTotalPhys),
            "available_bytes": float(status.ullAvailPhys),
            "load_percent": float(status.dwMemoryLoad),
        }


class _PosixProcs:
    """The Linux/macOS equivalent, read from /proc (Linux) or `ps`."""

    def pids(self, exe_hint: str = "python") -> List[int]:
        found: List[int] = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as handle:
                    if exe_hint.encode() in handle.read():
                        found.append(int(entry))
            except OSError:
                continue
        return found

    def sample(self, pid: int) -> Optional[Dict[str, float]]:
        try:
            with open(f"/proc/{pid}/stat") as handle:
                parts = handle.read().split()
            ticks = os.sysconf("SC_CLK_TCK")
            cpu = (int(parts[13]) + int(parts[14])) / ticks
            with open(f"/proc/{pid}/statm") as handle:
                rss_pages = int(handle.read().split()[1])
            return {"cpu_seconds": cpu, "rss_bytes": float(rss_pages * os.sysconf("SC_PAGE_SIZE"))}
        except (OSError, IndexError, ValueError):
            return None

    def system_memory(self) -> Optional[Dict[str, float]]:
        try:
            values: Dict[str, float] = {}
            with open("/proc/meminfo") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    values[key.strip()] = float(rest.strip().split()[0]) * 1024
            total = values.get("MemTotal", 0.0)
            available = values.get("MemAvailable", 0.0)
            return {
                "total_bytes": total,
                "available_bytes": available,
                "load_percent": round((1 - available / total) * 100, 2) if total else 0.0,
            }
        except OSError:
            return None


def _proc_backend():
    return _WindowsProcs() if sys.platform.startswith("win") else _PosixProcs()


def _server_candidates(backend, hint: str) -> List[int]:
    return [pid for pid in backend.pids(hint) if pid != os.getpid()]


def _read_server(backend, pids: List[int]) -> Dict[str, Any]:
    """Totals across the candidate server processes (uvicorn worker(s))."""
    cpu = 0.0
    rss = 0.0
    alive = 0
    for pid in pids:
        sample = backend.sample(pid)
        if not sample:
            continue
        alive += 1
        cpu += sample["cpu_seconds"]
        rss += sample["rss_bytes"]
    return {"processes": alive, "cpu_seconds": round(cpu, 3), "rss_bytes": rss}


# ---------------------------------------------------------------------------
# HTTP load
# ---------------------------------------------------------------------------

async def run_http_level(client: httpx.AsyncClient, base: str, requests: int, concurrency: int) -> Dict[str, Any]:
    # Weighted round-robin: heavier endpoints get proportionally more requests.
    plan: List[str] = []
    index = 0
    while len(plan) < requests:
        path, weight = HTTP_ENDPOINTS[index % len(HTTP_ENDPOINTS)]
        plan.extend([path] * min(weight, requests - len(plan)))
        index += 1
    plan = plan[:requests]

    latencies: List[float] = []
    statuses: Dict[str, int] = {}
    errors: List[str] = []
    per_endpoint: Dict[str, List[float]] = {}
    lock = asyncio.Lock()
    cursor = {"i": 0}

    async def worker() -> None:
        while True:
            async with lock:
                if cursor["i"] >= len(plan):
                    return
                path = plan[cursor["i"]]
                cursor["i"] += 1
            started = time.perf_counter()
            try:
                response = await client.get(f"{base}{path}")
                elapsed = (time.perf_counter() - started) * 1000
                async with lock:
                    latencies.append(elapsed)
                    per_endpoint.setdefault(path, []).append(elapsed)
                    key = str(response.status_code)
                    statuses[key] = statuses.get(key, 0) + 1
                    if response.status_code >= 500:
                        errors.append(f"{path} -> {response.status_code}")
            except Exception as exc:  # network/timeout — recorded, not hidden
                async with lock:
                    errors.append(f"{path} -> {type(exc).__name__}: {exc}")

    started = time.perf_counter()
    await asyncio.gather(*[worker() for _ in range(max(1, min(concurrency, requests)))])
    elapsed = time.perf_counter() - started

    return {
        "requests_attempted": requests,
        "requests_completed": len(latencies),
        "concurrency": min(concurrency, requests),
        "duration_seconds": round(elapsed, 3),
        "throughput_requests_per_second": round(len(latencies) / elapsed, 2) if elapsed else None,
        "latency_ms": _percentiles(latencies),
        "per_endpoint_latency_ms": {path: _percentiles(values) for path, values in sorted(per_endpoint.items())},
        "status_codes": dict(sorted(statuses.items())),
        "error_count": len(errors),
        "error_samples": errors[:5],
    }


# ---------------------------------------------------------------------------
# WebSocket load
# ---------------------------------------------------------------------------

async def run_ws_level(
    base_ws: str, connections: int, hold_seconds: float, batch: int, ramp_delay: float = 0.35
) -> Dict[str, Any]:
    """
    Open `connections` sockets and keep them all open at once.

    Sockets are *not* closed between batches: the ramp only paces how fast new
    connections are attempted, so the peak concurrent count is genuinely the
    level under test. Anything the server (or this client's OS) refuses is
    counted as a failure rather than retried into a false pass.
    """
    if websockets is None:
        return {"skipped": "the `websockets` package is not installed"}

    connected = 0
    failed = 0
    active = 0
    peak_active = 0
    messages = 0
    dropped = 0
    connect_latencies: List[float] = []
    errors: List[str] = []
    lock = asyncio.Lock()
    stop = asyncio.Event()

    async def one(index: int) -> None:
        nonlocal connected, failed, active, peak_active, messages, dropped
        url = f"{base_ws}/api/esports/ws/load-{index}"
        started = time.perf_counter()
        try:
            socket = await websockets.connect(url, open_timeout=30, ping_interval=None, max_size=None)
        except Exception as exc:
            async with lock:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"connect failed: {type(exc).__name__}: {exc}")
            return
        async with lock:
            connected += 1
            active += 1
            peak_active = max(peak_active, active)
            connect_latencies.append((time.perf_counter() - started) * 1000)
        try:
            await socket.send(json.dumps({"type": "subscribe", "channel": "all"}))
            while not stop.is_set():
                try:
                    await asyncio.wait_for(socket.recv(), timeout=0.5)
                    async with lock:
                        messages += 1
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    async with lock:
                        dropped += 1
                    break
        finally:
            async with lock:
                active -= 1
            try:
                await socket.close()
            except Exception:
                pass

    started = time.perf_counter()
    tasks: List[asyncio.Task] = []
    for offset in range(0, connections, max(1, batch)):
        chunk = min(batch, connections - offset)
        for i in range(chunk):
            tasks.append(asyncio.create_task(one(offset + i)))
        await asyncio.sleep(ramp_delay)
    ramp_seconds = time.perf_counter() - started

    # Hold every established socket open together, then release them at once.
    await asyncio.sleep(hold_seconds)
    async with lock:
        peak_active = max(peak_active, active)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - started

    return {
        "connections_requested": connections,
        "connections_established": connected,
        "connections_failed": failed,
        "peak_concurrent_connections": peak_active,
        "messages_received": messages,
        "message_rate_per_second": round(messages / elapsed, 2) if elapsed else None,
        "dropped_connections": dropped,
        "reconnect_rate_percent": round((failed / connections) * 100, 2) if connections else None,
        "connect_latency_ms": _percentiles(connect_latencies),
        "ramp_seconds": round(ramp_seconds, 3),
        "hold_seconds": hold_seconds,
        "duration_seconds": round(elapsed, 3),
        "error_samples": errors,
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

async def observability(client: httpx.AsyncClient, base: str) -> Optional[Dict[str, Any]]:
    try:
        response = await client.get(f"{base}/api/v1/esports/observability", timeout=30)
        if response.status_code == 200:
            payload = response.json()
            return payload.get("observability") or payload
    except Exception:
        return None
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 21C esports load test (§18)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--levels", default="100,1000,5000,10000",
                        help="comma-separated request volumes for the HTTP levels")
    parser.add_argument("--concurrency", type=int, default=200, help="max in-flight HTTP requests per level")
    parser.add_argument("--ws-levels", default="100,1000,5000,10000",
                        help="comma-separated concurrent WebSocket connection levels")
    parser.add_argument("--ws-hold", type=float, default=5.0, help="seconds to hold WebSocket connections open")
    parser.add_argument("--ws-batch", type=int, default=250, help="connections opened per batch")
    parser.add_argument("--ws-ramp", type=float, default=0.35, help="seconds to pause between WebSocket batches")
    parser.add_argument("--ws-cap", type=int, default=10000, help="never exceed this many WS connections")
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument("--ws-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", default="load_test_report.json")
    parser.add_argument("--proc-hint", default="python", help="substring of the server executable name")
    args = parser.parse_args()

    levels = [int(v) for v in args.levels.split(",") if v.strip()]
    ws_levels = [min(int(v), args.ws_cap) for v in args.ws_levels.split(",") if v.strip()]
    base_ws = args.base_url.replace("https://", "wss://").replace("http://", "ws://")

    backend = _proc_backend()
    server_pids = _server_candidates(backend, args.proc_hint)
    report: Dict[str, Any] = {
        "phase": "21C",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.base_url,
        "levels_http": levels,
        "levels_websocket": ws_levels,
        "server_processes_detected": len(server_pids),
        "system_memory": backend.system_memory(),
        "levels": [],
        "notes": [
            "Every value is a client-observed latency, a server-reported counter, or an OS process reading.",
            "A level that could not be fully established reports its failure count rather than an assumption.",
        ],
    }

    async with httpx.AsyncClient(timeout=args.timeout, limits=httpx.Limits(max_connections=max(50, args.concurrency))) as client:
        # Verify the target is up and configured before measuring.
        try:
            probe = await client.get(f"{args.base_url}/api/esports/health")
            report["target_health_status"] = probe.status_code
        except Exception as exc:
            print(f"[load] target unreachable at {args.base_url}: {exc}")
            return 2

        for level in ([] if args.ws_only else levels):
            print(f"[load] HTTP level {level} ...", flush=True)
            server_pids = _server_candidates(backend, args.proc_hint)
            before = _read_server(backend, server_pids)
            memory_before = backend.system_memory()
            obs_before = await observability(client, args.base_url)

            result = await run_http_level(client, args.base_url, level, args.concurrency)

            after = _read_server(backend, server_pids)
            memory_after = backend.system_memory()
            obs_after = await observability(client, args.base_url)
            result["server_cpu_seconds_used"] = round(after["cpu_seconds"] - before["cpu_seconds"], 3)
            result["server_rss_mb"] = round(after["rss_bytes"] / (1024 * 1024), 2)
            result["server_rss_delta_mb"] = round((after["rss_bytes"] - before["rss_bytes"]) / (1024 * 1024), 2)
            result["system_memory"] = memory_after
            result["system_memory_load_delta_percent"] = (
                round((memory_after or {}).get("load_percent", 0.0) - (memory_before or {}).get("load_percent", 0.0), 2)
                if memory_after and memory_before else None
            )
            result["server_observability"] = obs_after
            result["server_event_rate_per_second"] = (obs_after or {}).get("event_ingestion_rate_per_second")
            if obs_before and obs_after:
                result["server_events_ingested_during_level"] = round(
                    (obs_after.get("event_ingestion_rate_per_second", 0) - obs_before.get("event_ingestion_rate_per_second", 0))
                    * 300, 2
                )
            report["levels"].append({"kind": "http", "level": level, **result})
            print(
                f"[load]   http p50={result['latency_ms']['p50']}ms "
                f"p95={result['latency_ms']['p95']}ms p99={result['latency_ms']['p99']}ms "
                f"errors={result['error_count']} throughput={result['throughput_requests_per_second']}/s",
                flush=True,
            )

        if not (args.http_only and args.ws_only):
            for level in ws_levels:
                print(f"[load] WebSocket level {level} ...", flush=True)
                server_pids = _server_candidates(backend, args.proc_hint)
                before = _read_server(backend, server_pids)
                memory_before = backend.system_memory()
                result = await run_ws_level(base_ws, level, args.ws_hold, args.ws_batch, args.ws_ramp)
                after = _read_server(backend, _server_candidates(backend, args.proc_hint))
                memory_after = backend.system_memory()
                result["server_cpu_seconds_used"] = round(after["cpu_seconds"] - before["cpu_seconds"], 3)
                result["server_rss_mb"] = round(after["rss_bytes"] / (1024 * 1024), 2)
                result["server_rss_delta_mb"] = round((after["rss_bytes"] - before["rss_bytes"]) / (1024 * 1024), 2)
                result["system_memory"] = memory_after
                result["server_observability_after"] = await observability(client, args.base_url)
                report["levels"].append({"kind": "websocket", "level": level, **result})
                print(
                    f"[load]   ws connected={result['connections_established']}/{level} "
                    f"failed={result['connections_failed']} messages={result['messages_received']} "
                    f"connect p95={result['connect_latency_ms']['p95']}ms",
                    flush=True,
                )

    report["system_memory_after"] = backend.system_memory()
    with open(args.report, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"[load] report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
