"""Bounded research observations, never executable business capabilities."""

from typing import Any

from . import __version__


RESEARCH_TARGET = {
    "version": "4.1.13.26",
    "architecture": "aarch64",
    "sha256": "71e22a172018bf250b7b70493382bf55024727144eb7f13cf9b312cdf02e5bbc",
    "build_id": "67dcad7dc5ff4c67581b14a89385e3b3bfb4bbfd",
    "observed_on": "2026-10-18",
}

# Names were first found statically and then observed in the recorded runtime
# registry. Registration does not prove a callable business operation works.
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
    ("send_emoji", "发送普通Unicode表情", None),
    ("send_custom_sticker", "发送自定义表情或GIF", None),
    ("search_new_contact", "搜索新联系人", None),
    ("add_friend", "主动添加好友", None),
    ("list_friend_requests", "检查好友申请", None),
    ("accept_friend_request", "接受好友申请", None),
    ("publish_moments", "发表朋友圈", "sns::create_moments"),
    ("read_moments", "读取朋友圈", None),
    ("capture_ui", "UI截图", None),
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
FRIEND_VERIFIED = {"get_friend_info", "set_contact_remark", "list_friend_requests", "search_new_contact"}
VERIFIED = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text",
            "send_image", "send_file"} | GROUP_VERIFIED | FRIEND_VERIFIED


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
            "prototype_verified": "Actual native prototype verified; executable via opt-in backend only, client success is the send-success criterion",
            "candidate_runtime": "Name observed in recorded runtime registry; no business invocation or success verified",
            "unverified": "No usable implementation verified",
        },
        "capabilities": [
            {
                "id": name,
                "label": label,
                "status": "prototype_verified" if name in VERIFIED else "candidate_runtime" if seed else "unverified",
                "execution_available": False,
                "evidence": (
                    [{"kind": "native_runtime_verified", "source": "docs/GROUPS.md",
                      "limitation": "Ordinary test groups on the recorded build; invitations do not imply acceptance"}]
                    if name in GROUP_VERIFIED else
                    [{"kind": "native_runtime_verified", "source": "docs/FRIENDS.md",
                      "limitation": "Available local native records on the recorded build; not a remote refresh"}]
                    if name in FRIEND_VERIFIED else [{
                        "kind": "runtime_registered",
                        "seed": seed,
                        "source": "docs/FEATURES.md",
                        "source_scope": "Public capability summary; raw research and live payloads are private local artifacts",
                        "prototype_evidence": "docs/FEATURES.md#验证范围" if name in VERIFIED else None,
                        "limitation": "Recorded registration is not proof of private/group routing, parameters, permissions, or successful execution",
                    }] if seed else []
                ),
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
