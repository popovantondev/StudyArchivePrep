#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$ROOT/release-build}"
export PATH="$ROOT/.venv/bin:$PATH"
NATIVE="$ROOT/release-deps/macos-arm64"
FFMPEG_VERSION="8.1.3"
FFMPEG_SHA256="7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3"
LLAMA_COMMIT="7fe450e19305b828c199d602c23a8337aaa1f03b"
DOWNLOADS="$BUILD_ROOT/downloads"
SOURCES="$BUILD_ROOT/sources"
mkdir -p "$DOWNLOADS" "$SOURCES" "$NATIVE/ffmpeg" "$NATIVE/llama"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "Build this release on an Apple Silicon Mac." >&2
  exit 2
fi

FFMPEG_ARCHIVE="$DOWNLOADS/ffmpeg-$FFMPEG_VERSION.tar.xz"
if [[ ! -f "$FFMPEG_ARCHIVE" ]]; then
  curl -fL --retry 3 "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" -o "$FFMPEG_ARCHIVE"
fi
printf '%s  %s\n' "$FFMPEG_SHA256" "$FFMPEG_ARCHIVE" | shasum -a 256 -c -
FFMPEG_SOURCE="$SOURCES/ffmpeg-$FFMPEG_VERSION"
if [[ ! -d "$FFMPEG_SOURCE" ]]; then
  tar -xf "$FFMPEG_ARCHIVE" -C "$SOURCES"
fi
FFMPEG_STAGE="$BUILD_ROOT/install/ffmpeg"
FFMPEG_PREFIX="/usr/local"
mkdir -p "$FFMPEG_STAGE"
(
  cd "$FFMPEG_SOURCE"
  make distclean >/dev/null 2>&1 || true
  export CFLAGS="${CFLAGS:-} -mmacosx-version-min=13.0"
  export LDFLAGS="${LDFLAGS:-} -mmacosx-version-min=13.0"
  ./configure --prefix="$FFMPEG_PREFIX" --disable-debug --disable-doc --disable-ffplay \
    --disable-network --disable-autodetect --disable-gpl --disable-nonfree \
    --enable-ffmpeg --enable-ffprobe --enable-pthreads
  make -j6
  make DESTDIR="$FFMPEG_STAGE" install
)
install -m 755 "$FFMPEG_STAGE$FFMPEG_PREFIX/bin/ffmpeg" "$NATIVE/ffmpeg/ffmpeg"
install -m 755 "$FFMPEG_STAGE$FFMPEG_PREFIX/bin/ffprobe" "$NATIVE/ffmpeg/ffprobe"
install -m 644 "$FFMPEG_SOURCE/COPYING.LGPLv2.1" "$NATIVE/ffmpeg/COPYING.LGPLv2.1"
cp "$FFMPEG_ARCHIVE" "$NATIVE/ffmpeg/ffmpeg-$FFMPEG_VERSION-source.tar.xz"
printf 'URL=https://ffmpeg.org/releases/ffmpeg-%s.tar.xz\nSHA256=%s\nCONFIGURE=--disable-debug --disable-doc --disable-ffplay --disable-network --disable-autodetect --disable-gpl --disable-nonfree --enable-ffmpeg --enable-ffprobe --enable-pthreads\n' \
  "$FFMPEG_VERSION" "$FFMPEG_SHA256" > "$NATIVE/ffmpeg/BUILD-INFO.txt"
"$NATIVE/ffmpeg/ffmpeg" -version | head -3

LLAMA_SOURCE="$SOURCES/llama.cpp"
if [[ ! -d "$LLAMA_SOURCE/.git" ]]; then
  git clone --filter=blob:none --no-checkout https://github.com/ggml-org/llama.cpp.git "$LLAMA_SOURCE"
fi
git -C "$LLAMA_SOURCE" fetch --depth 1 origin "$LLAMA_COMMIT"
git -C "$LLAMA_SOURCE" checkout --detach "$LLAMA_COMMIT"
ACTUAL_COMMIT="$(git -C "$LLAMA_SOURCE" rev-parse HEAD)"
[[ "$ACTUAL_COMMIT" == "$LLAMA_COMMIT" ]]
LLAMA_BUILD="$BUILD_ROOT/llama-build"
cmake -S "$LLAMA_SOURCE" -B "$LLAMA_BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
  -DGGML_METAL=ON -DGGML_NATIVE=OFF -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_COMMON=ON \
  -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_APP=OFF \
  -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_TOOLS_INSTALL=ON
cmake --build "$LLAMA_BUILD" --config Release --target llama-cli --parallel 4
install -m 755 "$LLAMA_BUILD/bin/llama-cli" "$NATIVE/llama/llama-cli"
cp -pP "$LLAMA_BUILD"/bin/*.dylib "$NATIVE/llama/"
for binary in "$NATIVE/llama/llama-cli" "$NATIVE"/llama/*.dylib; do
  [[ -L "$binary" ]] && continue
  RPATH="$(otool -l "$binary" | awk '/cmd LC_RPATH/{getline; getline; print $2; exit}')"
  if [[ -n "$RPATH" && "$RPATH" != "@loader_path" ]]; then
    install_name_tool -delete_rpath "$RPATH" "$binary"
    install_name_tool -add_rpath '@loader_path' "$binary"
  fi
done
install -m 644 "$LLAMA_SOURCE/LICENSE" "$NATIVE/llama/LICENSE"
cp -R "$LLAMA_SOURCE/licenses" "$NATIVE/llama/licenses"
git -C "$LLAMA_SOURCE" archive --format=tar.gz \
  --prefix="llama.cpp-$LLAMA_COMMIT/" "$LLAMA_COMMIT" \
  > "$NATIVE/llama/llama.cpp-$LLAMA_COMMIT-source.tar.gz"
printf 'REPOSITORY=https://github.com/ggml-org/llama.cpp\nCOMMIT=%s\nCMAKE=GGML_METAL=ON GGML_NATIVE=OFF LLAMA_OPENSSL=OFF LLAMA_BUILD_SERVER=ON LLAMA_BUILD_APP=OFF LLAMA_BUILD_UI=OFF LLAMA_USE_PREBUILT_UI=OFF\n' \
  "$LLAMA_COMMIT" > "$NATIVE/llama/BUILD-INFO.txt"
"$NATIVE/llama/llama-cli" --version
if otool -L "$NATIVE/llama/llama-cli" | grep -E '/opt/homebrew|/tmp/|release-build'; then
  echo "llama-cli still depends on a build-host path." >&2
  exit 1
fi
