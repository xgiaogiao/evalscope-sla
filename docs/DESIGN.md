# evalscope-sla skill 设计文档

版本 v1.0（2026-11-23）｜对应工具：[evalscope-sla-kit](../../evalscope-sla-kit)（摸高测试线）

---

## 1. 背景与目标

evalscope-sla-kit 是一个对 OpenAI 兼容推理服务（vLLM / MindIE / 路由网关等）做
**evalscope 摸高测试**的工具：`--sla-auto-tune` 二分搜索满足 SLA 判据（TTFT / TPOT）的
最大并发数。但它本身是工程师工具——要手改 `config.yaml` 的场景清单、算数据集条数、
拼 nohup 命令、自己盯日志和解析 JSON 结果。

本 skill 的目标：**让用户用一句自然语言驱动完整压测流程**，从参数解析、配置生成、
预检、数据集生成、后台摸高、进度监控到性能数据汇总，全程由 Claude 按 SKILL.md 的
规程执行，不改动 kit 基座配置、不手写 YAML。

**范围 = 整个 kit（六条测试线全部保留、全部可用）**，封装深度分两档：

| 测试线 | 封装方式 |
|---|---|
| 摸高（性能） | 深度封装：三大场景组参数化默认 + 组级配置自动生成 + 条数预算 + 专用汇总（本文档主体） |
| 精度 / 功能 / AgentX / BFCL / SWE | 命令直达：自然语言路由到 kit 原生入口（`run.sh --accuracy/--functional/--agentx/--bfcl/--swe`），参数手册见 `references/kit-overview.md` |

kit 本体（52 个文件）原样部署在压测机，skill 不删改其任何代码；摸高线的 override
配置也只挂在基座之上（`base_config`），基座保持给其他五线与 Web 控制台共用。

## 2. 需求 → 场景覆盖矩阵（全覆盖确认）

需求原文三大场景，逐一映射到 skill 的场景组（gen_group_config.py `GROUPS` 表）：

| # | 需求原文 | skill 场景组 | kit 落地 | 覆盖 |
|---|---|---|---|---|
| 1 | 随机数据集测试·无缓存命中（prefix cache 0%），64k/75k/128k/256k/512k/1m 输入 + 1k 输出，5 人时 | `random-nocache`（上限 5） | `random` 数据集 + `hit=0`，6 个场景：`random_<len>_1k_hit0` | ✅ |
| 2 | 单前缀头测试·片上缓存命中（单前缀头 90%），同长度，5 人时 | `single-prefix`（上限 5） | `hit=0.9, prefix_num=1`，摸高前自动前缀预热灌 KV，6 个场景：`random_<len>_1k_hit90pct` | ✅ |
| 3 | 多前缀头测试·池化缓存命中（8/16/32 前缀头 90%），同长度，24 人时 | `multi-prefix`（上限 24） | `hit=0.9, prefix_num=8/16/32`，6 长度 × 3 前缀数 = 18 个场景：`random_<len>_1k_hit90pct_pN{8,16,32}` | ✅ |

公共需求「并发由低摸高至 TTFT 或 TPOT 突增」= evalscope `--sla-auto-tune`：
并发档从下界 1 倍增爬升（1,2,4,…,上限）并细化，每档跑 `sla_num_runs` 轮取均值，
判据 = avg TTFT≤X 且 avg TPOT≤Y 且失败数为 0；**"突增"（超判据）即停并回退**。
「输出性能数据」= collect_results.py 汇总出各档并发指标表 + 最大达标并发结论。

全量默认矩阵共 **30 个场景**（6+6+18），均写入 `references/scenario-matrix.md` 全表。

## 3. 已确认的设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 「5人/24人」语义 | = 摸高并发上限 `sla_upper_bound`（组 A/B=5，组 C=24） | 用户确认；到上限或 SLA 突增先到者停 |
| SLA 判据默认 | 0% 命中组：TTFT≤60000ms / TPOT≤50ms；90% 命中组：TTFT≤10000ms / TPOT≤50ms | 沿用 kit config.yaml 内置示例行，可被自然语言覆盖 |
| 执行环境 | 环境无关：SSH 驱动远端 Linux 压测机，目标存 skill 目录 `env.json` | kit 需要 bash/python3/evalscope/本地 tokenizer，Windows 本机跑不了；换机器只改 env.json |
| 数据集语料 | 三组默认 `random`（随机 token 定长） | 组 1 需求点名"随机数据集"；三组同语料横向可比；`--dataset gsm8k` 可切自然语言 |
| 「1m 输入」 | 统一归一为 kit 写法 `1000k` = **1024000** token（非 1048576） | kit `parse_len` 只认 k 简写，其内置 1M 档即 1000k |
| 配置方式 | 生成组级 override YAML（`base_config` 挂基座），不改基座 config.yaml | kit 的 `_deep_merge` 原生支持 base+override；基座保留给 web 控制台/其他测试线 |

## 4. 总体架构

```
┌─────────────── 本机 (Windows / Claude Code) ───────────────┐
│  用户自然语言 ──→ SKILL.md 规程（Claude 执行）               │
│       │ 解析: 场景组/长度/上限/SLA/前缀数/服务覆盖           │
│       │ env.json: ssh.host/user/port │ kit_dir │ tokenizer  │
└──────────┬──────────────────────────────────────────────────┘
           │ SSH（密钥 或 Posh-SSH 密码）
┌──────────▼─────────────── 远端 Linux 压测机 ─────────────────┐
│  <kit_dir>/skill_ext/gen_group_config.py                     │
│     └→ runs/<组>_<时间戳>.yaml   (base_config: ../config.yaml)│
│  <kit_dir>/runner.py --config runs/x.yaml                    │
│     ├→ datasets/random/*.jsonl + prompts.txt（定长随机数据）  │
│     ├→ [90%组] 前缀预热: 前缀数据集 1→64 并发阶梯灌 KV cache │
│     ├→ evalscope perf --sla-auto-tune（nohup 后台摸高）       │
│     └→ results/<场景ID>/<时间戳>/<model>/sla_summary.json    │
│        （预算切断时: results/<场景ID>/partial_summary.json）  │
│  <kit_dir>/skill_ext/collect_results.py                      │
│     └→ Markdown 性能表 + 最大达标并发 + JSON_RESULT          │
└──────────────────────────────────────────────────────────────┘
```

## 5. 端到端数据流（六步）

| 步骤 | 动作 | 产物/校验点 |
|---|---|---|
| 0 环境准备 | 读 env.json；`deployed=false` 则 scp 脚本 + `bash setup.sh` | `<kit>/skill_ext/` 两个脚本就位 |
| 1 NL→参数 | 按解析表抽取 场景组/长度/上限/SLA/前缀/预算 | 参数清单向用户复述确认 |
| 2 生成配置 | `gen_group_config.py --group …`（远端） | `runs/<组>_<ts>.yaml` + `JSON_RESULT`；`[WARN]` 必须先处理 |
| 3 预检+数据集 | `runner.py --config … --dry-run`；curl 探活；`--gen-datasets` 后台 | dry-run 打印 evalscope 命令；数据集条数=预算值 |
| 4 启动摸高 | `nohup python3 runner.py --config …`（多组用 `bash -c` 串联） | logs/skill_*.log；任意时刻仅一组在跑 |
| 5 汇总输出 | `collect_results.py --config … [--npu N]` | Markdown 逐场景表 + 组级汇总，原样转述用户 |

## 6. 与 kit 机制的映射（本 skill 依赖的关键事实）

| kit 机制 | skill 依赖方式 |
|---|---|
| 场景行 8 字段 `"dataset, in, out, hit, prefix_num, ttft, tpot[, num]"` | gen 按此格式生成行；collect 按同口径解析回场景 ID 与 SLA |
| `base_config` 深合并（dict 递归、**list 整体替换**） | override 只写 scenarios + sla_upper_bound + 显式 service 覆盖，其余继承基座 |
| `--sla-auto-tune --sla-variable parallel --sla-params [{avg_ttft,avg_tpot}]` | "摸高至突增"的底层实现；上限来自 benchmark.sla_upper_bound（组级覆盖） |
| `hit_rate>0` 时自动前缀预热（1→64 并发阶梯） | 片上/池化命中的前提，skill 无需干预，排障时看 `prefix_warmup/` |
| 数据集按文件名复用（RANDOM-in{len}-num{n}-{tok}[-pN{n}][-repeatRate]） | 不同组/前缀数天然分文件；调参后需删文件或 force_regenerate |
| `check_dataset_sufficient` 条数预检公式 | gen 用**同一公式**（档位倍增序列 × multiplier × runs + warmup，且与基座 benchmark 值取大）算 dataset_num 写进场景行，保证必过 |
| run.sh 的 FOREGROUND 扫描与 nohup 行为 | **多组串行禁止** `run.sh A; run.sh B`（会并行互踩）；skill 统一直连 `runner.py` + `bash -c` 串联 |
| sla_summary.json（parallel_N→metrics/percentiles）/ partial_summary.json | collect 的数据源；partial 的 selected 是真实上限的**下界** |
| tokenizer_path 必须是压测机本地目录 | gen 预检 + SKILL.md 强制从 env.json 传入 |

## 7. 判定与结果语义

- 单档判定：`Failed==0` 且 `avg TTFT≤SLA` 且 `avg TPOT≤SLA` → PASS（与 kit report.py 口径一致）
- 摸高结论：全部 PASS 档中的最大并发 = **最大达标并发**；该档的 TTFT/TPOT/输出吞吐随结论输出
- 无达标档：最低并发即违反 SLA 或请求失败（多为服务不可用，先排障）
- partial（给了 time_budget_min 且到限切断）：结论是真实上限的下界，转述必须带此语义

## 8. 目录结构

```
evalscope-sla/
├── SKILL.md                     # 主指令（Claude 每次加载执行）
├── README.md                    # 使用文档（面向人）
├── env.example.json             # → 复制为 env.json 填压测机信息
├── references/
│   ├── kit-overview.md          # kit 工具全貌：六条测试线命令手册 + Web 控制台
│   ├── scenario-matrix.md       # 三组场景全表/时长预估/结果目录结构
│   └── operations.md            # 进度/停止/重跑/排障表
├── scripts/                     # 部署到压测机 <kit>/skill_ext/
│   ├── gen_group_config.py      # 参数 → 组级 override YAML（stdlib + 可选 pyyaml）
│   └── collect_results.py       # sla_summary/partial_summary → Markdown（stdlib+pyyaml）
└── docs/
    ├── DESIGN.md                # 本文档
    └── DEVELOPMENT.md           # 开发文档（kit 机制详解/脚本内部/扩展指南）
```

## 9. 扩展点

- **新增场景组**：`gen_group_config.py` 的 `GROUPS` 加一项（hit/prefixes/upper/SLA 默认）→ `references/scenario-matrix.md` 补全表 → `SKILL.md` 第 1 步解析表加触发词
- **新增参数**：argparse 加参 → gen_one 写入 YAML 对应键 → SKILL.md 解析表补一行
- **新结果指标**：collect_results.py 的 `K_*` 键与 render 列扩展

## 10. 已知限制与风险

| 项 | 说明 | 缓解 |
|---|---|---|
| 脚本未实跑 | 本机无 Python，仅人工逐行核查 | 部署后先 `python3 -m py_compile` + 小场景冒烟（见 DEVELOPMENT.md 测试清单） |
| 长输入耗时/体量 | 1m×280 条 ≈ 1GB+、生成小时级；组 C 全量天级 | SKILL.md 建议分批 + time_budget_min |
| 服务上下文上限 | 256k+ 档需服务真支持（示例 204800 只够 128k+1k） | gen 预检 `[WARN]` 拦截 |
| report.py 交叉核对 | kit report.py 的 SLA 判据只读基座 config.yaml，不认组级覆盖 | 仅作参考，以 collect_results.py 为准 |
| web 双驱动 | webapp 看不到 runs/*.yaml，且并行启停会互踩 | skill 任务一律 CLI 驱动，operations.md 明令禁止 web 启停 |
| 共用压测机误杀 | `pkill -f evalscope` 会杀该机全部 evalscope | 停止前先 pgrep 确认（operations.md） |
