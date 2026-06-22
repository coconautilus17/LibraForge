# Third Party Notices

LibraForge is licensed under AGPL-3.0-or-later. This reflects the licenses
of its direct dependencies: `audible` (AGPL-3.0-only) and `mutagen`
(GPL-2.0-or-later). AGPL-3.0 is compatible with GPL-2.0-or-later via the
"or later" clause. Because LibraForge is fully open-source, the AGPL network-
service provision is automatically satisfied.

The following third-party Python dependencies are included in the runtime
image and test workflow.

## Direct Dependencies

| Package | Version | License | Notes |
|---|---:|---|---|
| `fastapi` | `0.115.6` | MIT | Web framework |
| `uvicorn` | `0.34.0` | BSD-3-Clause | ASGI server |
| `audible` | `0.10.0` | AGPL-3.0-only | Audible API client |
| `mutagen` | `1.47.0` | GPL-2.0-or-later | Audio metadata library |

## Runtime Dependencies Installed With The Image

The container image also installs the dependencies pulled in by the packages
above. The most relevant ones are:

| Package | Version | License | Notes |
|---|---:|---|---|
| `starlette` | `0.41.3` | BSD-3-Clause | FastAPI core dependency |
| `python-dotenv` | `1.2.2` | BSD-3-Clause | Uvicorn extra dependency |
| `watchfiles` | `1.2.0` | MIT | Uvicorn extra dependency |
| `uvloop` | `0.22.1` | MIT License | Uvicorn extra dependency |
| `h11` | `0.16.0` | MIT | Uvicorn extra dependency |
| `click` | `8.4.1` | BSD-3-Clause | Uvicorn extra dependency |

## Notes

- License data above is taken from the installed package metadata used by this
  repository's container image.
- Some transitive packages do not declare a license string in their core
  metadata even though they are open source. When that happens, the package's
  published project documentation remains the source of truth for its license.
