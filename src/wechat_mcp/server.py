"""MCP stdio entry point. Application code must never print to stdout.

API references: modelcontextprotocol/python-sdk v1.x docs/client.md and
src/mcp/server/fastmcp/server.py; annotations are protocol hints, not security.
"""

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .capabilities import capability_report
from .identity import inspect_identity, discover_client_pid


def create_server(client_path: Path, backend: Any = None) -> FastMCP:
    server = FastMCP(
        "wechat-mcp",
        instructions=(
            "Experimental local Linux WeChat toolbox. Inspect capabilities before use. "
            "Only diagnostic tools are exposed by default. Native mode adds contact/group search, "
            "allowlisted message queries and text sending. Client success does not confirm delivery."
        ),
        log_level="WARNING",
    )
    readonly = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=readonly)
    def get_client_identity() -> dict[str, Any]:
        """Read configured client ELF hash, Build ID and architecture without executing or attaching."""
        return inspect_identity(client_path)

    @server.tool(annotations=readonly)
    def get_capabilities() -> dict[str, Any]:
        """Return verified/experimental/planned features and the tools available in this session."""
        report = capability_report()
        if backend is not None:
            report["stage"] = "experimental_hooks"
            report["available_tools"].extend(["search_contacts", "get_messages", "send_text_message"])
            report["experimental_backend_enabled"] = True
            report["business_operations_available"] = True
            enabled = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text"}
            for operation in report["capabilities"]:
                if operation["id"] in enabled:
                    operation["execution_available"] = True
                    operation["constraints"] = "Researched binary only; message reads/writes require allowlisted IDs"
            report["write_policy"] = "Explicit recipient allowlist; durable idempotency key; unknown is never retried"
        return report

    if backend is not None:
        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def search_contacts(keywords: list[str], limit: int = 10, groups_only: bool = False) -> dict[str, Any]:
            """Search private contacts by default, or groups with groups_only; at most 50 matches."""
            return backend.search_contacts(keywords, limit, groups_only)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def get_messages(chat_ids: list[str], limit: int = 10) -> dict[str, Any]:
            """Read at most 20 messages per allowlisted chat. Server message IDs are decimal strings, not delivery receipts."""
            return backend.get_messages(chat_ids, limit)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def send_text_message(recipient_id: str, text: str, idempotency_key: str) -> dict[str, Any]:
            """Send once to an allowlisted internal contact/group ID. Reuse the same key after timeout; unknown never resends. Client success is not delivery confirmation."""
            return backend.send_text(recipient_id, text, idempotency_key)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Linux WeChat MCP; diagnostics by default, native hooks are opt-in")
    parser.add_argument(
        "--client-path", type=Path, default=Path("/opt/wechat/wechat"),
        help="ELF inspected on demand; never executed (default: /opt/wechat/wechat)",
    )
    parser.add_argument("--enable-experimental-hooks", action="store_true")
    parser.add_argument("--wechat-pid", type=int)
    parser.add_argument("--native-shim", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--allow-recipient", action="append", default=[])
    args = parser.parse_args()
    backend = None
    if args.enable_experimental_hooks:
        if args.native_shim is None or args.state_dir is None:
            parser.error("Experimental hooks require --native-shim and --state-dir")
        if args.wechat_pid is None:
            try:
                args.wechat_pid = discover_client_pid()
            except ValueError as error:
                parser.error(str(error))
        if args.client_path.resolve() != Path("/opt/wechat/wechat"):
            parser.error("Experimental hooks are bound to /opt/wechat/wechat")
        from .backend import ExperimentalBackend
        backend = ExperimentalBackend(args.wechat_pid, args.native_shim, args.state_dir, set(args.allow_recipient))
    create_server(args.client_path, backend=backend).run(transport="stdio")


if __name__ == "__main__":
    main()
