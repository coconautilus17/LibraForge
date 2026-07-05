# Reporting an issue

The single most useful thing you can attach to a bug report is the run's **JSON
report**, and, for anything matching/scoring related, a **debug trace log**. Both are
generated automatically - you just have to turn one of them on before you reproduce
the problem.

## 1. Turn on debug trace (for matching, scoring, or organizer-planning bugs)

Go to **Settings → Developer → Enable debug trace on runs**. Leave the log file path as
the suggested `/reports/debug-trace.log`, or set your own path under `/reports/` - that
folder is bind-mounted to your host, so the file lands in `reports/` next to your
clone (or the `libraforge-reports` volume for the published image).

Skip this step for problems that aren't about a match, score, or planned move (e.g. a
UI glitch, a crash on startup, a download failure) - the debug trace only instruments
matching/scoring/organizer decisions.

## 2. Reproduce the problem

Run the same operation again (Metadata Forge, Folder Forge, M4B Tool, or Library
Downloader) with debug trace still enabled.

## 3. Grab the report and log

After the run finishes, use the **Download JSON report** and **Download output log**
links shown on the page. If you enabled debug trace, also grab the trace file from
`reports/debug-trace.log` (or the path you chose).

## 4. Redact, then attach

Before posting anything publicly:

- Replace real paths with placeholders (`/audiobooks/...` → `[Book Title]/[File]`)
- Remove Audible account IDs, auth file contents, and any activation/voucher data
- Remove hostnames and local usernames

Then open a [GitHub issue](https://github.com/coconautilus17/LibraForge/issues) with
whichever template fits best (Bug report, Metadata mismatch, Organizer issue, M4B
conversion issue, or Feature request), and attach the redacted report/log as files
rather than pasting huge blocks of text inline.

That's the whole process - no need to summarize the report by hand, the raw JSON is
more useful than a paraphrase.
