"""
Win32 Working Set Trimming & Process Memory Metrics Engine
Leverages ctypes and direct Win32 API calls (kernel32.dll, psapi.dll)
to safely flush non-essential pages from Microsoft Edge working sets to standby.
"""

import ctypes
from ctypes import wintypes
from typing import Dict, Any, Tuple
import psutil

# Win32 Process Access Rights
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
PROCESS_VM_READ = 0x0010

# Load native Windows DLLs with last error tracking
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    """
    Win32 PROCESS_MEMORY_COUNTERS Structure
    Represents memory statistics for a process handle.
    Using c_size_t ensures 32-bit and 64-bit architecture compatibility.
    """
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


# Explicit Win32 API function signatures
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
psapi.EmptyWorkingSet.restype = wintypes.BOOL

psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
    wintypes.DWORD,
]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def get_edge_memory_metrics() -> Dict[str, Any]:
    """
    Inspects all running instances of msedge.exe and aggregates
    working set (physical RAM) and private/commit memory.

    Returns:
        Dict containing total_working_set_mb, total_private_mb,
        process_count, and per-process details.
    """
    total_working_set_bytes = 0
    total_private_bytes = 0
    edge_processes = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if not name or name.lower() != "msedge.exe":
                continue

            pid = proc.info["pid"]
            h_process = kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
            )

            if h_process:
                try:
                    pmc = PROCESS_MEMORY_COUNTERS()
                    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    if psapi.GetProcessMemoryInfo(h_process, ctypes.byref(pmc), pmc.cb):
                        ws_bytes = pmc.WorkingSetSize
                        commit_bytes = pmc.PagefileUsage

                        total_working_set_bytes += ws_bytes
                        total_private_bytes += commit_bytes

                        edge_processes.append({
                            "pid": pid,
                            "working_set_mb": round(ws_bytes / (1024 * 1024), 2),
                            "private_mb": round(commit_bytes / (1024 * 1024), 2),
                        })
                finally:
                    kernel32.CloseHandle(h_process)
            else:
                # Fallback to psutil memory_info if OpenProcess fails on elevated sub-process
                try:
                    mem = proc.memory_info()
                    total_working_set_bytes += mem.rss
                    total_private_bytes += getattr(mem, "vms", mem.rss)
                    edge_processes.append({
                        "pid": pid,
                        "working_set_mb": round(mem.rss / (1024 * 1024), 2),
                        "private_mb": round(getattr(mem, "vms", mem.rss) / (1024 * 1024), 2),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except (psutil.NoSuchProcess, psutil.AccessDenied, WindowsError, PermissionError):
            continue

    total_ws_mb = round(total_working_set_bytes / (1024 * 1024), 2)
    total_private_mb = round(total_private_bytes / (1024 * 1024), 2)

    return {
        "working_set_bytes": total_working_set_bytes,
        "private_bytes": total_private_bytes,
        "total_working_set_mb": total_ws_mb,
        "total_private_mb": total_private_mb,
        "process_count": len(edge_processes),
        "processes": edge_processes,
    }


def trim_edge_working_set() -> Tuple[float, int]:
    """
    Executes Win32 EmptyWorkingSet across all active msedge.exe processes.
    Forces Windows Memory Manager to flush inactive pages to the standby list,
    reclaiming physical RAM instantly without crashing tabs or closing renderer threads.

    Returns:
        Tuple of (freed_ram_mb: float, flushed_processes_count: int)
    """
    initial_ws_bytes = 0
    post_ws_bytes = 0
    flushed_count = 0

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if not name or name.lower() != "msedge.exe":
                continue

            pid = proc.info["pid"]

            # Open with PROCESS_SET_QUOTA (to empty working set) and PROCESS_QUERY_INFORMATION
            h_process = kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid
            )

            if not h_process:
                continue

            try:
                # 1. Read pre-trim memory
                pmc_pre = PROCESS_MEMORY_COUNTERS()
                pmc_pre.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                has_pre = psapi.GetProcessMemoryInfo(
                    h_process, ctypes.byref(pmc_pre), pmc_pre.cb
                )

                # 2. Call Win32 EmptyWorkingSet
                trimmed = psapi.EmptyWorkingSet(h_process)

                # 3. Read post-trim memory
                if trimmed and has_pre:
                    pmc_post = PROCESS_MEMORY_COUNTERS()
                    pmc_post.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    if psapi.GetProcessMemoryInfo(
                        h_process, ctypes.byref(pmc_post), pmc_post.cb
                    ):
                        initial_ws_bytes += pmc_pre.WorkingSetSize
                        post_ws_bytes += pmc_post.WorkingSetSize
                        flushed_count += 1
            finally:
                kernel32.CloseHandle(h_process)

        except (WindowsError, PermissionError, psutil.NoSuchProcess, psutil.AccessDenied):
            # Gracefully ignore elevated or transient sub-processes
            continue

    freed_bytes = max(0, initial_ws_bytes - post_ws_bytes)
    freed_mb = round(freed_bytes / (1024 * 1024), 2)

    return freed_mb, flushed_count
