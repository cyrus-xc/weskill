# 群工具约定

只读取当前任务对应的段落。以下是群操作目录；实际是否可用、参数名及返回结构以连接中的工具 schema 和 `get_capabilities` 为准。工具未开放时报告缺口，不从目录推断已经执行。

## 群资料与成员

- `get_group_info(group_id, refresh=True)`：读取群资料及已有公告。按返回值说明当前帐号的群角色与邀请确认状态；字段缺失时保留未知。
- `get_group_members(group_id, refresh=True)`：取得群成员及内部 ID。当前返回成员 ID、群主/管理员角色和本人角色，完整昵称资料尚未返回。用户给出好友名称时先用 `search_contacts` 解析，再与成员 ID 比对；重名时消歧。真实 @ 使用这些 ID。

群搜索沿用 `search_contacts(groups_only=true)`；普通群消息及历史沿用 `$weskill` 的基础工具，不需要把普通发送改成管理操作。

## 建群

`create_group(member_ids, name, idempotency_key)`

使用搜索结果中的联系人 ID 和用户指定群名；名称可选性按实际 schema。以返回的群 ID 标识创建结果。用户未要求后续消息或设置时，创建完成即结束该请求。

## 添加与邀请成员

`invite_group_members(group_id, member_ids, idempotency_key, mode="add" | "invite")`

默认 `invite`。`add` 对应客户端直接添加成员，`invite` 对应发送入群邀请。按用户意图和实际工具说明选模式；微信决定成员关系、群权限和邀请确认产生的结果。一次失败不构成自动改换模式再写一次的依据；已有明确授权覆盖另一模式时可继续，并为新的写请求记录新键。报告客户端返回的状态，区分邀请提交与实际入群。

## 踢出成员

`remove_group_members(group_id, member_ids, idempotency_key)` 将指定成员移出群。将用户给出的姓名解析为联系人 ID，再与该群成员列表比对，确定准确对象。支持一次传入多个成员 ID，写操作前刷新本人角色，仅群主或管理员继续；普通成员或角色查询失败时返回 `not_submitted`，不提交该写操作。


沿用持久幂等记录，客户端成功即报告成功，`unknown` 不自动重复提交。仅在用户明确要求重新邀请时把已移除成员加回。

## 真实 @

`send_group_mention(group_id, text, member_ids, idempotency_key, mention_all=False)`

从该群成员结果解析 `member_ids`，在正文中组织可读的 `@显示名`，同时使用原生提及工具传入实际成员 ID。仅在用户要求 @全体成员时设置 `mention_all=True`，权限按微信返回处理。工具不可用时说明真实提及尚不可执行；普通文本中的“@名字”不作为替代成功。

## 群公告

`set_group_announcement(group_id, text, idempotency_key)`

此接口以完整纯文本发布或替换公告，空文本清空；不保留原公告的富文本附件。用户要求发布或编辑时提交完整目标公告内容；按需要先读取 `get_group_info` 中的原文来完成编辑。成功后公告保持用户要求的新内容；恢复旧值仅在用户要求恢复或明确的测试约定中执行。

## 群消息置顶

`pin_group_message(group_id, message_id, idempotency_key, pinned=True)`

用该群实际消息结果中的原始 `svr_id`（作为参数 `message_id`），按 schema 指定的 ID 类型传递，保留字符串精度。`pinned=False` 对应取消群消息置顶。不要把会话置顶或收藏置顶当作这一操作。

## 群聊邀请确认

`set_group_invitation_confirmation(group_id, enabled, idempotency_key)`

此设置指“入群需要群主/管理员同意”。`enabled=True` 开启，`False` 关闭；不代表授予或撤销群管理员身份。微信返回权限不足时如实报告，不自动更改其他管理设置。

群查询默认请求原生刷新；`refresh=False` 明确读取本地缓存。以返回 `source`、`refresh_complete` 说明资料来源，邀请确认枚举来自客户端联系人缓存。刚发送消息的 `svr_id=0` 尚不能置顶，可稍后重新查询目标消息 ID；这不改变发送以 `client_success` 判断成功的规则。
