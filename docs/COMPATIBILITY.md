# 兼容性与未完成适配范围

当前 native 仅覆盖已研究的 Linux AArch64 微信 4.1.13.26：

- SHA-256：`71e22a172018bf250b7b70493382bf55024727144eb7f13cf9b312cdf02e5bbc`
- GNU Build ID：`67dcad7dc5ff4c67581b14a89385e3b3bfb4bbfd`
- 主程序路径：`/opt/wechat/wechat`

代码中的研究目标以 `src/weskill/capabilities.py` 的 `RESEARCH_TARGET` 为来源。版本号相同不代表二进制相同；native 仍使用原有路径、哈希和进程绑定检查，本文和诊断报告不放宽检查。

## 只读诊断与 native 的区别

`get_client_identity` 可以读取任意架构的常规 ELF 文件，包括 AArch64、x86_64 和 32 位 ELF。它读取文件内容、SHA-256、ELF 架构与 Build ID，不执行客户端、不附加进程。读取其它 ELF 的成功不证明微信业务能力可用。

身份结果的 `compatibility` 字段分开报告：

- `diagnostics.status`：该文件能否被只读 ELF 诊断读取。
- `native.status`：是否符合已记录构建和主机条件。`supported` 只表示这些静态条件满足；`execution_available` 始终为 `false`，运行时依赖仍未验证。
- `native.checks`：逐项列出 `client_elf`、`host_os`、`host_architecture`、`client_architecture`、`client_sha256`、`client_path` 的期望值、实际值和满足情况。
- `native.unsupported_reasons`：列出不满足条件的检查名；文件读取失败时，无法确认的文件架构、哈希、路径检查记为 `null`，避免把未知伪装为已检查。

主机要求为 Linux AArch64（架构名称接受 `aarch64` / `arm64`），客户端要求为 64 位 `EM_AARCH64`。原生兼容报告不以 Build ID 单独判断支持；精确 SHA-256 才是现有 native 的构建绑定依据。报告没有验证发布者真实性。

Python 调用 `weskill.compatibility.compatibility_report(Path(...))` 可在缺文件、非 ELF 或目录输入时取得结构化的 `unsupported` 报告。`inspect_identity` 和 MCP `get_client_identity` 在这些情况下仍返回原有错误，避免更改已有调用约定。

即使静态条件满足，仍需 Frida 16.7.19、已构建且匹配的 native executor shim、显式启用 native、可识别的运行中主进程、实时 PID/映射/哈希绑定，以及已登录客户端和相应账号权限。只读诊断不验证这些条件，也不代表任何业务操作已成功。

## 尚未完成的兼容工作

**x86_64、其它架构、其它微信版本及不同 SHA-256 构建的 native 适配均未完成。** 当前没有其它目标二进制或对应运行机器，不能将能诊断 ELF、通过比较器单元测试、发现名称/符号或存在类似源码解释为已移植。

每个新增目标至少需要：

1. 准确的操作系统、架构、微信版本及来源可信的目标 ELF（保留 SHA-256、Build ID，必要时同时提供依赖库）。
2. 对应架构的测试机器或可授权访问的测试环境，以及可登录的测试客户端和用于验证的账号/会话。
3. 重新确认目标中的地址、注册表、函数签名、调用约定、对象布局、所有权和线程要求，并移植相应 shim/agent；不能复用 AArch64 偏移或 ABI 假定。
4. 在真实目标上验证连接、只读能力和用户授权的业务能力，记录每项成功依据与限制后，才扩展支持清单和绑定规则。

## 当前验证范围

`tests/test_compatibility.py` 用明确标记的最小 AArch64/x86_64 ELF 头测试诊断解析，用纯身份映射测试各项比较规则；这些夹具不充当微信成功证据。真实 `/opt/wechat/wechat` 存在且哈希匹配时，还只读核验实际文件的架构与 Build ID；未匹配或不存在时该项跳过。整个验证过程不附加进程、不调用业务接口、不安装系统软件。
