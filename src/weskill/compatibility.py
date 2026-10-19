"""Read-only compatibility assessment; never enables or attaches native hooks."""

import platform
from pathlib import Path
from typing import Any

from .capabilities import RESEARCH_TARGET


def assess_compatibility(
    identity: dict[str, Any] | None,
    *,
    host_os: str | None = None,
    host_architecture: str | None = None,
    inspection_error: str | None = None,
) -> dict[str, Any]:
    """Compare observed identity with the recorded native target, without probing runtime.

    Injected host values support deterministic tests and offline assessment; they
    are reported explicitly and never constitute runtime verification.
    """
    host_os = platform.system() if host_os is None else host_os
    host_architecture = platform.machine() if host_architecture is None else host_architecture
    identity = identity or {}
    file_ok = bool(identity) and inspection_error is None
    checks = [
        {"requirement": "client_elf", "satisfied": file_ok,
         "expected": "readable regular ELF file", "actual": identity.get("path"),
         "reason": inspection_error if inspection_error else None},
        {"requirement": "host_os", "satisfied": host_os == "Linux",
         "expected": "Linux", "actual": host_os},
        {"requirement": "host_architecture",
         "satisfied": host_architecture.lower() in {"aarch64", "arm64"},
         "expected": RESEARCH_TARGET["architecture"], "actual": host_architecture},
        {"requirement": "client_architecture",
         "satisfied": identity.get("machine") == "EM_AARCH64" and identity.get("elf_class") == 64 if file_ok else None,
         "expected": {"machine": "EM_AARCH64", "elf_class": 64},
         "actual": {"machine": identity.get("machine"), "elf_class": identity.get("elf_class")}},
        {"requirement": "client_sha256",
         "satisfied": identity.get("sha256") == RESEARCH_TARGET["sha256"] if file_ok else None,
         "expected": RESEARCH_TARGET["sha256"], "actual": identity.get("sha256")},
        {"requirement": "client_path",
         "satisfied": identity.get("path") == "/opt/wechat/wechat" if file_ok else None,
         "expected": "/opt/wechat/wechat", "actual": identity.get("path")},
    ]
    failures = [item["requirement"] for item in checks if item["satisfied"] is False]
    return {
        "diagnostics": {
            "status": "supported" if file_ok else "unsupported",
            "scope": "Read-only identity inspection of any readable regular ELF, regardless of architecture or native support",
            "error": inspection_error,
        },
        "native": {
            "status": "supported" if all(item["satisfied"] is True for item in checks) else "unsupported",
            "scope": "Recorded build and host compatibility only; not runtime readiness or business verification",
            "research_target": dict(RESEARCH_TARGET),
            "checks": checks,
            "unsupported_reasons": failures,
            "runtime_prerequisites_checked": False,
            "execution_available": False,
            "unchecked_requirements": [
                "Frida 16.7.19 and a compatible built native executor shim",
                "Explicit opt-in and exactly identified running main process at the required path",
                "Live process executable hash, mapping identity, and PID lifetime binding",
                "Logged-in client, account permissions, and per-operation success",
            ],
        },
        "process_attached": False,
    }


def compatibility_report(client_path: Path) -> dict[str, Any]:
    """Include structured unsupported reasons when the file cannot be inspected."""
    # Keep the import local: identity also uses assess_compatibility.
    from .identity import inspect_identity

    try:
        return inspect_identity(client_path)["compatibility"]
    except ValueError as error:
        return assess_compatibility(None, inspection_error=str(error))
