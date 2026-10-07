"""Download each candidate GGUF and record the license read from the live model card."""
import json, os, re, sys
from huggingface_hub import hf_hub_download, HfApi
from models import CACHE, CANDIDATES

os.makedirs(CACHE, exist_ok=True)
api = HfApi()
out = {}
for name, (repo, fn, card) in CANDIDATES.items():
    rec = {"gguf_repo": repo, "file": fn, "card_repo": card}
    try:
        info = api.model_info(card)
        rec["card_license"] = (info.card_data.license if info.card_data else None)
        rec["card_license_name"] = getattr(info.card_data, "license_name", None) if info.card_data else None
        rec["card_license_link"] = getattr(info.card_data, "license_link", None) if info.card_data else None
        rec["card_gated"] = info.gated
    except Exception as e:
        rec["card_error"] = repr(e)[:200]
    try:
        ginfo = api.model_info(repo)
        rec["gguf_card_license"] = ginfo.card_data.license if ginfo.card_data else None
        rec["gguf_card_license_name"] = getattr(ginfo.card_data, "license_name", None) if ginfo.card_data else None
    except Exception as e:
        rec["gguf_error"] = repr(e)[:200]
    if "--no-download" not in sys.argv:
        try:
            p = hf_hub_download(repo, fn, local_dir=CACHE)
            rec["bytes"] = os.path.getsize(p)
        except Exception as e:
            rec["download_error"] = repr(e)[:300]
    out[name] = rec
    print(name, json.dumps(rec), flush=True)
json.dump(out, open(os.path.join(os.path.dirname(__file__), "licenses.json"), "w"), indent=2)
