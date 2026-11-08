"""How many confirmed answers Audible's search couldn't show where the runs were made.

Audible's search returns a book only in the markets that sell it, while a lookup by ASIN
works everywhere, so a tool that searches Audible can't find some books from some places.
This counts them, so the page can state the margin of error.

usage: geo.py rights [--manifest manifest.json]
           Audible's sales rights for every confirmed answer (public catalog, 50 per request),
           saved to the manifest's "rights"
       geo.py summary --market XX [--manifest manifest.json]
           the summary the page shows, saved to the manifest's "geo"

--market is the two-letter code of the country the runs were made from. It is used to count
and is written nowhere: the page never says where the runs were made.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request

from bench_data import TOOL_NAMES, Benchmark

ap = argparse.ArgumentParser()
ap.add_argument("step", choices=["rights", "summary"])
ap.add_argument("--market", help="where the runs were made (summary)")
ap.add_argument("--manifest", default="manifest.json")
opts = ap.parse_args()
bench = Benchmark(opts.manifest)
confirmed = [b for b in bench.books if b.get("asin")]

if opts.step == "rights":
    asins = sorted({b["asin"].upper() for b in confirmed})
    rights = {}
    for i in range(0, len(asins), 50):
        batch = asins[i:i + 50]
        url = "https://api.audible.com/1.0/catalog/products?" + urllib.parse.urlencode(
            {"asins": ",".join(batch), "num_results": len(batch),
             "response_groups": "product_attrs,customer_rights,product_plans,sku,price"})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60) as r:
            for p in json.load(r).get("products", []):
                rights[p["asin"].upper()] = {"world": p.get("is_world_rights"),
                                             "regions": p.get("distribution_rights_region"), "title": p.get("title")}
        time.sleep(0.6)
    json.dump(rights, open(bench.file("rights"), "w"))
    print(f"{len(rights)} of {len(asins)} confirmed answers have sales rights -> {bench.file('rights')}")
else:
    if not opts.market:
        ap.error("summary needs --market")
    rights = json.load(open(bench.file("rights")))
    final = json.load(open(bench.file("audit", "final")))
    # Sold only in some markets, and not in the one the runs were made from.
    hidden = [b for b in confirmed if (r := rights.get(b["asin"].upper()))
              and not r["world"] and r["regions"] and opts.market.upper() not in r["regions"]]
    summary = {
        "confirmed": len(confirmed),  # books with a confirmed listing
        "hidden": len(hidden),
        "hidden_with_asin": sum(1 for b in hidden if any(k.lower() == "asin" for k in b.get("tags") or {})),
        "books": len(bench.books),
        # The right book, however its fields came out.
        "right_on_hidden": {t: sum(1 for b in hidden if final[b["folder"]]["v"][t] in "CPES") for t in TOOL_NAMES},
    }
    json.dump(summary, open(bench.file("geo"), "w"), indent=1)
    print(json.dumps(summary))
