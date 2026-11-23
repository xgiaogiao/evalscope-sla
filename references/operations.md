# 运维操作与排障

以下命令均在压测机上执行（本机通过 SSH；`<kit>` = env.json 的 kit_dir）。

## 查进度

```bash
pgrep -af 'runner.py|evalscope'                  # 有输出=还在跑; 顺带看 PID
tail -n 40 <kit>/logs/skill_*.log                # 最新日志尾部
grep -E '^>>> 进度|PARTIAL|OK|FAILED' <kit>/logs/skill_*.log | tail -20   # 场景推进
ls -t <kit>/results/<场景ID>/ | head -3          # 某场景已有几轮结果
ls <kit>/datasets/random/                        # 数据集生成情况(gen 阶段)
```

日志里的关键行：`[场景 <sid>]` 开始、`>>> 进度 i/N`、`[<sid>] OK 耗时 X 分钟`、
`摸高结论: 最大达标并发 = N`（evalscope 输出）、`[预算看门狗]`/`[健康探活]`。

## 停止（杀进程树）

```bash
pkill -9 -f "runner.py --config runs/<本组配置>.yaml"   # 只杀本组 runner
pkill -9 -f evalscope                                    # 杀残留 evalscope worker
```

注意：`pkill -f evalscope` 会杀掉该机上**所有** evalscope 进程（含其他测试线），多人共用
压测机时先 `pgrep -af evalscope` 确认。停止后已完成的探测档仍在，可续跑/重跑。

## 续跑 / 重跑

```bash
# 重跑单场景(新时间戳目录, 旧结果保留, 汇总取最新):
cd <kit> && nohup python3 runner.py --config runs/<组>.yaml --only <场景ID> \
  > logs/rerun_<sid>.log 2>&1 &
# 数据集参数(seed/prefix/dp)变了要强制重新生成:
#   删 datasets/ 下对应文件, 或组配置里加 dataset.force_regenerate: true
```

## 汇总

```bash
cd <kit> && python3 skill_ext/collect_results.py --config runs/<组>.yaml [--npu 8]
# kit 自带全局汇总(SLA 判据读基座 config.yaml, 组配置里的自定义 SLA 不生效, 仅作交叉核对):
cd <kit> && python3 report.py [--npu 8]
```

## 排障表

| 症状 | 原因 | 处理 |
|---|---|---|
| runner 启动即 `FileNotFoundError: service.tokenizer_path 未配置/不存在` | tokenizer 没配或路径在压测机上不存在 | gen 时传 `--tokenizer-path`（压测机本地真实目录，含 tokenizer_config.json）；不能用推理集群路径 |
| gen `[WARN] 输入 … 超过服务上下文上限` | 服务 max_context_length < 输入+输出 | 256k/512k/1m 档需要服务真正支持长上下文；不支持就 `--lengths` 去掉该档，否则全部请求 400 |
| `Dataset is empty!` | 数据集条数 < 摸高全程消耗 | 用 gen 自动预算的 dataset_num（已按上限算好）；若手动调小过上限后重跑，重新 gen 配置 |
| `Failed at lower bound (1)`，Success=0 | 服务 400/不通/tokenizer 不符 | `curl --noproxy '*' -v` 单发一条；查 Success/Total；多为 url/model/tokenizer 配错 |
| `Failed at lower bound (1)`，Success>0 | 最低并发 1 就违反 SLA | 真实结论（服务太慢），确认 SLA 数值是否合理；90% 组检查前缀预热日志是否成功 |
| 90% 组命中不达标（TTFT 接近 0% 组） | 前缀没灌进 cache | 看 `results/<sid>/prefix_warmup/` 各 conc 档是否 FAILED；服务端 prefix caching 是否开启 |
| 压测期间日志刷 `服务无响应(连续 N 次)` | 服务闪断/网关超时 | 只告警不杀；连续≥3 次去看服务端；恢复后计数自动清零 |
| 数据集生成极慢/磁盘爆 | 1m 数据集体量 GB 级 | 分长度分批；`--num-runs 1` 可把条数预算减半（精度换时间） |
| 请求被代理劫持（连接超时但 curl 直连好） | 压测机 http_proxy 环境变量 | kit 探活已绕代理；确认 env 无 `http_proxy` 或加入 no_proxy |
| thinking 模型 TPOT 异常高 | 思考 token 计入 | 基座 config benchmark.extra_args 已带 `chat_template_kwargs.thinking=false` + `ignore_eos: true`，勿删 |

## partial 结论语义

给了 `--time-budget-min` 且到限被切断的场景：`partial_summary.json` 里 `selected` 是
**真实上限的下界**——真实上限落在 `selected` 与首个违反档之间。汇总转述时必须带此语义，
不能当作精确结论。

## Web 控制台（可选人工核对）

```bash
cd <kit> && python3 webapp.py --port 8300    # http://<压测机IP>:8300
```

「测试工程」页可看每场景最优结果/完整曲线/CSV 导出；本 skill 的 runs/*.yaml 配置对
webapp 不可见（webapp 只读基座 config.yaml + web_state.json），不要在 web 里启停 skill
发起的任务，避免双驱动。
