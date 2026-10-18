# 工具约定

| 工具 | 参数 | 边界 |
| --- | --- | --- |
| `get_client_identity` | 无 | 读取 ELF 身份，不附加进程 |
| `get_capabilities` | 无 | 当前可用工具与状态 |
| `search_contacts` | `keywords` 字符串数组、`limit`、`groups_only` | 1–8 个关键词，单项最多 128 字符；上限 50 条 |
| `get_messages` | `chat_ids` 字符串数组、`limit` | 1–8 个白名单会话，每处上限 20 条 |
| `send_text_message` | `recipient_id`、`text`、`idempotency_key` | 目标须在白名单，正文最多 4096 个 UTF-16 单位，幂等键 1–128 字符 |

搜索成功时从 `result.chat_list` 读取目标，核对 `chat_id`、可用名称及结果数量。读取历史消息时保留 `svr_id` 十进制字符串。

业务结果检查 `status`、`result` 与 `errors`。MCP 层 `isError=false` 不等于客户端业务成功。

发送状态：

- `not_submitted`：未建立提交，不自动重试。
- `client_success`：客户端发送管线回调成功，未确认收件端送达。
- `client_error`：客户端回调返回错误。
- `unknown`：无法确定提交或完成状态，不自动重发。

同一幂等键绑定同一目标和正文。重复调用返回持久记录，变更参数会报错。新键意味着新操作。当前 `delivery_confirmed` 恒为 `false`。
