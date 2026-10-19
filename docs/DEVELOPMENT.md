# 从原生入口到可用 Skill：weSkill 的开发方法

weSkill 的工作是把 Linux 微信里真实存在的能力，变成 Agent 能理解、能组合、能判断结果的工具。难点通常不在“找到一个函数”，而在于确认它接收什么、在哪个线程运行、谁拥有参数，以及何时才算结束。

本文记录项目的探索方法和设计理由。阅读路线是：先看整体结构，再选一条只读能力，沿着输入、原生调用、回调和输出走完整个链路。当前构建与验证范围以 [兼容性文档](COMPATIBILITY.md) 和 [功能说明](FEATURES.md) 为准。

## 先把三种证据分开

| 观察 | 能说明什么 | 不能据此推出什么 |
| --- | --- | --- |
| 二进制中有操作名、字符串或注册项 | 有一条值得调查的线索 | 参数可直接照猜、操作已经可用 |
| 隔离夹具与协议测试通过 | 我们写的序列化、所有权或错误处理符合预期 | 微信一定接受这次操作 |
| 真实客户端返回成功 | 当前构建、账号与场景下的原生通道有效 | 其他版本、权限、素材类型也全部有效 |

能力报告用 `prototype_verified`、`user_reported`、`candidate_runtime`、`unverified` 区分证据。用户反馈的真实测试是有价值的证据，但与开发者独立复现实测分开记录。不要为了让状态整齐而把它们合并。

项目采用 [REA](https://github.com/morluto/rea) 的探索工作流组织问题、假设和实验。公开文档留下可复用的方法；含账号、联系人、聊天与内存原文的实验产物留在本地。

## 1. 固定研究对象，缩小搜索范围

先读 ELF，不先调用业务。记录架构、SHA-256、Build ID 和文件路径，再确认运行进程的实际可执行文件与映射。版本字符串相同的包也可能有不同布局；Build ID 是线索，现有执行后端以精确哈希和运行时身份绑定为依据。

`identity.py` 负责只读识别，`compatibility.py` 解释哪些条件符合研究目标。能解析另一个架构的 ELF，只能说明诊断层可用，不能说明 ARM64 的桥接可在该架构执行。

定向搜索比全量堆反编译结果更有效：

1. 从用户动作出发，写清输入和期望结果，例如“读取群成员”或“发送一张本机图片”。
2. 搜索注册名、错误文案、序列化字段和相关字符串，寻找交叉引用。
3. 顺着调用链区分 UI 包装、缓存服务、网络提交和结果转换。优先复用完整业务入口。
4. 在调用点观察参数来源、对象构造和清理路径，再确定可探测的边界。

**窍门：同时看调用前和调用后。** 函数入口告诉你参数怎么进来，调用后的析构、分支和序列化往往更能解释对象类型、失败语义与所有权。其他平台的实现可以提示字段含义，不能代替当前 Linux 构建的 ABI 证据。

## 2. 先恢复 ABI 和对象，再提交任务

“地址正确”只解决了一个问题。还要恢复调用约定、返回方式、容器布局、引用计数、回调对象和线程要求。

### 隐藏返回值不是普通参数

当前 ARM64 桥中，部分 C++ 返回对象通过 `x8` 指向的存储区返回。把它当作普通返回指针或直接塞进参数表，可能读错对象或破坏内存。项目把已恢复的调用形式放在 C/AArch64 shim 中，再从 JS 访问，见 `native/readonly_executor_shim.S`。

这不是对所有函数通用的模板。每个新增入口都需从实际调用点证明参数寄存器、返回存储和对象大小，尤其是非平凡 C++ 类型。

### 字符串也有对象布局

原生 `std::string` 不是 UTF-8 字节指针。本项目当前适配的字符串布局有短字符串和堆字符串分支，长度、容量、标志和数据位置都要对应。仅分配一个字符串指针再冒充对象，会把“看起来能读”变成不可预测的内存访问。

例如 `friend_profile_agent.js` 的读写辅助函数体现了当前构建的布局。不要把其中的 24 字节对象或字段偏移推广成所有平台的规则；使用非 ASCII 内容时，区分 UTF-8 字节数、JavaScript 字符数和 UTF-16 单位数。

### 所有权要画到销毁为止

对每个参数问清楚：借用还是转移？调用结束后会不会被保存？回调可能被复制几次？谁减少最后一个引用？

先用独立夹具验证复制、移动、内联存储与堆分配的清理路径。当前 C shim 的 `RH_STANDIN_TEST` 覆盖这些所有权分支：

```bash
cc -std=c11 -Wall -Wextra -Werror -DRH_STANDIN_TEST \
  native/readonly_executor_shim.c -o /tmp/weskill-native-standin
/tmp/weskill-native-standin
```

这验证本项目的 C 所有权模型，不调用微信地址，也不替代真实 ABI 与运行时验证。

## 3. 使用客户端的执行器

从 Frida 的 RPC 线程直接进入业务服务，并不等价于客户端自己的调用环境。线程亲和、线程局部数据和上下文都可能不同。

weSkill 通过已恢复的应用 executor 投递任务。每次业务先跑一个无操作任务，核对执行线程与计数，再提交业务回调。入口指令、主程序身份与 PID 生命周期也会核对。这样，线程不匹配可以在业务之前被发现。

建议从只读、结果小、容易独立核对的能力开始。只读也会构造原生对象，因此仍需正确的 ABI 与生命周期；“不改聊天内容”并不意味着可以随意试错指针。

## 4. 让每一层只负责一件事

```text
Skill                       解释任务、选择能力、确定目标
  ↓
server.py                   MCP 工具、schema 与返回契约
  ↓
service_client / service    同用户本机通信、共享服务、空闲退出
  ↓
WorkerBackend / native_worker
                            隔离 Frida 建连与可能在途的回调
  ↓
ExperimentalBackend         校验、串行化、分页、持久幂等、结果归一化
  ↓
业务 JS agent + executor    原生对象、业务调用、回调与所有权
  ↓
C / AArch64 shim            必要 ABI、任务包装与原子计数
```

这样划分让失败能够落到具体层次：MCP 参数错、服务没启动、连接失败、客户端拒绝和结果未知，不需要都包装成一个“发送失败”。Skill 读取能力后组织步骤，调度与业务流程通过公开工具接口调用执行层。

**窍门：先设计输出，再接入口。** 工具返回的目标 ID、来源、分页、权限和错误语义，往往比把所有原生字段直接暴露更重要。返回字段缺失时保留缺失，不填造联系人资料或刷新状态。

## 5. 成功与释放是两件事

客户端返回 `client_success` 就按项目约定认为操作成功，不额外等待对方确认或历史回查。但原生代码可能仍持有回调；业务完成不代表脚本可以立即卸载。

`native_resources.py` 为每个 worker 复用一个执行桥。释放业务脚本前同时检查：

- 回调已完成、原生回调对象已销毁。
- executor 无活任务，分配与释放计数一致。
- 此次临时 hook 已按路径清理。

正常完成的脚本释放；延迟销毁的脚本在下一次请求检查；无法证明结束的对象继续保留。worker 退出时，仍可能被原生引用的脚本留存至微信退出。这解释了为什么不能在超时时简单 `unload()` 或杀进程。

对应测试见 `test_native_resources.py` 和 `test_connection.py`。观察 `diagnostics.resources` 能看到共享桥、待回收脚本与创建/释放计数；这些计数用于判断本项目资源路径，不能当作整个微信进程无泄漏的证明。

## 6. 未知结果不是失败重试的同义词

一次写操作先保存幂等记录，再允许原生提交。账本用文件锁串行化，写入采用临时文件替换和 `fsync`。调用方即使中断，下次进程仍能看到原任务的状态。

| 状态 | 调用方处理 |
| --- | --- |
| `not_submitted` | 明确没有建立提交，可用原键显式再试 |
| `client_success` | 客户端返回成功，记录结果 |
| `client_error` | 保存原生错误，按错误含义处理 |
| `unknown` | 保留原键与记录，不自动重新提交 |

连接在接收业务之前失败，可以用新 worker 重建；业务写入管道之后断开，则不能推断“客户端没收到”。这个分界比增加重试次数更重要。

每个独立动作使用自己的幂等键；重放同一个动作保持键不变。同键不能修改目标或内容。媒体还绑定文件路径和字节哈希。调用方应为流程实例中的每个动作持久保存键。

## 7. 数据边界决定工具是否好用

### 64 位 ID 不经过浮点数

服务器消息 ID、朋友圈 ID 可能超出 JavaScript 安全整数范围。能取得原始 JSON 时保留原始序列化，在 Python 端解析，再把 ID 作为十进制字符串输出。先转成 JS Number 再转字符串，精度已经无法挽回。

### 分页要保留重叠边界

客户端原生单页数量不是用户查询总量。历史读取按时间续页，对同秒密集记录做边界处理；表情和朋友圈还需要保留未消费结果或服务端游标。不能把“这一页为空”“命中缓存”或“全部是置顶记录”直接解释为历史结束。

`backend.py`、`stickers.py` 与 `moments.py` 分别承担这些语义。使用 `partial_result`、`pagination_stalled` 等结果明确报告不完整，而不是把半份数据称为全部。

### 可读正文不等于结构化动作

正文里的 `@某人` 不等于微信真实提及，需要原生元数据。媒体路径也不等于客户端可发送的素材模型，需要符合客户端的缓存与上传链路。朋友圈图片在 `moments.py` 中处理方向、RGB JPEG 和缩略图，原始输入保留；发布时显式传可见范围。

## 8. 接入一项新能力的落点

| 需要改变什么 | 代码或文档 |
| --- | --- |
| MCP 名称、参数与 annotations | `src/weskill/server.py` |
| 本机通信与方法派发 | `service_client.py`、`service.py`、`native_worker.py` |
| 校验、结果语义、账本或分页 | `backend.py` 或独立领域模块 |
| 原生布局、回调与业务入口 | `src/weskill/assets/*_agent.js` |
| 执行桥与必要 ABI | `assets/executor_bridge.js`、`native/readonly_executor_shim.*` |
| 生命周期管理 | `native_resources.py` |
| 能力证据与研究目标 | `capabilities.py` |
| Agent 使用流程 | `plugins/weskill/skills/<skill>/SKILL.md` 及 references |
| 使用与验证范围 | `docs/TOOLS.md` 与对应领域文档 |

新增能力先定义输入、成功标准与不确定状态，再实现最小原生探针。把验证过的路径接入后端和 MCP，补上有意义的边界测试，最后让 Skill 按实际工具发现来使用。不要在 Skill 里硬写当前机器的联系人、群或绝对目录。

完整回归与公开文件预检：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_release.py
```

自动测试不向真实微信联系人发送消息。真实集成验证使用专门的测试会话和明确的动作范围，结果只公开脱敏摘要。

## 9. 哪些经验值得保留

- 搜索注册线索时围绕一个业务动作收敛，避免先做全客户端符号大全。
- 先验证构造和销毁，再验证业务效果；错误字符串对象能在“成功返回”之前就破坏状态。
- 优先复用客户端已有业务链，减少重新实现网络、缓存或素材模型的猜测。
- 一个异常结果只支持一个有限结论。加载实验中退出不代表所有媒体通道不可用；找到替代通道也不证明原实验原因已确定。
- 真实客户端成功、回调生命周期、协议正确与数据完整分别验证，别让一个绿色测试替其他几项背书。
- 原生串行化和业务流程并发是不同问题，不要让流程层绕过执行层的所有权约束。

## 10. 公开素材与私密产物

`.state/` 保存运行与验证结果，`research/` 保存实验资料，两者均忽略。发布包不包含真实账号、联系人、聊天正文、素材下载凭据、客户端二进制或研究内存片段。`check_release.py` 检查配置的私密标记与可见路径，但不能替代人工审阅新增公开内容。

npm 分发与宿主接入的实现见 `bin/weskill.mjs`、`lib/runtime.mjs` 与 `lib/bootstrap.py`；打包检查和真实 tarball 测试见 [版本发布](RELEASING.md)。

README 动画由虚构任务生成，不打开微信。修改 `tools/render_demo.py` 后运行：

```bash
.venv/bin/python tools/render_demo.py
# 其他发行版可用 --font 指定本机 CJK 字体
```

品牌主文件是 `assets/logo.svg`。导出 PNG 后同步插件 assets、总 Skill assets 和群 Skill assets；保持 SVG/PNG 一致，避免 README 与插件目录显示不同图标。

## 参考资料

- [REA](https://github.com/morluto/rea)：研究工作流。
- [Frida JavaScript API](https://frida.re/docs/javascript-api/) 与 [Best Practices](https://frida.re/docs/best-practices/)：插桩、原生调用与内存可达性。
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)：工具协议、stdio 与 schema。
- [Rprop/ipad 的群邀请确认字段线索](https://github.com/Rprop/ipad/blob/0278be2947eef98cb73f46579bce4428f7e93b96/api/service/groupService.go#L404) 与 [协议定义](https://github.com/Rprop/ipad/blob/0278be2947eef98cb73f46579bce4428f7e93b96/protobuf/wechat_proto/chatRoomAccessVerify.proto#L8)：跨平台参考，Linux 行为仍通过原生通道验证。
- [Pillow](https://pillow.readthedocs.io/en/stable/)：图片预处理与 README 动画。
