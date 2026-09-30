import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_runtime_clears_inherited_credentials_without_loading_dotenv():
    from scripts.local_runtime import prepare_offline_environment

    environment = {
        "PATH": "/usr/bin", "HOME": "/tmp/example", "LLM_API_KEY": "synthetic-secret",
        "ENABLE_LIVE_APIS": "true", "ENABLE_SUPABASE": "true",
        "RETRIEVAL_BACKEND": "dense", "EVIDENCE_ASSISTANT_ENV_FILE": "/private/secret.env",
    }
    prepare_offline_environment(environment, ROOT)
    assert environment["PATH"] == "/usr/bin"
    assert environment["LLM_API_KEY"] == ""
    assert environment["ENABLE_LIVE_APIS"] == environment["ENABLE_SUPABASE"] == "false"
    assert environment["EVIDENCE_ASSISTANT_ENV_FILE"] == os.devnull
    assert environment["RETRIEVAL_BACKEND"] == "legacy"
    assert "synthetic-secret" not in repr(environment)


def test_network_guard_blocks_external_connect_and_dns_before_the_network():
    probe = '''
import socket
from scripts.local_runtime import install_loopback_only_guard
install_loopback_only_guard()
blocked = 0
for operation in (
    lambda: socket.getaddrinfo("offline-test.invalid", 443),
    lambda: socket.socket().connect(("203.0.113.1", 443)),
):
    try:
        operation()
    except PermissionError:
        blocked += 1
assert blocked == 2
assert socket.getaddrinfo("127.0.0.1", 8766)
print("PASS")
'''
    completed = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "PASS"
