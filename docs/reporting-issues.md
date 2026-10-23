# Reporting an issue

1. Enable debug trace: **Settings → Developer → Enable debug trace on runs**.
2. Reproduce the problem.
3. Grab the **JSON report**, **output log**, and debug trace log (download links shown
   after the run). The debug trace goes to the container's output
   (`docker compose logs libraforge`) unless you also set a log file path under
   **Settings → Developer**; use a path under `/app/reports/`, for example
   `/app/reports/debug-trace.log`, so the file survives the container.
4. Attach all of them to a [GitHub issue](https://github.com/coconautilus17/LibraForge/issues).
5. Point out the specific failure point(s) - which book/path, and what's wrong with it -
   so it doesn't have to be found by reading the whole report.
