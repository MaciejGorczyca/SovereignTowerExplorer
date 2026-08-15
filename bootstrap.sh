#!/bin/sh
# /app/bootstrap.sh - idempotent environment provisioning for the Alpine sandbox.
#
# Lives in /app (persistent volume) so it survives container rebuilds.
# Usage:
#   sh bootstrap.sh            install core tools (default)
#   sh bootstrap.sh --dev      also toolchain (build-base), nodejs, sqlite3, vim
#   sh bootstrap.sh --extra    also tmux, strace, gdb, man, ffmpeg, openssl
#   sh bootstrap.sh --full     --dev + --extra
#   sh bootstrap.sh --gdre     extra: download gdre_tools (Godot .res/.godot parsing)
#   sh bootstrap.sh --check    report what is missing; exit 1 if anything is
#   sh bootstrap.sh --debug    set -x
#
# Safe to re-run: exits fast (~0.1s) when everything is already in place.
# Logs actions to /app/ENVIRONMENT_SETUP.log

VERSION="2"
MARKER="/app/.bootstrap.version"
LOG="/app/ENVIRONMENT_SETUP.log"

# entries are "pkg:probebinary" - apk package name vs the binary used to probe presence
CORE_PKGS="bash:bash coreutils:coreutils grep:grep file:file jq:jq zstd:zstd xz:xz binutils:objdump curl:curl zip:zip git:git python3:python3 py3-pip:pip3 nodejs:node npm:npm"
DEV_PKGS="build-base:gcc sqlite3:sqlite3 vim:vim"
EXTRA_PKGS="tmux:tmux strace:strace gdb:gdb man-db:man ffmpeg:ffmpeg openssl:openssl"
PY_PKGS="${PY_PKGS:-zstandard}"

DO_DEV=0; DO_EXTRA=0; DO_GDRE=0; DO_CHECK=0; DO_DEBUG=0

for a in "$@"; do
  case "$a" in
    --dev) DO_DEV=1 ;;
    --extra) DO_EXTRA=1 ;;
    --full) DO_DEV=1; DO_EXTRA=1 ;;
    --gdre) DO_GDRE=1 ;;
    --check) DO_CHECK=1 ;;
    --debug) DO_DEBUG=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown flag: $a (see header or --help)" >&2; exit 2 ;;
  esac
done

[ "$DO_DEBUG" = 1 ] && set -x

log() { printf '%s %s\n' "$(date +%F\ %T 2>/dev/null || date)" "$*" >> "$LOG"; }

missing() {
  miss=""
  for e in "$@"; do
    command -v "${e#*:}" >/dev/null 2>&1 || miss="$miss ${e%%:*}"
  done
  printf '%s' "$miss"
}

packages() {
  p=""
  for e in "$@"; do p="$p ${e%%:*}"; done
  printf '%s' "$p"
}

TOOLS="$CORE_PKGS"
[ "$DO_DEV" = 1 ] && TOOLS="$TOOLS $DEV_PKGS"
[ "$DO_EXTRA" = 1 ] && TOOLS="$TOOLS $EXTRA_PKGS"

if [ "$DO_CHECK" = 1 ]; then
  m=$(missing $TOOLS)
  if [ -n "$m" ]; then
    echo "missing:$m"
    exit 1
  fi
  echo "all present"
  exit 0
fi

if [ "$(id -u)" != 0 ]; then
  echo "must run as root" >&2
  exit 2
fi

m=$(missing $TOOLS)
if [ -z "$m" ] && [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$VERSION" ]; then
  echo "bootstrap v$VERSION: already provisioned"
  exit 0
fi

if [ -n "$m" ]; then
  echo "installing:$m"
  log "apk add:$m"
  apk add --no-cache $(packages $TOOLS) || { echo "apk add failed" >&2; exit 1; }
fi

if ls /usr/lib/python3*/EXTERNALLY-MANAGED >/dev/null 2>&1; then
  echo "removing PEP 668 EXTERNALLY-MANAGED marker"
  rm -f /usr/lib/python3*/EXTERNALLY-MANAGED
  log "removed PEP 668 marker"
fi

echo "pip install:$PY_PKGS"
log "pip install:$PY_PKGS"
python3 -m pip install --quiet --root-user-action=ignore --upgrade $PY_PKGS \
  || echo "pip install warning (check log)"

if [ "$DO_GDRE" = 1 ]; then
  if command -v gdre_tools >/dev/null 2>&1; then
    echo "gdre_tools: already present"
  else
    echo "installing gdre_tools"
    log "installing gdre_tools"
    apk add --no-cache gcompat >/dev/null 2>&1
    rm -rf /opt/gdre /tmp/gdre.zip
    mkdir -p /opt/gdre
    if wget -q https://github.com/bruvzg/gdsdecomp/releases/latest/download/gdre_tools-linux64.zip -O /tmp/gdre.zip \
       && unzip -q -o /tmp/gdre.zip -d /opt/gdre; then
      chmod +x /opt/gdre/gdre_tools /opt/gdre/*/gdre_tools 2>/dev/null
      ln -sf /opt/gdre/gdre_tools /usr/local/bin/gdre_tools \
        || ln -sf /opt/gdre/*/gdre_tools /usr/local/bin/gdre_tools
      echo "gdre_tools: installed"
      log "gdre_tools installed"
    else
      echo "gdre_tools: download failed (check release asset name)" >&2
      log "gdre_tools download FAILED"
    fi
  fi
fi

printf '%s' "$VERSION" > "$MARKER"
echo "bootstrap v$VERSION: done"
log "bootstrap v$VERSION done"