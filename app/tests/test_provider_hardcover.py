"""Hardcover provider verification (abs-agg provider-verification workstream).

**Not reachable at all, 2026-07-20 -- confirmed a configuration gap, not a
LibraForge bug.** Hardcover is a Goodreads-alternative book cataloging/social
site, not itself an audiobook source -- it isn't clear yet whether its data
would even fit this pipeline's shape (no confirmed audiobook-specific fields
like narrator/duration until it's actually reachable).

Checked directly against the live abs-agg container's own startup log:

    Provider Hardcover (hardcover) disabled: missing env vars: HARDCOVER_TOKEN
    Skipping disabled provider: Hardcover (hardcover)

And confirmed live: querying it directly returns a 404, not empty results or
a validation error -- the provider genuinely does not exist in this instance
at all while the token is unset:

    docker exec abs-agg node -e "fetch('http://localhost:3000/hardcover/search?title=Dune')..."
    -> 404 {"error":"Provider not found: hardcover"}

Also absent from the live /providers listing entirely (unlike Storytel/
Audioteka/BookBeat, which appear in /providers with their full schema even
though their search endpoint has a separate bug -- Hardcover isn't listed at
all while disabled). Goodreads is disabled the same way here too (missing
GOODREADS_API_KEY), but Goodreads-via-abs-tract already ships separately and
is out of scope for this workstream.

**Also found, not previously tracked**: a tenth abs-agg provider, "Thalia"
(a German bookstore chain), is also present but disabled
("Skipping disabled provider: Thalia (thalia)") -- flagged in
libraforge-roadmap-backlog.md as a new discovery, not yet investigated.

**Next step, not something this pass can do**: obtain a real Hardcover API
token from hardcover.app, add HARDCOVER_TOKEN to the abs-agg container's
environment, restart it, confirm "hardcover" then appears in the live
/providers response with a real returnedFields schema, and only then run
the same live-fetch + standardization + full-pipeline checklist used for
every other provider in this workstream.
"""
import unittest
from unittest.mock import patch


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        import json
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HardcoverNotConfiguredTests(unittest.TestCase):
    def test_unconfigured_provider_surfaces_as_a_clear_502_not_a_silent_empty_result(self):
        # Documents today's real, confirmed behavior: querying a provider
        # abs-agg doesn't currently expose (Hardcover, while HARDCOVER_TOKEN
        # is unset) surfaces as an HTTPException, not a silently-empty
        # {"matches": []} that could be mistaken for "no results found".
        from fastapi import HTTPException

        from app.main import search_abs_agg_candidates
        import urllib.error as _urlerror

        def _raise_404(req, timeout=15):
            raise _urlerror.HTTPError(req.full_url, 404, "Not Found", {}, None)

        with patch("urllib.request.urlopen", _raise_404):
            with self.assertRaises(HTTPException) as ctx:
                search_abs_agg_candidates(
                    query="Dune", base_url="http://abs-agg:3000", provider="hardcover",
                )
        self.assertEqual(ctx.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
