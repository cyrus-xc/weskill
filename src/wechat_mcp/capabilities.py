"""Bounded research observations, never executable business capabilities."""

from typing import Any


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
    ("list_contacts", "搜索联系人（有界）", "contact::search_contacts"),
    ("list_groups", "搜索群聊（有界）", "contact::search_contacts"),
    ("send_private_text", "发送私聊文本", "message::send_text_message"),
    ("send_group_text", "发送群聊文本", "message::send_text_message"),
    ("send_image", "发送图片", None),
    ("send_file", "发送文件", None),
    ("send_emoji", "发送普通Unicode表情", None),
    ("send_custom_sticker", "发送自定义表情或GIF", None),
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
    ("pin_group_message", "标记群置顶消息", None),
    ("send_group_announcement", "发送群公告", None),
    ("edit_group_announcement", "编辑群公告", None),
    ("group_invitation_confirmation", "开关群聊邀请确认（群主/管理员同意）", None),
    ("get_group_members", "获取群成员", None),
    ("mention_group_member", "@群成员", None),
)


VERIFIED = {"get_messages", "list_contacts", "list_groups", "send_private_text", "send_group_text"}


def capability_report() -> dict[str, Any]:
    return {
        "stage": "research_diagnostics",
        "transport": "stdio",
        "available_tools": ["get_client_identity", "get_capabilities"],
        "business_operations_available": False,
        "research_target": dict(RESEARCH_TARGET),
        "candidate_scope": "Recorded build and runtime capture only; not automatically matched to the configured client or current process",
        "status_definitions": {
            "prototype_verified": "Actual native prototype verified; executable via opt-in backend only, delivery not confirmed",
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
                    [{
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
