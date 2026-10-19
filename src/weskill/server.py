"""MCP stdio entry point. Application code must never print to stdout.

API references: modelcontextprotocol/python-sdk v1.x docs/client.md and
src/mcp/server/fastmcp/server.py; annotations are protocol hints, not security.
"""

import argparse
from pathlib import Path
from typing import Any, Literal

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
            "message queries and user-authorized text, local image and file sending. Friend and group management, system/custom stickers and Moments share the same service. Client success is the success criterion."
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
                "set_group_invitation_confirmation", "remove_group_members",
                                              "get_friend_info", "set_contact_remark", "list_friend_requests", "search_new_contact", "add_friend", "accept_friend_request", "list_system_emojis", "list_saved_stickers", "search_stickers", "send_sticker", "get_moments", "publish_moments"])
            report["experimental_backend_enabled"] = True
            report["connection_policy"] = {"max_attempts": 2, "attach_timeout_seconds": 15,
                                           "retry_scope": "fresh_worker_only_before_business_requests",
                                           "isolation": "native_worker"}
            report["service_policy"] = {"idle_timeout_seconds": 3600, "transport": "unix_socket",
                                        "shared_across_mcp_sessions": True}
            report["resource_policy"] = {"executor_bridge": "shared_per_worker",
                                         "business_agents": "release_after_native_task_idle_and_callback_destroy",
                                         "pending_agents": "retain_until_proven_finished; recheck_on_next_request"}
            report["history_policy"] = {"default_limit": 20, "max_limit": None,
                                        "all_records": "limit=0 or null", "include_xml": "caller_selected"}
            report["send_success_policy"] = "client_success; no history verification"
            report["recipient_policy"] = {"allowlist_required": False,
                                          "target": "explicit_contact_or_group_id"}
            report["business_operations_available"] = True
            enabled = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text", "send_image", "send_file", "get_group_members", "get_group_info",
                       "create_group", "invite_group_members", "mention_group_member", "send_group_announcement",
                       "edit_group_announcement", "pin_group_message", "group_invitation_confirmation",
                       "remove_group_members", "get_friend_info", "set_contact_remark", "list_friend_requests", "search_new_contact", "add_friend", "accept_friend_request", "send_emoji", "list_saved_stickers", "search_stickers", "send_custom_sticker", "read_moments", "publish_moments"}
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
            """Send a local image once to a confirmed internal contact/group ID. Private and ordinary-group PNG sending is verified; other image formats are not individually verified. No toolkit size/extension cap. Client success is sufficient. Preserve the key after timeout."""
            return backend.send_image(recipient_id, file_path, idempotency_key)

        @server.tool(annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        ))
        def send_file(recipient_id: str, file_path: str, idempotency_key: str) -> dict[str, Any]:
            """Send a local file once. Private and ordinary-group text-file sending is verified; other formats are not individually verified. No toolkit size/extension cap. Same key binds target, source path and bytes. Client success is sufficient; unknown never resends."""
            return backend.send_file(recipient_id, file_path, idempotency_key)


        group_read = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=True)
        group_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                      idempotentHint=True, openWorldHint=True)

        group_destructive = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=True, openWorldHint=True)

        @server.tool(annotations=group_read)
        def list_system_emojis(keyword: str = '', limit: int | None = 20,
                               offset: int = 0) -> dict[str, Any]:
            """List native system-expression tokens such as [微笑]. Send a chosen token with send_text_message. Default 20; 0/null returns all matching tokens."""
            from .emoji import system_emojis
            return system_emojis(keyword, limit, offset)

        @server.tool(annotations=group_read)
        def list_saved_stickers(limit: int | None = 20, offset: int = 0) -> dict[str, Any]:
            """List personal favourite stickers with source=saved and selectable sticker_id. Does not add favourites. Default 20; 0/null returns all; no toolkit count cap."""
            return backend.list_saved_stickers(limit, offset)

        @server.tool(annotations=group_read)
        def search_stickers(keyword: str, limit: int | None = 20,
                            cursor: str | None = None) -> dict[str, Any]:
            """Search custom stickers online through WeChat. Use next_cursor with the same keyword for stable continuation. source=search; no favourite is added. Default 20; 0/null follows all available native pages."""
            return backend.search_stickers(keyword, limit, cursor)

        @server.tool(annotations=group_write)
        def send_sticker(recipient_id: str, sticker_id: str, source: Literal["saved", "search"],
                          idempotency_key: str) -> dict[str, Any]:
            """Send a sticker selected from saved/search results. The client downloads its material if needed without adding it to favourites. Native client_success is sufficient. Preserve the key after timeout; unknown never resends."""
            return backend.send_sticker(recipient_id, sticker_id, source, idempotency_key)

        @server.tool(annotations=group_read)
        def get_moments(limit: int | None = 20, cursor: str | None = None,
                        contact_id: str | None = None, include_xml: bool = False) -> dict[str, Any]:
            """Read the native Moments timeline, or a specific contact's posts. Default 20; 0/null follows all accessible pages. Preserve opaque next_cursor and its contact scope. Top posts are separate. Access is decided by WeChat; all means accessible pages, not every historical post."""
            return backend.get_moments(limit, cursor, contact_id, include_xml)

        @server.tool(annotations=group_write)
        def publish_moments(content: str, visibility: Literal["private", "public"], idempotency_key: str,
                            image_paths: list[str] | None = None) -> dict[str, Any]:
            """Publish text and/or local images. visibility is explicit: private means only self; public means friends allowed by WeChat. Preserve content, paths, visibility and key after timeout. Client success confirms publication; unknown never republishes."""
            return backend.publish_moments(content, visibility, idempotency_key, image_paths)

        @server.tool(annotations=group_read)
        def get_friend_info(contact_ids: list[str]) -> dict[str, Any]:
            """Read complete available local-native contact records for confirmed contact/member IDs, including nicknames, remarks, region, signature and avatars. This does not request a remote refresh. Missing records/fields are reported explicitly."""
            return backend.get_friend_info(contact_ids)

        @server.tool(annotations=group_read)
        def list_friend_requests(limit: int | None = 20, offset: int = 0) -> dict[str, Any]:
            """Read local friend-request records, newest first. Default 20; 0/null reads all; offset pages records. Native status is reported; unknown status is not assumed pending."""
            return backend.list_friend_requests(limit, offset)

        @server.tool(annotations=group_read)
        def search_new_contact(query: str) -> dict[str, Any]:
            """Search the exact user-provided WeChat identifier through the native client. This does not send a friend request; verification credentials stay internal."""
            return backend.search_new_contact(query)

        @server.tool(annotations=group_write)
        def add_friend(query: str, idempotency_key: str, greeting: str = '', remark: str = '') -> dict[str, Any]:
            """Search the user-specified WeChat identifier through the client, then submit a friend request with its real verification credentials. Client success confirms this operation; it does not prove the recipient accepted. Preserve the key after timeout."""
            return backend.add_friend(query, idempotency_key, greeting, remark)

        @server.tool(annotations=group_write)
        def accept_friend_request(request_id: str, idempotency_key: str,
                                  remark: str | None = None) -> dict[str, Any]:
            """Accept the user-selected request from list_friend_requests, using its current native ticket and scene. None preserves the record's remark; empty text clears it. Client success is sufficient; unknown is never replayed."""
            return backend.accept_friend_request(request_id, idempotency_key, remark)

        @server.tool(annotations=group_write)
        def set_contact_remark(contact_id: str, remark: str, idempotency_key: str) -> dict[str, Any]:
            """Set the user-requested friend remark; empty text clears it. Client success is sufficient. Preserve the original key and value after timeout; unknown is never resubmitted."""
            return backend.set_contact_remark(contact_id, remark, idempotency_key)

        @server.tool(annotations=group_destructive)
        def remove_group_members(group_id: str, member_ids: list[str], idempotency_key: str) -> dict[str, Any]:
            """Remove the user-specified members from a group through WeChat. Requires this account to be owner/admin after a native role refresh. Resolve names to actual member IDs first. Client success is sufficient; preserve the key after timeout and never replay unknown."""
            return backend.remove_group_members(group_id, member_ids, idempotency_key)

        @server.tool(annotations=group_read)
        def get_group_members(group_id: str, refresh: bool = True) -> dict[str, Any]:
            """Read all group members, roles, nicknames and available contact profiles. Refresh controls the native member list; profiles come from local contact records. Inspect profiles_status and missing records."""
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
