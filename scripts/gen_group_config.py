#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成组级 override 配置（三大场景组之一），供 runner.py --config 使用。

部署位置: <kit>/skill_ext/gen_group_config.py（与 collect_results.py 一起）
用法示例:
    python3 skill_ext/gen_group_config.py --group random-nocache
    python3 skill_ext/gen_group_config.py --group single-prefix --lengths 128k,256k
    python3 skill_ext/gen_group_config.py --group multi-prefix --prefixes 8,16 --upper 24
    python3 skill_ext/gen_group_config.py --group all            # 顺序生成 A/B/C 三份配置

产出: <out-dir>/<group>_<时间戳>.yaml
    base_config 指向基座 config.yaml（service/request/benchmark/dataset 全继承，
    仅覆盖 scenarios 清单 + sla_upper_bound + 显式给出的 service 覆盖）。

三大场景组（对应需求）:
    random-nocache  随机数据集测试   prefix cache 0%   摸高上限 5   SLA TTFT<=60s/TPOT<=50ms
    single-prefix   单前缀头测试     片上缓存 90%      摸高上限 5   SLA TTFT<=10s/TPOT<=50ms
    multi-prefix    多前缀头测试     池化缓存 90%      摸高上限 24  SLA TTFT<=10s/TPOT<=50ms

末尾输出一行 JSON_RESULT: {...} 供上层（Claude/skill）直接解析。
"""
import argparse
import datetime
import json
import os
import re
import sys

# ---------------------------------------------------------------- 长度解析
# kit 的 parse_len 只认 k 简写（1k=1024, 1000k=1024000），不认 1m。
# 本脚本把 "1m" 归一为 kit 约定的 1000k=1024000（注意不是 1048576）。
DEFAULT_LENGTHS = ["64k", "75k", "128k", "256k", "512k", "1m"]


def parse_len_tokens(s: str) -> int:
    """'64k'->65536  '1m'->1024000  '75k'->76800  '1024000'->1024000"""
    s = str(s).strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)(k|kb|m|mb)?$", s)
    if not m:
        raise ValueError(f"无法解析长度: {s!r}")
    val = float(m.group(1))
    if m.group(2) and m.group(2).startswith("k"):
        val *= 1024
    elif m.group(2) and m.group(2).startswith("m"):
        val *= 1000 * 1024   # 1m = 1000k = 1024000（与 kit config 内置 1000k 行一致）
    return int(val)


def len_shorthand(tokens: int) -> str:
    """65536->'64k'  1024000->'1000k'  76800->'75k'"""
    return f"{tokens // 1024}k" if tokens % 1024 == 0 else str(tokens)


# ---------------------------------------------------------------- 数据集条数预算
# 与 runner.sla_dataset_requirement 同一套估算公式（倍增档位序列 ×
# number_multiplier × num_runs + 每档 warmup）。gen 用同一公式算出的
# dataset_num 写进场景行第 8 字段，保证 runner 的 check_dataset_sufficient 必过。
def ladder_levels(lo: int, hi: int) -> list:
    levels = []
    v = max(1, lo)
    while v < hi:
        levels.append(v)
        v = v * 2 if v * 2 <= hi else hi
    levels.append(hi)
    return levels


def dataset_need(upper: int, mult: int, runs: int, warmup: int, lower: int = 1) -> int:
    return sum(l * mult * max(1, runs) + warmup for l in ladder_levels(lower, upper))


# ---------------------------------------------------------------- 场景组定义
GROUPS = {
    "random-nocache": {
        "hit": "0", "prefixes": None, "upper": 5,
        "ttft": 60000, "tpot": 50,
        "desc": "随机数据集测试·无缓存命中(prefix cache 0%)",
    },
    "single-prefix": {
        "hit": "0.9", "prefixes": [1], "upper": 5,
        "ttft": 10000, "tpot": 50,
        "desc": "单前缀头测试·片上缓存命中90%",
    },
    "multi-prefix": {
        "hit": "0.9", "prefixes": [8, 16, 32], "upper": 24,
        "ttft": 10000, "tpot": 50,
        "desc": "多前缀头测试·池化缓存命中90%(8/16/32前缀)",
    },
}
ALL_GROUPS = ["random-nocache", "single-prefix", "multi-prefix"]


def build_scenarios(group_key, args, dnum):
    """返回 (scenario 行列表, 场景ID 列表)。行格式:
    dataset, input_len, output_len, hit, prefix_num, ttft, tpot, dataset_num
    """
    g = GROUPS[group_key]
    lengths = sorted({parse_len_tokens(x) for x in args.lengths.split(",") if x.strip()})
    out_sh = len_shorthand(parse_len_tokens(args.output_len))
    prefixes = g["prefixes"]
    lines, sids = [], []
    for tok in lengths:
        in_sh = len_shorthand(tok)
        plist = prefixes if prefixes is not None else [1]
        for pnum in plist:
            lines.append(f"{args.dataset}, {in_sh}, {out_sh}, {g['hit']}, {pnum}, "
                         f"{args.ttft_ms or g['ttft']}, {args.tpot_ms or g['tpot']}, {dnum}")
            hit_tag = "0" if g["hit"] == "0" else "90pct"
            sid = f"{args.dataset}_{in_sh}_{out_sh}_hit{hit_tag}"
            if int(pnum) > 1:
                sid += f"_pN{pnum}"
            sids.append(sid)
    return lines, sids


def yaml_quote(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def gen_one(group_key, args, base_cfg=None, base_load_warn=None) -> dict:
    g = GROUPS[group_key]
    upper = args.upper if args.upper else g["upper"]
    # 数据集条数预算的生效参数: 基座 benchmark 值与命令行默认取大——
    # 保证 runner 的 check_dataset_sufficient 与 evalscope 实际消耗都被覆盖
    bb = (base_cfg or {}).get("benchmark") or {}
    eff_mult = max(args.num_multiplier, int(bb.get("number_multiplier") or 0),
                   int(bb.get("sla_number_multiplier") or 0), 2)
    eff_runs = max(args.num_runs, int(bb.get("sla_num_runs") or 0), 1)
    eff_warm = max(args.warmup, int(bb.get("warmup_num") or 0))
    dnum = args.dataset_num or dataset_need(upper, eff_mult, eff_runs, eff_warm)
    lines, sids = build_scenarios(group_key, args, dnum)

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    base_abs = os.path.abspath(args.base_config)
    base_rel = os.path.relpath(base_abs, out_dir).replace("\\", "/")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"_{args.tag}" if args.tag else ""
    cfg_path = os.path.join(out_dir, f"{group_key}{tag}_{ts}.yaml")

    warns = [base_load_warn] if base_load_warn else []
    # 基座预检（pyyaml 不可用时 main 已注入 base_load_warn，此处只做内容检查）
    if base_cfg is not None:
        svc = base_cfg.get("service") or {}
        tok = args.tokenizer_path or svc.get("tokenizer_path") or ""
        if not tok:
            warns.append("service.tokenizer_path 为空：runner 启动预检必失败。"
                         "请用 --tokenizer-path 给出压测机上存在的 tokenizer 目录")
        elif not os.path.isdir(tok):
            warns.append(f"tokenizer_path 目录在压测机上不存在: {tok}")
        mcl = (svc.get("max_context_length") or 0)
        if mcl:
            for tokn in sorted({parse_len_tokens(x) for x in args.lengths.split(",") if x.strip()}):
                if tokn + parse_len_tokens(args.output_len) > mcl:
                    warns.append(f"输入 {len_shorthand(tokn)} + 输出超过服务上下文上限 "
                                 f"max_context_length={mcl}，该长度会被服务端拒绝或截断")

    y = []
    y.append(f"# 自动生成: {g['desc']}")
    y.append(f"# 生成时间: {ts}  摸高上限: {upper}  数据集条数: {dnum}")
    y.append(f"# 启动: cd <kit> && nohup python3 runner.py --config "
             f"{os.path.relpath(cfg_path, os.path.dirname(base_abs)).replace(chr(92), '/')} > "
             f"logs/skill_{group_key}_{ts}.log 2>&1 &")
    y.append(f"base_config: {base_rel}")
    if args.url or args.model or args.tokenizer_path:
        y.append("service:")
        if args.url:
            y.append(f"  url: {yaml_quote(args.url)}")
        if args.model:
            y.append(f"  model: {yaml_quote(args.model)}")
        if args.tokenizer_path:
            y.append(f"  tokenizer_path: {yaml_quote(args.tokenizer_path)}")
    y.append("benchmark:")
    y.append(f"  sla_upper_bound: {upper}")
    if args.time_budget_min:
        y.append(f"  time_budget_min: {args.time_budget_min}")
    y.append("scenarios:")
    for ln in lines:
        y.append(f"  - {yaml_quote(ln)}")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(y) + "\n")

    need_detail = (f"档位序列 {ladder_levels(1, upper)} × "
                   f"请求数倍数 {eff_mult} × 轮数 {eff_runs} + 每档 warmup "
                   f"{eff_warm} => 每场景数据集 {dnum} 条")
    print(f"[gen] {g['desc']}")
    print(f"[gen] 配置: {cfg_path}")
    print(f"[gen] 场景 {len(sids)} 个: {', '.join(sids)}")
    print(f"[gen] 数据集条数推导: {need_detail}")
    for w in warns:
        print(f"[WARN] {w}")
    rel_cfg = os.path.relpath(cfg_path, os.path.dirname(base_abs)).replace("\\", "/")
    print(f"[gen] 下一步:")
    print(f"  预检:     python3 runner.py --config {rel_cfg} --dry-run")
    print(f"  预生成:   nohup python3 runner.py --config {rel_cfg} --gen-datasets > "
          f"logs/gen_{group_key}_{ts}.log 2>&1 &")
    print(f"  启动摸高: nohup python3 runner.py --config {rel_cfg} > "
          f"logs/skill_{group_key}_{ts}.log 2>&1 &")
    return {"group": group_key, "desc": g["desc"], "config": cfg_path,
            "config_rel": rel_cfg, "scenario_ids": sids, "upper": upper,
            "dataset_num": dnum, "ttft_ms": args.ttft_ms or g["ttft"],
            "tpot_ms": args.tpot_ms or g["tpot"], "log": f"logs/skill_{group_key}_{ts}.log",
            "warnings": warns}


def main():
    ap = argparse.ArgumentParser(description="生成组级摸高 override 配置")
    ap.add_argument("--group", required=True,
                    choices=ALL_GROUPS + ["all"], help="场景组（all=顺序生成三组）")
    ap.add_argument("--lengths", default=",".join(DEFAULT_LENGTHS),
                    help="输入长度逗号分隔（默认 64k,75k,128k,256k,512k,1m；1m=1000k=1024000）")
    ap.add_argument("--output-len", default="1k", help="输出长度（默认 1k）")
    ap.add_argument("--upper", type=int, default=0,
                    help="摸高并发上限（默认: 随机/单前缀=5, 多前缀=24）")
    ap.add_argument("--prefixes", default=None,
                    help="多前缀组的前缀数列表（默认 8,16,32）")
    ap.add_argument("--dataset", default="random", choices=["random", "gsm8k"],
                    help="数据集语料（默认 random=随机token；gsm8k=自然语言数学题）")
    ap.add_argument("--ttft-ms", type=int, default=0, help="TTFT SLA 上限 ms（默认: 0%组=60000, 90%组=10000）")
    ap.add_argument("--tpot-ms", type=int, default=0, help="TPOT SLA 上限 ms（默认 50）")
    ap.add_argument("--dataset-num", type=int, default=0,
                    help="手动指定数据集条数（默认按摸高档位自动预算）")
    ap.add_argument("--num-runs", type=int, default=2, help="每档并发轮数（默认 2，与 kit 一致）")
    ap.add_argument("--num-multiplier", type=int, default=2,
                    help="每档请求数=并发×此值（默认 2，与 kit 一致）")
    ap.add_argument("--warmup", type=int, default=10, help="每档 warmup 请求数（默认 10）")
    ap.add_argument("--time-budget-min", type=int, default=0,
                    help="单场景时间预算分钟（0=不限；长输入建议给预算保 partial 结论）")
    ap.add_argument("--url", default=None, help="覆盖被测服务 url")
    ap.add_argument("--model", default=None, help="覆盖被测模型名")
    ap.add_argument("--tokenizer-path", default=None, help="覆盖 tokenizer 目录（压测机本地路径）")
    ap.add_argument("--base-config", default="config.yaml", help="基座配置（默认 kit 的 config.yaml）")
    ap.add_argument("--out-dir", default="runs", help="配置输出目录（默认 <kit>/runs/）")
    ap.add_argument("--tag", default=None, help="配置文件名后缀标记")
    args = ap.parse_args()

    if args.lengths.strip().lower() in ("all", "全部", "默认"):
        args.lengths = ",".join(DEFAULT_LENGTHS)
    if args.prefixes and args.group != "all":
        GROUPS[args.group]["prefixes"] = [int(x) for x in args.prefixes.split(",") if x.strip()]

    keys = ALL_GROUPS if args.group == "all" else [args.group]
    # 基座只读一次（预算参数 + 预检都要用）；读不到不阻断，仅注入告警
    base_cfg, base_load_warn = None, None
    try:
        import yaml
        with open(os.path.abspath(args.base_config), encoding="utf-8") as f:
            base_cfg = yaml.safe_load(f) or {}
    except Exception:
        base_load_warn = ("未能读取基座 config 做预检（pyyaml 不可用或路径不对），"
                          "请人工确认 tokenizer_path / 服务上下文上限")
    results = [gen_one(k, args, base_cfg, base_load_warn) for k in keys]
    print("JSON_RESULT: " + json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
