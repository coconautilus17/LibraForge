#!/bin/sh
# Checks that this image's m4b-tool imports a cue sheet's chapters when it
# merges a single file (#541): m4b-tool 0.5.2 drops them silently unless
# scripts/patch-m4b-tool-cuesheet.php was applied. Run inside the image:
#   docker run --rm --entrypoint sh <image> /app/tools/check-m4b-cuesheet.sh
# Paths must be absolute: m4b-tool looks for cuesheet.cue next to the input
# file, and a relative input makes it look in "/".
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
ffmpeg -v error -f lavfi -i sine=frequency=440:duration=60 -c:a aac -b:a 64k "$work/book.m4a"
# The format LibraForge's write_chapter_cue() produces.
cat > "$work/cuesheet.cue" <<'CUE'
FILE "book.m4a" MP3
TRACK 01 AUDIO
  TITLE "One"
  INDEX 01 00:00:000
TRACK 02 AUDIO
  TITLE "Two"
  INDEX 01 00:20:000
TRACK 03 AUDIO
  TITLE "Three"
  INDEX 01 00:40:000
CUE
m4b-tool merge "$work/book.m4a" --output-file="$work/out.m4b" \
    --audio-codec=libfdk_aac --audio-bitrate=64k --audio-samplerate=44100 -n > "$work/merge.log" 2>&1 \
    || { cat "$work/merge.log"; exit 1; }
chapters=$(ffprobe -v error -show_chapters -of csv "$work/out.m4b" | wc -l)
if [ "$chapters" -ne 3 ]; then
    echo "m4b-tool merge gave $chapters chapter(s) from a 3-track cue sheet, expected 3" >&2
    exit 1
fi
echo "m4b-tool cue sheet import ok (3 chapters)"
