"""Start the Docker playground with a client key from macOS Keychain."""

import getpass
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


SERVICE = "tinytroupe-playground-cliproxyapi-client"
ACCOUNT = getpass.getuser()
APP_URL = "http://127.0.0.1:8765"
HERE = Path(__file__).resolve().parent


def save_key():
    # With -w last, macOS prompts for the secret; it never appears in argv.
    subprocess.run(["security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE,
                    "-l", "TinyTroupe CLIProxyAPI istemci anahtarı", "-U", "-w"], check=True)


def load_key():
    result = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT,
                             "-s", SERVICE, "-w"], check=True, capture_output=True, text=True)
    key = result.stdout.rstrip("\r\n")
    if not key:
        raise RuntimeError("Anahtar Zinciri'nde istemci anahtarı boş.")
    return key


def inject_key(key, opener=None):
    opener = opener or build_opener(ProxyHandler({})).open
    with opener(Request(APP_URL + "/"), timeout=5) as response:
        page = response.read().decode("utf-8")
    match = re.search(r'<meta name="app-token" content="([^"]+)">', page)
    if not match:
        raise RuntimeError("Uygulama güvenlik anahtarı bulunamadı.")
    body = json.dumps({"api_key": key}).encode("utf-8")
    request = Request(APP_URL + "/api/settings/key", data=body,
                      headers={"Content-Type": "application/json", "X-App-Token": match.group(1)})
    with opener(request, timeout=5) as response:
        result = json.load(response)
    if result != {"key_available": True}:
        raise RuntimeError("Anahtar uygulamaya aktarılmadı.")


def start():
    key = load_key()
    subprocess.run(["docker", "compose", "up", "--build", "-d"], cwd=HERE, check=True)
    for attempt in range(30):
        try:
            inject_key(key)
            print(f"Uygulama hazır: {APP_URL}/")
            return
        except URLError:
            if attempt == 29:
                raise
            time.sleep(1)


def forget():
    subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT,
                    "-s", SERVICE], check=True)


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("Bu yardımcı program yalnız macOS üzerinde çalışır.")
    if len(sys.argv) != 2 or sys.argv[1] not in ("set", "start", "forget"):
        raise SystemExit("Kullanım: python3 mac_keychain.py set|start|forget")
    try:
        {"set": save_key, "start": start, "forget": forget}[sys.argv[1]]()
    except (subprocess.CalledProcessError, URLError, RuntimeError) as exc:
        raise SystemExit(f"Anahtar Zinciri işlemi tamamlanamadı: {exc}") from exc
