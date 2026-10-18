<p align="center">
  <img src="assets/logo.svg" width="120" height="120" alt="weskill 标志：对话气泡中的桥梁">
</p>

<h1 align="center">weskill</h1>

<p align="center"><strong>一个 Skill，编排 Linux 微信操作；本机 MCP，执行原生调用。</strong></p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-38bda4"></a>
  <img alt="Status: Experimental" src="https://img.shields.io/badge/Status-Experimental-e7b45c">
  <img alt="Platform: Linux ARM64" src="https://img.shields.io/badge/Linux-ARM64-192d38">
  <img alt="Transport: MCP stdio" src="https://img.shields.io/badge/MCP-stdio-192d38">
</p>

weskill 是面向 **Linux 原生微信的操作 Skill 项目**，让 Codex 和 Claude Code 根据自然语言完成一系列微信任务。项目以一个微信操作 Skill 为入口：它负责理解任务、确定联系人或群、组织调用与解释结果；我们开发的本机 MCP 负责查询和执行，其他兼容 MCP 的助手也可直接接入执行层。

**能力范围**覆盖联系人、私聊与群聊、消息与媒体、群管理、朋友圈和界面辅助。当前已实现联系人/群搜索、有界历史消息查询、私聊与群聊文本发送，以及共享服务管理和持久幂等去重。图片、文件、表情、好友申请、好友备注、群成员、建群/邀请、群置顶、公告、入群确认、真实 @、朋友圈与截图仍在研究或计划中，详见下方功能进度。

项目采用 [REA（Reverse Engineer Anything）](https://github.com/morluto/rea) 仓库的 `reverse-engineer-anything` 工作流组织 Linux 微信逆向研究，结合 ELF 静态分析与 Frida 动态验证，寻找可复用的原生调用入口，再将验证通过的能力接入 MCP 与 Skill。目标是在执行微信任务时保持桌面可正常使用：当前业务调用无需移动鼠标、模拟按键或切换窗口焦点。

[快速开始](#快速开始) · [功能进度](#功能进度) · [接入助手](#接入-codex--claude-code) · [使用示例](#使用示例) · [参与开发](#参与开发)

## 为什么做 weskill

- **一个入口，组织多步任务。** Skill 将“找到会话、读取所需消息、发送指定文本”等步骤串起来，并处理重名与结果不确定的情况。
- **Skill 与执行层一起交付。** 同一份 Skill 服务于 Codex / Claude Code，配套 MCP 暴露当前真正可用的原生操作。
- **桌面继续由你使用。** 当前原生调用不依赖屏幕位置，也不占用输入焦点。
- **每次发送都有边界。** 目标白名单、持久幂等记录与明确的返回状态，帮助避免误发和重复发送。
- **能力如实报告。** `get_capabilities` 区分可用能力和开发计划，Skill 按实际能力完成任务。

```text
你的微信任务 → Codex / Claude Code
                       ↓
               weskill（Skill）
           理解任务 → 确定目标 → 编排操作
                       ↓
               weskill MCP（本机 stdio）
             版本校验 → 原生 executor → 微信
                       ↓
               查询结果 / 客户端回执
```

## Skill 如何组织微信操作

当前提供一个 `$weskill` Skill，按任务编排现有工具。例如，“查找测试群并查看最近 5 条消息”会先确认可用能力、启动或复用共享服务，再搜索目标并读取指定范围；发送任务还会检查用户意图、目标与正文，并保留幂等键。

未来媒体、联系人和群管理能力也接入这一入口，逐项验证后开放。Skill 负责操作流程，MCP 负责具体执行；安装 Skill 后仍需按下文配置本机 MCP。

## 功能进度

### 已实现 · 原生实验模式

| 能力 | MCP 工具 | 当前范围 |
| --- | --- | --- |
| 服务生命周期 | `ensure_service` / `get_service_status` / `stop_service` | 跨会话共用，空闲一小时自动退出 |
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
git clone https://github.com/cyrus-xc/weskill.git weskill
cd weskill
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

初始白名单为空，可以先搜索联系人或群。需要读取消息或发送文本时，将确认过的搜索结果 `chat_id` 加入私有配置的 `allowed_recipients` 数组，然后停止旧服务并重新连接 MCP。联系人名称可能重复，发送接口接受内部 ID。

`.state/` 已加入 `.gitignore`，包含白名单和运行记录。已有配置请直接编辑，保留原有幂等记录。

## 接入 Codex / Claude Code

在仓库根目录运行以下命令，使用绝对路径注册本机 stdio 服务：

**Codex**

```bash
codex mcp add weskill -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

**Claude Code**

```bash
claude mcp add --transport stdio --scope user weskill -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

重新连接 MCP 或新开会话后，检查是否发现 8 个工具。微信重启或白名单改变后，先停止旧服务再启动；MCP 代码升级后先停止旧服务，再重新连接。启动器自动选择唯一的微信主进程；存在多个匹配进程时会停止并报告歧义。

暂时只想查看客户端识别与功能状态，可将启动命令改成 `.venv/bin/weskill`，进入默认诊断模式，此模式只暴露两个诊断工具，不附加微信。

### 安装 weskill Skill

仓库提供同一份 skill 和两端插件清单。先完成上面的 MCP 接入，再安装 Skill：

```bash
# Codex
codex plugin marketplace add "$PWD"
codex plugin add weskill@weskill-local

# Claude Code
claude plugin marketplace add "$PWD"
claude plugin install weskill@weskill-local
```

插件包当前只包含 skill，MCP 运行环境需单独安装。它不会自动下载微信、附加进程或发送测试消息。两端的布局和发布前检查见 [插件发布说明](docs/PLUGINS.md)。

## 常驻服务与空闲退出

调用 skill 开始微信任务时，`ensure_service` 确保本机共享服务运行；各个 MCP 会话复用同一服务和原生连接。后续请求自动续期，最后一次请求完成后一小时没有新请求就退出，正在处理的请求不会被中断。再次使用时自动启动，无需让助手反复检查进程。

控制服务也可以在仓库根目录执行：

```bash
.venv/bin/python scripts/run_local_mcp.py --service start
.venv/bin/python scripts/run_local_mcp.py --service status
.venv/bin/python scripts/run_local_mcp.py --service stop
```

状态查询不会启动已停止的服务；显式停止在服务忙碌时会被拒绝。服务通过权限为 `0600` 的本机 Unix socket 通信，不开放 TCP 端口。配置和日志留在 `.state/`；有待完成的原生调用时会保留工作进程完成清理。

## 使用示例

安装 Skill 并接入 MCP 后，可以用 `$weskill` 调用，或直接向助手描述微信任务：

> 搜索名字包含“测试”的群，只列出匹配结果。
>
> 查看我指定的白名单会话最近 5 条消息，整理成待办。
>
> 向指定测试群发送“连接测试完成”，只发一次。

助手的典型调用顺序是 `get_capabilities` → `ensure_service` → `search_contacts` → `get_messages` 或 `send_text_message`。重名时先确定目标，发送前明确收件人与正文。

一次发送需要一个幂等键。重连或超时后，**保留同一个键和相同内容**；更换键会被视为新操作。

| 发送状态 | 含义 |
| --- | --- |
| `not_submitted` | 未建立提交；保留记录，不自动重试 |
| `client_success` | 客户端发送管线返回成功；尚未确认收件端送达 |
| `client_error` | 客户端回调返回错误 |
| `unknown` | 提交或完成状态无法确定；不自动重发 |

接口参数与典型响应见 [工具参考](docs/TOOLS.md)。

## 连接超时排查

若出现 `OperationCancelledError`，可能是 Frida 建立原生连接时触发超时。服务通过独立的常驻子进程建立原生连接，每次设置 15 秒超时。启动失败时，先清理尚未接受业务请求的子进程，再用新进程尝试一次；只有连接成功才提交业务，不会因此重复发送消息。两次均失败会返回 `connection_timeout` 和具体失败阶段。

升级后需重新连接 MCP 或新开会话，让已运行的服务加载新代码。可用 `get_capabilities` 中的 `connection_policy` 核对连接策略。遇到 `unknown` 时保留原幂等键和运行记录，不要换键重发。

## 隐私与当前限制

MCP 接口以本机 stdio 运行，内部服务使用同用户 Unix socket，没有远程访问服务。被查询的联系人和消息会返回给调用它的 AI 客户端，并受该客户端及模型服务的数据处理规则约束。原始聊天结果、帐号标识、运行记录、实验报告和构建产物均留在被忽略的本地目录。

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

- [REA：Reverse Engineer Anything](https://github.com/morluto/rea)：本项目采用其逆向研究工作流，组织 Linux 微信原生接口的定向分析与验证。

- [Model Context Protocol](https://modelcontextprotocol.io/) 与 [Python SDK](https://github.com/modelcontextprotocol/python-sdk)：工具协议和 stdio 服务实现。
- [Frida 文档](https://frida.re/docs/home/)：本机动态插桩与原生接口调用。
- [OpenAI 插件打包规范](https://developers.openai.com/plugins/build/plugins) 与 [MCP 接入文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：Codex 插件与服务接入。
- [Claude Code 插件规范](https://code.claude.com/docs/en/plugins-reference)、[Marketplace 规范](https://code.claude.com/docs/en/plugin-marketplaces) 与 [Skills](https://code.claude.com/docs/en/skills)：Claude 插件布局与操作流程。

如果 weskill 对你有帮助，欢迎为本项目点一颗 **Star ⭐**。也欢迎提交兼容性反馈与功能贡献，一起把 Linux 微信变成更好用的 AI 工具。
