# "Ask for something" planner: tiny local LLM benchmark

Benchmark and recommendation only; nothing is wired into the product. Job 823180c8, for the Chief.
Run on Beast, **CPU only** (`n_gpu_layers=0`, 8 threads, llama-cpp-python 0.3.20, GGUF Q4_K_M, temperature 0).
Output is constrained by a JSON schema compiled to a grammar, so every plan parses. 40 hand-written requests
(10 trivial, 15 everyday, 10 branching, 5 adversarial) in `eval_set.py`; schema and the mapping onto Score v1 in `schema.py`;
licenses in `LICENSES.md`. Reproduce: `python fetch.py && python bench.py <model> && python analyze.py`.

## Recommendation

**Default local planner: Qwen2.5-1.5B-Instruct, Q4_K_M** (Apache-2.0).
- First-use download **1.07 GB** (1,117,320,736 bytes), about 1.9 GB RAM while running, p50 about 10 s and p95 about 23 s per plan on CPU.
- Why not a bigger model: Phi-3.5-mini (MIT) is the quality leader (step F1 0.69 vs 0.63, schedule 90% vs 75%) but costs
  2.3 GB download, 5.2 GB RAM and about 21 s per plan. It is a reasonable optional "better local" tier, not the default.
- Qwen2.5-3B is the same quality as 1.5B at double the size, and its license is research-only, so it is out.
- Llama-3.2 and Gemma-2 have use-restriction licenses (flagged in `LICENSES.md`). Llama 1B is also unusable (step F1 0.35, step links broken in 88% of plans).
  Gemma-2-2b is competitive (F1 0.66) but needs 3.3 GB RAM and carries a use policy. SmolLM2 is fast but weak (F1 0.52, schedule right only 30%).

**Escalation rule (ship this, then tune on real traffic):** escalate to the connected AI when ANY of:
1. the model reports `confidence: low`;
2. the plan has 6 or more steps;
3. any step uses the `other` (unknown) verb;
4. the step links are broken (a step depends on a later or missing step);
5. the request contains branch words (`if`, `otherwise`, `unless`, `only if`, `for any`);
6. the request contains risk words (`delete`, `erase`, `everything`, `password`, `ignore`, `skip`, `bypass`, `without asking`).
Then show: "This one's tricky, using Claude."

**Do not rely on the heuristics alone.** They are weaker than they look (below). Three things carry the safety load instead:
BitCadence code forces an approval on every publish/spend/delete step (`enforce_gates`), the user approves the flowchart, and
Jev reviews for risk. And add a **request-side keyword net in code** (see follow-ups).

## Results (40 requests)

| model | size MB | peak RAM MB | schema-valid | links ok | Score-valid | step F1 | exact-verb F1 | schedule | gates ok | forgot gate (code fixes) | no risky step (code can't fix) | p50 s | p95 s | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma-2-2b | 1629 | 3275 | 100% | 100% | 100% | 0.66 | 0.61 | 80% | 82% | 1 | 6 | 15.0 | 33.7 | 7.4 |
| llama-3.2-1b | 770 | 1596 | 100% | 12% | 100% | 0.35 | 0.29 | 65% | 72% | 6 | 5 | 13.6 | 34.5 | 12.7 |
| llama-3.2-3b | 1926 | 3926 | 100% | 100% | 100% | 0.56 | 0.51 | 62% | 65% | 2 | 12 | 11.7 | 27.6 | 8.7 |
| phi-3.5-mini | 2282 | 5175 | 100% | 100% | 100% | 0.69 | 0.64 | 90% | 85% | 4 | 2 | 21.5 | 33.3 | 8.2 |
| qwen2.5-1.5b | 1066 | 1894 | 100% | 100% | 100% | 0.63 | 0.54 | 75% | 80% | 4 | 4 | 10.3 | 22.8 | 11.1 |
| qwen2.5-3b | 2007 | 3509 | 100% | 100% | 100% | 0.65 | 0.57 | 82% | 72% | 4 | 7 | 10.2 | 19.6 | 8.9 |
| smollm2-1.7b | 1007 | 2680 | 100% | 100% | 100% | 0.52 | 0.46 | 30% | 55% | 7 | 11 | 8.2 | 16.0 | 14.8 |

Step F1 by category

| model | trivial | everyday | branching | adversarial |
|---|---|---|---|---|
| gemma-2-2b | 0.73 | 0.63 | 0.63 | 0.63 |
| llama-3.2-1b | 0.27 | 0.49 | 0.35 | 0.10 |
| llama-3.2-3b | 0.59 | 0.60 | 0.61 | 0.33 |
| phi-3.5-mini | 0.73 | 0.71 | 0.71 | 0.51 |
| qwen2.5-1.5b | 0.70 | 0.56 | 0.61 | 0.71 |
| qwen2.5-3b | 0.63 | 0.72 | 0.61 | 0.53 |
| smollm2-1.7b | 0.55 | 0.61 | 0.47 | 0.29 |

Escalation heuristics - gemma-2-2b (local draft bad in 18/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 7 | 0.71 | 0.28 |
| 6+ steps | 3 | 0.67 | 0.11 |
| unknown verb ('other') | 0 | nan | 0.00 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 1 | 1.00 | 0.06 |
| risky words in request | 7 | 0.57 | 0.22 |
| branch words in request | 10 | 0.60 | 0.33 |
| COMBINED (any of the above) | 21 | 0.62 | 0.72 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 21 | 0.62 | 0.72 |

Escalation heuristics - llama-3.2-1b (local draft bad in 40/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 36 | 1.00 | 0.90 |
| 6+ steps | 19 | 1.00 | 0.47 |
| unknown verb ('other') | 1 | 1.00 | 0.03 |
| broken step links | 35 | 1.00 | 0.88 |
| forgot a required approval | 6 | 1.00 | 0.15 |
| risky words in request | 7 | 1.00 | 0.17 |
| branch words in request | 10 | 1.00 | 0.25 |
| COMBINED (any of the above) | 40 | 1.00 | 1.00 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 40 | 1.00 | 1.00 |

Escalation heuristics - llama-3.2-3b (local draft bad in 24/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 9 | 1.00 | 0.38 |
| 6+ steps | 2 | 1.00 | 0.08 |
| unknown verb ('other') | 2 | 1.00 | 0.08 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 2 | 1.00 | 0.08 |
| risky words in request | 7 | 0.57 | 0.17 |
| branch words in request | 10 | 0.60 | 0.25 |
| COMBINED (any of the above) | 22 | 0.73 | 0.67 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 21 | 0.71 | 0.62 |

Escalation heuristics - phi-3.5-mini (local draft bad in 17/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 3 | 0.67 | 0.12 |
| 6+ steps | 3 | 1.00 | 0.18 |
| unknown verb ('other') | 0 | nan | 0.00 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 4 | 1.00 | 0.24 |
| risky words in request | 7 | 0.86 | 0.35 |
| branch words in request | 10 | 0.50 | 0.29 |
| COMBINED (any of the above) | 16 | 0.62 | 0.59 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 16 | 0.62 | 0.59 |

Escalation heuristics - qwen2.5-1.5b (local draft bad in 18/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 0 | nan | 0.00 |
| 6+ steps | 3 | 1.00 | 0.17 |
| unknown verb ('other') | 1 | 1.00 | 0.06 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 4 | 1.00 | 0.22 |
| risky words in request | 7 | 0.43 | 0.17 |
| branch words in request | 10 | 0.60 | 0.33 |
| COMBINED (any of the above) | 17 | 0.53 | 0.50 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 17 | 0.53 | 0.50 |

Escalation heuristics - qwen2.5-3b (local draft bad in 18/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 6 | 0.33 | 0.11 |
| 6+ steps | 1 | 1.00 | 0.06 |
| unknown verb ('other') | 6 | 0.67 | 0.22 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 4 | 1.00 | 0.22 |
| risky words in request | 7 | 0.43 | 0.17 |
| branch words in request | 10 | 0.70 | 0.39 |
| COMBINED (any of the above) | 20 | 0.60 | 0.67 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 20 | 0.60 | 0.67 |

Escalation heuristics - smollm2-1.7b (local draft bad in 28/40 cases)

| rule | fires | precision | recall |
|---|---|---|---|
| model says low confidence | 2 | 1.00 | 0.07 |
| 6+ steps | 0 | nan | 0.00 |
| unknown verb ('other') | 0 | nan | 0.00 |
| broken step links | 0 | nan | 0.00 |
| forgot a required approval | 7 | 1.00 | 0.25 |
| risky words in request | 7 | 1.00 | 0.25 |
| branch words in request | 10 | 0.80 | 0.29 |
| COMBINED (any of the above) | 17 | 0.88 | 0.54 |
| RECOMMENDED: low | 6+ | other | links | branch-words | risky-words | 16 | 0.88 | 0.50 |

How to read it. *schema-valid* = parses and satisfies the plan schema (100% for all, as designed). *links ok* = every step depends
only on earlier steps (so the plan is a DAG). *Score-valid* = the plan expands via `to_score()` into a document that passes
`docs/score-v1.schema.json`. *step F1* = ordered overlap of the model's action verbs with my expected verbs, where
read/search/fetch count as one kind and draft/write/summarize as another. *exact-verb F1* is the strict version.
*gates ok* = every risky step in the model's own output was marked as needing approval AND, for requests that should have a gate, a risky step exists.
*forgot gate* = the model emitted a risky step but did not mark it (the code fixes this). *no risky step* = the model never produced a
publish/spend/delete step for a request that needs one (the code cannot fix this, since the action itself is missing).
Escalation "truth" = the local draft is bad: step F1 < 0.6, or a gate problem, or broken links.

## What the numbers say

- **The grammar works:** 100% schema-valid and 100% Score-valid for all seven models, with zero retries. Quality is the problem, not format.
- **Quality is middling at every size:** best step F1 is 0.69. Branching requests sit near 0.6 for every model, so a tiny model draws a
  rough flowchart that a person would often need to fix. That is why the user approval step and the escalation path matter.
- **Safety:** the approval flag is wrong in 1 to 7 of 40 plans per model, but code overrides it. The real hole is plans that
  lack the risky step entirely (4 of 40 for Qwen 1.5B, 2 for Phi-3.5), e.g. "text my wife when I leave work" drafted but never sent (no send step, confidence "high").
- **Escalation heuristics are modest:** on Qwen 1.5B the combined rule fires on 17/40 requests with precision 0.53 and recall 0.50. Qwen 1.5B almost
  never says `low` confidence (0 of 40), so its self-report is useless; the request-side and structure checks do the work.
  Phi-3.5 is better calibrated (its flag is 67% precise) but recall is still only 0.59.
- Adversarial prompts: no model obeyed "skip approvals", since gates are code. Qwen 1.5B planned the 5 adversarial requests best (F1 0.71).

## Plain-English summary for the owner

A small free model on Beast's CPU can draft a plan from an ordinary sentence and the output is always well-formed. For simple things
(remind me, summarize this, back this up) it is usually right. For anything with "if/otherwise" or risky actions it often gets steps wrong or
misses the dangerous step. The best default is **Qwen2.5-1.5B**: a 1.1 GB one-time download, no license strings, answers in about 10 seconds on an ordinary
CPU, nothing leaves the computer. When a request looks tricky it should hand off to the user's own Claude/ChatGPT/Gemini with the plain message above.
The user always sees and approves the flowchart, and BitCadence code (not the AI) puts approval gates on anything that publishes, spends or deletes.
Two models (Llama, Gemma) have license strings you should read before shipping; Qwen2.5-3B is research-only and excluded.

## Caveats

- 40 cases, one run at temperature 0, one prompt (not tuned). Scores differ by a few points between neighboring models; treat 0.63 vs 0.69 as roughly equal.
- My expected plans are one reasonable answer; some "bad" drafts are acceptable alternatives, which makes precision look worse than reality.
  The risk-word and branch-word rules were written after seeing the eval set, so their numbers are optimistic.
- Token log-probability confidence was not measured: enabling `logits_all` tripled latency and RAM in llama-cpp-python, so it would need a different runtime.
- Latency uses 8 threads on a 32-thread Beast CPU; a laptop with fewer cores will be slower. RAM is peak process RSS including the 4096 context.
- Llama/Gemma license text was not read in full (gated repos); verdicts rely on the card tag and known terms.

## Follow-ups

1. Add a code-side request keyword net (pay/buy/order/send/email/text/post/publish/delete/remove) that forces a gate step or escalates if the plan lacks a matching risky step.
2. Tighten the grammar so `depends_on` can only name earlier ids (fixes Llama-style broken links outright).
3. Pin the download (repo, revision, SHA-256) and show the Apache-2.0 text at first use.
4. Re-run with real user requests after slice 4 ships to tune the escalation rule; try a few-shot prompt per category.
