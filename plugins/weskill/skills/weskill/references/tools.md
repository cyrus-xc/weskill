# 工具约定

| 工具 | 参数 | 边界 |
| --- | --- | --- |
| `ensure_service` | 无 | 启动或续期本机共享服务；空闲一小时退出 |
| `get_service_status` | 无 | 查询状态，不启动已停止服务；请求会续期 |
| `stop_service` | 无 | 无在途请求时停止服务 |
| `get_client_identity` | 无 | 读取 ELF 身份，不附加进程 |
| `get_capabilities` | 无 | 当前可用工具与状态 |
| `search_contacts` | `keywords`、`limit`、`groups_only`、`sort_by_time` | 关键词数量和长度无工具箱上限；自定义结果条数和排序 |
| `get_messages` | `chat_ids`、`limit=20`、`include_xml=false` | 批量数量不设上限；任意正整数条数，`0` / `null` 拉全部本机可读历史 |
| `send_text_message` | `recipient_id`、`text`、`idempotency_key` | 使用已确认的内部 ID，无需预登记；正文和幂等键没有工具箱长度上限 |
| `send_image` | `recipient_id`、`file_path`、`idempotency_key` | 发送本机图片；私聊已验证，群媒体尚未实测 |
| `send_file` | `recipient_id`、`file_path`、`idempotency_key` | 发送本机文件；无工具箱大小或扩展名白名单 |

搜索成功时从 `result.chat_list` 读取目标，核对 `chat_id`、可用名称及结果数量。读取历史消息时保留 `svr_id` 十进制字符串。

业务结果检查 `status`、`result` 与 `errors`。MCP 层 `isError=false` 不等于客户端业务成功。

发送状态：

- `not_submitted`：未建立提交，可原键再次调用。
- `client_success`：发送成功；不做历史回查。
- `client_error`：客户端回调返回错误。
- `unknown`：无法确定提交或完成状态，不自动重发。

同一幂等键绑定同一目标和正文。已提交或结果不明时重复调用返回持久记录；未提交可原键再试，变更参数会报错。新键意味着新操作。兼容字段 `delivery_confirmed=false` 不影响 `client_success` 的成功判断。

## 本地媒体

`file_path` 使用 MCP 所在主机上的文件路径，推荐绝对路径。先确认用户要发送的文件和目标，再调用 `send_image` 或 `send_file`。两者共享文本发送的幂等键空间；同键绑定操作类型、目标、规范路径和文件 SHA256。内容变化使用新发送任务与新键，`unknown` 不重发。返回 `file_name` 是实际发送名称，原名含 XML 特殊字符或与缓存中不同文件重名时会调整名称。

媒体会复制到活跃微信帐号缓存以供原生发送，缓存保留供客户端后续渲染。工具箱不设置文件大小或扩展名上限；格式和大小能否发送由客户端决定。当前实测为私聊与普通群的 PNG、文本文件，其他格式尚未逐项验证。
