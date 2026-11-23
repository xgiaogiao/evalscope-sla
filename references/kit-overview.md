# evalscope-sla-kit 工具全貌（六条测试线 + Web 控制台）

> 本文档完整介绍被封装工具 evalscope-sla-kit 的**全部功能**。skill 对六条线全部可达：
> 摸高线深度封装（三大场景组，见 `scenario-matrix.md`），其余五线经自然语言直达 kit
> 原生命令（本文档即命令手册）。工具本体永远原样使用，skill 不删不改其任何代码。

## 六条测试线总览

| 测试线 | 测什么 | 入口（压测机上执行） | 产出 |
|---|---|---|---|
| **摸高（性能）** | SLA 摸高：并发爬升找最大达标并发（TTFT/TPOT 判据） | `bash run.sh` / `python3 runner.py`（skill 深度封装） | `results/<场景ID>/…/sla_summary.json` + report.py 表 |
| **精度（pass@k）** | 数据集组精度：gsm8k/mmlu/gpqa/aime 等，pass@k 口径 | `bash run.sh --accuracy` | `results/accuracy/<tag>_r<N>/` + `scores.md` |
| **功能（API E2E）** | 50 条用例 C01-C61：兼容性/参数/能力/结构化/思考泄漏/负向 | `bash run.sh --functional` | `results/functional/e2e_<ts>/report.md` |
| **智能体回放（AgentX）** | 回放真实 Claude Code 会话 trace 测真实负载性能 | `bash run.sh --agentx` | `results/agentx/<tag>_<ts>/` |
| **函数调用（BFCL v4）** | Berkeley 函数调用榜单 22 子集（AST/多轮/幻觉拒绝） | `bash run.sh --bfcl` | `results/bfcl/<tag>/reports/…/bfcl_v4.json` + `scores.md` |
| **智能体代码（SWE-bench_Pro）** | 642 真实仓库实例生成补丁跑金标测试，resolved 率 | `bash run.sh --swe status`（只读监控+补跑） | live 工作区 `swe_pro/` |

`run.sh` 通用约定：默认 nohup 后台跑（日志 `logs/<前缀>_<时间戳>.log`，前缀=
run/acc/agentx/func/bfcl）；加 `-f` 前台调试；`--dry-run`/`--list` 只看不跑。

---

## 1. 摸高线（本 skill 的深度封装对象）

见 `SKILL.md` 主体与 `scenario-matrix.md`：三大场景组（随机 0% / 单前缀 90% / 多前缀
8·16·32 90%），64k~1m 输入 + 1k 输出，并发 1→5/1→24 摸高至 TTFT/TPOT 突增。
skill 之外也可用 kit 原生方式：改 `config.yaml` scenarios 段（注释=停用）→ `bash run.sh`
→ `python3 report.py --npu 8`。

配套的**池对照工具**（多前缀/池化缓存测试后常用）：`compare_pools.py` 对比
mooncake / memcache 等外置 KV 池的摸高结果——每个池跑完一轮后把 `results/<场景ID>/`
整目录移到 `results/<池名>/<场景ID>/`，然后：

```bash
python3 compare_pools.py                    # 对比 results/ 下所有池
python3 compare_pools.py mooncake memcache  # 指定池顺序
```

另：`functional_runner.py` 是功能线的兼容壳（转发到 `scripts/run_api_e2e.py`），
两种调用等价。

## 2. 精度线（accuracy_runner.py）

对被测服务跑 evalscope eval 数据集组，**pass@k 口径**：每题重复采样 k 次，
`mean_and_pass_at_k` 聚合同时给 mean 与 pass@1..pass@k。宿主机直跑。

```bash
bash run.sh --accuracy                    # 后台跑所有启用组（config accuracy 段）
bash run.sh --accuracy -f                 # 前台
bash run.sh --accuracy --resume           # 断点续跑（复用已有 predictions，秒级重出报告）
python3 accuracy_runner.py --list         # 列启用数据集组
python3 accuracy_runner.py --only all5    # 只跑指定组
python3 accuracy_runner.py --k 4          # pass@k 的 k
python3 accuracy_runner.py --limit 10     # 冒烟：每组 N 条（mmlu 是每子集 N 条！）
python3 accuracy_runner.py --report       # 重打已有结果汇总表
```

config `accuracy.datasets` 行格式：`"tag, evalscope_datasets, rounds, effort, max_tokens,
batch_size [, k]"`。要点：

- `effort` 避开 `medium`（部分部署必 400，已知缺陷）
- k>1 时请求量 ×k；全量 all5 + k=4 ≈ 20 小时，中断**别删 work-dir**，用 `--resume`
- 换 k/数据集组合续跑会混入旧预测——换口径换 tag

## 3. 功能线（scripts/run_api_e2e.py）

Simaas 风格 API E2E：50 条用例单一 C 编号（C01-C61，流式空洞保留编号），全非流式，
判定 PASS/WARN/FAIL/SKIP。覆盖：openai 兼容性（C01-C04）/ 参数探测（C05-C06）/
能力（C07-C15）/ SDK（C16-C19）/ 结构化输出（C21-C26）/ 思考泄漏（C27-C33）/
上下文（C34-C38）/ 计费一致性（C39-C40）/ 负向（C41）/ 鲁棒性（C51-C53）/
effort 矩阵（C54-C60）。

```bash
bash run.sh --functional                         # 后台跑全部
python3 scripts/run_api_e2e.py --list            # 列出全部用例
python3 scripts/run_api_e2e.py --only C30        # 只跑指定用例（C 编号/tag/名字子串）
python3 scripts/run_api_e2e.py --dry-run         # 打印计划不发请求
```

开关：`--skip-responses-api`（跳过 13 条 /v1/responses 用例）、`--thinking-depth-check`
（C33 思考深度探针）、`--long-context-api`（C37/C38）。FAIL 计入退出码；WARN=已知缺陷
或可选能力未实现，不算失败。

## 4. AgentX 线（agentx_runner.py）

用 agentx-harness 回放 SemiAnalysis 公开的 Claude Code 真实会话 trace（393 个智能体
编码会话：多轮/子智能体/前缀复用/KV cache 命中），测**真实智能体工作负载**下的
TTFT/吞吐/缓存命中。宿主机直跑。

```bash
bash run.sh --agentx                            # 后台跑启用变体
bash run.sh --agentx -f --only 256k             # 前台只跑指定变体
python3 agentx_runner.py --list                 # 列启用变体
python3 agentx_runner.py --concurrency 80       # 覆盖并发会话数
```

config `agentx.datasets` 行格式：`"tag, 公共语料 | local:<目录>, concurrency [, tokenizer]"`。
公共语料：`full`（1M ctx，135k 请求）/ `256k`（推荐）。本地裁剪语料用
`tools/curate_weka_traces.py` 生成目标画像（会话数/主轮数/平均输入/命中率）：
`local:datasets/weka8` 变体会自动固定 mvp 场景/无预热/封顶重放等实战参数。
中途终止用 Ctrl-C（SIGINT 优雅取消，指标仍可解析）。

## 5. BFCL 线（bfcl_runner.py）

Berkeley Function-Calling Leaderboard v4，22 子集 6 大类，测函数调用精度（AST 匹配/
多轮状态机/幻觉拒绝）。评测跑在独立 venv（setup.sh 自动建 `kit .cache/bfcl-venv`），
容器环境经 docker exec 派发（`bfcl.container` 配置）。

```bash
bash run.sh --bfcl                                          # 后台跑启用子集
bash run.sh --bfcl -f --only simple_python,irrelevance --limit 10   # 冒烟（20 请求）
bash run.sh --bfcl -f --resume                              # 断点续跑
python3 bfcl_runner.py --list                               # 列 22 子集
python3 bfcl_runner.py --report                             # 重打 scores.md
```

config `bfcl` 段：`enabled_subsets`（默认 17 离线子集）、`enable_web_search`（要
SERPAPI key）、`enable_memory`（要联网拉 HF 嵌入模型）、`is_fc_model`（端点无原生
函数调用时改 false）。Overall = 40%Agentic+30%MultiTurn+10%Live+10%NonLive+10%Hallucination，
只跑部分子集时缺项按 0 计权（部分运行与全量不可比）。

## 6. SWE-bench_Pro 线（swe_runner.py）

智能体代码评测：模型对 642 个真实仓库 issue 生成补丁，每实例独立 amd64 沙箱镜像跑
金标测试，产 resolved 率。**评测本体不在本仓库**（live 分批驱动在 `swe.work_dir`
工作区），runner 只提供只读监控 + 带双驱动护栏的补跑：

```bash
bash run.sh --swe status          # 状态：当前批/进度/ETA/进程/磁盘/崩溃标记（--json 出 JSON）
bash run.sh --swe aggregate       # 已评分聚合：repo × resolved/total/acc
bash run.sh --swe rerun-list      # 补跑队列
bash run.sh --swe env-check       # 环境自检 7 项
bash run.sh --swe start-rerun     # 补跑 dry-run（--yes 真启动，有护栏防双驱动）
```

## 7. Web 控制台（webapp.py）

```bash
python3 webapp.py --port 8300     # 浏览器 http://<压测机IP>:8300
```

八页签：配置项（服务 URL/模型/tokenizer/连接测试）/ 测试用例（增删启停+摸高参数）/
测试工程（进度条+最优结果+曲线+CSV+打包下载+启停）/ 功能测试 / 精度测试 / AgentX /
BFCL / SWE-bench_Pro 监控。启停按钮真杀进程树（killpg）。

> 与 skill 的关系：Web 看不到 skill 生成的 `runs/*.yaml` 组级配置——**skill 发起的
> 摸高任务一律 CLI 驱动，不要在 Web 里启停**（双驱动会互相覆盖）；Web 适合人工查看
> 曲线/导出 CSV（只读）。

## 8. 目录结构与 tools/ 工具脚本

```
evalscope-sla-kit/
├── setup.sh / run.sh / config.yaml     # 一键安装 / 统一入口 / 全部配置
├── runner.py            # 摸高   ├── accuracy_runner.py  # 精度
├── agentx_runner.py     # AgentX ├── bfcl_runner.py      # BFCL
├── swe_runner.py        # SWE    ├── scripts/run_api_e2e.py  # 功能
├── webapp.py + web/     # Web 控制台
├── report.py            # 摸高汇总（并发-指标表，--npu 折算单卡吞吐）
├── tools/               # gen_dataset_only / gen_random_dataset / jsonl_to_prompts /
│                        # curate_weka_traces / passk_evalscope / 守护脚本 / SWE 补丁等
├── datasets/            # 生成的数据集（按文件名复用）
├── results/             # 六条线的全部输出
└── logs/                # 运行日志
```

常用 tools：`gen_random_dataset.py`（随机定长数据集，本 skill 摸高线用）、
`gen_dataset_only.py`（gsm8k 定长）、`curate_weka_traces.py`（AgentX 本地语料裁剪）、
`passk_evalscope.py`（pass@k 报告期必需的 wrapper）、`f05_claude_code.sh`
（真实 Claude Code 会话自动化）。

## 9. 快速排障（六线通用，摘自 kit README「已知坑」）

1. tokenizer_path 必须压测机本地存在，否则 modelscope 远程下载 404
2. `Dataset is empty` = 数据集条数不足（摸高线 skill 已自动预算）
3. `Failed at lower bound (1)` 且 Success=0：先 curl 单发一条确认服务/模型名
4. http_proxy 劫持内网请求：curl 一律 `--noproxy '*'`
5. thinking 模型必须 `chat_template_kwargs.thinking=false`；`ignore_eos:true` 固定输出长度
6. 精度/摸高长任务必须后台 + 定期 tail；退出码 0 ≠ 有分数（假通过按失败处理）
7. 停任务要杀进程树（killpg/pkill -f），proc.kill() 不够
8. MaaS 网关 60s 首字节超时：非流式长回答必踩，功能线已全非流式兜底
