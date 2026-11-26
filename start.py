"""Start the web playground, or the original notebook with --notebook."""

from getpass import getpass
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit
import os
import subprocess
import sys

from i18n import t


HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / "bin" / "python"
PYTHON = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)  # the Docker image has no .venv
NOTEBOOK = HERE / "playground.ipynb"


def valid_gateway(value: str) -> tuple[bool, str]:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        tailnet = ip_address(host) in ip_network("100.64.0.0/10")
        port = parsed.port
    except ValueError:
        return False, ""
    valid = (
        tailnet
        and parsed.scheme == "http"
        and port == 8317
        and parsed.path.rstrip("/") == "/v1"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    return valid, host


def main() -> int:
    if not NOTEBOOK.is_file():
        raise SystemExit(t("Playground notebook not found.", "Playground notebook'u bulunamadı."))

    gateway = input(t("CLIProxyAPI Tailscale address (http://...:8317/v1/): ", "CLIProxyAPI Tailscale adresi (http://...:8317/v1/): ")).strip()
    valid, host = valid_gateway(gateway)
    if not valid:
        raise SystemExit(t("The address must be :8317/v1 on a Tailscale IP.", "Adres bir Tailscale IP'sinde :8317/v1 olmalı."))

    model = input("Model [gpt-6-luna]: ").strip() or "gpt-6-luna"
    client_key = getpass(t("CLIProxyAPI client key (hidden): ", "CLIProxyAPI istemci anahtarı (ekranda görünmez): ")).strip()
    if not client_key:
        raise SystemExit(t("The client key cannot be empty.", "İstemci anahtarı boş olamaz."))

    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = gateway
    env["OPENAI_API_KEY"] = client_key
    env["TINY_TROUPE_MODEL"] = model
    env["NO_PROXY"] = ",".join(filter(None, (env.get("NO_PROXY", ""), host)))
    env["PATH"] = f"{PYTHON.parent}{os.pathsep}{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = str(PYTHON.parent.parent)
    print(t("Opening JupyterLab. The key was not written to a file; press Ctrl+C to quit.",
            "JupyterLab açılıyor. Anahtar dosyaya yazılmadı; çıkmak için Ctrl+C."))
    return subprocess.call(
        [str(PYTHON), "-m", "jupyterlab", str(NOTEBOOK), "--ServerApp.ip=127.0.0.1"],
        cwd=HERE,
        env=env,
    )


if __name__ == "__main__":
    if Path(sys.executable).resolve() != PYTHON.resolve():
        os.execv(str(PYTHON), [str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    if "--notebook" in sys.argv:
        raise SystemExit(main())
    from web_app import main as web_main

    web_main()
