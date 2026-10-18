# 本机连接

此 skill 依赖单独安装的 WeChat MCP 服务。缺少工具时报告连接问题，不声称操作成功。工具箱源码与安装说明位于 https://github.com/cyrus-xc/weskill 。

本机环境：Python 3.12+、GCC、已登录的 Linux 原生微信；当前只验证 ARM64 4.1.13.26 的指定文件哈希。MCP 须能访问宿主微信进程。容器中看不到进程时需要在宿主运行服务。

完成源码安装和原生库编译后即可注册 MCP，无需创建联系人配置文件。通过搜索结果确定目标内部 ID，再查询消息或执行用户授权的发送；更换目标无需重启服务。保留 `.state/operations/` 中的发送记录。

Codex 注册方式：

```bash
codex mcp add weskill -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

Claude Code 注册方式：

```bash
claude mcp add --transport stdio --scope user weskill -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

连接后应发现八个工具，包括 `ensure_service`、`get_service_status` 和 `stop_service`。仅两个工具表示当前是默认诊断模式。微信重启后停止旧服务再启动；MCP 升级后先停止旧服务再重新连接。出现构建身份不符时停止原生调用，需要开发适配，不能绕过校验。

诊断输出、帐号信息和原始聊天结果保存在私有位置。
