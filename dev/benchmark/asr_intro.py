"""What each book's narrator announces in its opening seconds: title, author, narrator.

Cuts the first --seconds of every benchmark book whose audio is on disk and sends it to a
faster-whisper server (POST /transcribe). One line per book in the output jsonl; a rerun
skips the books already there, so it can be stopped and resumed.

usage: asr_intro.py --out data/asr_intro.jsonl [--server http://host:8000] [--seconds 45]
                    [--start 0] [--model large] [--root /mnt/audiobooks] [--only folders.txt]
"""
import argparse
import json
import os
import queue
import subprocess
import tempfile
import threading
import time

from bench_data import Benchmark, path


def clip(src, start, seconds, dst):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", src,
                    "-vn", "-ac", "1", "-ar", "16000", "-y", dst], check=True, timeout=120)


def transcribe(server, wav, model):
    out = subprocess.run(["curl", "-s", "-m", "600", "-F", f"audio=@{wav}",
                          f"{server}/transcribe?language=en&model={model}&word_timestamps=false"],
                         capture_output=True, text=True, timeout=660)
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--server", default="http://10.0.0.50:8000")
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--model", default="large")
    ap.add_argument("--root", default="/mnt/audiobooks")
    ap.add_argument("--only", help="a file of folders, one per line")
    ap.add_argument("--manifest", default="manifest.json")
    opts = ap.parse_args()

    bench = Benchmark(opts.manifest)
    bench.books.sort(key=lambda b: b["answer"] is not None)  # the unscored books first
    only = set(open(opts.only).read().splitlines()) if opts.only else None
    done = set()
    if os.path.exists(path(opts.out)):
        done = {json.loads(l)["folder"] for l in open(path(opts.out), encoding="utf-8")}
    todo = [b for b in bench.books if b["folder"] not in done and (only is None or b["folder"] in only)
            and os.path.isfile(os.path.join(opts.root, b["folder"], b["file"]))]
    print(f"{len(todo)} books to transcribe ({len(done)} already done)", flush=True)

    tmp = tempfile.mkdtemp(prefix="asr_")
    clips = queue.Queue(maxsize=4)

    def cutter():
        for i, b in enumerate(todo):
            wav = os.path.join(tmp, f"{i}.wav")
            try:
                clip(os.path.join(opts.root, b["folder"], b["file"]), opts.start, opts.seconds, wav)
                clips.put((b, wav, ""))
            except Exception as e:  # unreadable file: recorded, not fatal
                clips.put((b, None, f"clip failed: {e}"))
        clips.put(None)

    threading.Thread(target=cutter, daemon=True).start()
    out = open(path(opts.out), "a", encoding="utf-8")
    n, t0 = 0, time.time()
    while (item := clips.get()) is not None:
        b, wav, err = item
        row = {"folder": b["folder"], "start": opts.start, "seconds": opts.seconds, "model": opts.model}
        if wav:
            s = time.time()
            for attempt in range(3):
                try:
                    r = transcribe(opts.server, wav, opts.model)
                    break
                except Exception as e:
                    r, err = None, f"transcribe failed: {e}"
                    time.sleep(30 * (attempt + 1))
            os.remove(wav)
            if r and r.get("success"):
                row.update(text=r.get("text", "").strip(), took=round(time.time() - s, 1),
                           segments=[[round(x["start"], 1), round(x["end"], 1), x["text"].strip()] for x in r.get("segments", [])])
                err = ""
            elif r:
                err = f"server: {str(r)[:300]}"
        if err:
            row["error"] = err
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
        n += 1
        if n % 50 == 0:
            rate = (time.time() - t0) / n
            print(f"{n}/{len(todo)}  {rate:.1f}s per book, about {rate * (len(todo) - n) / 3600:.1f} h left", flush=True)
    print(f"done: {n} books in {(time.time() - t0) / 3600:.2f} h", flush=True)


if __name__ == "__main__":
    main()
