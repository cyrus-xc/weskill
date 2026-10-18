# MCP 工具参考

默认诊断模式提供前两项；显式启用原生后端后增加三项业务工具。工具以 MCP 会话实际返回的 schema 为准。

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `get_client_identity` | 无 | 读取配置的 ELF 架构、SHA256 与 Build ID |
| `get_capabilities` | 无 | 查询当前模式、可用工具与功能状态 |
| `search_contacts` | `keywords: string[]`、`limit=10`、`groups_only=false` | 搜索联系人；设 `groups_only=true` 搜索群；最多 50 条 |
| `get_messages` | `chat_ids: string[]`、`limit=10` | 每会话最多 20 条；目标须在白名单 |
| `send_text_message` | `recipient_id: string`、`text: string`、`idempotency_key: string` | 向白名单目标提交一次文本操作 |

`chat_id` 是微信内部会话标识，来自搜索结果。群使用群标识，私聊使用联系人标识；不要由昵称推测 ID。

## 搜索与读取

```json
{"keywords": ["测试"], "limit": 5, "groups_only": true}
```

成功结果的 `result.chat_list` 包含匹配项的 `chat_id` 及可用名称。多个匹配项时由用户确定目标。空结果或失败状态不能当作目标存在的证据。

```json
{"chat_ids": ["<已确认并加入白名单的 chat_id>"], "limit": 5}
```

消息中的 `svr_id` 使用十进制字符串，避免 64 位 ID 经 JavaScript 数值解析后丢失精度。当前接口是有界历史查询，未提供分页保证或完整历史导出。

## 发送

```json
{
  "recipient_id": "<已确认并加入白名单的 chat_id>",
  "text": "连接测试完成",
  "idempotency_key": "<为这一次用户请求生成并保存的唯一键>"
}
```

同一个键绑定相同目标与正文。再次调用返回原记录；换目标或内容会报错。超时、重连、客户端重启后继续保留原键与 `.state/operations`，以免重复发送。新请求使用新键。

| 状态 | 解释 |
| --- | --- |
| `not_submitted` | 未建立提交；不自动重试 |
| `client_success` | 客户端发送管线回调成功 |
| `client_error` | 客户端回调返回错误 |
| `unknown` | 无法确定是否提交或完成；不自动重发 |

发送响应中的 `delivery_confirmed` 当前恒为 `false`。查询到自己发送的消息仍不能证明对方收到。

## 私有配置与调用限制

`scripts/run_local_mcp.py` 默认读取仓库 `.state/local-targets.json`：

```json
{"allowed_recipients": []}
```

可通过 `--config`、`--native-shim`、`--state-dir` 指定其他绝对路径。初始空白名单允许搜索；读取消息和发送需要配置已确认的内部 ID。配置改变后重启服务。

进程附加失败时，先确认本机微信已登录、MCP 能看到宿主进程且构建匹配。身份校验失败时停止原生调用；需要新的适配。不要将进程 ID、地址偏移或任意新库替换视为普通重试。
