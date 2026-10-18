"""Inspect a configured ELF file without executing or attaching to it."""

import hashlib
import os
from pathlib import Path
from typing import Any

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile


def inspect_identity(client_path: Path) -> dict[str, Any]:
    """Read identity from one open file, rejecting missing or non-ELF targets."""
    try:
        path = client_path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("Configured client path must be a regular ELF file")
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            elf = ELFFile(stream)
            build_id = None
            for segment in elf.iter_segments():
                if segment["p_type"] == "PT_NOTE":
                    for note in segment.iter_notes():
                        if note["n_type"] == "NT_GNU_BUILD_ID":
                            build_id = note["n_desc"]
            after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ):
                raise ValueError("Client file changed during identity inspection; retry explicitly")
            return {
                "path": str(path),
                "sha256": digest,
                "build_id": build_id,
                "size_bytes": before.st_size,
                "elf_class": elf.elfclass,
                "machine": elf["e_machine"],
                "elf_type": elf["e_type"],
                "evidence_type": "live_file_read",
                "authenticity_verified": False,
                "process_attached": False,
            }
    except (OSError, ELFError) as error:
        raise ValueError(f"Cannot inspect configured client ELF: {error}") from error


def discover_client_pid(proc_root: Path = Path('/proc')) -> int:
    """Select exactly one installed main executable; never choose a child/name match."""
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if os.readlink(entry / 'exe') == '/opt/wechat/wechat':
                matches.append(int(entry.name))
        except OSError:
            continue
    if len(matches) != 1:
        raise ValueError('Expected exactly one running WeChat main process; start/login first or set --wechat-pid')
    return matches[0]
