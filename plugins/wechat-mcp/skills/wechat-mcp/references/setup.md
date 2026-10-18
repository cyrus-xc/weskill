# 本机连接

此 skill 依赖单独安装的 WeChat MCP 服务。缺少工具时报告连接问题，不声称操作成功。工具箱源码与安装说明位于 https://github.com/cyrus-xc/wechat-mcp 。

本机环境：Python 3.12+、GCC、已登录的 Linux 原生微信；当前只验证 ARM64 4.1.13.26 的指定文件哈希。MCP 须能访问宿主微信进程。容器中看不到进程时需要在宿主运行服务。

完成源码安装和原生库编译后，在仓库根目录复制 `examples/local-targets.example.json` 为私有 `.state/local-targets.json`，初始白名单为空。已有文件保留并编辑。白名单字段为 `allowed_recipients`，存储从搜索结果确认的内部 ID；修改配置后重启 MCP，保留发送记录。

Codex 注册方式：

```bash
codex mcp add wechat-mcp -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

Claude Code 注册方式：

```bash
claude mcp add --transport stdio --scope user wechat-mcp -- \
  "$PWD/.venv/bin/python" "$PWD/scripts/run_local_mcp.py"
```

连接后应发现五个工具。仅两个工具表示当前是默认诊断模式。微信重启后需重启 MCP。出现构建身份不符时停止原生调用，需要开发适配，不能绕过校验。

配置修改仅限用户要求的微信服务与目标。诊断输出、帐号信息和原始聊天结果保存在私有位置。
