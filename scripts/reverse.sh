#!/usr/bin/env bash
#
# Reproduce the whole reverse-engineering pipeline from nothing.
#
#   scripts/reverse.sh [workdir]
#
# Steps: download the original, unpack, identify, extract resources, convert the
# 90 Delphi forms to text, recover the string literals and string tables, run
# Ghidra analysis + decompilation, and regenerate the device table docs.
#
# Requires: curl, unzip, python3 with pefile, and a JDK (for Ghidra).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

GHIDRA_VERSION="${GHIDRA_VERSION:-12.1.4}"
GHIDRA_DIR="$ROOT/ghidra_${GHIDRA_VERSION}_PUBLIC"
SITE="https://datalyse.dk/datauk"

log() { printf '\n=== %s\n' "$*"; }

# ---------------------------------------------------------------- 1. download
log "1/9 download"
mkdir -p original site/help
if [ ! -f datalyse.zip ]; then
  curl -fsSL --max-time 300 -o datalyse.zip "$SITE/original/datalyse.zip"
fi
ls -la datalyse.zip
unzip -o -q datalyse.zip -d original
echo "unpacked $(ls original | wc -l) files"

# the site is a FrontPage frameset; the useful pages are the device help
for p in hoved venstre indhold appaemne apparate installa omdataly \
         abu93 acculab adp220 anemo aogd bell5080 bioorbit boschvgt brymen \
         cbl cbl2 cecil consort diva dmg ecolog elcanic elmabeha extech fluke \
         Frederiksen genesys hameg81 hamg407 handimpo hitachi; do
  [ -f "site/help/$p.htm" ] || curl -fsSL --max-time 20 -o "site/help/$p.htm" "$SITE/$p.htm" || true
done

# --------------------------------------------------------------- 2. identify
log "2/9 identify"
file original/Datalyse.exe
strings -a original/Datalyse.exe | grep -iE 'borland|delphi' | sort -u | head

# --------------------------------------------------------------- 3. resources
log "3/9 extract PE resources"
"$PY" scripts/extract_resources.py original/Datalyse.exe decompiled/resources

# -------------------------------------------------------------------- 4. DFM
log "4/9 convert Delphi forms to text"
mkdir -p decompiled/dfm
"$PY" - <<'PYEOF'
import glob, os, sys
sys.path.insert(0, 'scripts')
from dfm2text import convert, DfmError
ok = bad = 0
for p in sorted(glob.glob('decompiled/resources/RT_RCDATA__*__0.bin')):
    name = os.path.basename(p)[len('RT_RCDATA__'):-len('__0.bin')]
    if name in ('DVCLAL', 'PACKAGEINFO'):
        continue
    blob = open(p, 'rb').read()
    if not blob.startswith(b'TPF0'):
        continue
    try:
        txt, left = convert(blob)
    except DfmError as exc:
        print('FAIL', name, exc); bad += 1; continue
    if left:
        print('LEFTOVER', name, left); bad += 1; continue
    open(f'decompiled/dfm/{name}.dfm', 'w').write(txt + '\n')
    ok += 1
print(f'forms converted: {ok}  problems: {bad}')
assert bad == 0, 'DFM conversion must consume every byte'
PYEOF

# ----------------------------------------------------------------- 5. strings
log "5/9 recover string literals and string tables"
"$PY" scripts/delphi_strings.py original/Datalyse.exe 3 > decompiled/strings_pascal.txt
"$PY" scripts/delphi_strtable.py original/Datalyse.exe > decompiled/string_tables.txt
"$PY" scripts/make_interest_list.py decompiled/interesting.txt
"$PY" scripts/parse_help.py site/help docs_devices.json

# ------------------------------------------------------------------ 6. Ghidra
log "6/9 Ghidra"
if [ ! -x "$GHIDRA_DIR/support/analyzeHeadless" ]; then
  if [ ! -f ghidra.zip ]; then
    url="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/ghidra_${GHIDRA_VERSION}_PUBLIC.zip"
    echo "downloading $url"
    curl -fL --max-time 900 -o ghidra.zip "$url"
  fi
  rm -rf "$GHIDRA_DIR"
  unzip -q ghidra.zip
fi
if [ ! -f ghidra_proj/Datalyse.rep/project.prp ]; then
  mkdir -p ghidra_proj
  "$GHIDRA_DIR/support/analyzeHeadless" "$ROOT/ghidra_proj" Datalyse \
      -import "$ROOT/original/Datalyse.exe" -analysisTimeoutPerFile 7200
fi

log "7/9 decompile"
"$GHIDRA_DIR/support/analyzeHeadless" "$ROOT/ghidra_proj" Datalyse \
    -process Datalyse.exe -noanalysis -scriptPath "$ROOT/scripts/ghidra" \
    -postScript ExportDecomp.java "$ROOT/decompiled/ghidra" \
    "$ROOT/decompiled/interesting.txt"

# -------------------------------------------------------------------- 8. docs
log "8/9 regenerate the device table docs"
"$PY" scripts/make_device_doc.py docs/DEVICES.md

# -------------------------------------------------------------------- 9. tests
log "9/9 tests"
"$PY" -m pytest tests -q

log "done"
echo "artifacts under decompiled/ and docs/"
