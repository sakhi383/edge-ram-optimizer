"""
EdgeRAM-Optimizer Core Package
Exposes modules for Win32 memory trimming, Chromium Edge process launching,
and Windows kernel memory compression management.
"""

from .memory_trimmer import (
    trim_edge_working_set,
    get_edge_memory_metrics,
    PROCESS_MEMORY_COUNTERS,
)
from .edge_launcher import (
    locate_edge_executable,
    launch_optimized_edge,
    is_edge_running_optimized,
    create_optimized_shortcut,
    relaunch_optimized_edge,
    OPTIMIZED_FLAGS,
)
from .kernel_mmagent import (
    get_mmagent_status,
    enable_kernel_features,
)

__all__ = [
    "trim_edge_working_set",
    "get_edge_memory_metrics",
    "PROCESS_MEMORY_COUNTERS",
    "locate_edge_executable",
    "launch_optimized_edge",
    "is_edge_running_optimized",
    "create_optimized_shortcut",
    "relaunch_optimized_edge",
    "OPTIMIZED_FLAGS",
    "get_mmagent_status",
    "enable_kernel_features",
]
