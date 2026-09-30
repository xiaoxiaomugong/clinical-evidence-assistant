"""Local development helpers; this module never imports application settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import MutableMapping


def prepare_offline_environment(environment: MutableMapping[str, str], root: Path) -> None:
    """Keep OS runtime essentials, discard inherited provider/configuration values."""
    keep = {"PATH", "HOME", "USER", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
            "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "VIRTUAL_ENV",
            "CLINICAL_REQUIRE_MCP"}
    retained = {key: value for key, value in environment.items() if key in keep}
    environment.clear()
    environment.update(retained)
    environment.update({
        "EVIDENCE_ASSISTANT_ENV_FILE": os.devnull,
        "CLINICAL_EVIDENCE_ROOT": str(root),
        "EVIDENCE_ASSISTANT_DATA_DIR": str(root / "data"),
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
        "ENABLE_LIVE_APIS": "false", "ENABLE_SUPABASE": "false",
        "LLM_API_KEY": "", "PUBMED_API_KEY": "", "NCBI_EMAIL": "",
        "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": "", "SUPABASE_SECRET_KEY": "",
        "RETRIEVAL_BACKEND": "legacy", "RERANK_BACKEND": "deterministic",
        "MODEL_LOCAL_FILES_ONLY": "true", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    })


def install_loopback_only_guard() -> None:
    """Block outbound Python sockets/DNS except loopback and Unix sockets.

    This process-local audit hook is an extra verification guard, not an OS
    firewall. It is intentionally not inherited by separately spawned programs.
    """
    allowed = {"localhost", "127.0.0.1", "::1"}

    def guard(event, args):
        host = None
        if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
            address = args[1] if event == "socket.connect" else args[-1]
            if isinstance(address, tuple):
                host = address[0]
        elif event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            host = args[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        if host is not None and host not in allowed:
            raise PermissionError("Local offline mode blocks external network access")

    sys.addaudithook(guard)
