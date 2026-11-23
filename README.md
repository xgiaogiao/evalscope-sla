# evalscope-sla 使用文档

用自然语言驱动 [evalscope-sla-kit](../evalscope-sla-kit) 的 Claude Code skill。
被封装的工具是一个 OpenAI 兼容推理服务（vLLM / MindIE / 路由网关等）**综合测试台**。

## 工具一共有什么功能（kit 全貌）

| # | 功能 | 一句话说明 | 入口 |
|---|---|---|---|
| 1 | 摸高（性能） | 并发从低爬升找满足 SLA（TTFT/TPOT）的最大并发；随机/前缀命中/多前缀池场景 | `bash run.sh` |
| 2 | 精度（pass@k） | gsm8k/mmlu/gpqa/aime 数据集组精度，pass@1..k，断点续跑 | `bash run.sh --accuracy` |
| 3 | 功能（API E2E） | 50 条用例：兼容性/参数/工具调用/结构化输出/思考泄漏/负向 | `bash run.sh --functional` |
| 4 | AgentX 回放 | 回放真实 Claude Code 会话 trace 测真实智能体负载 | `bash run.sh --agentx` |
| 5 | BFCL 函数调用 | Berkeley 函数调用榜单 v4（22 子集）精度 | `bash run.sh --bfcl` |
| 6 | SWE-bench_Pro | 642 实例智能体代码评测 resolved 率（监控+补跑） | `bash run.sh --swe status` |
| 配1 | 池对照 | mooncake/memcache 外置 KV 池摸高结果对比 | `python3 compare_pools.py` |
| 配2 | Web 控制台 | 八页签界面：配置/进度/曲线/CSV/启停 | `python3 webapp.py --port 8300` |
| 配3 | 工具箱 | 数据集生成/语料裁剪/守护/SWE 补丁等 20+ 脚本 | tools/ |

**全部功能保留、全部可经自然语言使用**：摸高线为深度封装（三大场景组自动配置+汇总），
其余直达 kit 原生命令。

- 设计文档：[设计文档.md](设计文档.md)（架构/决策/场景覆盖矩阵 + 7 幅 Mermaid 流程图）
- 开发文档：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)（kit 机制详解/脚本内部/扩展指南）
- 工具全貌手册：[references/kit-overview.md](references/kit-overview.md)（六线命令/参数/产出/排障）
- 运维排障：[references/operations.md](references/operations.md)

## 三大场景组（默认矩阵，共 30 个场景）

| 组 | 场景 | 输入（+1k 输出） | 缓存命中 | 摸高上限 | SLA 默认 |
|---|---|---|---|---|---|
| A | 随机数据集测试·无缓存 | 64k/75k/128k/256k/512k/1m | prefix cache 0% | 5 | TTFT≤60s / TPOT≤50ms |
| B | 单前缀头测试·片上缓存 | 同上 | 90%（单前缀） | 5 | TTFT≤10s / TPOT≤50ms |
| C | 多前缀头测试·池化缓存 | 同上 | 90%（8/16/32 前缀） | 24 | TTFT≤10s / TPOT≤50ms |

每组每档输出：并发数、成功/总数、TTFT avg/p99、TPOT avg、输出吞吐（可折算单卡）、
PASS/FAIL 判定；结论给出最大达标并发。90% 组摸高前自动做前缀预热把前缀灌进 KV cache。

## 六条线的自然语言用法示例

摸高线是深度封装（上面的三大场景组），其余五条线同样可以用自然语言触发，直达 kit
原生命令：

| 测试线 | 测什么 | 自然语言示例 |
|---|---|---|
| 摸高（性能） | 并发爬升找最大达标并发 | "跑一下随机数据集摸高，全部长度" |
| 精度（pass@k） | gsm8k/mmlu/gpqa/aime 精度，pass@1..k | "跑 all5 精度，k=4，冒烟 limit 10" |
| 功能（API E2E） | 50 条用例：兼容性/参数/能力/思考泄漏/负向 | "跑一遍功能测试，只跑 C30" |
| AgentX 回放 | 真实 Claude Code 会话 trace 负载 | "AgentX 只跑 256k 变体" |
| BFCL v4 | 函数调用精度（22 子集） | "BFCL 冒烟 simple_python 加 irrelevance" |
| SWE-bench_Pro | 642 实例智能体代码评测（只读监控+补跑） | "看下 SWE 评测进度" |

另有 Web 控制台（`python3 webapp.py --port 8300`，八页签，人工查看曲线/导出用）。
六条线的命令手册、参数、产出位置、已知坑：**[references/kit-overview.md](references/kit-overview.md)**。

## 安装（一次性）

1. **装 skill**：把本目录复制到 `~/.claude/skills/evalscope-sla/`（新会话生效）。
2. **填环境**：把 `env.example.json` 复制为 `env.json`，填压测机 SSH（host/user/port）、
   `kit_dir`（kit 在压测机上的路径）、`service.tokenizer_path`（压测机本地 tokenizer 目录）。
3. **首次部署**（skill 会引导，也可手动）：
   ```powershell
   ssh <user>@<host> "mkdir -p <kit_dir>/skill_ext"
   scp scripts\gen_group_config.py scripts\collect_results.py <user>@<host>:<kit_dir>/skill_ext/
   ssh <user>@<host> "cd <kit_dir> && bash setup.sh"    # 装 evalscope+补丁, 幂等
   ```
   压测机还没有 kit 时先 `scp -r evalscope-sla-kit <user>@<host>:<kit_dir>`。

## 快速上手（示例对话）

```
你: 跑一下随机数据集摸高，全部长度                          → 组 A（6 场景，上限 5）
你: 单前缀测试，只跑 128k 和 256k，摸到 4                  → 组 B 子集，上限改 4
你: 多前缀 8 和 16，全长度                                  → 组 C 子集（12 场景，上限 24）
你: 三组全部按默认跑一遍                                    → A→B→C 串行（30 场景）
你: TTFT 阈值放宽到 90 秒再摸                               → 覆盖 SLA 判据
你: 每场景最多跑 90 分钟                                    → time_budget_min=90（切断出下界结论）
你: 现在跑到哪了 / 停掉当前压测 / 重跑 64k 那个场景         → 运维操作
你: 汇总上次多前缀的结果，按 8 卡折算                       → 只汇总不新跑
```

skill 每次启动前会向你复述：场景组/长度/上限/SLA/目标服务，确认后开跑。

## 标准工作流

```
读 env.json → 解析自然语言参数
  → gen_group_config.py 生成 runs/<组>_<时间戳>.yaml（自动预算数据集条数、预检告警）
  → runner.py --dry-run 预检 + curl 探活
  → nohup 后台: 预生成数据集 → (90%组)前缀预热 → evalscope --sla-auto-tune 摸高
  → collect_results.py 汇总 → Markdown 性能表 + 最大达标并发
```

长输入（≥256k）是小时~天级任务：建议先跑 64k/75k 验证链路，再分批上长输入；
1m 数据集体量 GB 级、生成小时级（详见 [references/scenario-matrix.md](references/scenario-matrix.md) 时长表）。

## 常见问题

| 问题 | 答案 |
|---|---|
| 在哪台机器跑？ | env.json 里配置的远端 Linux 压测机（kit 需要 bash/python3/evalscope/本地 tokenizer），本 skill 经 SSH 驱动，随时可换机器 |
| "1m 输入"是多少 token？ | 1024000（kit 写法 1000k，非 1048576） |
| 256k+ 报警"超上下文上限"？ | 被测服务 max_context_length 不够，该档会被服务端拒绝；让服务方放开或去掉该长度 |
| 摸高停在某档不动了？ | 正常——每档要跑 并发×2 个请求 × 2 轮；1m 档单轮数十分钟。问 skill "跑到哪了" |
| 结果里 selected 是下界？ | 该场景被 time_budget_min 切断（partial），真实上限在 已达标档 与 首个违反档 之间 |
| 想看曲线/导出 CSV？ | 压测机 `python3 <kit>/webapp.py --port 8300` 开 Web 控制台查看（只读，勿在 web 启停 skill 任务） |

## 目录说明

| 文件/目录 | 用途 |
|---|---|
| `SKILL.md` | skill 主指令（Claude 加载执行的操作规程） |
| `env.example.json` | → 复制为 `env.json`：压测机与被测服务信息 |
| `references/scenario-matrix.md` | 三组 30 个场景的全表、时长/体量预估、结果目录结构 |
| `references/operations.md` | 进度查询/停止/重跑/排障表/partial 语义 |
| `scripts/gen_group_config.py` | 部署到压测机：参数→组级 override YAML（数据集条数自动预算） |
| `scripts/collect_results.py` | 部署到压测机：结果 JSON→Markdown 性能表 |
| `设计文档.md` / `docs/DEVELOPMENT.md` | 设计文档（含流程图）/ 开发文档 |
