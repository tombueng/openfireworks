#!/bin/bash
# Publish the GitHub Pages site of github.com/tombueng/openfireworks (branch gh-pages):
#   /         the enclosure + board 3D viewer (enclosure/viewer: index.html + GLBs)
#   /studio/  OpenFireworks Studio (web/studio/index.html)
# Run after enclosure/viewer/make_assets.py. Builds in build/pages, force-pushes an orphan gh-pages commit.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
SITE="$ROOT/build/pages"
rm -rf "$SITE"
mkdir -p "$SITE/studio"
cp enclosure/viewer/index.html enclosure/viewer/*.glb "$SITE/"
cp web/studio/index.html "$SITE/studio/"
touch "$SITE/.nojekyll"
cd "$SITE"
git init -q -b gh-pages
git add -A
git -c user.name="$(git -C "$ROOT" config user.name)" -c user.email="$(git -C "$ROOT" config user.email)" \
    commit -q -m "Pages: enclosure viewer + OpenFireworks Studio ($(git -C "$ROOT" rev-parse --short HEAD))"
git push -q -f "$(git -C "$ROOT" remote get-url origin)" gh-pages
echo "pushed gh-pages: $(ls | tr '\n' ' ')"
