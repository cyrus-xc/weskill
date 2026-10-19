# 本机连接

缺少工具或遇到安装/连接错误时读取本说明。当前支持 Linux ARM64 微信 4.1.13.26 的指定构建；运行 MCP 的用户需要能访问宿主微信进程。

推荐 npm 安装，包内包含执行层和五个 Skill：

```bash
npm install -g weskill
weskill setup
weskill install codex
# 或 weskill install claude
```

需要 Node.js 22+、Python 3.12+（含 venv）和 GCC。`setup` 准备独立 Python 环境及原生桥，不附加微信；业务请求才建立原生连接。其他支持本机 stdio MCP 的平台使用 `weskill config` 输出配置，`weskill skills --dir` 导出 Skill。

原生模式应发现 31 个工具，包括共享服务管理、好友、群、表情与朋友圈工具；只有两个工具表示诊断模式。开始任务先读实时能力，再确保共享服务运行，按搜索结果确定目标 ID。无需联系人配置文件，更换目标无需重启服务。

npm 默认账本在用户数据目录 `~/.local/share/weskill/state/operations`（可由 XDG 或 `--data-dir` 改变）；源码启动器仍用源码根目录 `.state/operations`。保持原幂等键与账本，安装或升级不等于旧任务未提交。

微信重启或执行环境升级后，先停止旧空闲服务，再重新连接 MCP。构建身份不符需开发适配，不能绕过检查。诊断输出和账号/聊天数据保存在私有位置。

完整安装、源码方式与路径语义见 https://github.com/cyrus-xc/weskill/blob/main/docs/INSTALL.md 。
