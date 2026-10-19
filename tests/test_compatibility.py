"""Compatibility assessment is evidence scoping, never a simulated native success."""

import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from weskill.capabilities import RESEARCH_TARGET
from weskill.compatibility import assess_compatibility, compatibility_report
from weskill.identity import inspect_identity


def elf_fixture(machine: int) -> bytes:
    """Minimal ELF64 header for parser coverage; not a WeChat or native fixture."""
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    return ident + struct.pack("<HHIQQQIHHHHHH", 2, machine, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)


class CompatibilityTests(unittest.TestCase):
    def test_aarch64_and_x86_64_elf_diagnostics_are_supported(self):
        for number, name in [(183, "EM_AARCH64"), (62, "EM_X86_64")]:
            with self.subTest(machine=name), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "fixture.elf"
                path.write_bytes(elf_fixture(number))
                result = inspect_identity(path)
                self.assertEqual(result["machine"], name)
                self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(result["compatibility"]["diagnostics"]["status"], "supported")
                self.assertEqual(result["compatibility"]["native"]["status"], "unsupported")
                self.assertIn("client_sha256", result["compatibility"]["native"]["unsupported_reasons"])
                self.assertFalse(result["process_attached"])

    def test_missing_non_elf_and_directory_report_file_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            text = root / "not-elf"
            text.write_text("not an ELF")
            for path in (root / "missing", text, root):
                with self.subTest(path=path):
                    report = compatibility_report(path)
                    self.assertEqual(report["diagnostics"]["status"], "unsupported")
                    self.assertIn("client_elf", report["native"]["unsupported_reasons"])
                    checks = {item["requirement"]: item for item in report["native"]["checks"]}
                    self.assertIsNone(checks["client_sha256"]["satisfied"])
                    self.assertFalse(report["process_attached"])

    def matching_identity(self):
        # This mapping tests the comparison logic only. It is not file evidence.
        return {"path": "/opt/wechat/wechat", "machine": "EM_AARCH64", "elf_class": 64,
                "sha256": RESEARCH_TARGET["sha256"]}

    def test_matching_identity_still_does_not_claim_runtime_readiness(self):
        report = assess_compatibility(self.matching_identity(), host_os="Linux", host_architecture="aarch64")
        native = report["native"]
        self.assertEqual(native["status"], "supported")
        self.assertEqual(native["unsupported_reasons"], [])
        self.assertFalse(native["runtime_prerequisites_checked"])
        self.assertFalse(native["execution_available"])
        self.assertFalse(report["process_attached"])

    def test_independent_hash_path_os_and_architecture_requirements(self):
        cases = [
            ({"sha256": "0" * 64}, "Linux", "aarch64", {"client_sha256"}),
            ({"path": "/tmp/wechat"}, "Linux", "aarch64", {"client_path"}),
            ({}, "Darwin", "aarch64", {"host_os"}),
            ({}, "Linux", "x86_64", {"host_architecture"}),
            ({"machine": "EM_X86_64"}, "Linux", "aarch64", {"client_architecture"}),
        ]
        for changes, host_os, host_arch, expected in cases:
            with self.subTest(expected=expected):
                report = assess_compatibility(self.matching_identity() | changes,
                                              host_os=host_os, host_architecture=host_arch)
                self.assertEqual(report["native"]["status"], "unsupported")
                self.assertEqual(set(report["native"]["unsupported_reasons"]), expected)
                self.assertEqual(report["diagnostics"]["status"], "supported")

    def test_installed_research_sample_when_available(self):
        path = Path("/opt/wechat/wechat")
        if not path.is_file():
            self.skipTest("No installed client; no real sample compatibility claim")
        identity = inspect_identity(path)
        if identity["sha256"] != RESEARCH_TARGET["sha256"]:
            self.skipTest("Installed client is not the recorded research sample")
        self.assertEqual(identity["machine"], "EM_AARCH64")
        self.assertEqual(identity["build_id"], RESEARCH_TARGET["build_id"])
        checks = {item["requirement"]: item for item in identity["compatibility"]["native"]["checks"]}
        self.assertTrue(checks["client_sha256"]["satisfied"])
        self.assertTrue(checks["client_architecture"]["satisfied"])
        self.assertFalse(identity["process_attached"])


if __name__ == "__main__":
    unittest.main()
