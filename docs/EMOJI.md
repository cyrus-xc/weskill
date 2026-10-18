# 微信表情

表情由 `weskill-emoji` Skill 组织操作，与消息、好友、群管理共用本机 MCP 和一小时空闲退出服务。

## 系统表情

`list_system_emojis(keyword="", limit=20, offset=0)` 查询当前研究构建识别的方括号代码。目录直接来自客户端内置匹配表，包含中文、英文别名，不冒充稳定数字编号。

使用 `send_text_message` 发送所选代码，例如 `[微笑]`，可与正文组合。普通 Unicode emoji 仍可按文本发送。

## 自定义表情的两个入口

| 入口 | 工具 | 选择与续读 |
| --- | --- | --- |
| 个人收藏 | `list_saved_stickers(limit=20, offset=0)` | 使用 offset 与 has_more |
| 在线搜索 | `search_stickers(keyword, limit=20, cursor=null)` | 同关键词原样使用 next_cursor；服务保留页内剩余结果并跨页去重 |

默认20条，可自定义；0/null读取当前可访问记录。结果提供 `sticker_id`、`source`、预览地址和本地可用状态。下载密钥和原生对象信息保留在本机私有索引，不要求 Agent 拼接 XML 或处理解密。

`send_sticker(recipient_id, sticker_id, source, idempotency_key)` 发送所选结果，source 为 `saved` 或 `search`。先列出或搜索再选择真实 ID；目标联系人与群 ID 从联系人搜索取得。素材下载、解码与表情消息构造均复用微信原生服务，不添加收藏。两种入口共用实际表情发送管线；项目侧不需要解密转发或把图片伪装成 GIF。

同键绑定目标、来源和表情 ID。`client_success` 即成功，不回查历史；超时保留同键，unknown不自动重发，not_submitted允许原键再试。

## 验证范围

当前构建已实测系统表情代码发送、收藏 PNG 表情发送、未缓存搜索 GIF 的下载与原生发送，以及收藏列表、关键词搜索和原生跨页续读。其他素材类型与各类表情包尚未逐项验证。发送使用原生消息类型，不把表情作为普通文件发送。

添加、保存到收藏、删除和管理表情包不在当前开发范围。原始表情记录、缓存和实验报告均留在本地忽略目录。
