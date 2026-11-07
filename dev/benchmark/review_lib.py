"""A review library for the books with no confirmed match, and reading back what you confirm.

build: copies each unconfirmed book's mock file (bo_mock.py, without --itunes) into a
writable library and gives it the backup a real library book has: libraforge.json with
its original tags and real duration, written by the fixer's own
write_original_metadata_backup. A Metadata Forge dry run there matches from that original
state, the same as on the real library, and its report can be reviewed and applied in a
throwaway LibraForge.

confirm: reads that library back with collect.py (an applied match is a confirmed ASIN,
as in the real library) and writes the dataset with those books' answers filled in.

Runs in a LibraForge image with this checkout's app/ and scripts/ mounted at /app:
  review_lib.py build <books.json> <mock_root> <review_root>
  review_lib.py confirm <books.json> <review_root> <out.json>
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).parent))
from collect import collect  # noqa: E402


def build(books_path, mock_root, review_root):
    spec = importlib.util.spec_from_file_location("fixer", "/app/scripts/audible-metadata-fixer-v5.py")
    fixer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixer)
    done = missing = 0
    for book in json.load(open(books_path)):
        if book["asin"]:
            continue
        stem, ext = Path(book["file"]).stem, Path(book["file"]).suffix.lower()
        name = stem + (".mp3" if ext == ".mp3" else ".m4b")  # the names bo_mock.py gives
        src, dst = Path(mock_root, book["folder"], name), Path(review_root, book["folder"], name)
        if not src.exists():
            missing += 1
            print("no mock file:", src)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copyfile(src, dst)
        fixer.write_original_metadata_backup(dst, tags=book["tags"], duration_minutes=book["minutes"], alone=True)
        done += 1
    print(f"{review_root}: {done} books, {missing} without a mock file")


def confirm(books_path, review_root, out_path):
    confirmed = {b["folder"]: b for b in collect(review_root) if b["asin"]}
    books = json.load(open(books_path))
    for book in books:
        c = confirmed.get(book["folder"])
        if c and not book["asin"]:
            book.update(asin=c["asin"], manual=c["manual"], final=c["final"])
    json.dump(books, open(out_path, "w"), ensure_ascii=False)
    print(f"{out_path}: {len(confirmed)} confirmed in review, {sum(1 for b in books if b['asin'])} of {len(books)} with an answer")


if __name__ == "__main__":
    {"build": build, "confirm": confirm}[sys.argv[1]](*sys.argv[2:])
