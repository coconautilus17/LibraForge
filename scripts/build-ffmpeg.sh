#!/bin/sh
# Builds a static ffmpeg and ffprobe into /opt/ffmpeg/bin, for both images'
# ffmpeg-build stage (Alpine, musl). Static, so the same two files run on the
# Alpine image and the Debian one with no libraries beside them.
#
# The release is the one PyAV's wheels bundle (requirements.txt), so files are
# read and written by the same FFmpeg. The m4b-tool base image's own ffmpeg is
# 5.0.1; it can't open xHE-AAC books.
#
# The codecs match that 5.0.1 build where LibraForge or m4b-tool use them:
# libfdk_aac is M4B building's default encoder, plus LAME, Opus and Vorbis.
# Alpine ships no static fdk-aac or opus, so those two are built here.
set -eu

FFMPEG_VERSION=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
FDK_AAC_VERSION=2.0.3
FDK_AAC_SHA256=e25671cd96b10bad896aa42ab91a695a9e573395262baed4e4a2ff178d6a3a78
OPUS_VERSION=1.5.2
OPUS_SHA256=65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1

apk add --no-cache build-base cmake nasm pkgconf curl xz \
    lame-dev libvorbis-dev libvorbis-static libogg-static

PREFIX=/opt/ffmpeg
JOBS=$(nproc)
cd /tmp

fetch() {  # fetch <url> <file> <sha256>
    curl -sSfL --retry 5 --retry-all-errors "$1" -o "$2"
    echo "$3  $2" | sha256sum -c -
}

fetch "https://github.com/mstorsjo/fdk-aac/archive/refs/tags/v${FDK_AAC_VERSION}.tar.gz" fdk-aac.tar.gz "$FDK_AAC_SHA256"
tar xzf fdk-aac.tar.gz
cmake -S "fdk-aac-${FDK_AAC_VERSION}" -B fdk-build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_PROGRAMS=OFF -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build fdk-build -j "$JOBS" --target install

fetch "https://downloads.xiph.org/releases/opus/opus-${OPUS_VERSION}.tar.gz" opus.tar.gz "$OPUS_SHA256"
tar xzf opus.tar.gz
(cd "opus-${OPUS_VERSION}" && ./configure --prefix=/usr/local --disable-shared --enable-static --disable-doc --disable-extra-programs \
    && make -j "$JOBS" install)

fetch "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" ffmpeg.tar.xz "$FFMPEG_SHA256"
tar xJf ffmpeg.tar.xz
cd "ffmpeg-${FFMPEG_VERSION}"
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig ./configure \
    --prefix="$PREFIX" \
    --pkg-config-flags=--static \
    --extra-ldflags=-static \
    --enable-static --disable-shared \
    --disable-debug --disable-doc --disable-ffplay \
    --enable-gpl --enable-version3 --enable-nonfree \
    --enable-libfdk-aac --enable-libmp3lame --enable-libopus --enable-libvorbis
make -j "$JOBS"
make install
strip "$PREFIX/bin/ffmpeg" "$PREFIX/bin/ffprobe"
"$PREFIX/bin/ffmpeg" -hide_banner -version | head -1
