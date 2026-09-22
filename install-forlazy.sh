#!/usr/bin/env bash
set -euo pipefail

repo="EpplaAlpsoni/ForLazy"
branch="main"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

echo "Downloading ForLazy..."
curl --fail --location --proto '=https' --tlsv1.2   "https://github.com/$repo/archive/refs/heads/$branch.tar.gz"   -o "$tmp_dir/forlazy.tar.gz"

tar -xzf "$tmp_dir/forlazy.tar.gz" -C "$tmp_dir"

echo "Installing ForLazy..."
bash "$tmp_dir/ForLazy-$branch/install.sh"

echo
echo "Done. You can launch ForLazy from your app menu or run:"
echo "  ~/.local/bin/forlazy"
