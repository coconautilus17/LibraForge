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
| `av` (PyAV) | `19.0.2` | BSD-3-Clause; its wheels bundle FFmpeg's libraries (LGPL-3.0-or-later) | Reads audio files in-process |

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

## FFmpeg

Both images carry `ffmpeg` and `ffprobe` 9.0.2, built from FFmpeg's signed
release by `scripts/build-ffmpeg.sh` as static binaries, with Fraunhofer FDK AAC
2.0.3 (`libfdk_aac`, M4B building's default encoder), LAME, Opus 1.5.2 and
Vorbis. FDK AAC is under the Fraunhofer FDK AAC license, which FFmpeg's build
counts as non-free next to its GPL parts; the m4b-tool base image's own ffmpeg,
which these replace, was built the same way. PyAV's wheels bundle their own
FFmpeg 9.0.2 libraries without FDK AAC.

## Ported Code

`app/abs_names.py` is a Python port of Audiobookshelf's author-name parser. The
Folder Forge naming scheme uses it to stay aligned with how Audiobookshelf reads
author folder names: which text it treats as separate authors, and how it splits
a name into first and last parts. The port runs on its own and never calls
Audiobookshelf; `tools/abs_name_fixture.js` regenerates its test data from a
running Audiobookshelf container after an update.

| Source | Files | License |
|---|---|---|
| [Audiobookshelf](https://github.com/advplyr/audiobookshelf) v2.37.2 | `server/utils/parsers/parseNameString.js` | GPL-3.0 (compatible with AGPL-3.0-or-later) |
| [parse-full-name](https://github.com/RateGravity/parse-full-name) 1.2.x, as copied into Audiobookshelf | `server/utils/parsers/parseFullName.js` | MIT |

## Notes

- License data above is taken from the installed package metadata used by this
  repository's container image.
- Some transitive packages do not declare a license string in their core
  metadata even though they are open source. When that happens, the package's
  published project documentation remains the source of truth for its license.
