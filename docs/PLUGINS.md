# Codex 与 Claude 插件发布准备

同一插件中的 `weskill` 总入口与 `weskill-group` 群管理 Skill 服务于两端，插件身份与版本均为 `weskill` / `0.2.1`。skill 提供操作流程，原生 MCP 环境按 README 单独安装与注册；插件不包含私有配置、客户端二进制或预编译原生库。

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
    └── weskill-group/                     群管理流程
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── assets/logo.svg
        └── references/
```

Codex 使用仍受支持的 `.codex-plugin/plugin.json` 布局，Claude 使用 `.claude-plugin/plugin.json` 和默认 `skills/` 目录。插件没有生命周期 hooks，也没有自动启动原生注入的 MCP 配置。

## 本机验证

先按 README 注册 MCP，再执行对应宿主命令：

```bash
codex plugin marketplace add "$PWD"
codex plugin add weskill@weskill-local
```

```bash
claude plugin validate .
claude plugin validate ./plugins/weskill
claude plugin marketplace add "$PWD"
claude plugin install weskill@weskill-local
```

重新加载插件或新开会话。验证“列出当前能力”“搜索群”“重名目标”“发送超时”“请求未实现的朋友圈功能”等场景；涉及真实发送时使用用户明确指定的测试会话与正文。

## 形成公开包

运行 `scripts/check_release.py` 检查 Git 可见文件、包内路径及私有标识。Git 忽略规则不会清除已提交的历史，发布前仍应检查提交范围；当前研究产物从未被提交。

插件归档只收录插件目录：

```bash
mkdir -p dist
python3 -m zipfile -c dist/weskill-plugin-0.2.1.zip plugins/weskill
```

OpenAI 和 Claude 的公开目录有各自的审核与发布流程。本仓库包含本地安装所需清单，不表示已通过审核或已上架。公开提交时还需按目标平台要求完善维护者、支持方式与隐私信息，并在干净环境中复核安装说明。

## 官方规范

- [OpenAI：打包插件](https://developers.openai.com/plugins/build/plugins)
- [OpenAI：从 Claude 插件提交](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [Claude：插件清单](https://code.claude.com/docs/en/plugins-reference)
- [Claude：Marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude：Skills](https://code.claude.com/docs/en/skills)

编写时核对日期：2026-10-18。发布时重新检查目标平台当前要求。

插件的 `skills/` 目录会同时安装两项 Skill；`weskill` 保留能力目录及基础操作，`weskill-group` 按实时 MCP 能力处理群任务。升级后重新连接 MCP 或新开会话，原生模式应发现 19 个工具。
