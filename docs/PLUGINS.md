# Codex 与 Claude 插件发布准备

同一插件中的 `weskill` 总入口、群管理、好友管理、表情与朋友圈 Skill 服务于两端，插件身份与版本均为 `weskill` / `0.4.2`。skill 提供操作流程，安装由 npm CLI 统一组织；插件不包含私有配置、客户端二进制或预编译原生库。

```text
.agents/plugins/marketplace.json            Codex 本地 marketplace
.claude-plugin/marketplace.json            Claude 本地 marketplace
plugins/weskill/
├── .codex-plugin/plugin.json              Codex 兼容清单
├── .claude-plugin/plugin.json             Claude 清单
├── LICENSE
├── assets/logo.svg
└── skills/
    ├── weskill/                           总入口与基础操作
    │   ├── SKILL.md
    │   ├── agents/openai.yaml
    │   ├── assets/logo.svg
    │   └── references/
    ├── weskill-group/                     群管理
    ├── weskill-friends/                   好友资料、备注与申请
    ├── weskill-emoji/                     系统与自定义表情
    └── weskill-moments/                   朋友圈读取与发布
```

Codex 使用仍受支持的 `.codex-plugin/plugin.json` 布局，Claude 使用 `.claude-plugin/plugin.json` 和默认 `skills/` 目录。插件没有生命周期 hooks，也没有自动启动原生注入的 MCP 配置。

## 推荐安装

```bash
npm install -g weskill
weskill setup
weskill install codex
# 或 weskill install claude
```

CLI 注册本机 MCP，再从 npm 包内 marketplace 安装五个 Skill。插件与 Python 执行层在同一 npm 包中分发；用户级 Python 环境和操作账本保存在包目录之外。其他平台使用 `weskill config` 和 `weskill skills --dir`。

完整参数与源码方式见 [安装指南](INSTALL.md)。从源代码验证插件布局时仍可在仓库根目录调用宿主的 marketplace add / plugin install 命令。

## 形成公开包

运行 `scripts/check_release.py` 检查 Git 可见文件、包内路径及私有标识。Git 忽略规则不会清除已提交的历史，发布前仍应检查提交范围；当前研究产物从未被提交。

插件归档只收录插件目录：

```bash
mkdir -p dist
cd plugins/weskill
python3 -m zipfile -c ../../dist/weskill-plugin-0.4.2.zip .codex-plugin .claude-plugin skills assets LICENSE
cd ../..
```

OpenAI 和 Claude 的公开目录有各自的审核与发布流程。本仓库包含本地安装所需清单，不表示已通过审核或已上架。公开提交时还需按目标平台要求完善维护者、支持方式与隐私信息，并在干净环境中复核安装说明。

## 官方规范

- [OpenAI：打包插件](https://developers.openai.com/plugins/build/plugins)
- [OpenAI：从 Claude 插件提交](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [Claude：插件清单](https://code.claude.com/docs/en/plugins-reference)
- [Claude：Marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude：Skills](https://code.claude.com/docs/en/skills)

编写时核对日期：2026-10-18。发布时重新检查目标平台当前要求。

插件的 `skills/` 目录会同时安装五项 Skill；`weskill` 保留能力目录及基础操作，其余四项分别处理群、好友、表情与朋友圈任务。升级后重新连接 MCP 或新开会话，原生模式应发现 31 个工具。

发布流水线与 npm OIDC 配置见 [版本发布](RELEASING.md)。
