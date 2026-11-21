#!/bin/sh
# Download and verify a Foundry client release using system tools.
set -eu

install_foundry() (
  export LC_ALL=C
  umask 077
  repo='kekxv/foundry'
  release_base=
  version=
  signers=
  destination=
  work=
  created=
  trap 'if [ -n "$created" ]; then rm -f "$created/foundry" "$created/foundry-worker"; rmdir "$created"; fi; if [ -n "$work" ]; then rm -rf "$work"; fi' 0
  trap 'exit 1' HUP INT TERM

  die() {
    printf 'Foundry installation failed: %s\n' "$*" >&2
    exit 1
  }

  while [ "$#" -gt 0 ]; do
    option=$1
    case "$option" in
      --help|-h)
        printf '%s\n' 'Usage: install.sh --allowed-signers FILE [--repo OWNER/REPO] [--version X.Y.Z] [--install-dir DIR] [--release-base-url HTTPS_URL]'
        exit 0
        ;;
      --allowed-signers|--repo|--version|--install-dir|--release-base-url)
        [ "$#" -ge 2 ] && [ -n "$2" ] || die "$option requires a value"
        case "$option" in
          --allowed-signers) signers=$2 ;;
          --repo) repo=$2 ;;
          --version) version=$2 ;;
          --install-dir) destination=$2 ;;
          --release-base-url) release_base=$2 ;;
        esac
        shift 2
        ;;
      *) die "unknown option: $option" ;;
    esac
  done

  [ -n "$signers" ] && [ -f "$signers" ] ||
    die 'supply a trusted public key file with --allowed-signers'
  for command in curl ssh-keygen unzip; do
    command -v "$command" >/dev/null 2>&1 || die "$command is required"
  done
  case "$(uname -s):$(uname -m)" in
    Linux:x86_64) platform=linux-x64; hash=sha256sum ;;
    Linux:aarch64|Linux:arm64) platform=linux-arm64; hash=sha256sum ;;
    Darwin:arm64) platform=macos-arm64; hash=shasum ;;
    *) die 'unsupported operating system or architecture' ;;
  esac
  command -v "$hash" >/dev/null 2>&1 || die "$hash is required"

  stable_version() {
    case "$1" in *[!0-9.]*) return 1 ;; esac
    printf '%s\n' "$1" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
  }

  if [ -z "$release_base" ]; then
    case "$repo" in *[!A-Za-z0-9_./-]*) die 'invalid GitHub repository' ;; esac
    printf '%s\n' "$repo" | grep -Eq '^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$' ||
      die 'provide the GitHub repository with --repo OWNER/REPO'
    case "$repo" in */.|*/..) die 'invalid GitHub repository' ;; esac
    release_base=https://github.com/$repo/releases
  fi
  release_base=${release_base%/}
  case "$release_base" in
    *\?*|*\#*|*@*) die 'invalid release base URL' ;;
    https://?*) ;;
    *) die 'release downloads require HTTPS' ;;
  esac

  endpoint=$release_base/latest/download
  if [ -n "$version" ]; then
    stable_version "$version" || die 'expected version x.y.z'
    endpoint=$release_base/download/v$version
  fi
  work=$(mktemp -d "${TMPDIR:-/tmp}/foundry-install.XXXXXXXX")

  fetch() {
    url=$1
    output=$2
    limit=$3
    set --
    if [ -n "${FOUNDRY_CA_CERT:-}" ]; then
      set -- --cacert "$FOUNDRY_CA_CERT"
    fi
    curl -q -fsSL --proto '=https' --proto-redir '=https' --globoff \
      --connect-timeout 15 --max-time 180 --max-filesize "$limit" \
      "$@" --output "$output" -- "$url"
    [ "$(wc -c < "$output")" -le "$limit" ] || die 'download exceeds size limit'
  }

  manifest=$work/install-manifest.txt
  signature=$work/install-manifest.txt.sig
  case "$signers" in /*) ;; *) signers=$PWD/$signers ;; esac
  cp "$signers" "$work/allowed_signers"
  now=$(date +%s)
  expiry=$(awk -v now="$now" '
    NR == 1 && NF == 4 && $1 == "#" && $2 == "foundry-install-v1" &&
      $3 == "expires-at" && $4 ~ /^[0-9]+$/ && $4 > now { print $4 }
  ' "$work/allowed_signers")
  [ -n "$expiry" ] || die 'invalid or expired allowed-signers file'
  fetch "$endpoint/install-manifest.txt" "$manifest" 16384
  fetch "$endpoint/install-manifest.txt.sig" "$signature" 16384
  ssh-keygen -Y verify -I foundry-release -n foundry-install-v1 \
    -f "$work/allowed_signers" -s "$signature" < "$manifest" >/dev/null ||
    die 'release signature verification failed'

  # Parse only authenticated text. Require one matching platform record.
  record=$(awk -v platform="$platform" -v requested="$version" -v now="$now" -v expiry="$expiry" '
    NR == 1 {
      if (NF != 3 || $1 != "foundry-install-v1" ||
          $2 !~ /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/ ||
          $3 !~ /^[0-9]+$/ || $3 <= now || $3 > expiry ||
          (requested != "" && $2 != requested))
        exit 1
      release = $2
      name = "foundry-" release "-" platform ".zip"
    }
    NR > 1 && $3 == name {
      if (NF != 3 || length($1) != 64 || $1 !~ /^[0-9a-f]+$/ ||
          $2 !~ /^[1-9][0-9]*$/ || $2 > 134217728)
        exit 1
      count++
      size = $2
      digest = $1
    }
    END {
      if (count != 1) exit 1
      print release, size, digest, name
    }
  ' "$manifest") || die 'invalid, expired, or mismatched installation manifest'
  IFS=' ' read -r release size expected name <<EOF_RECORD
$record
EOF_RECORD
  archive=$work/$name
  fetch "$release_base/download/v$release/$name" "$archive" "$size"
  [ "$(wc -c < "$archive")" -eq "$size" ] || die 'ZIP size mismatch'
  if [ "$hash" = shasum ]; then
    actual=$(shasum -a 256 < "$archive")
  else
    actual=$(sha256sum < "$archive")
  fi
  [ "${actual%% *}" = "$expected" ] || die 'ZIP SHA-256 mismatch'

  entries=$(unzip -Z -l "$archive")
  for name in foundry foundry-worker; do
    printf '%s\n' "$entries" | awk -v name="$name" '
      NF >= 10 && $NF == name {
        count++
        if ($1 !~ /^-/ || $4 !~ /^[0-9]+$/ || $4 < 1 || $4 > 134217728) exit 1
      }
      END { if (count != 1) exit 1 }
    ' || die "invalid ZIP entry: $name"
    unzip -p "$archive" "$name" > "$work/$name"
    [ -s "$work/$name" ] || die "ZIP entry is empty: $name"
  done

  if [ -z "$destination" ]; then
    destination=${XDG_DATA_HOME:-$HOME/.local/share}/foundry/clients/$release
  fi
  case "$destination" in /*) ;; *) destination=$PWD/$destination ;; esac
  mkdir -p "$(dirname "$destination")"
  [ ! -e "$destination" ] && [ ! -L "$destination" ] ||
    die "install directory already exists: $destination"
  mkdir "$destination" || die "cannot create install directory: $destination"
  created=$destination
  for name in foundry foundry-worker; do
    cp "$work/$name" "$destination/$name"
    chmod 755 "$destination/$name"
  done
  created=
  printf 'Installed Foundry %s in %s\n' "$release" "$destination"
)

install_foundry "$@"
