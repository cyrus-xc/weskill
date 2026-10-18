<p align="center">
  <img src="assets/logo.svg" width="120" height="120" alt="微桥标志：对话气泡中的桥梁">
</p>

<h1 align="center">微桥 · WeChat MCP</h1>

<p align="center"><strong>让 AI 通过 MCP，在 Linux 上静默使用微信。</strong></p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-38bda4"></a>
  <img alt="Status: Experimental" src="https://img.shields.io/badge/Status-Experimental-e7b45c">
  <img alt="Platform: Linux ARM64" src="https://img.shields.io/badge/Linux-ARM64-192d38">
  <img alt="Transport: MCP stdio" src="https://img.shields.io/badge/MCP-stdio-192d38">
</p>

微桥是面向 **Linux 原生微信客户端**的本机 MCP 工具箱。它把联系人搜索、聊天记录查询、私聊与群聊文本发送交给 AI 助手调用，支持 Codex、Claude Code 和其他兼容 MCP 的本机客户端。

目标是覆盖日常微信操作，同时保持桌面可正常使用：当前业务调用走原生进程桥接，无需移动鼠标、模拟按键或切换窗口焦点。项目仍处于实验阶段，已验证的能力与开发计划分别列出。

[快速开始](#快速开始) · [功能进度](#功能进度) · [接入助手](#接入-codex--claude-code) · [使用示例](#使用示例) · [参与开发](#参与开发)

## 为什么做微桥

- **让微信成为工具。** 助手可以先找到会话，再读取所需消息或发送用户指定的文本。
- **桌面继续由你使用。** 当前原生调用不依赖屏幕位置，也不占用输入焦点。
- **每次发送都有边界。** 目标白名单、持久幂等记录与明确的返回状态，帮助避免误发和重复发送。
- **能力如实报告。** `get_capabilities` 告诉助手当前真正可用的工具；研究线索不会被当作已实现功能。
- **协议与操作流程一起交付。** Python MCP 服务负责执行，Codex / Claude skill 负责目标消歧、调用顺序与结果解释。

```text
你的请求 → Codex / Claude → MCP（本机 stdio）
                                ↓
                     版本校验 → 原生 executor → 微信
                                ↓
                        查询结果 / 客户端回执
```

## 功能进度

### 已实现 · 原生实验模式

| 能力 | MCP 工具 | 当前范围 |
| --- | --- | --- |
| 客户端识别 | `get_client_identity` | 架构、ELF SHA256、Build ID；无需附加进程 |
| 能力查询 | `get_capabilities` | 区分已验证、待验证与当前可执行能力 |
| 联系人和群搜索 | `search_contacts` | 按关键词查询，最多 50 条；支持仅搜索群 |
| 聊天记录查询 | `get_messages` | 白名单会话，每个会话最多 20 条 |
| 私聊文本发送 | `send_text_message` | 指定内部 ID，目标须在白名单中 |
| 群聊文本发送 | `send_text_message` | 使用群内部 ID，与私聊共用发送接口 |
| 发送去重 | 服务内置 | 幂等键持久化，跨进程去重，不确定结果不自动重发 |

私聊、群聊文本发送和历史查询均做过真实客户端验证，客户端重启并重新登录后也完成过查询验证。**客户端返回成功，不代表对方已经收到或已读。**

### 计划实现

| 方向 | 计划能力 |
| --- | --- |
| 消息与媒体 | 实时消息事件、图片、文件、表情与 GIF、@群成员 |
| 联系人 | 获取完整好友信息、修改好友备注、主动加好友、检查与接受好友申请 |
| 群管理 | 获取群成员、创建群聊、邀请入群、群置顶消息、发布与编辑群公告、开关群聊邀请确认 |
| 朋友圈与界面 | 读取与发表朋友圈、UI 截图 |

“群聊邀请确认”指入群需要群主或管理员同意。媒体能力优先研究，随后完善联系人与群管理；具体可用状态以服务返回为准。完整范围见 [功能说明](docs/FEATURES.md)。

## 快速开始

### 1. 准备环境

当前原生后端仅验证过 **Linux ARM64 / 微信 4.1.13.26 的一个具体构建**，安装路径为 `/opt/wechat/wechat`。即使版本号相同，文件哈希不同也会拒绝调用。其他架构、版本与发行版组合尚未验证。

需要 Python 3.12+、`venv`、GCC，以及已登录的本机微信。MCP 进程需以能够访问该微信进程的本机用户运行；容器或受限沙箱可能无法附加。

### 2. 安装源码与依赖

```bash
git clone https://github.com/cyrus-xc/wechat-mcp.git wechat-mcp
cd wechat-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[hooks]'
mkdir -p native/build
gcc -std=c11 -O2 -fPIC -shared \
  native/readonly_executor_shim.c native/readonly_executor_shim.S \
  -o native/build/libreadonly-executor-shim.so
```

`hooks` 依赖固定使用已验证的 Frida 16.7.19。原生库加载后会留存到微信退出；升级库文件前先退出客户端。

### 3. 创建私有配置

```bash
mkdir -p .state
chmod 700 .state
cp examples/local-targets.example.json .state/local-targets.json
chmod 600 .state/local-targets.json
```

初始白名单为空，可以先搜索联系人或群。需要读取消息或发送文本时，将确认过的搜索结果 `chat_id` 加入私有配置的 `allowed_recipients` 数组，然后重启 MCP。联系人名称可能重复，发送接口接受内部 ID。

`.state/` 已加入 `.gitignore`，包含白名单和运行记录。已有配置请直接编辑，保留原有幂等记录。

## 接入 Codex / Claude Code

在仓库根目录运行以下命令，使用绝对路径注册本机 stdio 服务：

**Codex**

```bash
codex mcp add wechat-mcp -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

**Claude Code**

```bash
claude mcp add --transport stdio --scope user wechat-mcp -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

重新连接 MCP 或新开会话后，检查是否发现 5 个工具。微信重启后也需重启 MCP。启动器自动选择唯一的微信主进程；存在多个匹配进程时会停止并报告歧义。

暂时只想查看客户端识别与功能状态，可将启动命令改成 `.venv/bin/wechat-mcp`，进入默认诊断模式，此模式只暴露两个诊断工具，不附加微信。

### 安装配套 skill

仓库提供同一份 skill 和两端插件清单。先完成上面的 MCP 接入，再安装操作流程：

```bash
# Codex
codex plugin marketplace add "$PWD"
codex plugin add wechat-mcp@wechat-mcp-local

# Claude Code
claude plugin marketplace add "$PWD"
claude plugin install wechat-mcp@wechat-mcp-local
```

插件包当前只包含 skill，MCP 运行环境需单独安装。它不会自动下载微信、附加进程或发送测试消息。两端的布局和发布前检查见 [插件发布说明](docs/PLUGINS.md)。

## 使用示例

接入后可以直接向助手描述任务：

> 搜索名字包含“测试”的群，只列出匹配结果。
>
> 查看我指定的白名单会话最近 5 条消息，整理成待办。
>
> 向指定测试群发送“连接测试完成”，只发一次。

助手的典型调用顺序是 `get_capabilities` → `search_contacts` → `get_messages` 或 `send_text_message`。重名时先确定目标，发送前明确收件人与正文。

一次发送需要一个幂等键。重连或超时后，**保留同一个键和相同内容**；更换键会被视为新操作。

| 发送状态 | 含义 |
| --- | --- |
| `not_submitted` | 未建立提交；保留记录，不自动重试 |
| `client_success` | 客户端发送管线返回成功；尚未确认收件端送达 |
| `client_error` | 客户端回调返回错误 |
| `unknown` | 提交或完成状态无法确定；不自动重发 |

接口参数与典型响应见 [工具参考](docs/TOOLS.md)。

## 隐私与当前限制

工具箱以本机 stdio 运行，没有远程访问服务。被查询的联系人和消息会返回给调用它的 AI 客户端，并受该客户端及模型服务的数据处理规则约束。原始聊天结果、帐号标识、运行记录、实验报告和构建产物均留在被忽略的本地目录。

当前为非官方实验项目，与腾讯、微信、OpenAI 或 Anthropic 无隶属关系。原生代码仍可能影响客户端稳定性；图片缓存桥接实验曾在加载期间遇到客户端退出，原因未确定，该实验已隔离且不属于发布运行路径。当前每次请求的部分桥接资源会留存到微信退出，尚不适合长期无人值守或高频任务。

项目优先研究静默原生调用。未来若某项功能需要 UI 自动化，会先说明原因并由用户决定方案。

## 参与开发

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_release.py
```

测试包含真实 MCP/stdio 握手和隔离的幂等、授权、并发与数值精度验证；自动测试不会向真实联系人发送消息。提交问题时，请提供架构、微信版本和脱敏错误信息，并移除聊天正文及帐号标识。

研究报告与临时探针保存在本地，不进入 Git 或发布包。代码采用 [MIT License](LICENSE)。

## 引用与致谢

- [Model Context Protocol](https://modelcontextprotocol.io/) 与 [Python SDK](https://github.com/modelcontextprotocol/python-sdk)：工具协议和 stdio 服务实现。
- [Frida 文档](https://frida.re/docs/home/)：本机动态插桩与原生接口调用。
- [OpenAI 插件打包规范](https://developers.openai.com/plugins/build/plugins) 与 [MCP 接入文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：Codex 插件与服务接入。
- [Claude Code 插件规范](https://code.claude.com/docs/en/plugins-reference)、[Marketplace 规范](https://code.claude.com/docs/en/plugin-marketplaces) 与 [Skills](https://code.claude.com/docs/en/skills)：Claude 插件布局与操作流程。

如果微桥对你有帮助，欢迎为本项目点一颗 **Star ⭐**。也欢迎提交兼容性反馈与功能贡献，一起把 Linux 微信变成更好用的 AI 工具。
