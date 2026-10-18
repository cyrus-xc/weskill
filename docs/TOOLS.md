# MCP 工具参考

默认诊断模式提供 `get_client_identity` 与 `get_capabilities`；显式启用原生后端后增加十四项业务工具和三项服务控制工具。工具以 MCP 会话实际返回的 schema 为准。

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
| `send_image` | `recipient_id`、`file_path`、`idempotency_key` | 发送本机图片；私聊已验证，群媒体尚未实测 |
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

同一个键绑定相同目标与正文。再次调用返回原记录；换目标或内容会报错。超时、重连、客户端重启后继续保留原键与 `.state/operations`，以免重复发送。新请求使用新键。

| 状态 | 解释 |
| --- | --- |
| `not_submitted` | 未建立提交；可用原键再次调用 |
| `client_success` | 按本项目标准发送成功；不再做历史回查 |
| `client_error` | 客户端回调返回错误 |
| `unknown` | 无法确定是否提交或完成；不自动重发 |

发送成功标准为 `client_success`。兼容字段 `delivery_confirmed=false` 不影响成功判断，不要求收件方确认或历史回查。

## 目标选择与调用限制

`scripts/run_local_mcp.py` 无需联系人配置文件。联系人或群的内部 ID 从搜索结果取得，查询与发送时直接传入，更换目标无需重启服务。可通过 `--native-shim`、`--state-dir` 指定原生库和私有记录目录的绝对路径。

`get_capabilities.recipient_policy.allowlist_required=false` 表示当前实现已取消目标预登记。发送仍以用户明确指定的目标与正文为依据，并使用持久幂等键。

进程附加失败时，先确认本机微信已登录、MCP 能看到宿主进程且构建匹配。身份校验失败时停止原生调用；需要新的适配。不要将进程 ID、地址偏移或任意新库替换视为普通重试。

## 连接诊断

原生连接在独立常驻子进程中建立，最多尝试两个全新的进程，每次附加设置 15 秒超时。启动超时会清理尚未接收业务请求的进程，再重建一次；权限错误、外部取消或身份变化直接返回错误。业务请求一旦写入管道，就不再重试或强行终止可能仍持有回调的进程。

错误响应可能包含 `error_code`、`failure_stage` 与 `diagnostics`。`connection_timeout` 表示两次连接均超时，尚未提交业务；`operation_cancelled` 需结合失败阶段和 `status` 判断。`diagnostics` 记录耗时、连接尝试次数和 `isolation=native_worker`，不含聊天正文。

无论在哪一步失败，消息发送都保留持久幂等记录。提交阶段发生取消时返回 `unknown`，已提交或结果不明时同键调用不会重发；明确未提交时可原键再试。升级后重新连接 MCP，使用 `get_capabilities.connection_policy` 检查新服务已加载。

## 服务生命周期

多个本机 MCP 会话共享同一 Unix socket 服务。`ensure_service` 只确保控制服务运行，原生连接在首次业务请求时建立；其余请求复用连接。空闲一小时后自动退出，有在途请求或正在清理的工作进程时继续等待，不强制中断。

手动停止后，下次业务请求会自动启动。微信 PID 或原生库、记录目录变更导致配置不匹配时，先停止旧服务再重新连接 MCP。运行信息和 socket 在私有 `.state/service/`；发送记录仍在原 `.state/operations/`，停止服务不会清除记录。

`native_connected` 表示已建立的原生工作进程仍在运行，业务连接是否可用以每次调用结果为准。客户端使用本地连接缓存，不要求助手反复扫描进程。

完整的参数与运行限制说明见 [当前约束清单](LIMITS.md)。

## 本地媒体

`file_path` 使用 MCP 所在主机上的文件路径，推荐绝对路径。先确认用户要发送的文件和目标，再调用 `send_image` 或 `send_file`。两者共享文本发送的幂等键空间；同键绑定操作类型、目标、规范路径和文件 SHA256。内容变化使用新发送任务与新键，`unknown` 不重发。返回 `file_name` 是实际发送名称，原名含 XML 特殊字符或与缓存中不同文件重名时会调整名称。

媒体会复制到活跃微信帐号缓存以供原生发送，缓存保留供客户端后续渲染。工具箱不设置文件大小或扩展名上限；格式和大小能否发送由客户端决定。当前实测为私聊 PNG 与文本文件，其他格式和群媒体尚未逐项验证。

## 群管理工具

原生模式另提供 `get_group_members`、`get_group_info`、`create_group`、`invite_group_members`、`remove_group_members`、`send_group_mention`、`set_group_announcement`、`pin_group_message`、`set_group_invitation_confirmation`。参数、字段来源及真实验证范围见 [群管理说明](GROUPS.md)。总计 19 个工具，默认诊断模式仍为 2 个。
