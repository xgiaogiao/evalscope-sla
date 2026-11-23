---
name: evalscope-sla
description: 自然语言驱动 evalscope-sla-kit 的全部六条测试线。摸高（性能）线深度封装三大场景组：①随机数据集测试·无缓存命中（prefix cache 0%，64k/75k/128k/256k/512k/1m 输入+1k 输出，摸高上限 5）②单前缀头测试·片上缓存命中 90%（同长度，上限 5）③多前缀头测试·池化缓存命中 90%（8/16/32 前缀，同长度，上限 24），并发从 1 爬升至 TTFT/TPOT 超 SLA 判据即"突增"停止，输出各档性能数据与最大达标并发；其余五条线（精度 pass@k / 功能 API E2E / AgentX 智能体回放 / BFCL v4 函数调用 / SWE-bench_Pro 代码评测）经自然语言直达 kit 原生命令。自动完成组级配置生成、数据集条数预算、预检、SSH 远程后台启动、进度监控与结果汇总。Triggers: "摸高", "摸高测试", "SLA 测试", "SLA 压测", "性能摸高", "随机数据集测试", "无缓存测试", "前缀缓存", "单前缀", "多前缀", "片上缓存", "池化缓存", "TTFT", "TPOT", "evalscope", "压测大模型", "并发摸高", "跑一下压测", "精度测试", "pass@k", "功能测试", "API E2E", "兼容性用例", "AgentX", "智能体回放", "BFCL", "函数调用评测", "SWE-bench", "代码评测".
---

# evalscope-sla：自然语言压测 skill（覆盖 kit 全部功能）

对远端 Linux 压测机上的 evalscope-sla-kit 发号施令。你（Claude）负责把自然语言解析成
参数 → SSH 到压测机生成配置/启动/监控/汇总，**不直接手写 YAML、不改动 kit 基座
config.yaml、不删改 kit 的任何功能**。

## 工具功能总览：evalscope-sla-kit 一共有这些功能（介绍时先讲全貌）

被封装的 evalscope-sla-kit 是一个 OpenAI 兼容推理服务（vLLM / MindIE / 路由网关等）
**综合测试台**：6 条测试线 + 3 个配套件。向用户介绍本工具时，按此表全量说明，不要只讲摸高线：

| # | 功能 | 一句话说明 | 入口 |
|---|---|---|---|
| 1 | **摸高（性能）** | 并发从低爬升找满足 SLA（TTFT/TPOT）的最大并发，支持随机/前缀命中率/多前缀池场景 | `bash run.sh` |
| 2 | **精度（pass@k）** | gsm8k/mmlu/gpqa/aime 等数据集组精度，每题采样 k 次出 pass@1..k，支持断点续跑 | `bash run.sh --accuracy` |
| 3 | **功能（API E2E）** | 50 条用例（C01-C61）：OpenAI 兼容性/参数探测/工具调用/结构化输出/思考泄漏/负向 | `bash run.sh --functional` |
| 4 | **AgentX 智能体回放** | 回放真实 Claude Code 会话 trace（393 会话），测真实智能体负载的 TTFT/吞吐/缓存命中 | `bash run.sh --agentx` |
| 5 | **BFCL 函数调用** | Berkeley 函数调用榜单 v4（22 子集）：AST 匹配/多轮状态机/幻觉拒绝精度 | `bash run.sh --bfcl` |
| 6 | **SWE-bench_Pro 代码评测** | 642 个真实仓库 issue 生成补丁跑金标测试的 resolved 率（只读监控+补跑） | `bash run.sh --swe status` |
| 配1 | 池对照 | mooncake/memcache 等外置 KV 池的摸高结果对比表 | `python3 compare_pools.py` |
| 配2 | Web 控制台 | 八页签图形界面：配置/用例/工程进度/曲线/CSV 导出/启停 | `python3 webapp.py --port 8300` |
| 配3 | 工具箱 | 数据集生成/语料裁剪/守护脚本/pass@k wrapper/SWE 环境补丁（tools/ 下 20+ 脚本） | 各脚本独立运行 |

**skill 的分工**：摸高线深度封装（下文三大场景组）；其余功能经自然语言直达 kit 原生
命令（「工具全貌」一节的路由表 + `references/kit-overview.md` 参数手册）。

```
本机(Windows)                       远端 Linux 压测机
Claude ──SSH──→ <kit_dir>/skill_ext/gen_group_config.py   生成 runs/<组>_<时间戳>.yaml
                    │                <kit_dir>/runner.py --config runs/x.yaml   摸高(nohup后台)
                    │                <kit_dir>/skill_ext/collect_results.py     汇总→Markdown
                    └── 结果: results/<场景ID>/…/sla_summary.json
```

## 工具全貌：其他五条测试线的自然语言入口（kit 功能全部保留）

用户提到下表意图时，按对应命令经 SSH 执行（`cd <kit_dir> && …`）。这五线用 kit 原生
入口，目标服务/tokenizer 沿用 env.json 或基座 config.yaml；详细参数手册与产出位置见
`references/kit-overview.md`：

| 用户意图（示例说法） | 远端命令 |
|---|---|
| 精度测试 / pass@k / "跑一下 gsm8k mmlu 精度" | `bash run.sh --accuracy [--only <tag>] [--k N] [--limit N] [--resume]`；汇总 `python3 accuracy_runner.py --report` |
| 功能测试 / API E2E / "跑兼容性用例" | `bash run.sh --functional`；单用例 `python3 scripts/run_api_e2e.py --only C30`；清单 `--list` |
| AgentX / "回放真实会话 / 智能体负载" | `bash run.sh --agentx [-f --only 256k] [--concurrency N]`；`python3 agentx_runner.py --list` |
| BFCL / "函数调用评测" | `bash run.sh --bfcl [-f --only <子集> --limit N] [--resume]`；汇总 `python3 bfcl_runner.py --report` |
| SWE-bench_Pro / "代码评测跑到哪了" | `bash run.sh --swe status｜aggregate｜rerun-list｜env-check｜start-rerun [--yes]`（只读监控+带护栏补跑） |
| Web 控制台 / "看曲线" | `python3 webapp.py --port 8300`（人工只读查看用；**勿在 web 启停 skill 任务**，双驱动互踩） |
| 池对照 / "mooncake 和 memcache 哪个池好" | `python3 compare_pools.py [mooncake memcache]`（前提：各池跑完把 results/<场景ID>/ 移到 results/<池名>/ 下） |

五线通用约定：后台任务同样 nohup+日志（`logs/acc_*/func_*/agentx_*/bfcl_*.log`）；
同一时刻整台压测机只跑一条线；结果落 `results/accuracy|functional|agentx|bfcl/`，
转述时读对应 `scores.md` / `report.md` / summary JSON。

## 已确认的设计决策（不要重新发明）

| 决策点 | 结论 |
|---|---|
| 「5人/24人」 | = **摸高并发上限**（sla_upper_bound）。随机/单前缀组摸到 5，多前缀组摸到 24，中途 TTFT 或 TPOT 超 SLA 判据即停（即"突增"） |
| SLA 判据默认 | 无缓存 0%：TTFT≤60000ms / TPOT≤50ms；命中 90%：TTFT≤10000ms / TPOT≤50ms（"突增"=超阈值；可被自然语言覆盖） |
| 执行环境 | 环境无关：SSH 驱动远端 Linux 压测机，目标在 `env.json` 里，随时可换 |
| 数据集语料 | 三组默认 `random`（随机 token）；用户说"gsm8k/自然语言"时切 `--dataset gsm8k` |
| 「1m 输入」 | kit 不认 `1m`，**统一写 `1000k`（=1024000 token，不是 1048576）**，gen 脚本已自动归一 |

## 第 0 步：环境（每次执行前）

1. 读本 skill 目录的 `env.json`（不存在 → 从 `env.example.json` 复制，向用户要
   host/user/kit_dir/tokenizer_path 后填好再继续）。
2. `deployed: false` 或 `<kit_dir>/skill_ext/gen_group_config.py` 不存在 → 先走**首次部署**：
   ```powershell
   # 密钥认证（密码认证用 Posh-SSH 的 New-SSHSession/Invoke-SSHCommand, 命令内容相同）
   ssh <user>@<host> "mkdir -p <kit_dir>/skill_ext"
   scp <skill目录>\scripts\gen_group_config.py <skill目录>\scripts\collect_results.py <user>@<host>:<kit_dir>/skill_ext/
   ssh <user>@<host> "cd <kit_dir> && bash setup.sh"        # 装 evalscope + custom 插件补丁, 幂等
   ```
   若压测机还没有 kit：先 `scp -r evalscope-sla-kit <user>@<host>:<kit_dir>`。
3. 摸高目标必须是**授权的测试服务**。首次或换目标 URL 时，向用户确认一次再开跑。

## 第 1 步：自然语言 → 参数

| 用户说法 | 解析 |
|---|---|
| "随机数据集 / 无缓存 / 0% 命中 / 不带前缀" | `--group random-nocache` |
| "单前缀 / 单前缀头 / 片上缓存 / 90% 单命中" | `--group single-prefix` |
| "多前缀 / 池化缓存 / 8(16/32) 前缀" | `--group multi-prefix`（只测部分前缀 → `--prefixes 8,16`） |
| "全部 / 三组 / 完整跑一遍" | `--group all`（A→B→C 串行） |
| 长度列举 "只跑 128k 和 256k" | `--lengths 128k,256k`（默认全六档） |
| "摸到 16 / 上限 16 / 16 并发 / 16 人" | `--upper 16` |
| "TTFT 阈值 30 秒" / "TPOT 100 毫秒" | `--ttft-ms 30000` / `--tpot-ms 100` |
| "用 gsm8k / 自然语言文本" | `--dataset gsm8k` |
| "每场景最多跑 2 小时" | `--time-budget-min 120`（到限算 partial 下界结论） |
| "按 8 卡折算" | 汇总时 `--npu 8` |
| "汇总/出报告"（不新跑） | 只走第 5 步 collect |
| "跑到哪了 / 看进度 / 停掉" | 见 `references/operations.md` |

三大场景组默认矩阵（细节、场景 ID 全表、时长预估见 `references/scenario-matrix.md`）：

| 组 | 内容 | 命中/前缀 | 长度 | 上限 | SLA 默认 | 场景数 |
|---|---|---|---|---|---|---|
| A `random-nocache` | 随机数据集·无缓存 | 0%，无前缀 | 64k~1m +1k 输出 | 5 | 60s / 50ms | 6 |
| B `single-prefix` | 单前缀头·片上缓存 | 90%，pN=1 | 同上 | 5 | 10s / 50ms | 6 |
| C `multi-prefix` | 多前缀头·池化缓存 | 90%，pN=8/16/32 | 同上 | 24 | 10s / 50ms | 18 |

## 第 2 步：生成组级配置（远端）

```powershell
# 单行命令（<组>=random-nocache|single-prefix|multi-prefix|all；按解析结果拼参数）
ssh <user>@<host> "cd <kit_dir> && python3 skill_ext/gen_group_config.py --group <组> --lengths <...> --upper <N> --tokenizer-path <tok> [--prefixes 8,16,32] [--ttft-ms ..] [--tpot-ms ..] [--dataset gsm8k] [--time-budget-min ..] [--url ..] [--model ..]"
```

- `tokenizer_path` 取 env.json（基座 config.yaml 该字段常为空，不给必失败）。
- url/model 只有 env.json 里填了才传，否则继承基座。
- 读取输出末尾的 `JSON_RESULT:`——记下 config 路径、场景 ID 清单、数据集条数、警告。
- **有 `[WARN]` 必须先处理**（tokenizer 不存在 / 长度超服务上下文上限是最常见的两类）。

## 第 3 步：预检 + 预生成数据集（强烈推荐）

```powershell
# 预检: 打印将执行的 evalscope 命令, 校验 tokenizer/服务配置
ssh <user>@<host> "cd <kit_dir> && python3 runner.py --config <rel.yaml> --dry-run"
# 服务可达性(注意绕代理)
ssh <user>@<host> "curl -s --noproxy '*' -o /dev/null -w '%{http_code}' '<url去掉/chat/completions>/models'"
# 预生成数据集(后台; 1m×280 条可达 GB 级、小时级, 提前生成避免摸高中途卡住)
ssh <user>@<host> "cd <kit_dir> && nohup python3 runner.py --config <rel.yaml> --gen-datasets > logs/gen_<组>.log 2>&1 &"
```

数据集生成完的标志：gen 日志尾出现 `数据集生成完成`。90% 命中组摸高时会**自动先做前缀
预热**（把前缀灌进 KV cache，1→64 并发阶梯），这是"片上/池化命中"的前提，无需人工干预。

## 第 4 步：启动摸高（后台、组间串行）

```powershell
# 单组
ssh <user>@<host> "cd <kit_dir> && nohup python3 runner.py --config <relA.yaml> > logs/skill_A.log 2>&1 & echo PID=\$!"
# 多组串行("全部"): 一个 bash -c 串起来, 跑完一组自动下一组
ssh <user>@<host> "cd <kit_dir> && nohup bash -c 'python3 runner.py --config <relA.yaml>; python3 runner.py --config <relB.yaml>; python3 runner.py --config <relC.yaml>' > logs/skill_all.log 2>&1 & echo PID=\$!"
```

**硬规则**：
- 禁止 `bash run.sh --config A; bash run.sh --config B` 链式串跑——run.sh 对非前台参数会
  nohup 后立即返回，两组会**并行**互相干扰。多组一律用上面的 `bash -c` 包 runner.py。
- 任意时刻**只能有一组摸高在跑**；启动前 `pgrep -af 'runner.py|evalscope'` 确认无残留。
- 启动后向用户报告：日志路径、场景清单、预计时长（见 references/scenario-matrix.md 的
  时长表），并告知可随时问"跑到哪了"。

## 第 5 步：汇总输出性能数据

```powershell
ssh <user>@<host> "cd <kit_dir> && python3 skill_ext/collect_results.py --config <rel.yaml> [--npu 8]"
```

把输出的 Markdown 原样转述给用户（每场景一张并发-指标表 + **最大达标并发**结论 + 组级
汇总）。没跑完的场景显示"运行中或无汇总"——部分完成的场景若被时间预算切断，结论是
**真实上限的下界**（真实上限落在 已达标档 与 首个违反档 之间），转述时要带这个语义。
需要交叉核对时也可跑 `python3 report.py`（kit 自带，按基座 config 判 SLA）。

## 交互纪律

- **介绍工具时先讲全貌**：用户问"这个工具能干什么/有什么功能"，或首次使用时，先按
  「工具功能总览」表完整介绍 6 条测试线 + 3 个配套件，再谈具体任务——不要只说摸高线。
- 每次启动前用 3~5 行向用户**复述**：场景组/长度/摸高上限/SLA 判据/目标服务，确认后再执行。
- 长输入（≥256k）全六档是**小时~天级**任务：主动建议分批（先 64k/75k 验证链路再跑长输入）、
  给 `--time-budget-min`、预生成数据集。
- 任何 `[WARN]`、`Failed at lower bound`、`Dataset is empty` → 按 `references/operations.md` 排障表处理，不要盲目重试。
- 详细运维（进度/停止/重跑单场景/结果目录结构/已知坑）看 `references/operations.md`；
  场景矩阵细节看 `references/scenario-matrix.md`；其他五条测试线的完整参数手册看
  `references/kit-overview.md`（kit 工具全貌）。
