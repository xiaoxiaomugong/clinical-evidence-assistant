"""Launch the packaged Streamlit UI as a local desktop application."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import sysconfig
from pathlib import Path
from typing import Sequence, Tuple


APP_NAME = "Clinical Evidence Assistant"
PACKAGE_SLUG = "clinical-evidence-assistant"


def _bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[2]


def _installed_root() -> Path:
    return (
        Path(sysconfig.get_path("data"))
        / "share"
        / "clinical-evidence-assistant"
    )


def find_web_app() -> Path:
    """Return the Streamlit script in a source, wheel, or frozen install."""
    configured = os.getenv("CLINICAL_EVIDENCE_ROOT", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser() / "app.py")
    candidates.extend((_bundle_root() / "app.py", _installed_root() / "app.py"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"找不到 Web UI 入口 app.py；已检查：{checked}")


def _user_paths(platform: str | None = None) -> Tuple[Path, Path]:
    """Return writable cache and configuration paths without extra packages."""
    platform = platform or sys.platform
    home = Path.home()
    if platform == "darwin":
        cache = home / "Library" / "Caches" / APP_NAME
        config = home / "Library" / "Application Support" / APP_NAME / ".env"
    elif platform.startswith("win"):
        local = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        cache = local / APP_NAME / "Cache"
        config = roaming / APP_NAME / ".env"
    else:
        cache_home = Path(os.getenv("XDG_CACHE_HOME", home / ".cache"))
        config_home = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        cache = cache_home / PACKAGE_SLUG
        config = config_home / PACKAGE_SLUG / ".env"
    return cache, config


def configure_runtime() -> None:
    """Point bundled resources and runtime writes at safe locations."""
    if getattr(sys, "frozen", False):
        os.environ.setdefault("CLINICAL_EVIDENCE_ROOT", str(_bundle_root()))
    default_cache, default_env_file = _user_paths()
    cache = Path(
        os.getenv("EVIDENCE_ASSISTANT_CACHE_DIR", str(default_cache))
    ).expanduser()
    env_file = Path(
        os.getenv("EVIDENCE_ASSISTANT_ENV_FILE", str(default_env_file))
    ).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("EVIDENCE_ASSISTANT_CACHE_DIR", str(cache))
    os.environ.setdefault("EVIDENCE_ASSISTANT_ENV_FILE", str(env_file))


def _bind_available_port(port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", port))
        return int(candidate.getsockname()[1])


def find_available_port(preferred: int = 8501) -> int:
    """Prefer Streamlit's usual port, falling back to an ephemeral local port."""
    for port in (preferred, 0):
        try:
            selected = _bind_available_port(port)
            if selected:
                return selected
        except OSError:
            if port == 0:
                raise
    raise RuntimeError("无法为本地界面分配端口")


def offline_check() -> None:
    """Validate bundled resources and one offline query without starting a server."""
    app_path = find_web_app()
    if not app_path.is_file():
        raise RuntimeError("Web UI 资源缺失")

    import streamlit

    streamlit_index = Path(streamlit.__file__).resolve().parent / "static" / "index.html"
    if not streamlit_index.is_file():
        raise RuntimeError("Streamlit 前端资源缺失")

    from evidence_assistant.config import settings
    from evidence_assistant.pipeline import EvidencePipeline

    pipeline = EvidencePipeline(settings)
    result = pipeline.run(
        "降压药应早上服用还是睡前服用？",
        mode="knowledge",
        enable_live_apis=False,
    )
    if not result.entries:
        raise RuntimeError("离线检查未检索到内置证据")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动循证知问本地界面")
    parser.add_argument("--port", type=int, default=8501, help="首选本地端口")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动服务但不自动打开浏览器",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查安装资源与离线问答后退出",
    )
    parser.add_argument(
        "--server-check",
        action="store_true",
        help="检查资源、离线问答和本地服务器启动后退出",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    configure_runtime()
    if args.check:
        offline_check()
        print("Clinical Evidence Assistant offline check passed.")
        return
    if args.server_check:
        offline_check()

    from streamlit import config as streamlit_config
    from streamlit.web import bootstrap

    app_path = find_web_app()
    port = find_available_port(args.port)
    options = {
        "server.address": "127.0.0.1",
        "server.port": port,
        "server.headless": args.no_browser or args.server_check,
        "server.fileWatcherType": "none",
        "server.enableCORS": True,
        "server.enableXsrfProtection": True,
        "browser.gatherUsageStats": False,
        "client.toolbarMode": "viewer",
        "global.developmentMode": False,
        "global.showWarningOnDirectExecution": False,
    }
    streamlit_config._main_script_path = str(app_path)
    bootstrap.load_config_options(flag_options=options)
    bootstrap.run(
        str(app_path),
        False,
        [],
        options,
        stop_immediately_for_testing=args.server_check,
    )
    if args.server_check:
        print("Clinical Evidence Assistant server check passed.")


if __name__ == "__main__":
    main()
