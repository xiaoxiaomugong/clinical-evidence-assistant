#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.1.0}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_root="${repo_root}/build/linux-package"
release_dir="${repo_root}/release"

rm -rf "${package_root}"
mkdir -p \
  "${package_root}/DEBIAN" \
  "${package_root}/opt/clinical-evidence-assistant" \
  "${package_root}/usr/bin" \
  "${package_root}/usr/share/applications" \
  "${package_root}/usr/share/icons/hicolor/scalable/apps" \
  "${release_dir}"

cp -R "${repo_root}/dist/ClinicalEvidenceAssistant/." \
  "${package_root}/opt/clinical-evidence-assistant/"
cp "${repo_root}/packaging/assets/clinical-evidence-assistant.svg" \
  "${package_root}/usr/share/icons/hicolor/scalable/apps/clinical-evidence-assistant.svg"

install -m 0755 /dev/stdin "${package_root}/usr/bin/clinical-evidence-assistant" <<'EOF'
#!/usr/bin/env sh
exec /opt/clinical-evidence-assistant/ClinicalEvidenceAssistant "$@"
EOF

cat > "${package_root}/DEBIAN/control" <<EOF
Package: clinical-evidence-assistant
Version: ${version}
Section: science
Priority: optional
Architecture: amd64
Maintainer: Clinical Evidence Assistant contributors
Description: Offline-first, citation-grounded clinical evidence assistant
 A local Streamlit application for clinical education and research.
EOF

cat > "${package_root}/usr/share/applications/clinical-evidence-assistant.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Clinical Evidence Assistant
Name[zh_CN]=循证知问
Comment=Offline-first clinical evidence assistant
Exec=clinical-evidence-assistant
Icon=clinical-evidence-assistant
Terminal=false
Categories=Education;Science;MedicalSoftware;
EOF

dpkg-deb --build --root-owner-group "${package_root}" \
  "${release_dir}/clinical-evidence-assistant_${version}_amd64.deb"
