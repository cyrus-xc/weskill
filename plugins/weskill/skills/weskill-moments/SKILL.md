---
name: weskill-moments
description: "Read the WeChat Moments timeline or personal posts and publish user-authorized text or local images through the local weskill MCP."
---

# weskill 朋友圈

查看 `get_capabilities`，用 `ensure_service` 复用本机服务。

## 读取动态

`get_moments(limit=20, cursor=null, contact_id=null, include_xml=false)` 读取朋友圈时间线；指定真实联系人 ID 可读取其个人动态。通过 `search_contacts` 解析名字。

默认 20 条，可自定义；`0` / `null` 跟随当前可访问分页。续读保留原 `contact_id` 和不透明 `next_cursor`。置顶动态独立返回为 `top_moments`，不作为普通动态的分页边界。检查 `has_more`、`pagination_stalled` 和 `partial_result`，如实报告可见范围，不能把权限、缓存或分页中止称为完整历史。需要完整客户端结构时使用 `include_xml=true`。

## 发布动态

正文、图片和可见范围明确且用户已授权时，调用 `publish_moments(content, visibility, idempotency_key, image_paths)`：

- `visibility="private"` 为仅自己可见；`"public"` 按微信好友可见规则发布。可见范围必填，缺失时只补问这一项。
- `image_paths` 是 MCP 所在主机的图片路径列表；纯文字传空列表。图片可不带正文。服务负责生成上传图片和缩略图。
- 幂等键绑定正文、可见范围、路径和图片字节。超时保留同键；`unknown` 不重新发布，`not_submitted` 允许原键再试。

`client_success` 即按发布成功报告，不强制回查动态。开发或读取授权本身不包含替用户发测试动态的授权；沿用已有的明确发布授权。视频、点赞和评论不在本轮范围。
