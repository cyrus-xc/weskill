# 安装 weSkill

## 推荐：npm

需要 Node.js 22+、Python 3.12+（含 venv）和 GCC。原生业务运行于已适配的 Linux ARM64 微信构建；使用的 Agent 可以是 Codex、Claude Code 或其他支持本机 stdio MCP 的平台。操作系统/微信构建适配见 [兼容性说明](COMPATIBILITY.md)。

```bash
npm install -g weskill
weskill setup
weskill install codex
# 或：weskill install claude
```

npm 包没有安装生命周期脚本。`setup` 显式创建用户级 Python venv、从包内源码安装 Python 执行层和依赖、编译 C/AArch64 原生桥。原生依赖包括固定的 Frida 16.7.19；这些步骤不附加微信。首次 `mcp` 启动也会准备缺失环境，提前运行 `setup` 可以避免宿主工具在等待依赖安装时超时。

有多个 Python 时可选择解释器：

```bash
weskill setup --python /path/to/python3.12
```

`weskill install codex` 调用宿主 CLI 注册 MCP、添加包内 marketplace 并安装五个 Skill；Claude 使用用户范围的 stdio MCP 配置。需先安装相应宿主 CLI，并确保 `codex` / `claude` 在 PATH 中。配置完成后重新连接 MCP 或新开会话。

## 其他 Agent 平台

```bash
weskill config
weskill skills --dir /path/to/agent/skills
```

`config` 返回常见的 `mcpServers` JSON。将其中的服务名称、`command` 和 `args` 放进宿主要求的位置；部分平台的根字段叫 `servers`。输出引用当前安装包和 Node 的绝对路径，不依赖图形界面的 shell PATH。`skills` 将五个完整的 Skill 目录复制到指定位置，可重复执行；本地改动冲突时会提示，使用 `--force` 替换包内同名文件。

只支持 MCP 的平台可以使用全部工具；支持 `SKILL.md` 的平台还可以加载任务编排说明。宿主如何加载 Skills 由其自身规范决定，通用导出不承诺自动识别所有宿主目录。

也可以在平台内配置固定版本的 npx 启动：

```json
{
  "mcpServers": {
    "weskill": {
      "command": "npx",
      "args": ["-y", "weskill@0.5.0", "mcp"]
    }
  }
}
```

使用 npx 前建议先在终端执行 `npx -y weskill@0.5.0 setup`，让依赖准备完成。

## 运行目录与服务管理

默认数据根目录为 `$XDG_DATA_HOME/weskill`；未设置 XDG 时为 `~/.local/share/weskill`。

- `runtime/<版本与源码指纹>/`：Python 环境和原生桥，与运行代码绑定。
- `state/operations/`：幂等账本、查询素材等私有运行数据。
- `state/service/`：共享服务 socket、配置和日志。

升级 npm 包会选择匹配的新 runtime，保留同一数据根目录的操作记录。不要删除或复制出正在使用的账本。npm 入口的数据目录与源码开发的 `.state/` 分开，切换安装方式时需保留原有记录；`--data-dir` 指定的是整个数据根目录，不能把账本子目录直接当作该参数。

```bash
weskill service start
weskill service status
weskill service stop
```

服务空闲一小时退出，再次使用自动启动。在途原生调用仍按原有所有权处理。微信重启或切换执行环境时先停止旧空闲服务，再连接。默认状态命令不连接微信。

自定义数据目录时在 `setup`、`install` 和 `config` 中保持一致：

```bash
weskill setup --data-dir /path/to/private-data
weskill install codex --data-dir /path/to/private-data
```

也可以设置 `WESKILL_DATA_DIR` 和 `WESKILL_PYTHON`。这些路径与变量不应包含在公开的项目配置中。

## 只读诊断模式

其他 Linux ELF 架构可以使用只读身份和能力诊断，不启用原生业务：

```bash
weskill setup --diagnostics
weskill mcp --diagnostics
weskill config --diagnostics
```

诊断不附加微信，只提供 `get_client_identity` 和 `get_capabilities`。可以传 `--client-path /path/to/elf` 给 MCP 入口。

## 源码开发

```bash
git clone https://github.com/cyrus-xc/weskill.git
cd weskill
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[hooks]'
mkdir -p native/build .state
chmod 700 .state
cc -std=c11 -O2 -fPIC -shared \
  native/readonly_executor_shim.c native/readonly_executor_shim.S \
  -o native/build/libreadonly-executor-shim.so
```

源码启动器保留：

```bash
.venv/bin/python scripts/run_local_mcp.py
```

它使用源码根目录的 `.state/operations` 和 `native/build`。npm CLI 使用自己的用户级 runtime，二者不要同时对同一账户提交同一写任务。开发方法见 [开发指南](DEVELOPMENT.md)。
