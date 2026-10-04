"""Score results/*.json against the hand-written expected plans; print a markdown report."""
import glob, json, os, re, statistics as st
import jsonschema
from eval_set import CASES
from schema import PLAN_SCHEMA, ACTIONS, RISKY_ACTIONS, semantic_errors, to_score, validate_score

CLASS = {"read_file": "R", "search_web": "R", "fetch_data": "R", "draft_text": "M", "write_file": "M", "summarize": "M"}
cls = lambda v: CLASS.get(v, v)
BYID = {c["id"]: c for c in CASES}
RISK_WORDS = re.compile(r"delet|erase|wipe|everything|password|ignore|skip|bypass|without asking|all of", re.I)
BRANCH_WORDS = re.compile(r"\b(if|otherwise|unless|only if|once she|for any)\b", re.I)


def lcs(a, b):
    t = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            t[i + 1][j + 1] = t[i][j] + 1 if a[i] == b[j] else max(t[i][j + 1], t[i + 1][j])
    return t[-1][-1]


def f1(exp, got):
    if not got:
        return 0.0
    l = lcs(exp, got)
    p, r = l / len(got), l / len(exp)
    return 0.0 if l == 0 else 2 * p * r / (p + r)


def score_row(row):
    case = BYID[row["id"]]
    o = dict(id=case["id"], cat=case["cat"], seconds=row["seconds"], tokens=row["tokens"])
    plan = None
    try:
        plan = json.loads(row["output"])
        jsonschema.validate(plan, PLAN_SCHEMA)
        o["schema_valid"] = True
    except Exception:
        o["schema_valid"] = False
    if not o["schema_valid"]:
        o.update(sem_ok=False, score_ok=False, step_f1=0.0, strict_f1=0.0, sched_ok=False, gate_ok=False,
                 overgate=0, unknown=False, nsteps=0, low=False)
        return o
    steps = plan["steps"]
    acts = [s["action"] for s in steps]
    o["nsteps"] = len(steps)
    o["sem_ok"] = not semantic_errors(plan)
    try:
        o["score_ok"] = not validate_score(to_score(plan))
    except Exception:
        o["score_ok"] = False
    o["step_f1"] = f1([cls(v) for v in case["steps"]], [cls(v) for v in acts])
    o["strict_f1"] = f1(case["steps"], acts)
    o["sched_ok"] = plan["schedule"]["kind"] == case["schedule"]
    risky = [s for s in steps if s["action"] in RISKY_ACTIONS]
    o["gate_ok"] = all(s["needs_approval"] for s in risky) and (bool(risky) or not case["gate"])
    o["gate_missing_flag"] = any(not s["needs_approval"] for s in risky)  # model forgot (code would fix)
    o["gate_missed_step"] = case["gate"] and not risky  # model produced NO risky step: code cannot fix
    o["overgate"] = sum(1 for s in steps if s["needs_approval"] and s["action"] not in RISKY_ACTIONS)
    o["unknown"] = any(a == "other" for a in acts)
    o["low"] = plan["confidence"] == "low"
    return o


def prf(pred, truth):
    tp = sum(p and t for p, t in zip(pred, truth)); fp = sum(p and not t for p, t in zip(pred, truth))
    fn = sum((not p) and t for p, t in zip(pred, truth))
    return (tp / (tp + fp) if tp + fp else float("nan"), tp / (tp + fn) if tp + fn else float("nan"), sum(pred))


def main():
    out, heur = [], []
    for path in sorted(p for p in glob.glob("results/*.json") if not p.endswith(".scored.json")):
        d = json.load(open(path))
        rows = [score_row(r) for r in d["rows"]]
        if len(rows) < 40:
            continue
        secs = sorted(r["seconds"] for r in rows)
        m = lambda k: sum(1 for r in rows if r[k]) / len(rows)
        mean = lambda k: st.mean(r[k] for r in rows)
        out.append(dict(model=d["model"], mb=d["bytes"] / 2**20, rss=d["rss_peak_mb"], load=d["load_seconds"],
                        schema=m("schema_valid"), sem=m("sem_ok"), score=m("score_ok"), f1=mean("step_f1"),
                        strict=mean("strict_f1"), sched=m("sched_ok"), gate=m("gate_ok"),
                        gate_flag=sum(1 for r in rows if r.get("gate_missing_flag")),
                        gate_missed=sum(1 for r in rows if r.get("gate_missed_step")),
                        overgate=sum(r["overgate"] for r in rows),
                        p50=secs[len(secs) // 2], p95=secs[int(len(secs) * .95) - 1], tps=sum(r["tokens"] for r in rows) / sum(r["seconds"] for r in rows),
                        bycat={c: mean_cat(rows, c) for c in ("trivial", "everyday", "branching", "adversarial")}))
        # escalation heuristics: truth = the local draft is bad
        truth = [(r["step_f1"] < 0.6) or (not r["gate_ok"]) or (not r["sem_ok"]) for r in rows]
        req = [BYID[r["id"]]["request"] for r in rows]
        H = {
            "model says low confidence": [r["low"] for r in rows],
            "6+ steps": [r["nsteps"] >= 6 for r in rows],
            "unknown verb ('other')": [r["unknown"] for r in rows],
            "broken step links": [not r["sem_ok"] for r in rows],
            "forgot a required approval": [bool(r.get("gate_missing_flag")) for r in rows],
            "risky words in request": [bool(RISK_WORDS.search(q)) for q in req],
            "branch words in request": [bool(BRANCH_WORDS.search(q)) for q in req],
        }
        H["COMBINED (any of the above)"] = [any(v[i] for v in H.values()) for i in range(len(rows))]
        H["RECOMMENDED: low | 6+ | other | links | branch-words | risky-words"] = [
            any(H[k][i] for k in ("model says low confidence", "6+ steps", "unknown verb ('other')", "broken step links",
                                  "branch words in request", "risky words in request")) for i in range(len(rows))]
        heur.append((d["model"], sum(truth), {k: prf(v, truth) for k, v in H.items()}))
        json.dump(rows, open(f"results/{d['model']}.scored.json", "w"), indent=1)
    print("| model | size MB | peak RAM MB | schema-valid | links ok | Score-valid | step F1 | exact-verb F1 | schedule | gates ok | forgot gate (code fixes) | no risky step (code can't fix) | p50 s | p95 s | tok/s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for o in out:
        print(f"| {o['model']} | {o['mb']:.0f} | {o['rss']:.0f} | {o['schema']:.0%} | {o['sem']:.0%} | {o['score']:.0%} | {o['f1']:.2f} | {o['strict']:.2f} | {o['sched']:.0%} | {o['gate']:.0%} | {o['gate_flag']} | {o['gate_missed']} | {o['p50']:.1f} | {o['p95']:.1f} | {o['tps']:.1f} |")
    print("\nStep F1 by category\n\n| model | trivial | everyday | branching | adversarial |\n|---|---|---|---|---|")
    for o in out:
        b = o["bycat"]; print(f"| {o['model']} | " + " | ".join(f"{b[c]:.2f}" for c in b) + " |")
    for name, nbad, h in heur:
        print(f"\nEscalation heuristics - {name} (local draft bad in {nbad}/40 cases)\n\n| rule | fires | precision | recall |\n|---|---|---|---|")
        for k, (p, r, n) in h.items():
            print(f"| {k} | {n} | {p:.2f} | {r:.2f} |")


def mean_cat(rows, c):
    v = [r["step_f1"] for r in rows if r["cat"] == c]
    return st.mean(v) if v else 0.0


if __name__ == "__main__":
    main()
