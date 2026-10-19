"""Recorded validation evidence, independent of this session's execution mode."""

from typing import Any

from . import __version__


RESEARCH_TARGET = {
    "version": "4.1.13.26",
    "architecture": "aarch64",
    "sha256": "71e22a172018bf250b7b70493382bf55024727144eb7f13cf9b312cdf02e5bbc",
    "build_id": "67dcad7dc5ff4c67581b14a89385e3b3bfb4bbfd",
    "observed_on": "2026-10-18",
}

# A seed is a recorded native name, not proof that the business operation works.
# Actual validation is described separately below, including user-reported tests.
_OPERATIONS = (
    ("receive_messages", "接收消息事件", None),
    ("get_messages", "获取聊天消息", "message::list_messages"),
    ("list_contacts", "搜索联系人", "contact::search_contacts"),
    ("list_groups", "搜索群聊", "contact::search_contacts"),
    ("get_group_info", "获取群资料与公告", None),
    ("send_private_text", "发送私聊文本", "message::send_text_message"),
    ("send_group_text", "发送群聊文本", "message::send_text_message"),
    ("send_image", "发送图片", "message::send_message"),
    ("send_file", "发送文件", "message::send_message"),
    ("send_emoji", "发送微信系统表情", None),
    ("send_custom_sticker", "发送自定义表情或GIF", None),
    ("list_saved_stickers", "读取个人收藏表情", None),
    ("search_stickers", "在线搜索表情", None),
    ("search_new_contact", "搜索新联系人", None),
    ("add_friend", "主动添加好友", None),
    ("list_friend_requests", "检查好友申请", None),
    ("accept_friend_request", "接受好友申请", None),
    ("publish_moments", "发表朋友圈", "sns::create_moments"),
    ("read_moments", "读取朋友圈", None),
    ("set_contact_remark", "修改好友备注", None),
    ("get_friend_info", "获取好友信息", "contact::getcontact"),
    ("create_group", "发起群聊", None),
    ("invite_group_members", "拉朋友进群", None),
    ("remove_group_members", "踢出群成员", None),
    ("pin_group_message", "标记群置顶消息", None),
    ("send_group_announcement", "发送群公告", None),
    ("edit_group_announcement", "编辑群公告", None),
    ("group_invitation_confirmation", "开关群聊邀请确认（群主/管理员同意）", None),
    ("get_group_members", "获取群成员", None),
    ("mention_group_member", "@群成员", None),
)


GROUP_VERIFIED = {"get_group_members", "get_group_info", "create_group", "invite_group_members", "remove_group_members",
                  "mention_group_member", "send_group_announcement", "edit_group_announcement",
                  "pin_group_message", "group_invitation_confirmation"}
USER_VERIFIED = {"add_friend", "accept_friend_request"}
FRIEND_VERIFIED = {"get_friend_info", "set_contact_remark", "list_friend_requests", "search_new_contact"} | USER_VERIFIED
SOCIAL_VERIFIED = {"read_moments", "publish_moments", "send_emoji", "list_saved_stickers", "search_stickers", "send_custom_sticker"}
VERIFIED = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text",
            "send_image", "send_file"} | GROUP_VERIFIED | FRIEND_VERIFIED | SOCIAL_VERIFIED


def _evidence(name: str, seed: str | None) -> list[dict[str, Any]]:
    if name in USER_VERIFIED:
        return [{"kind": "user_reported_validation", "source": "docs/FRIENDS.md",
                 "limitation": "User confirmed real add/accept tests; other builds and account types are not covered"}]
    if name in VERIFIED:
        source = "docs/FEATURES.md#验证范围"
        limitation = "Contact/group search and local history on the recorded build; no real-time subscription"
        if name in {"send_private_text", "send_group_text"}:
            limitation = "Private and ordinary-group text sends returned client_success on the recorded build"
        elif name in {"send_image", "send_file"}:
            limitation = "Private and ordinary-group PNG/text-file sends returned client_success; other formats are not individually verified"
        elif name in GROUP_VERIFIED:
            source = "docs/GROUPS.md"
            limitation = "Ordinary test groups on the recorded build; invitations do not imply acceptance"
        elif name in FRIEND_VERIFIED:
            source = "docs/FRIENDS.md"
            limitation = "Local records, remark update/restore and native new-contact search on the recorded build; profile lookup is not a remote refresh"
        elif name == "read_moments":
            source = "docs/MOMENTS.md"
            limitation = "Timeline, personal posts and cursor continuation on the recorded build; only client-accessible history"
        elif name == "publish_moments":
            source = "docs/MOMENTS.md"
            limitation = "Text-only and single-PNG publication with private/self visibility verified; public and multi-image publication are not live-verified"
        elif name in SOCIAL_VERIFIED:
            source = "docs/EMOJI.md"
            limitation = "System tokens, saved PNG and searched GIF native send/download verified; other sticker types are not individually verified"
        return [{"kind": "native_runtime_verified", "source": source, "limitation": limitation}]
    if seed:
        return [{"kind": "runtime_registered", "seed": seed, "source": "docs/FEATURES.md",
                 "limitation": "Recorded registration is not proof of parameters, permissions, or successful execution"}]
    return []


def capability_report() -> dict[str, Any]:
    return {
        "stage": "research_diagnostics",
        "toolbox_version": __version__,
        "transport": "stdio",
        "available_tools": ["get_client_identity", "get_capabilities"],
        "business_operations_available": False,
        "research_target": dict(RESEARCH_TARGET),
        "candidate_scope": "Recorded build and runtime capture only; not automatically matched to the configured client or current process",
        "status_definitions": {
            "prototype_verified": "Native operation verified on the recorded build within its evidence limitations; this is not a current-session health check",
            "user_reported": "User reported successful real operation; not independently reproduced by the automated validation suite",
            "candidate_runtime": "Name observed in recorded runtime registry; no business invocation or success verified",
            "unverified": "No usable implementation verified",
        },
        "capabilities": [
            {
                "id": name,
                "label": label,
                "status": "user_reported" if name in USER_VERIFIED else "prototype_verified" if name in VERIFIED else "candidate_runtime" if seed else "unverified",
                "execution_available": False,
                "evidence": _evidence(name, seed),
            }
            for name, label, seed in _OPERATIONS
        ],
        "side_effect_policy": {
            "automatic_attach": False,
            "automatic_send": False,
            "network_listener": False,
            "ui_automation": False,
        },
    }
