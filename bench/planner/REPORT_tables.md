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
