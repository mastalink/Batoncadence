"""Candidate models: GGUF Q4_K_M repos. Models are cached OUTSIDE the repo."""
import os

CACHE = os.environ.get("PLANNER_BENCH_MODELS", r"C:\AI\model\planner-bench")

# name -> (hf repo for GGUF, filename, hf repo holding the license/model card)
CANDIDATES = {
    "qwen2.5-1.5b": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf", "Qwen/Qwen2.5-1.5B-Instruct"),
    "qwen2.5-3b": ("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf", "Qwen/Qwen2.5-3B-Instruct"),
    "phi-3.5-mini": ("bartowski/Phi-3.5-mini-instruct-GGUF", "Phi-3.5-mini-instruct-Q4_K_M.gguf", "microsoft/Phi-3.5-mini-instruct"),
    "llama-3.2-1b": ("bartowski/Llama-3.2-1B-Instruct-GGUF", "Llama-3.2-1B-Instruct-Q4_K_M.gguf", "meta-llama/Llama-3.2-1B-Instruct"),
    "llama-3.2-3b": ("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf", "meta-llama/Llama-3.2-3B-Instruct"),
    "smollm2-1.7b": ("bartowski/SmolLM2-1.7B-Instruct-GGUF", "SmolLM2-1.7B-Instruct-Q4_K_M.gguf", "HuggingFaceTB/SmolLM2-1.7B-Instruct"),
    "gemma-2-2b": ("bartowski/gemma-2-2b-it-GGUF", "gemma-2-2b-it-Q4_K_M.gguf", "google/gemma-2-2b-it"),
}
