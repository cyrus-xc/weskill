# 群管理

`weskill` 是总入口与能力目录，直接提供搜索、历史、文本和本地媒体操作。`weskill-group` 负责群管理流程；两者安装在同一个插件中，共用 MCP、原生连接、幂等记录和一小时空闲退出的服务。

## 当前工具

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| `get_group_members` | `group_id, refresh=True` | 返回成员 ID、群内昵称、好友资料、群主/管理员角色与本人角色；资料来源单独标注 |
| `get_group_info` | `group_id, refresh=True` | 返回公告、XML、编辑者、发布时间与邀请确认状态 |
| `create_group` | `member_ids, name, idempotency_key` | 原生建群，返回新 `group_id`；名称可传空字符串 |
| `invite_group_members` | `group_id, member_ids, idempotency_key, mode="invite"` | `invite` 发邀请；`add` 直接添加，由微信决定是否允许 |
| `remove_group_members` | `group_id, member_ids, idempotency_key` | 将指定成员踢出群，支持多个成员 ID |
| `send_group_mention` | `group_id, text, member_ids, idempotency_key, mention_all=False` | 原生真实提及；全体可传 `member_ids=[]` |
| `set_group_announcement` | `group_id, text, idempotency_key` | 发布或替换完整纯文本公告，空文本清空 |
| `pin_group_message` | `group_id, message_id, idempotency_key, pinned=True` | 置顶指定消息；`pinned=False` 取消 |
| `set_group_invitation_confirmation` | `group_id, enabled, idempotency_key` | 开关入群需群主或管理员同意 |

群 ID 来自群搜索，联系人 ID 来自联系人搜索或成员列表。用户给出姓名时先解析，再与成员 ID 比对。当前适配普通 `@chatroom` 群，企业互通群等其他群类型尚未验证。没有群白名单，也不增加成员数量、邀请频率或每日操作配额。

## 查询来源

群查询默认走客户端原生刷新路径，`refresh=False` 明确选择本地缓存。返回的 `source` 说明资料来源；群资料还返回 `refresh_requested` 与 `refresh_complete`，请求刷新并不冒充已完成刷新。邀请确认值来自客户端联系人缓存中的群类型枚举，由微信同步更新。

成员查询返回当前客户端取得的成员 ID 与角色，不等于完整个人资料。权限最终由微信处理；工具箱不会自动授予管理员。

## 写操作与结果

每个逻辑写操作使用独立的持久 `idempotency_key`。同键绑定操作类型和参数，跨工具共享去重空间。`not_submitted` 可原键重试；已提交或 `unknown` 不自动重发。新的发布、编辑、取消或恢复动作分别使用各自的键。

客户端返回 `client_success` 即按成功处理，不做发送后的历史回查。`invite` 成功说明该邀请操作成功，不能据此声称对方已接受；`add` 被微信拒绝时原样报告，不自动换模式重发。邀请确认以原生网络状态和对应 oplog 逐项结果判断完成。

踢人先将用户指定姓名解析为该群中的成员 ID。写操作前刷新本人角色，仅群主或管理员继续；普通成员或角色查询失败时返回 `not_submitted`，不提交移除请求。复用持久幂等记录，不增加白名单或额外确认参数。

真实提及同时包含正文与原生成员 ID 列表。调用方在 `text` 中组织可读的 `@显示名`，`member_ids` 负责真实通知对象；`mention_all=True` 表示全体，可与个别成员并用。

公告编辑目前是完整纯文本替换；不会保留原公告中的富文本附件。需要在现有内容上编辑时先读取公告，按用户目标构造最终文本；用户要求的新值保留生效。测试中的恢复仅属于明确的测试约定。

置顶的 `message_id` 使用 `get_messages` 中的 `svr_id` 十进制字符串。新消息在微信分配服务器 ID 前可能为 `0`，此时还不能置顶，可稍后重新查询目标 ID。这不改变发送以客户端成功为准的规则。置顶内部按群和服务器 ID 定位真实消息，并通过客户端工厂构造所需对象。

## 验证范围

Linux ARM64 微信 4.1.13.26 的已适配构建，在专用普通测试群完成成员和本人角色查询、建群、邀请、移出成员、真实成员提及与全体提及、公告发布/编辑/清空、消息置顶/取消、邀请确认开启/关闭。直接添加入口能返回客户端错误，当前成功路径验证为邀请模式。

所有操作使用原生服务与现有执行器，没有使用 UI 自动化或新增缓存实验库。大群、企业互通群、公告富媒体与不同客户端构建尚未逐项验证。原始结果、群 ID、联系人 ID 和研究报告仅保存在本地忽略目录。

公告以纯文本为产品范围，富文本不在待办中。邀请模式满足本项目拉人入群需求，直接添加不再作为待办。群成员返回群昵称，并与好友管理共用本地联系人资料查询能力。
