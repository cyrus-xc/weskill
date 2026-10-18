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
from .identity import inspect_identity


def create_server(client_path: Path, backend: Any = None) -> FastMCP:
    server = FastMCP(
        "weskill",
        instructions=(
            "Experimental local Linux WeChat toolbox. Inspect capabilities before use. "
            "Only diagnostic tools are exposed by default. In native mode ensure_service starts a shared local service, which expires after one idle hour. Native mode adds contact/group search, "
            "message queries and user-authorized text, local image and file sending. Native group management shares the same service. Client success is the success criterion."
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
            report["available_tools"].extend(["ensure_service", "get_service_status", "stop_service",
                                              "search_contacts", "get_messages", "send_text_message", "send_image", "send_file",
                "get_group_members", "get_group_info", "create_group", "invite_group_members",
                "send_group_mention", "set_group_announcement", "pin_group_message",
                "set_group_invitation_confirmation", "remove_group_members"])
            report["experimental_backend_enabled"] = True
            report["connection_policy"] = {"max_attempts": 2, "attach_timeout_seconds": 15,
                                           "retry_scope": "fresh_worker_only_before_business_requests",
                                           "isolation": "native_worker"}
            report["service_policy"] = {"idle_timeout_seconds": 3600, "transport": "unix_socket",
                                        "shared_across_mcp_sessions": True}
            report["history_policy"] = {"default_limit": 20, "max_limit": None,
                                        "all_records": "limit=0 or null", "include_xml": "caller_selected"}
            report["send_success_policy"] = "client_success; no history verification"
            report["recipient_policy"] = {"allowlist_required": False,
                                          "target": "explicit_contact_or_group_id"}
            report["business_operations_available"] = True
            enabled = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text", "send_image", "send_file", "get_group_members", "get_group_info",
                       "create_group", "invite_group_members", "mention_group_member", "send_group_announcement",
                       "edit_group_announcement", "pin_group_message", "group_invitation_confirmation",
                       "remove_group_members"}
            for operation in report["capabilities"]:
                if operation["id"] in enabled:
                    operation["execution_available"] = True
                    operation["constraints"] = "Researched binary only; use explicit contact/group IDs"
            report["write_policy"] = "Explicit user request and recipient ID; durable idempotency key; unknown is never retried"
        return report

    if backend is not None:
        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ))
        def ensure_service() -> dict[str, Any]:
            """Start or renew the shared local service; expires after one idle hour. Does not send messages or attach by itself."""
            return backend.ensure_service()

        @server.tool(annotations=readonly)
        def get_service_status() -> dict[str, Any]:
            """Read local service state; a request renews its idle deadline. Does not start a stopped service."""
            return backend.get_service_status()

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ))
        def stop_service() -> dict[str, Any]:
            """Stop the shared service if idle; refuse while an operation or native drain is active."""
            return backend.stop_service()

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def search_contacts(keywords: list[str], limit: int = 10, groups_only: bool = False,
                            sort_by_time: bool = False) -> dict[str, Any]:
            """Search contacts or groups with a caller-selected positive count and sorting; no toolkit count cap."""
            return backend.search_contacts(keywords, limit, groups_only, sort_by_time)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def get_messages(chat_ids: list[str], limit: int | None = 20, include_xml: bool = False) -> dict[str, Any]:
            """Read local history, default 20 per chat. Set any positive count, or 0/null for all. include_xml returns raw XML."""
            return backend.get_messages(chat_ids, limit, include_xml)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def send_text_message(recipient_id: str, text: str, idempotency_key: str) -> dict[str, Any]:
            """Send once to a user-specified internal contact/group ID. Reuse the same key after timeout; unknown never resends. Client success means the send succeeded; no history verification is required."""
            return backend.send_text(recipient_id, text, idempotency_key)


        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def send_image(recipient_id: str, file_path: str, idempotency_key: str) -> dict[str, Any]:
            """Send a local image once to a confirmed internal contact/group ID. Private-chat native sending is verified; group media is untested. No toolkit size/extension cap. Client success is sufficient. Preserve the key after timeout."""
            return backend.send_image(recipient_id, file_path, idempotency_key)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def send_file(recipient_id: str, file_path: str, idempotency_key: str) -> dict[str, Any]:
            """Send a local file once. Private-chat native sending is verified; group media is untested. No toolkit size/extension cap. Same key binds target, source path and bytes. Client success is sufficient; unknown never resends."""
            return backend.send_file(recipient_id, file_path, idempotency_key)


        group_read = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=True)
        group_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                      idempotentHint=True, openWorldHint=True)

        group_destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=True, openWorldHint=True)

        @server.tool(annotations=group_destructive)
        def remove_group_members(group_id: str, member_ids: list[str], idempotency_key: str) -> dict[str, Any]:
            """Remove the user-specified members from a group through WeChat. Requires this account to be owner/admin after a native role refresh. Resolve names to actual member IDs first. Client success is sufficient; preserve the key after timeout and never replay unknown."""
            return backend.remove_group_members(group_id, member_ids, idempotency_key)

        @server.tool(annotations=group_read)
        def get_group_members(group_id: str, refresh: bool = True) -> dict[str, Any]:
            """Read all native group member IDs, owner/admin roles and this account's role. Refreshes by default; false selects local cache. Full member profiles/nicknames are not yet returned."""
            return backend.get_group_members(group_id, refresh)

        @server.tool(annotations=group_read)
        def get_group_info(group_id: str, refresh: bool = True) -> dict[str, Any]:
            """Read group announcement, XML and invitation-confirmation state. Requests native refresh by default; inspect source/refresh_complete. Confirmation state follows the native contact cache."""
            return backend.get_group_info(group_id, refresh)

        @server.tool(annotations=group_write)
        def create_group(member_ids: list[str], name: str, idempotency_key: str) -> dict[str, Any]:
            """Create a group with confirmed contact IDs; name may be empty. Returns the native-created group_id. Preserve the key after timeout; unknown never resends."""
            return backend.create_group(member_ids, name, idempotency_key)

        @server.tool(annotations=group_write)
        def invite_group_members(group_id: str, member_ids: list[str], idempotency_key: str,
                                 mode: str = 'invite') -> dict[str, Any]:
            """Invite contacts to a group. Default invite uses the verified invitation route; add selects direct addition. WeChat decides eligibility. Invitation success does not prove acceptance. No automatic mode switching."""
            return backend.invite_group_members(group_id, member_ids, idempotency_key, mode)

        @server.tool(annotations=group_write)
        def send_group_mention(group_id: str, text: str, member_ids: list[str],
                               idempotency_key: str, mention_all: bool = False) -> dict[str, Any]:
            """Send text with real native mention metadata. Use member IDs; pass [] with mention_all=true for everyone. Caller composes visible @ labels in text. Client success is sufficient, without history verification."""
            return backend.send_group_mention(group_id, text, member_ids, idempotency_key, mention_all)

        @server.tool(annotations=group_write)
        def set_group_announcement(group_id: str, text: str, idempotency_key: str) -> dict[str, Any]:
            """Publish or replace the whole group announcement with plain text; empty text clears it. Rich attachments are not preserved by this tool. Native completion determines success."""
            return backend.set_group_announcement(group_id, text, idempotency_key)

        @server.tool(annotations=group_write)
        def pin_group_message(group_id: str, message_id: str, idempotency_key: str,
                              pinned: bool = True) -> dict[str, Any]:
            """Pin/unpin an actual group message by decimal server ID (get_messages.svr_id), preserving uint64 precision. New messages may have svr_id=0 until assigned; select a valid ID before pinning."""
            return backend.pin_group_message(group_id, message_id, idempotency_key, pinned)

        @server.tool(annotations=group_write)
        def set_group_invitation_confirmation(group_id: str, enabled: bool,
                                               idempotency_key: str) -> dict[str, Any]:
            """Enable/disable invitation approval by the group owner/admin. This changes the join-approval setting. Success requires native network and per-item oplog success; unknown never resends."""
            return backend.set_group_invitation_confirmation(group_id, enabled, idempotency_key)

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
    args = parser.parse_args()
    backend = None
    if args.enable_experimental_hooks:
        if args.native_shim is None or args.state_dir is None:
            parser.error("Experimental hooks require --native-shim and --state-dir")
        if args.client_path.resolve() != Path("/opt/wechat/wechat"):
            parser.error("Experimental hooks are bound to /opt/wechat/wechat")
        from .service_client import ServiceBackend
        backend = ServiceBackend(args.wechat_pid, args.native_shim, args.state_dir)
    create_server(args.client_path, backend=backend).run(transport="stdio")


if __name__ == "__main__":
    main()
