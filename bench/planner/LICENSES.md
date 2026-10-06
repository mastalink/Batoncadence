# Candidate model licenses

Read from the live Hugging Face model cards by `fetch.py` on 2026-10-03 (raw data: `licenses.json`).
BitCadence would **redistribute by first-use download**, so the license must allow commercial use and
redistribution with no use-restriction or user-count clauses.

| Model (GGUF Q4_K_M) | License on the card | Commercial + redistribute? | Verdict |
|---|---|---|---|
| Qwen2.5-1.5B-Instruct | Apache-2.0 | Yes, no restrictions | **OK** |
| SmolLM2-1.7B-Instruct | Apache-2.0 | Yes, no restrictions | **OK** |
| Phi-3.5-mini-instruct | MIT | Yes, no restrictions | **OK** |
| Qwen2.5-3B-Instruct | `qwen-research` (card says "other") | **No.** Research/non-commercial license | **EXCLUDE** (benchmarked for reference only) |
| Llama-3.2-1B / 3B-Instruct | Llama 3.2 Community License | Yes, but: 700M monthly-active-user clause, Acceptable Use Policy (use restriction), must ship the license + "Built with Llama" notice, derived-model naming rule. Model repo is gated (manual approval) | **FLAG for owner**: usable, but carries a use-restriction and MAU clause |
| Gemma-2-2b-it | Gemma Terms of Use | Yes, but: Prohibited Use Policy (use restriction) that must be passed on to every user; Google may require restricting use remotely | **FLAG for owner** |

The GGUF conversions come from `Qwen/` (official) and `bartowski/` (community quantizer). The GGUF repos
carry the same license tag as the base model. Before shipping, the product must download from a pinned
repo + revision + SHA-256 and display the license text to the user at first use. The two model cards
that are gated (Llama, Gemma) need a manual license acceptance, so the license text was not read in full
by this job; the verdicts above rely on the card's license tag plus the known terms of those licenses.
Owner/legal should read them before anyone ships either.
