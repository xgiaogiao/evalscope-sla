# evalscope-sla skill 开发文档

版本 v1.0（2026-11-23）｜前提：先读 [DESIGN.md](DESIGN.md)（架构与决策）。

本文面向需要修改/维护本 skill 的开发者，内容分四部分：
**A. 被封装工具（evalscope-sla-kit）的机制详解**——全部源自 kit 的 README.md 与
runner.py/config.yaml 源码，是本 skill 每个设计选择的依据；
**B. skill 两个脚本的内部实现**；**C. 扩展指南**；**D. 测试清单与已知差异**。

---

## A. evalscope-sla-kit 机制详解（摸高线）

kit 有六条测试线（摸高/精度/功能/AgentX/BFCL/SWE），**六条全部保留在 skill 的能力
范围内**：摸高线由本 skill 深度封装（本文 A 节即其机制依据），其余五线经自然语言
路由到 kit 原生入口（命令手册见 `references/kit-overview.md`，底层机制可对照 kit
README 各线章节——精度线的 pass@k 断点续跑、AgentX 的 local: 语料固定参数、BFCL 的
独立 venv、SWE 的只读监控+双驱动护栏，都是 kit 已封装好的能力，skill 不重复造轮子）。
以下按数据流顺序讲清摸高线的每个环节。

### A.1 入口与分发：run.sh

```
bash run.sh                    # 后台 nohup 跑所有启用场景
bash run.sh -f                 # 前台（tee 日志）
bash run.sh --dry-run/--list/--gen-datasets   # 这三个开关强制前台
bash run.sh --only <场景ID>     # 单场景重跑
bash run.sh --report [--npu N] # 汇总
```

关键行为（skill 必须绕开的坑）：run.sh 扫描全部参数，只有
`-f/--foreground/--dry-run/--gen-datasets/--list` 会让它前台执行；**其他参数（含
`--config`）一律走 `nohup runner.py … &` 后立即返回**。因此
`bash run.sh --config A; bash run.sh --config B` 会让 A、B **并行**——多组串行必须
直连 runner.py：

```bash
nohup bash -c 'python3 runner.py --config A.yaml; python3 runner.py --config B.yaml' > log 2>&1 &
```

skill 的所有启动命令都直连 runner.py，run.sh 仅作人工兜底入口。

### A.2 配置装载：config.yaml + base_config 深合并

`runner.load_config` 用 `yaml.safe_load` 读配置后，若文件里有 `base_config: <相对路径>`
（相对**该文件自身目录**解析），会把基座配置读进来做 `_deep_merge`：

- dict 递归合并；**list / 标量整体替换**（kit 有意为之——scenarios 做"部分叠加"无合理语义）
- 必需段 `service/request/benchmark/dataset/scenarios` 缺一即抛错（合并后检查）

本 skill 的组级配置就利用这个机制：override 文件放 `runs/` 下，`base_config: ../config.yaml`，
只写 `scenarios`（整表替换）、`benchmark.sla_upper_bound`（组级摸高上限）和可选的
`service` 覆盖（url/model/tokenizer_path），其余全部继承基座。

### A.3 场景行：8 个逗号分隔字段

```yaml
scenarios:
  - "dataset, input_len, output_len, cache_hit_rate, prefix_num, ttft_sla_ms, tpot_sla_ms [, dataset_num]"
```

| 字段 | 约定 | skill 用法 |
|---|---|---|
| dataset | `random`（随机 token）/ `gsm8k`（数学题文本） | 三组默认 random |
| input_len/output_len | k 简写 `1k=1024`；**无 m 简写**，1M 档写 `1000k=1024000` | gen 把用户说的 1m 归一为 1000k |
| cache_hit_rate | 0 / 0.3 / 0.9（也认 `90%`） | 组 A=0，组 B/C=0.9 |
| prefix_num | ≥1；>1 时场景 ID 与数据集文件名都带 `pN{n}` | 组 C=8/16/32 |
| ttft/tpot_sla_ms | 正整数，摸高判据 | 组 A=60000/50，组 B/C=10000/50 |
| dataset_num | 数据集条数；不填用 dataset.gsm8k_number 全局默认 | gen 按预算公式算好填入 |

注释行=跳过。场景 ID 生成规则（`scenario_id`）：

```
random_64k_1k_hit0                # hit=0
random_64k_1k_hit90pct            # hit=0.9（4位有效数字去尾零，防 0.295/0.3 碰撞）
random_64k_1k_hit90pct_pN8        # prefix_num>1 追加
random_1000k_1k_hit90pct_pN32     # 1024000 → "1000k"
```

gen 与 collect 各自复刻了这套规则（最小实现），保证 ID 与 runner 完全一致。

### A.4 数据集：生成就绪 + 文件名复用 + 条数预检

`ensure_gsm8k_dataset`（random 场景同样走它）：

1. 目标文件名由 `(数据集类型, input_len, hit_rate, dataset_num, prefix_num, tokenizer名)`
   决定，**存在即复用**，不重生成：
   - `datasets/random/RANDOM-in{len}-num{n}-{tok}[-pN{n}][-repeatRate{rr}].jsonl`
   - 90% 命中另生前缀文件 `prefix-RANDOM-in{int(len*hit)}-num{dp*prefix_num}-{tok}.jsonl`
2. random 语料由 `tools/gen_random_dataset.py` 生成：从 tokenizer 词表随机抽 token
   （排除 special / byte-fallback），decode→re-encode 校正到**精确定长**；
   `hit_rate>0` 时生成 `prefix_num` 条随机前缀，主数据集每条 = `prefix[i % prefix_num]`
   + 随机后缀——这就是 8/16/32 前缀池的构造方式。
3. jsonl → `jsonl_to_prompts.py` 转纯文本（evalscope custom 插件只吃纯文本）。

改了 seed/prefix_num/dp 想重新生成：删对应文件或 `dataset.force_regenerate: true`。

**条数预检** `check_dataset_sufficient`（摸高前必过，不足直接抛错）：

```
档位序列: 1,2,4,…(倍增至 upper，尾档=upper)     # ladder_levels(1, upper)
need = Σ (档位并发 × number_multiplier × max(1,sla_num_runs) + warmup_num)
```

注意两个键名差异（kit 的历史遗留）：预检读 `sla_number_multiplier`（缺省 2），
而实际请求量由 `number_multiplier`（config 默认 2）决定。两者默认一致；gen 的预算
公式**与两者取大**（连同基座值），保证预检必过且不低估实际消耗。

### A.5 命令构建与摸高执行

`build_evalscope_cmd` 为每个场景构建（dry-run 可直接看）：

```
evalscope perf --model <model> --tokenizer-path <tok> --url <url> --api openai \
  --apply-chat-template --max-tokens <output_len> \
  --sla-auto-tune --sla-variable parallel \
  --sla-params '[{"avg_ttft":"<=60000","avg_tpot":"<=50"}]' \
  --sla-lower-bound 1 --sla-upper-bound <5|24> --sla-num-runs 2 \
  --sla-number-multiplier 2 --warmup-num 10 \
  --outputs-dir results/<场景ID>/ \
  --dataset custom --dataset-path <prompts.txt> --max-prompt-length <input+2000> \
  [--headers …] [--extra-args '{"ignore_eos":true,"chat_template_kwargs":{"thinking":false}}']
```

- 每档请求数 = 并发 × `--sla-number-multiplier`；每档跑 `--sla-num-runs` 轮
- `ignore_eos:true` 固定输出长度使 TPOT 可比；thinking 模型必须关思考
- 执行带两重看门狗（`benchmark` 段）：`time_budget_min` 到限杀进程并写
  `partial_summary.json`（逐档判定，selected=真实上限**下界**）；`health_check_interval_s`
  定期探活 `/v1/models`，连续失败只告警不杀。

### A.6 前缀预热（90% 组的"片上/池化命中"前提）

场景 `hit_rate>0` 时，摸高前 runner 自动执行 `run_prefix_warmup`：用前缀数据集按
`[1,2,4,8,16,32,64]` 并发阶梯压测（每档请求数=并发×5，输出 16 token），把前缀灌进
服务端 KV cache。预热失败不阻断摸高只告警；`warmup_budget_min` 可给预热限时。
**多前缀（pN=8/16/32）时前缀池更大，单前缀被逐出风险更高——这正是池化场景要测的。**

### A.7 结果结构

```
results/<场景ID>/<时间戳>/<model>/sla_summary.json
    # {"parallel_1": {"metrics": {...}, "percentiles": {...}}, "parallel_2": …}
    # metrics 键: "Avg TTFT (ms)"/"Avg TPOT (ms)"/"Success Requests"/
    #            "Failed Requests"/"Total Requests"/"Output Throughput (tok/s)" …
results/<场景ID>/<时间戳>/<model>/sla_tuning/sla_parallel_N_run_M/benchmark_summary.json
results/<场景ID>/partial_summary.json     # 预算切断: {status,budget_min,selected,probes}
results/<场景ID>/prefix_warmup/conc*/     # 90% 组预热日志
```

`report.py`（kit 自带）的 SLA 判定：`Failed==0 且 TTFT/TPOT 双达标 → PASS`，最大达标并发
= 全 PASS 档最大并发。**其判据只读基座 config.yaml**，不认本 skill 的组级覆盖——所以
汇总以 collect_results.py 为准，report.py 仅人工交叉核对。

### A.8 kit README 里的高频坑（skill 排障表的出处）

tokenizer 必须压测机本地存在（否则 modelscope 远程下载 404）；`Dataset is empty`=
条数不足；`Failed at lower bound(1)` 且 Success=0 多为服务不通/模型名错；MaaS 网关
60s 首字节超时（性能线流式不受影响）；http_proxy 劫持内网请求要 `--noproxy '*'`；
thinking 模型必须 `chat_template_kwargs.thinking=false`；数据集按文件名复用导致改参不生效。

---

## B. skill 脚本内部实现

两个脚本都是 **Python 3 标准库 + 可选 pyyaml**，部署在 `<kit>/skill_ext/`，
输出末尾一律有 `JSON_RESULT: <json>` 行供 Claude 结构化解析（这是 skill 与脚本的
唯一机器契约）。

### B.1 gen_group_config.py

```
main()
 ├─ argparse（--group/--lengths/--upper/--prefixes/--dataset/--ttft-ms/--tpot-ms/
 │           --dataset-num/--num-runs/--num-multiplier/--warmup/--time-budget-min/
 │           --url/--model/--tokenizer-path/--base-config/--out-dir/--tag）
 ├─ 基座只读一次（pyyaml 可用则读，否则注入告警继续）
 └─ 对每个组调 gen_one()
     ├─ upper = --upper 或组默认（A/B=5, C=24）
     ├─ eff_mult/eff_runs/eff_warm = max(命令行, 基座 benchmark 值, kit 缺省)
     ├─ dnum = --dataset-num 或 dataset_need(upper, eff_*)   # A.4 同款公式
     ├─ build_scenarios(): 长度解析(1m→1024000) → 每长度×每前缀数生成场景行+场景ID
     ├─ 预检: tokenizer 空/不存在、长度超 max_context_length → warns
     ├─ 手写 YAML（不依赖 pyyaml 也能生成）:
     │    # 注释头(含启动命令) / base_config: ../config.yaml
     │    service:（仅当有覆盖）/ benchmark: sla_upper_bound[, time_budget_min]
     │    scenarios: ["…8字段…", …]
     └─ 打印 [gen]/[WARN]/下一步命令 + JSON_RESULT
```

核心不变量：
- **场景 ID 与 runner 一字不差**（`_hit0/_hit90pct/_pN{n}`、`1000k`）——collect 靠它定位
  results 目录，错了就汇总不到
- **dnum ≥ runner 预检需求**——档位序列同构（`ladder_levels` 复刻 kit），倍数/轮数与
  基座取大，预检必过
- **不碰基座**——所有覆盖只写进 runs/*.yaml

### B.2 collect_results.py

```
main()
 ├─ --config（可多次）→ load_scenarios_from_config（yaml 读 override 的 scenarios,
 │                      逐行解析出 场景ID+SLA）；或 --scenario-ids + --sla 直给
 └─ 对每个 (sid, ttft_sla, tpot_sla):
     collect_scenario()
      ├─ find_latest_summary(): results/<sid>/ 下 ^\d{8}_\d{6}$ 目录按 mtime 取最新,
      │   再找 <ts>/sla_summary.json 或 <ts>/<model>/sla_summary.json
      ├─ 有 summary → parallel_N → metrics 行（含 verdict: Failed==0 且双达标）
      ├─ 无 summary → 读 partial_summary.json 的 probes（状态标 partial 下界）
      └─ selected = max(PASS 档)；best = 该档指标
     render(): Markdown 表（并发/成功/TTFT avg/TTFT p99/TPOT/输出吞吐[/单卡吞吐]/判定）
              + 结论行 + 组级汇总表
     末尾 JSON_RESULT: [{sid,status,selected,ttft_sla_ms,tpot_sla_ms},…]
```

判定口径与 kit report.py / runner.partial_verdict 完全同构；TTFT p99 为 best-effort
（percentiles 键名随 evalscope 版本浮动，匹配 "*ttft*99*"）。

---

## C. 扩展指南

### C.1 新增场景组（例：30% 命中组）

1. `gen_group_config.py`：`GROUPS` 加
   `"hit30": {"hit": "0.3", "prefixes": [1], "upper": 30, "ttft": 30000, "tpot": 50, "desc": "…"}`
   并入 `ALL_GROUPS`；注意 scenario_id 对 0.3 的渲染是 `hit30pct`
2. `references/scenario-matrix.md`：补该组全表（场景 ID/行/dnum 推导）
3. `SKILL.md` 第 1 步解析表加触发词行，第 2 步 groups 说明
4. 冒烟：`gen --group hit30 --dry` 看 YAML → 压测机 `runner.py --config … --dry-run`

### C.2 新增可配参数

argparse 加参 → `gen_one` 写进 YAML（注意 kit 端对应键名，查 A 节）→ SKILL.md 解析表
补一行 → DEVELOPMENT.md B.1 参数清单更新。涉及汇总的再加 collect 的列。

### C.2b 给其他五条线加深封装（可选演进）

当前精度/功能/AgentX/BFCL/SWE 五线是"命令直达 + 参数手册"（kit-overview.md）。
若某线需要与摸高线同级的深度封装（如组级配置/专用汇总），套路复用摸高线的三件套：
gen_group_config.py 加一个生成器（读该线 config 段写 override）→ collect_results.py
加该线结果解析（如 accuracy 的 `reports/<model>/<ds>.json` metrics、bfcl 的
`bfcl_v4.json`）→ SKILL.md 路由表升级。改前先读 kit README 对应线章节与 runner 源码，
本文件 A 节的方法论（场景行/结果结构/判定口径先摸清再封装）完全适用。

### C.3 换 kit 版本时的回归点

kit 升级后重点回归：场景行字段数/顺序、`scenario_id` 渲染、数据集文件名规则、
sla_summary.json 的 metrics 键名、`base_config` 合并语义。前四个任一变化都会让
gen/collect 与 runner 静默失配（配置能跑但汇总不到、或条数预算失准）。

---

## D. 测试清单与已知差异

### D.1 部署后冒烟（首次必做，约 10 分钟）

```bash
# 1. 语法
python3 -m py_compile skill_ext/gen_group_config.py skill_ext/collect_results.py
# 2. 生成三组配置（不跑压测），检查 JSON_RESULT 与 YAML 内容
python3 skill_ext/gen_group_config.py --group all --tokenizer-path <tok>
python3 runner.py --config runs/random-nocache_*.yaml --dry-run     # evalscope 命令正确性
# 3. 汇总脚本对空/运行中目录的容错（应输出"无结果目录"而非崩溃）
python3 skill_ext/collect_results.py --config runs/random-nocache_*.yaml
# 4. 小场景端到端: 单长度小输入（如 --lengths 64k 的组 A）跑通全链路后再上长输入
```

### D.2 已知差异 / 遗留

| 项 | 说明 |
|---|---|
| 未实跑 | 本机无 Python，脚本仅人工逐行核查（已修 2 处迭代字符串 bug）；部署后按 D.1 验证 |
| report.py 判据来源 | 只读基座 config.yaml，组级 SLA 覆盖不生效——汇总一律用 collect_results.py |
| sla_number_multiplier 键名差 | kit 预检与实际请求量用不同键名（默认都是 2）；gen 已对两者与基座取大，勿单独调小 --num-multiplier |
| web 双驱动 | webapp 不知道 runs/*.yaml；skill 任务禁止从 web 启停 |
| TTFT p99 | best-effort 解析，键名不匹配时显示 "-"（avg 指标不受影响） |
