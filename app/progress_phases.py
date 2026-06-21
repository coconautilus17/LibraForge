from __future__ import annotations


Phase = tuple[str, str, str]


def fixer_phase_for_line(line: str, current_file: str = "") -> Phase | None:
    stripped = line.strip()
    if stripped.startswith("Scanning library folder"):
        detail = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
        return ("scanning", "Scanning library folder", detail)
    if stripped.startswith("Reading chapter data"):
        return ("probing", "Reading chapter data from library", current_file)
    if stripped.startswith("Analyzing multi-part audiobooks"):
        return ("grouping", "Grouping multi-part audiobooks", "")
    if stripped.startswith("Checking the library for existing ASINs"):
        return ("dedup-check", "Checking for duplicate ASINs", "")
    if stripped.startswith("Trying query:"):
        return (
            "searching",
            "Searching Audible",
            stripped.removeprefix("Trying query:").strip(),
        )
    if stripped.startswith("Results:"):
        return ("scoring", "Scoring candidates", stripped)
    if stripped.startswith("Candidate:"):
        return ("evaluating", "Evaluating best match", stripped)
    if stripped == "Reusing cached match for shared search context":
        return ("cached-match", "Using cached match", current_file)
    if stripped.startswith(("Mutagen MP4 write:", "Metadata backup:", "Cover embedded:")):
        return ("writing", "Writing metadata", current_file)
    if stripped.startswith("APPLIED ("):
        return ("recording", "Recording result", current_file)
    if stripped in {
        "Summary:",
        "Restore summary:",
        "Mode breakdown:",
        "Duration breakdown:",
        "File type breakdown:",
    } or stripped.startswith(("DURATION REVIEW REPORT", "ASIN VERIFICATION REPORT")):
        return ("summarizing", "Calculating summary", stripped.rstrip(":"))
    return None


def organizer_progress_phase(indexing: bool, refreshing: bool = False) -> Phase:
    if indexing:
        return (
            "caching",
            "Refreshing structure cache" if refreshing else "Caching library structures",
            "",
        )
    return ("analyzing", "Analyzing library items", "")


def organizer_move_phase(apply_mode: bool, move_number: int) -> Phase:
    return (
        "moving" if apply_mode else "building-preview",
        "Moving books" if apply_mode else "Building move preview",
        f"Move {move_number}",
    )


def m4b_phase_for_line(line: str) -> Phase | None:
    if line.startswith("found ") and " files to convert" in line:
        return ("preparing", "Preparing audio", line)
    if line.startswith("running silence detection"):
        return ("detecting-chapters", "Detecting chapters", "Analyzing silence markers")
    if line == "silence detection finished":
        return ("tagging", "Writing chapters and tags", line)
    if line.startswith("tagged file "):
        return ("writing-output", "Writing final output", line)
    if line.startswith("successfully merged "):
        return ("complete", "Complete", line)
    return None


def terminal_phase(status: str, error: str = "") -> Phase:
    if status == "completed":
        return ("complete", "Complete", "Run finished successfully")
    if status == "cancelled":
        return ("cancelled", "Cancelled", "Run was cancelled")
    return ("failed", "Failed", error or "Run stopped with an error")
