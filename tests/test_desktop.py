from __future__ import annotations

from pathlib import Path

from evidence_assistant import desktop


def test_find_web_app_from_source() -> None:
    assert desktop.find_web_app() == Path(__file__).parents[1] / "app.py"


def test_user_paths_are_platform_specific(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    mac_cache, mac_config = desktop._user_paths("darwin")
    linux_cache, linux_config = desktop._user_paths("linux")

    assert mac_cache == tmp_path / "Library" / "Caches" / desktop.APP_NAME
    assert mac_config.name == ".env"
    assert linux_cache == tmp_path / ".cache" / desktop.PACKAGE_SLUG
    assert linux_config == tmp_path / ".config" / desktop.PACKAGE_SLUG / ".env"


def test_find_available_port_falls_back_when_preferred_is_busy(monkeypatch) -> None:
    attempts = []

    def fake_bind(port: int) -> int:
        attempts.append(port)
        if port == 8501:
            raise OSError("busy")
        return 49152

    monkeypatch.setattr(desktop, "_bind_available_port", fake_bind)

    assert desktop.find_available_port(8501) == 49152
    assert attempts == [8501, 0]


def test_offline_check_uses_bundled_corpus(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVIDENCE_ASSISTANT_CACHE_DIR", str(tmp_path / "cache"))
    desktop.offline_check()


def test_configure_runtime_honors_explicit_writable_paths(
    monkeypatch, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    env_file = tmp_path / "config" / ".env"
    monkeypatch.setenv("EVIDENCE_ASSISTANT_CACHE_DIR", str(cache))
    monkeypatch.setenv("EVIDENCE_ASSISTANT_ENV_FILE", str(env_file))

    desktop.configure_runtime()

    assert cache.is_dir()
    assert env_file.parent.is_dir()
