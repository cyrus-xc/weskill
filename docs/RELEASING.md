# npm 与 GitHub 版本发布

npm 包和 Python 包、插件共用版本号。npm 包携带公开源码、五个 Skill、CLI 和本机构建脚本，不携带账号数据、研究目录、预编译 native 库或私人协作文档。

## 本机检查

```bash
npm ci --ignore-scripts
npm test
npm run check:package
python -m unittest discover -s tests -q
python scripts/check_release.py
mkdir -p dist
npm pack --ignore-scripts --pack-destination dist
python tools/smoke_npm.py dist/weskill-0.4.2.tgz
```

冒烟测试从真正的 tarball 解包到带空格的临时目录，创建独立 Python 环境，通过真实 MCP SDK 握手两次，不调用微信业务。ARM64 环境可增加 `--native` 验证 native 依赖/编译和 31 工具发现，仍不附加微信。

## 首次 npm 发布

`npm trust` 要求包已存在。首次注册时，先从独立目录发布最小的 `0.0.0` 初始化包，使用 `bootstrap` 标签而非 `latest`；不改主项目的版本号，也不把业务源码或本地文件放进该初始化包。然后配置可信发布者，让正式版本由 Actions 首发。

```bash
npm login
# 独立初始化目录只含公开的 package.json、README 和 LICENSE
npm publish .state/npm-bootstrap --tag bootstrap --access public --ignore-scripts
npm trust github weskill --repo cyrus-xc/weskill --file publish.yml --allow-publish --yes
```

维护者自行完成 npm 登录与需要的双因素验证；不把令牌写进仓库或聊天。可信发布者绑定仓库 `cyrus-xc/weskill` 与 workflow 文件 `publish.yml`，允许直接 publish。流水线只用 GitHub OIDC，不配置长期 `NPM_TOKEN`。新配置应在 npm 规定期限内完成首次 OIDC 发布；首次自动发布成功才证明整条认证路径可用。

正式版本使用默认的 `latest` 标签。初始化版本没有 CLI，不用于安装或测试正式业务。

## 日常流水线

1. 同步 `package.json`、`package-lock.json`、`pyproject.toml`、Python 版本、插件清单、marketplace 与公开版本文档。
2. 准备 `docs/releases/<版本>.md`，提交并推送。
3. CI 在 Node 22/24、Linux x86_64/ARM64 执行测试；ARM64 另验 native 包准备与工具发现。
4. 创建并推送 `v<版本>` 标签，触发 `.github/workflows/publish.yml`。
5. 发布 workflow 再次验证包和 MCP，通过 OIDC 发布 npm，生成 GitHub Release 和四种附件及校验值。

workflow 支持手动以现有版本标签重跑。已存在的 npm 版本只有在 tarball integrity 完全一致时才接受为已发布；不会覆盖不同内容，也不移动既有标签。npm 与 GitHub 发布步骤独立，重跑可以补齐尚未生成的 GitHub 附件。

npm 包和 GitHub Release 完成后，再从 registry 安装对应版本核验。公开 Agent 插件目录的审核属于各平台流程，npm 发布不表示已经上架其目录。

## 官方参考

- [npm Trusted publishing](https://docs.npmjs.com/trusted-publishers/)
- [npm trust](https://docs.npmjs.com/cli/v11/commands/npm-trust/)
- [GitHub Actions Node 发布](https://docs.github.com/en/actions/tutorials/publish-packages/publish-nodejs-packages)
