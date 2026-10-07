"""Run one model over the eval set on CPU only. Usage: python bench.py <model-name> [--limit N]
Each model runs in its own process so RSS is clean. Output: results/<model>.json"""
import json, os, sys, time
import psutil
from llama_cpp import Llama
from models import CACHE, CANDIDATES
from eval_set import CASES
from schema import PLAN_SCHEMA, ACTIONS

THREADS = int(os.environ.get("PLANNER_THREADS", "8"))  # a typical desktop; Beast has 32 logical
VERBS = ", ".join(ACTIONS)

INSTRUCTIONS = f"""You turn a plain-English request into a small step-by-step plan, as JSON.
Rules:
- "action" must be one of: {VERBS}. Use "other" only if nothing fits.
- Each step has id (s1, s2, ...), what (short), depends_on (earlier step ids), condition (text if the step only runs on a branch, else ""), needs_approval (true if the step publishes, spends money, deletes, or messages other people).
- schedule.kind is one of on_demand, once, hourly, daily, weekly, monthly; schedule.detail is the time in words or "".
- confidence is low if the request is vague, risky, or you are unsure.
- Output only the JSON plan.

Example request: Every Tuesday, collect the new orders and email the totals to the accountant.
Example plan: {{"title":"Weekly order totals to accountant","schedule":{{"kind":"weekly","detail":"Tuesdays"}},"steps":[{{"id":"s1","action":"fetch_data","what":"collect new orders","depends_on":[],"condition":"","needs_approval":false}},{{"id":"s2","action":"summarize","what":"total the orders","depends_on":["s1"],"condition":"","needs_approval":false}},{{"id":"s3","action":"send_email","what":"email totals to the accountant","depends_on":["s2"],"condition":"","needs_approval":true}}],"confidence":"high"}}

Request: """


def main():
    name = sys.argv[1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else len(CASES)
    _, fn, _ = CANDIDATES[name]
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    t0 = time.time()
    llm = Llama(model_path=os.path.join(CACHE, fn), n_ctx=4096, n_threads=THREADS, n_gpu_layers=0,
                verbose=False)
    load_s = time.time() - t0
    peak = proc.memory_info().rss
    rows = []
    for case in CASES[:limit]:
        t = time.time()
        try:
            r = llm.create_chat_completion(
                messages=[{"role": "user", "content": INSTRUCTIONS + case["request"]}],
                response_format={"type": "json_object", "schema": PLAN_SCHEMA},
                temperature=0.0, max_tokens=1200)
            ch = r["choices"][0]
            text = ch["message"]["content"]
            lps = [float(x["logprob"]) for x in (ch.get("logprobs") or {}).get("content", [])]
            ntok = r["usage"]["completion_tokens"]
            err = None
        except Exception as e:  # record, never hide
            text, lps, ntok, err = None, [], 0, repr(e)[:300]
        dt = time.time() - t
        peak = max(peak, proc.memory_info().rss)
        rows.append(dict(id=case["id"], output=text, seconds=dt, tokens=ntok,
                         mean_logprob=(sum(lps) / len(lps) if lps else None),
                         min_logprob=(min(lps) if lps else None), error=err))
        print(f"{name} #{case['id']} {dt:.1f}s {ntok}tok", flush=True)
    os.makedirs("results", exist_ok=True)
    json.dump(dict(model=name, file=fn, bytes=os.path.getsize(os.path.join(CACHE, fn)), threads=THREADS,
                   load_seconds=load_s, 
                   rss_peak_mb=peak / 2**20, rss_baseline_mb=rss0 / 2**20, rows=rows),
              open(f"results/{name}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
