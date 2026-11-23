#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总摸高结果为 Markdown 性能数据表（按组级配置逐场景输出并发-指标表 + 最大达标并发）。

部署位置: <kit>/skill_ext/collect_results.py
用法:
    python3 skill_ext/collect_results.py --config runs/multi-prefix_20261123_120000.yaml
    python3 skill_ext/collect_results.py --config runs/a.yaml --config runs/b.yaml --npu 8
    python3 skill_ext/collect_results.py --scenario-ids random_64k_1k_hit0,random_75k_1k_hit0 \
        --sla 60000,50

数据来源（每场景）:
    results/<场景ID>/<时间戳>/<model>/sla_summary.json   摸高完整结束
    results/<场景ID>/partial_summary.json                时间预算到限被切断（结论=下界）
判定口径与 report.py 一致: Failed==0 且 avg TTFT/TPOT 双达标 -> PASS；
最大达标并发 = 全部 PASS 档中的最大并发。末尾输出 JSON_RESULT 供上层解析。
"""
import argparse
import glob
import json
import os
import re
import sys

TS_RE = re.compile(r"^\d{8}_\d{6}$")
K_TTFT = "Avg TTFT (ms)"
K_TPOT = "Avg TPOT (ms)"
K_OK = "Success Requests"
K_FAIL = "Failed Requests"
K_TOTAL = "Total Requests"
K_OUT_TPS = "Output Throughput (tok/s)"


# ---------------- 场景行解析（与 runner.py 同口径的最小实现） ----------------
def parse_scenario_line(line: str) -> dict:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 7:
        raise ValueError(f"场景行字段不足: {line!r}")
    dset, in_len, out_len, hit, pnum, ttft, tpot = parts[:7]
    m = re.match(r"^(\d+(?:\.\d+)?)(k|kb)?$", in_len.lower())
    in_tok = int(float(m.group(1)) * (1024 if m.group(2) else 1))
    m2 = re.match(r"^(\d+(?:\.\d+)?)(k|kb)?$", out_len.lower())
    out_tok = int(float(m2.group(1)) * (1024 if m2.group(2) else 1))
    hit_f = float(hit[:-1]) / 100 if hit.endswith("%") else float(hit)
    return {"dataset": dset, "input_len": in_tok, "output_len": out_tok,
            "hit_rate": hit_f, "prefix_num": int(pnum),
            "ttft_sla_ms": int(ttft), "tpot_sla_ms": int(tpot)}


def kfmt(n: int) -> str:
    return f"{n // 1024}k" if n % 1024 == 0 else str(n)


def scenario_id(sc: dict) -> str:
    if sc["hit_rate"] == 0:
        hit = "0"
    else:
        pct = round(sc["hit_rate"] * 100, 4)
        hit = (f"{int(round(pct))}pct" if abs(pct - round(pct)) < 1e-9
               else f"{pct:.2f}".rstrip("0").replace(".", "p") + "pct")
    sid = f"{sc['dataset']}_{kfmt(sc['input_len'])}_{kfmt(sc['output_len'])}_hit{hit}"
    if int(sc["prefix_num"]) > 1:
        sid += f"_pN{int(sc['prefix_num'])}"
    return sid


# ---------------- 结果定位与解析 ----------------
def find_latest_summary(scen_dir: str):
    """最新时间戳目录下的 sla_summary.json（mtime 口径，兼容 <ts>/<model>/ 与 <ts>/ 两种深度）"""
    tses = [d for d in glob.glob(os.path.join(scen_dir, "*"))
            if TS_RE.match(os.path.basename(d)) and os.path.isdir(d)]
    for d in sorted(tses, key=os.path.getmtime, reverse=True):
        cands = ([os.path.join(d, "sla_summary.json")]
                 + sorted(glob.glob(os.path.join(d, "*", "sla_summary.json"))))
        for p in cands:
            if os.path.isfile(p):
                return p
    return None


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_p99_ttft(percentiles) -> str:
    """best-effort 取 TTFT p99（不同 evalscope 版本键名略有差异）"""
    if not isinstance(percentiles, dict):
        return "-"
    for k, v in percentiles.items():
        if "ttft" in k.lower() and "99" in k:
            return f"{float(v):.0f}"
    return "-"


def verdict(metrics: dict, ttft_sla: int, tpot_sla: int) -> str:
    try:
        ttft, tpot = metrics.get(K_TTFT), metrics.get(K_TPOT)
        ok = ((metrics.get(K_FAIL) or 0) == 0 and ttft is not None and tpot is not None
              and float(ttft) <= ttft_sla and float(tpot) <= tpot_sla)
        return "PASS" if ok else "FAIL"
    except (TypeError, ValueError):
        return "FAIL"


def fmt_v(v, nd=1):
    try:
        v = float(v)
        return "-" if v < 0 else f"{v:.{nd}f}"
    except (TypeError, ValueError):
        return "-"


def collect_scenario(sid: str, ttft_sla: int, tpot_sla: int, results_dir: str, npu: int):
    """返回 dict: {sid, status, rows, selected, best}；rows=按并发排序的指标行"""
    scen_dir = os.path.join(results_dir, sid)
    if not os.path.isdir(scen_dir):
        return {"sid": sid, "status": "无结果目录", "rows": [], "selected": None}
    rows, status = [], "完成"
    summary_path = find_latest_summary(scen_dir)
    if summary_path:
        data = load_json(summary_path) or {}
        for k, v in sorted(data.items(), key=lambda kv: _par_num(kv[0])):
            if not k.startswith("parallel") or not isinstance(v, dict):
                continue
            m = v.get("metrics", {}) or {}
            tps = m.get(K_OUT_TPS)
            rows.append({
                "parallel": _par_num(k), "succ": m.get(K_OK), "failed": m.get(K_FAIL),
                "total": m.get(K_TOTAL), "ttft": m.get(K_TTFT), "tpot": m.get(K_TPOT),
                "tps": tps, "ttft_p99": extract_p99_ttft(v.get("percentiles")),
                "pass": verdict(m, ttft_sla, tpot_sla) == "PASS",
            })
    else:
        ppath = os.path.join(scen_dir, "partial_summary.json")
        pdata = load_json(ppath) if os.path.isfile(ppath) else None
        if isinstance(pdata, dict) and pdata.get("probes"):
            status = "partial（时间预算切断，结论为真实上限的下界）"
            for n, v in sorted(pdata["probes"].items(), key=lambda kv: int(kv[0])):
                rows.append({
                    "parallel": int(n), "succ": v.get("succ"), "failed": v.get("failed"),
                    "total": v.get("total"), "ttft": v.get("ttft"), "tpot": v.get("tpot"),
                    "tps": None, "ttft_p99": "-", "pass": bool(v.get("pass")),
                })
        else:
            return {"sid": sid, "status": "运行中或无汇总", "rows": [], "selected": None}
    passing = [r["parallel"] for r in rows if r["pass"]]
    selected = max(passing) if passing else None
    best = next((r for r in rows if r["parallel"] == selected), None) if selected else None
    return {"sid": sid, "status": status, "rows": rows, "selected": selected, "best": best}


def _par_num(key: str) -> int:
    try:
        return int(key.split("_")[1])
    except (IndexError, ValueError):
        return 0


# ---------------- 渲染 ----------------
def render(res: dict, ttft_sla: int, tpot_sla: int, npu: int) -> [str, list]:
    lines = [f"### {res['sid']}",
             f"状态: {res['status']}｜SLA 判据: TTFT≤{ttft_sla}ms / TPOT≤{tpot_sla}ms"]
    if not res["rows"]:
        return lines, []
    head = ("| 并发 | 成功/总 | TTFT avg(ms) | TTFT p99(ms) | TPOT avg(ms) "
            "| 输出吞吐(tok/s) |" + (" 单卡吞吐(tok/s) |" if npu else "") + " 判定 |")
    sep = "|" + "---|" * (7 + (1 if npu else 0))
    lines += [head, sep]
    for r in sorted(res["rows"], key=lambda x: x["parallel"]):
        row = (f"| {r['parallel']} | {fmt_v(r['succ'],0)}/{fmt_v(r['total'],0)} "
               f"| {fmt_v(r['ttft'])} | {r['ttft_p99']} | {fmt_v(r['tpot'],2)} "
               f"| {fmt_v(r['tps'])} |")
        if npu:
            row += f" {fmt_v(r['tps'] / npu if r['tps'] else None)} |"
        row += f" {'PASS' if r['pass'] else 'FAIL'} |"
        lines.append(row)
    if res["selected"]:
        b = res["best"]
        lines.append(f"**结论: 最大达标并发 = {res['selected']}**（该档 TTFT avg="
                     f"{fmt_v(b['ttft'])}ms / TPOT avg={fmt_v(b['tpot'],2)}ms / "
                     f"输出吞吐={fmt_v(b['tps'])} tok/s）")
    else:
        lines.append("**结论: 无达标档（最低并发即违反 SLA 或请求失败，先排查服务可用性）**")
    return lines, []


def load_scenarios_from_config(cfg_path: str) -> list:
    """从组级配置读场景行（含 base_config 场景合并语义: 覆盖文件的 scenarios 整体替换）"""
    import yaml
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    out = []
    for line in cfg.get("scenarios") or []:
        line = str(line).strip()
        if not line or line.startswith("#"):
            continue
        sc = parse_scenario_line(line)
        out.append((scenario_id(sc), sc["ttft_sla_ms"], sc["tpot_sla_ms"]))
    if not out:
        raise ValueError(f"{cfg_path} 里没有启用场景")
    return out


def main():
    ap = argparse.ArgumentParser(description="汇总摸高结果为 Markdown 性能表")
    ap.add_argument("--config", action="append", default=None,
                    help="组级配置（可多次给；场景与 SLA 判据从中读取）")
    ap.add_argument("--scenario-ids", default=None, help="直接指定场景 ID 逗号分隔")
    ap.add_argument("--sla", default=None, help="直接指定场景时给的 SLA，如 60000,50")
    ap.add_argument("--results-dir", default="results", help="结果根目录（默认 ./results）")
    ap.add_argument("--npu", type=int, default=0, help="卡数>0 时增加单卡吞吐列")
    args = ap.parse_args()

    plan = []   # [(sid, ttft_sla, tpot_sla)]
    if args.config:
        for cp in args.config:
            plan.extend(load_scenarios_from_config(cp))
    elif args.scenario_ids:
        if not args.sla:
            sys.exit("--scenario-ids 需要 --sla ttft_ms,tpot_ms")
        t, p = args.sla.split(",")
        for sid in args.scenario_ids.split(","):
            plan.append((sid.strip(), int(t), int(p)))
    else:
        sys.exit("需要 --config 或 --scenario-ids")

    out, jrows = [], []
    for sid, t_sla, p_sla in plan:
        res = collect_scenario(sid, t_sla, p_sla, args.results_dir, args.npu)
        block, _ = render(res, t_sla, p_sla, args.npu)
        out.extend(block + [""])
        jrows.append({"sid": sid, "status": res["status"], "selected": res["selected"],
                      "ttft_sla_ms": t_sla, "tpot_sla_ms": p_sla})
    if jrows:
        out.append("## 组级汇总")
        out.append("| 场景 | 状态 | 最大达标并发 |")
        out.append("|---|---|---|")
        for r in jrows:
            out.append(f"| {r['sid']} | {r['status']} | "
                       f"{r['selected'] if r['selected'] else '—'} |")
        done = [r for r in jrows if r["selected"]]
        if done:
            out.append(f"\n共 {len(jrows)} 场景，已完成且有达标档: {len(done)}；"
                       f"最大达标并发区间: {min(r['selected'] for r in done)}"
                       f"~{max(r['selected'] for r in done)}")
    print("\n".join(out))
    print("\nJSON_RESULT: " + json.dumps(jrows, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
