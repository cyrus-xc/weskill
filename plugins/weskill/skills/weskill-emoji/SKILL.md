---
name: weskill-emoji
description: "Browse and send WeChat system expressions or custom stickers from personal favourites and online search using the local weskill MCP."
---

# weskill 表情

先查看 `get_capabilities` 并调用 `ensure_service` 复用本机服务。使用 `search_contacts` 确定用户指定的联系人或群 ID。

- **系统表情**：`list_system_emojis(keyword, limit=20, offset=0)` 查客户端识别的方括号代码，再用 `send_text_message` 发送代码，可与正文组合。不要以普通 Unicode 表情冒充微信系统表情。
- **个人收藏**：`list_saved_stickers(limit=20, offset=0)`，结果来源为 `saved`。
- **在线搜索**：`search_stickers(keyword, limit=20, cursor=null)`，结果来源为 `search`。续读保留原关键词与 `next_cursor`；素材密钥和原生游标由服务管理。
- **发送自定义表情**：从对应结果选择真实 `sticker_id`，调用 `send_sticker(recipient_id, sticker_id, source, idempotency_key)`。不要从图片链接或名称编造 ID。需要用户选择时提供预览；素材准备由客户端完成，不添加收藏。

列表默认 20 条，可自定义；`0` / `null` 遍历当前可访问记录。搜索结果和收藏列表是两个独立入口。当前不提供添加、删除或收藏表情的操作。

用户已经授权发送、目标和表情明确时直接执行。每项发送保留唯一幂等键；`client_success` 即成功，不回查历史。`not_submitted` 可以原键重试；`unknown` 保留原键且不重新发送。报告客户端实际错误，按实时能力状态说明尚未验证的范围。
