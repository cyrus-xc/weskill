# MCP 工具参考

默认诊断模式提供 `get_client_identity` 与 `get_capabilities`；显式启用原生后端后提供服务控制、消息、好友和群管理工具。工具以 MCP 会话实际返回的 schema 为准。

能力报告中的 `prototype_verified` 表示记录构建内的原生实测，`user_reported` 表示使用者反馈的实测（当前为添加/接受好友），`candidate_runtime` 仅为注册线索，`unverified` 表示尚无可用实现验证。`evidence` 给出具体范围与公开说明；`execution_available` 才表示当前模式是否提供该操作，不代表已经附加或检查了当前客户端健康。

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `ensure_service` | 无 | 启动或续期共享服务，空闲一小时退出 |
| `get_service_status` | 无 | 查询当前服务，不启动已停止服务；请求会续期 |
| `stop_service` | 无 | 无在途请求时停止服务 |
| `get_client_identity` | 无 | 读取配置的 ELF 架构、SHA256 与 Build ID |
| `get_capabilities` | 无 | 查询当前模式、可用工具与功能状态 |
| `search_contacts` | `keywords: string[]`、`limit=10`、`groups_only=false`、`sort_by_time=false` | 搜索联系人；设 `groups_only=true` 搜索群；条数和排序由调用方选择 |
| `get_messages` | `chat_ids: string[]`、`limit=20`、`include_xml=false` | 批量会话数量不设上限；正整数指定条数，`0` / `null` 拉全部 |
| `send_text_message` | `recipient_id: string`、`text: string`、`idempotency_key: string` | 向已确认的目标提交一次文本操作 |
| `send_image` | `recipient_id`、`file_path`、`idempotency_key` | 发送本机图片；私聊与普通群已验证 |
| `send_file` | `recipient_id`、`file_path`、`idempotency_key` | 发送本机文件；无工具箱大小或扩展名白名单 |

`chat_id` 是微信内部会话标识，来自搜索结果。群使用群标识，私聊使用联系人标识；不要由昵称推测 ID。

## 搜索与读取

```json
{"keywords": ["测试"], "limit": 5, "groups_only": true}
```

成功结果的 `result.chat_list` 包含匹配项的 `chat_id` 及可用名称。多个匹配项时由用户确定目标。空结果或失败状态不能当作目标存在的证据。

```json
{"chat_ids": ["<已确认的 chat_id>"], "limit": 5}
```

消息中的 `svr_id` 使用十进制字符串，避免 64 位 ID 经 JavaScript 数值解析后丢失精度。默认返回每会话最近 20 条。任意正整数指定数量，`limit=0` 或 `null` 读取全部本机可读记录；内部按时间分页，处理边界重叠和同秒多条消息。记录按时间顺序返回，客户端没有的远端历史不会凭空补齐。`include_xml=true` 可返回原始 XML。

## 发送

```json
{
  "recipient_id": "<已确认的 chat_id>",
  "text": "连接测试完成",
  "idempotency_key": "<为这一次用户请求生成并保存的唯一键>"
}
```

同一个键绑定相同目标与正文。再次调用返回原记录；换目标或内容会报错。超时、重连、客户端重启后继续保留原键与所用安装环境的操作账本，以免重复发送。新请求使用新键。

| 状态 | 解释 |
| --- | --- |
| `not_submitted` | 未建立提交；可用原键再次调用 |
| `client_success` | 按本项目标准发送成功；不再做历史回查 |
| `client_error` | 客户端回调返回错误 |
| `unknown` | 无法确定是否提交或完成；不自动重发 |

发送成功标准为 `client_success`。兼容字段 `delivery_confirmed=false` 不影响成功判断，不要求收件方确认或历史回查。

## 目标选择与调用限制

npm 入口 `weskill mcp` 与源码启动器 `scripts/run_local_mcp.py` 均无需联系人配置文件。联系人或群的内部 ID 从搜索结果取得，查询与发送时直接传入，更换目标无需重启服务。npm CLI 用 `--data-dir` 选择用户数据根目录；源码启动器用 `--native-shim`、`--state-dir` 指定库和账本路径。详见 [安装指南](INSTALL.md)。

`get_capabilities.recipient_policy.allowlist_required=false` 表示当前实现已取消目标预登记。发送仍以用户明确指定的目标与正文为依据，并使用持久幂等键。

进程附加失败时，先确认本机微信已登录、MCP 能看到宿主进程且构建匹配。身份校验失败时停止原生调用；需要新的适配。不要将进程 ID、地址偏移或任意新库替换视为普通重试。

## 连接诊断

原生连接在独立常驻子进程中建立，最多尝试两个全新的进程，每次附加设置 15 秒超时。启动超时会清理尚未接收业务请求的进程，再重建一次；权限错误、外部取消或身份变化直接返回错误。业务请求一旦写入管道，就不再重试或强行终止可能仍持有回调的进程。

错误响应可能包含 `error_code`、`failure_stage` 与 `diagnostics`。`connection_timeout` 表示两次连接均超时，尚未提交业务；`operation_cancelled` 需结合失败阶段和 `status` 判断。`diagnostics` 记录耗时、连接尝试次数和 `isolation=native_worker`，不含聊天正文。

无论在哪一步失败，消息发送都保留持久幂等记录。提交阶段发生取消时返回 `unknown`，已提交或结果不明时同键调用不会重发；明确未提交时可原键再试。升级后重新连接 MCP，使用 `get_capabilities.connection_policy` 检查新服务已加载。

## 服务生命周期

多个本机 MCP 会话共享同一 Unix socket 服务。`ensure_service` 只确保控制服务运行，原生连接在首次业务请求时建立；其余请求复用连接。空闲一小时后自动退出，有在途请求或正在清理的工作进程时继续等待，不强制中断。

手动停止后，下次业务请求会自动启动。微信 PID 或原生库、记录目录变更导致配置不匹配时，先停止旧服务再重新连接 MCP。npm 安装的运行信息与 socket 在用户数据目录 `state/service/`，账本在 `state/operations/`；源码方式对应 `.state/` 下的同名目录。停止服务不会清除记录。

`native_connected` 表示已建立的原生工作进程仍在运行，业务连接是否可用以每次调用结果为准。客户端使用本地连接缓存，不要求助手反复扫描进程。

完整的参数与运行限制说明见 [当前约束清单](LIMITS.md)。

## 本地媒体

`file_path` 使用 MCP 所在主机上的文件路径，推荐绝对路径。先确认用户要发送的文件和目标，再调用 `send_image` 或 `send_file`。两者共享文本发送的幂等键空间；同键绑定操作类型、目标、规范路径和文件 SHA256。内容变化使用新发送任务与新键，`unknown` 不重发。返回 `file_name` 是实际发送名称，原名含 XML 特殊字符或与缓存中不同文件重名时会调整名称。

媒体会复制到活跃微信帐号缓存以供原生发送，缓存保留供客户端后续渲染。工具箱不设置文件大小或扩展名上限；格式和大小能否发送由客户端决定。当前实测为私聊与普通群的 PNG、文本文件，其他格式尚未逐项验证。

## 群管理工具

原生模式另提供 `get_group_members`、`get_group_info`、`create_group`、`invite_group_members`、`remove_group_members`、`send_group_mention`、`set_group_announcement`、`pin_group_message`、`set_group_invitation_confirmation`。参数、字段来源及真实验证范围见 [群管理说明](GROUPS.md)。当前开发版本共 32 个工具，默认诊断模式仍为 2 个。

## 好友管理

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `get_friend_info` | `contact_ids: string[]` | 读取可用本地完整联系人记录，不请求远端刷新 |
| `set_contact_remark` | `contact_id, remark, idempotency_key` | 设置备注；空字符串清除 |
| `list_friend_requests` | `limit=20, offset=0` | 读取申请记录；0/null为全部；原生状态缺失时保留未知 |
| `search_new_contact` | `query` | 通过微信原生通道搜索指定微信号等标识，不提交申请 |
| `add_friend` | `query, idempotency_key, greeting="", remark=""` | 原生搜索后以真实验证凭据提交申请 |
| `accept_friend_request` | `request_id, idempotency_key, remark=null` | 使用所选申请的原生凭据接受；null保留其备注 |

搜索新联系人已做原生验证，主动添加及接受申请由使用者确认实测通过，见 [好友管理说明](FRIENDS.md)。以能力报告的验证状态和证据范围区分两类来源。

## 表情与朋友圈

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `list_system_emojis` | `keyword="", limit=20, offset=0` | 发现原生系统表情代码，使用文本工具发送 |
| `list_saved_stickers` | `limit=20, offset=0` | 读取个人收藏表情，不添加收藏 |
| `search_stickers` | `keyword, limit=20, cursor=null` | 微信在线搜索，保留不透明游标续读 |
| `send_sticker` | `recipient_id, sticker_id, source, idempotency_key` | 发送所选收藏或搜索结果，来源为 saved/search |
| `get_moments` | `limit=20, cursor=null, contact_id=null, include_xml=false` | 时间线或个人动态，置顶单独返回 |
| `publish_moments` | `content, visibility, idempotency_key, image_paths=[]` | 发布文字和/或本机图片，private仅自己可见/public好友可见 |

列表默认20，支持自定义条数；0/null跟随全部当前可访问记录。微信可见权限、缓存和分页中止会明确报告。字段与验证范围见 [表情](EMOJI.md) 和 [朋友圈](MOMENTS.md)。

## 原生资源诊断

业务结果的 `diagnostics.resources` 包含 `resident_scripts`、`pending_agents`、`agents_created`、`agents_released` 与 `bridge_reused`。同一 worker 复用一个执行桥，健康且回调对象已销毁的请求完成后，通常为一个驻留桥、零待回收业务脚本。发送成功仍只依据 `client_success`；资源释放检查不要求收件方确认，也不查询历史。延迟销毁的脚本在后续请求回收，状态不明的原生引用继续保留。

`get_client_identity` 的 `compatibility` 字段分开报告只读 ELF 诊断与 native 构建匹配；静态匹配不代表登录、连接或业务健康。详见 [兼容性说明](COMPATIBILITY.md)。


## 增量事件

`get_events(account_id, cursor=0, limit=100, resume=False)` 通过已有原生查询提供私聊消息与新好友申请的持久化拉取流。`account_id` 是调用者确认的当前登录账号命名空间，不是自动账号识别。首次调用只建立历史基线；后续返回 `events`、`cursor`、`head` 和 `source=native_history_poll`。保存事件后再保存游标；断开和重启后使用原游标继续，重复读取同一游标返回相同已保存事件。`limit=0/null` 返回全部排队事件，没有工具箱条数上限。

事件数据保存在本地私有状态目录。该接口不发送消息、不接受申请，不使用鼠标或键盘；轮询前已被删除且未保留本地记录的消息可能无法捕获。好友申请中的未知状态仍是未知状态，不因事件出现就自动认定有效或待接受。

事件轮询会缓存快照与查询容量：会话列表每15秒检查一次，好友申请每60秒一次；重复读游标不会绕过时间表。首次基线不拉取全部历史，后续按新增范围从20条扩展。原生失败将持久暂停，重启不会自动解除；核对客户端后显式传入 `resume=True` 才恢复。遵循 `status`、`pause_reason` 和 `next_poll_seconds`，不要通过快速循环重试。后台申请采集不逐条补查联系人关系，unknown 不代表有效待接受申请。

所有原生操作及历史分页统一限制为每用户任意60秒最多20次，达到额度会等待；状态查询不计入。该额度不是反外挂安全保证。

原生操作共享跨进程互斥锁，操作结束后继续持锁随机1–3秒（失败也冷却），之后才允许下一次原生操作；分页逐页加锁。本机状态查询和缓存读取不等待此锁。20次/滚动60秒额度同时生效。`rate_limit.cooldown_seconds` 记录本次冷却，服务状态返回冷却区间和剩余时间。
