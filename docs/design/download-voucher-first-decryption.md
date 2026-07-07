# Library Downloader: Voucher-First Decryption

Date: 2026-07-07
Status: Fixed and enforced in code

## The bug

The main account's `activation_bytes` (the account-wide value needed to decrypt legacy AAX/`Adrm`-DRM titles) was `null`, with no evidence it was ever successfully fetched in any saved auth-file snapshot going back over a month. Every live fetch attempt (`auth.get_activation_bytes()`) hit an identical **CloudFront 403 "Request blocked"** page on `www.audible.com` — Audible's legacy activation endpoint, not an account/credential problem. This is the same block already diagnosed 2026-07-03 (see `project_libraforge.md` memory); re-confirmed live on 2026-07-07, unchanged.

Ruled out as workarounds (all tested live, don't retry):
- **AAXC-only request**: the stuck titles have no AAXC asset at all (hard 404).
- **Cookies-based activation flow**: hits the identical CloudFront block on a different URL under the same domain.
- **Reusing a cached `activation_bytes` value from a second, genuinely-owned account**: activation bytes are per-account; the file decrypts but the audio is garbage (`mean_volume: -91dB`, heavy AAC corruption errors) — verified by actually decoding the audio, not just checking the ffmpeg exit code (a wrong key still lets ffmpeg mechanically "succeed" and even report a plausible container duration, since that metadata isn't protected by the key).
- **`inAudible-NG/tables` rainbow-table lookup**: a legitimate, fully-offline community technique (extract a SHA1 checksum from the AAX file via `ffprobe`, look it up against precomputed tables to recover `activation_bytes` — no server contact at all). Cloned and confirmed working end-to-end, but became unnecessary once the actual fix was found (below).

## The actual fix: try the per-book voucher first, always

While preparing the rainbow-table test, downloading one of the stuck titles live and probing it directly (`ffprobe`) revealed the container is `major_brand: aaxc` — a newer format decrypted with a **per-book voucher** (`audible_key`/`audible_iv`), not account-wide `activation_bytes`, even though the API's `licenserequest` response still labels the title `drm_type: "Adrm"`.

Tested directly: `decrypt_voucher_from_licenserequest(auth, lr)` (from the `audible` package, `audible.aescipher`) succeeded for **all 3** of the previously-stuck titles, producing a real, usable key+IV pair for each — confirmed by fully decoding the resulting audio (`-20.7dB` mean volume, natural speech pause patterns, zero AAC decode errors), not just checking ffmpeg's exit code.

**The `drm_type` field is not a reliable signal for which decryption material is actually available.** `run_download_worker()` (`app/main.py`) previously branched directly on it: `Adrm` → always use `activation_bytes` (the blocked path), anything else → voucher. This meant a title genuinely capable of voucher decryption was never even attempted via that path if Audible happened to label it `Adrm`.

Fixed: always attempt `decrypt_voucher_from_licenserequest()` first, **regardless of the declared `drm_type`**. It only fails (raises) for a title that genuinely has no voucher in the license response — in that case, fall back to the existing account-wide `activation_bytes` flow (with its established per-run caching of both success and failure, so a title that genuinely needs `activation_bytes` doesn't re-hammer the blocked endpoint once per book).

```python
try:
    voucher = decrypt_voucher_from_licenserequest(auth, lr)
    decrypt_kwargs = {"key": voucher["key"], "iv": voucher["iv"]}
    enc_path = book_dir / f"{base}.aaxc"
except Exception as v_exc:
    voucher_error = v_exc
    # fall through to the activation_bytes path below
```

This requires zero contact with the blocked endpoint for any title where a voucher exists — voucher decryption is derived entirely locally from already-known device/customer credentials plus the book's own encrypted voucher blob in the license response.

## A second, unrelated risk found while testing: the license-grant threshold

Audible enforces a **separate, account-wide cap** on the number of license grants (`licenserequest` calls) issuable in some period — distinct from the CloudFront block and unrelated to request rate/concurrency. Documented precedent: [mkb79/audible-cli#60](https://github.com/mkb79/audible-cli/issues/60), where a user's `audible download --all --aaxc` against a ~1500-book library hit `403: Customer is above threshold for content license grant count`.

Root cause there (per the maintainer): `--all --aaxc` issued a `licenserequest` for **every item in the entire library, including already-downloaded ones**, just to determine the file codec before checking whether the file already existed. The confirmed fix that shipped was eliminating those redundant calls (skip `licenserequest` when the file already exists) — not pacing/delaying requests. There's no evidence in that thread that spacing out calls prevents this specific error; it reads as a count-based cap, not a burst-rate limiter that recovers with a quiet window (unlike the CloudFront block).

This app's downloader is structurally safer than that pattern already: `req.items` is always the user's explicit checkbox selection (never a blind "whole library" iteration), and the UI already flags already-owned titles before selection. There is no proactive fix needed to match here — this app never had the `--all`-style redundant-call pattern that caused the upstream issue.

As a reactive safety net (matching the existing `activation_bytes_error` caching pattern), `run_download_worker()` now detects a "threshold" 403 (Audible raises this as a generic `audible.exceptions.Unauthorized` for HTTP 403, with the real reason only in the message text — matched via a case-insensitive `"threshold"` substring check) and short-circuits every remaining item in the run immediately, rather than making one wasted `licenserequest` per remaining book against an account already known to be capped for this run:

```python
if license_threshold_error is not None:
    log("  skipping: Audible license-grant threshold was hit earlier this run")
    raise license_threshold_error
```

## Conformance checklist

| Scenario | Behavior |
|---|---|
| Title has a real per-book voucher (regardless of declared `drm_type`) | Used immediately, no `activation_bytes` fetch, no CloudFront contact |
| Title genuinely has no voucher (legacy AAX-only) | Falls back to `activation_bytes`, fetched once per run and cached (success or failure) |
| `activation_bytes` fetch fails (CloudFront block) | Cached; every remaining `activation_bytes`-needing item in the run fails immediately without a live retry |
| Any `licenserequest` call returns a "threshold" 403 | Cached; every remaining item in the run fails immediately without a live retry |

If a future change touches this decryption branch, preserve the "try voucher first, `drm_type` is advisory only" ordering — this is the actual fix, not an incidental detail.

## Concurrency: 3 downloads at a time

`run_download_worker()` processes `LIBRARY_DOWNLOAD_CONCURRENCY = 3` items at once via a `ThreadPoolExecutor`, matching `audible-cli`'s own default (`audible download --jobs 3`). Confirmed live against a real 10-item run (2026-07-07): the voucher-first fix worked for all 8 owned titles, the 2 failures were unrelated ownership errors, and no CloudFront or threshold issues occurred.

Introducing concurrency meant every per-run shared value the serial version relied on had to be made safe for multiple workers touching it at once, guarded by one `bookkeeping_lock` (`threading.RLock`, reentrant because `log()` is called from within other locked blocks):

| Shared state | Why it needs the lock under concurrency |
|---|---|
| `activation_bytes_cache` / `activation_bytes_error` | The whole check-fetch-cache sequence is locked, not just the check — otherwise two workers discovering they both need it at the same moment would both fire a live fetch, reintroducing the exact CloudFront-hammering bug this caching was built to prevent. The second worker blocks on the lock and then sees the first one's cached result or error. |
| `license_threshold_error` | Read and written under the lock so the moment one worker hits the threshold, every other worker's next check sees it and skips its own `licenserequest`. |
| Folder-collision resolution (`keep_both` numbering) | Locked because it reads-then-creates a directory name from the shared `target` folder; without the lock two workers with the same computed folder name (e.g. duplicate titles) could race onto the same `(2)` suffix. |
| `completed` / `failures` lists, `done_count`, `active_titles` | Appends/increments guarded so progress reporting (`state.current`, `state.percent`, `state.current_file`) stays consistent instead of torn between workers. |
| `log()` / `state.lines_tail` / log file writes | Guarded so interleaved log lines from concurrent workers don't corrupt the tail buffer or the on-disk log file. |

The actual network I/O and `ffmpeg` decrypt subprocess for each item run **outside** the lock — only the bookkeeping around them is serialized, so the concurrency gain is real, not illusory.

Regression tests (`app/tests/test_library_download_activation_bytes.py::ConcurrentDownloadTests`) use real `time.sleep` inside mocked I/O to widen the race window rather than relying on fast mocks that could pass by accident: one proves peak in-flight items is >1 and <=3 (concurrency is real and capped), the other proves `activation_bytes` is still fetched exactly once across 6 items racing for it.

## End-of-run report: per-item outcome, not just counts

A large run (10-100 items) used to end with only an aggregate `"N downloaded, M failed"` line plus a raw scrolling log — finding out *which* title failed, *why*, and which decrypt method a given title actually used meant reading the whole log by hand. `state.stats["results"]` now carries one entry per item:

```python
{"asin": ..., "title": ..., "status": "success", "method": "voucher" | "activation_bytes", "path": "..."}
{"asin": ..., "title": ..., "status": "failed", "method": "voucher" | "activation_bytes" | None, "error": "..."}
```

`method` is `None` on a failure only when the item failed before a decrypt method was even chosen (e.g. the `licenserequest` itself was rejected for an ownership reason) — if the method was already decided and a later step (e.g. `ffmpeg` decrypt) failed, the report still shows which method was attempted.

Built from `results_by_idx` (keyed by original list index, not append/completion order) so the list stays in the same order the user selected the items in, even though the 3 concurrent workers finish items out of order. `write_final_report()` already persists the whole `stats` dict verbatim, so this is in the downloadable report JSON for free with no separate plumbing.

The downloader page (`app/static/downloader.html`) renders this as a table (status pill, title, ASIN, method, path or error) once the run reaches a terminal state, and collapses the old raw log into a `<details>` so the table is the primary view for a large run instead of a wall of interleaved per-item log lines.
