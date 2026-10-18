"""Exercise the real SDK handshake, discovery and calls through child stdio."""

import asyncio
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class StdioIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def connect_and_check(self, client_path: Path, check) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "weskill", "--client-path", str(client_path)],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        async with asyncio.timeout(30):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "weskill")
                    await check(session)

    async def test_discovery_and_real_identity(self) -> None:
        # A real host ELF provides a portable integration target, not a fake
        # WeChat business response. Also inspect the installed client if present.
        target = Path("/opt/wechat/wechat")
        if not target.is_file():
            target = Path(sys.executable).resolve()

        async def check(session):
            listing = await session.list_tools()
            self.assertEqual({t.name for t in listing.tools}, {"get_client_identity", "get_capabilities"})
            for tool in listing.tools:
                self.assertTrue(tool.annotations.readOnlyHint)
                self.assertFalse(tool.annotations.openWorldHint)
            identity = await session.call_tool("get_client_identity", {})
            self.assertFalse(identity.isError)
            actual = identity.structuredContent
            with target.open("rb") as stream:
                self.assertEqual(actual["sha256"], hashlib.file_digest(stream, "sha256").hexdigest())
            self.assertEqual(actual["path"], str(target.resolve()))
            self.assertFalse(actual["process_attached"])
            self.assertIn(actual["elf_class"], (32, 64))
            report = await session.call_tool("get_capabilities", {})
            self.assertFalse(report.isError)
            self.assertFalse(report.structuredContent["business_operations_available"])
            operations = report.structuredContent["capabilities"]
            self.assertGreaterEqual(len(operations), 24)
            self.assertTrue(all(not item["execution_available"] for item in operations))
            self.assertTrue(all(item["status"] in {"prototype_verified", "candidate_runtime", "unverified"} for item in operations))
            missing = await session.call_tool("send_private_text", {"text": "must not send"})
            self.assertTrue(missing.isError)

        await self.connect_and_check(target, check)

    async def test_missing_client_returns_tool_error_and_server_survives(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            async def check(session):
                failed = await session.call_tool("get_client_identity", {})
                self.assertTrue(failed.isError)
                self.assertIn("Cannot inspect configured client ELF", failed.content[0].text)
                subsequent = await session.call_tool("get_capabilities", {})
                self.assertFalse(subsequent.isError)

            await self.connect_and_check(Path(folder) / "missing", check)

    async def test_non_elf_client_returns_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "not-elf"
            target.write_text("This is not an executable.\n")

            async def check(session):
                failed = await session.call_tool("get_client_identity", {})
                self.assertTrue(failed.isError)
                self.assertIn("Cannot inspect configured client ELF", failed.content[0].text)

            await self.connect_and_check(target, check)


if __name__ == "__main__":
    unittest.main()
