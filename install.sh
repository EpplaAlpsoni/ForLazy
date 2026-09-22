#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
install_root="$data_home/forlazy"
bin_dir="$HOME/.local/bin"
applications_dir="$data_home/applications"

mkdir -p "$install_root" "$bin_dir" "$applications_dir"
for file in main.py clicker.py portal.py requirements.txt run.sh; do
    install -m 0644 "$source_dir/$file" "$install_root/$file"
done
chmod 0755 "$install_root/run.sh"
ln -sfn "$install_root/run.sh" "$bin_dir/forlazy"

cat > "$applications_dir/forlazy.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ForLazy
Comment=Simple Linux autoclicker
Exec="$install_root/run.sh"
Icon=input-mouse
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod 0644 "$applications_dir/forlazy.desktop"

"$install_root/run.sh" --install-only

echo
echo "ForLazy was installed for this user."
echo "Launch it from the application menu or run: $bin_dir/forlazy"
