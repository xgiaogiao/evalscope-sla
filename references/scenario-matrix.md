# 三大场景组完整矩阵

## 术语 ↔ kit 实现 ↔ 语义

| 用户术语 | kit 机制 | 测的是什么 |
|---|---|---|
| 随机数据集（prefix cache 0%） | `random` 数据集，随机 token 定长样本，hit=0 | 冷 prefill 全量算力：每请求输入全新，KV cache 无命中 |
| 单前缀头 90%（片上缓存） | hit=0.9 + prefix_num=1：全部样本共享同一条 0.9×L 前缀，摸高前自动前缀预热（1→64 并发阶梯灌 KV） | 单条大前缀常驻片上 KV cache 时的 prefill 加速与并发承载力 |
| 多前缀头 90%（池化缓存） | hit=0.9 + prefix_num=8/16/32：样本按 `i % prefix_num` 轮流挂 8/16/32 条前缀池 | 前缀池化（多条共享前缀分散在池中）时的命中行为与承载力；pN 越大单前缀被逐出的概率越高 |
| 并发由低摸高至 TTFT/TPOT 突增 | evalscope `--sla-auto-tune`：并发档 1,2,4,…,上限 倍增爬升+细化，每档 2 轮取均值 | 每档判据 = avg TTFT≤X 且 avg TPOT≤Y 且 0 失败；"突增"= 超判据，搜索停止并回退 |
| 1m 输入 | kit 写法 `1000k` = 1024000 token（非 1048576） | 与 kit config 内置 1000k 行同口径 |

## 长度换算（k=1024）

| 写法 | token | 写法 | token |
|---|---|---|---|
| 64k | 65536 | 256k | 262144 |
| 75k | 76800 | 512k | 524288 |
| 128k | 131072 | 1000k(=1m) | 1024000 |

输出统一 1k=1024。注意服务端 `max_context_length` 必须 ≥ 输入+输出（glm5.3 示例 204800
只够到 128k+1k 档；256k/512k/1m 档需要服务真正支持，gen 脚本会 `[WARN]` 提示）。

## 组 A：random-nocache（随机数据集·无缓存命中）

上限 5｜SLA TTFT≤60000ms/TPOT≤50ms｜数据集条数 88（档位 1,2,4,5 × 倍数2 × 轮2 + warmup）

| 场景 ID | 场景行 |
|---|---|
| random_64k_1k_hit0 | random, 64k, 1k, 0, 1, 60000, 50, 88 |
| random_75k_1k_hit0 | random, 75k, 1k, 0, 1, 60000, 50, 88 |
| random_128k_1k_hit0 | random, 128k, 1k, 0, 1, 60000, 50, 88 |
| random_256k_1k_hit0 | random, 256k, 1k, 0, 1, 60000, 50, 88 |
| random_512k_1k_hit0 | random, 512k, 1k, 0, 1, 60000, 50, 88 |
| random_1000k_1k_hit0 | random, 1000k, 1k, 0, 1, 60000, 50, 88 |

## 组 B：single-prefix（单前缀头·片上缓存 90%）

上限 5｜SLA TTFT≤10000ms/TPOT≤50ms｜数据集条数 88（同上，另含 1 条前缀数据集）

| 场景 ID | 场景行 |
|---|---|
| random_64k_1k_hit90pct | random, 64k, 1k, 0.9, 1, 10000, 50, 88 |
| random_75k_1k_hit90pct | random, 75k, 1k, 0.9, 1, 10000, 50, 88 |
| random_128k_1k_hit90pct | random, 128k, 1k, 0.9, 1, 10000, 50, 88 |
| random_256k_1k_hit90pct | random, 256k, 1k, 0.9, 1, 10000, 50, 88 |
| random_512k_1k_hit90pct | random, 512k, 1k, 0.9, 1, 10000, 50, 88 |
| random_1000k_1k_hit90pct | random, 1000k, 1k, 0.9, 1, 10000, 50, 88 |

## 组 C：multi-prefix（多前缀头·池化缓存 90%）

上限 24｜SLA TTFT≤10000ms/TPOT≤50ms｜数据集条数 280（档位 1,2,4,8,16,24 × 倍数2 × 轮2 + warmup）

18 个场景 = 6 长度 × pN{8,16,32}（ID 带 `_pN{n}` 后缀，前缀池不同数据集不同文件）：

| 长度 | 场景 ID（三个前缀数各一个） | 场景行示例（pN8） |
|---|---|---|
| 64k | random_64k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 64k, 1k, 0.9, 8, 10000, 50, 280 |
| 75k | random_75k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 75k, 1k, 0.9, 8, 10000, 50, 280 |
| 128k | random_128k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 128k, 1k, 0.9, 8, 10000, 50, 280 |
| 256k | random_256k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 256k, 1k, 0.9, 8, 10000, 50, 280 |
| 512k | random_512k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 512k, 1k, 0.9, 8, 10000, 50, 280 |
| 1000k | random_1000k_1k_hit90pct_pN8 / _pN16 / _pN32 | random, 1000k, 1k, 0.9, 8, 10000, 50, 280 |

## 时长与体量预估（向用户设预期用）

| 环节 | 量级 | 说明 |
|---|---|---|
| 数据集生成 64k~128k | 每档分钟级 | tokenizer 解码+重编码到精确定长 |
| 数据集生成 256k~1m | 每档 10 分钟~数小时 | 1m×280 条 ≈ 1GB+ 文本；组 C 的 1m 要为 pN8/16/32 各生成一份 |
| 前缀预热（90% 组每场景） | 分钟~几十分钟 | 1→64 并发阶梯灌 KV；pool 异常时可被 warmup_budget_min 截断 |
| 单场景摸高 64k | ~10-30 分钟 | 4 个并发档 × 2 轮 |
| 单场景摸高 1m | 数小时 | 每档 number=并发×2 个 1m prefill |
| 整组 C（18 场景全长度） | 天级 | 务必分批 + time_budget_min |

实务建议：先 `--lengths 64k,75k` 快速验证链路与 SLA 合理性 → 再跑 128k/256k → 512k/1m
单独分批跑；组 C 可按前缀数分三批（`--prefixes 8` 等）。

## 结果目录结构

```
results/<场景ID>/<时间戳>/<model>/sla_summary.json      # 摸高完整: parallel_N -> metrics/percentiles
results/<场景ID>/<时间戳>/<model>/sla_tuning/sla_parallel_N_run_M/benchmark_summary.json
results/<场景ID>/partial_summary.json                   # 时间预算切断的逐档判定 + selected(下界)
results/<场景ID>/prefix_warmup/conc*/                   # 90% 组的前缀预热日志
datasets/random/RANDOM-in*.jsonl + .prompts.txt          # 数据集(按文件名复用)
runs/<组>_<时间戳>.yaml                                  # 本 skill 生成的组级配置
logs/skill_*.log / gen_*.log                             # 摸高/数据集生成日志
```
