#!/bin/sh
set -eu

case "${RENEWED_LINEAGE:-}" in
  /etc/letsencrypt/live/clinicalevidenceassistant.xin)
    /usr/sbin/nginx -t
    /bin/systemctl reload nginx
    ;;
esac
