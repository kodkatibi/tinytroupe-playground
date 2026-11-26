"""Local, single-user web front end for TinyTroupe experiments."""

import base64
import binascii
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from ipaddress import ip_address
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import string
import subprocess
import tempfile
from threading import Lock, Thread, Timer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser

from PIL import Image, UnidentifiedImageError

from i18n import lang, set_lang, t
from start import PYTHON, valid_gateway


HERE = Path(__file__).resolve().parent
MAX_BODY = 30 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}
EVENT_PREFIX = "@@TINY_PLAYGROUND@@"
ACTIVE = ("queued", "running", "waiting_login")
LOGIN_TIMEOUT = 15 * 60
VNC_URL = "http://127.0.0.1:6080/vnc.html"  # compose publishes noVNC on the Mac's loopback


def fetch_models(base_url, api_key):
    valid, _ = valid_gateway(base_url)
    if not valid or not api_key.strip():
        raise ValueError(t("A valid Tailscale address and client key are required.", "Geçerli Tailscale adresi ve istemci anahtarı gerekli."))
    request = Request(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"})
    with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
        data = json.load(response)
    models = sorted({entry["id"] for entry in data.get("data", []) if isinstance(entry, dict) and isinstance(entry.get("id"), str)})
    if not models:
        raise ValueError(t("No models found on this connection.", "Bu bağlantıda model bulunamadı."))
    return models


def _required_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(t(f"{label} is required and can be at most {limit} characters.",
                           f"{label} gerekli ve en fazla {limit} karakter olabilir."))
    return value.strip()


def valid_target(value):
    url = _required_text(value, t("Target address", "Hedef adres"), 2000)
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        parsed.port
    except ValueError as exc:
        raise ValueError(t("Target address is invalid.", "Hedef adres geçersiz.")) from exc
    try:
        loopback_ip = ip_address(host).is_loopback
    except ValueError:
        loopback_ip = False
    if loopback_ip:
        raise ValueError(t("Use localhost instead of 127.0.0.1 or ::1.", "127.0.0.1 veya ::1 yerine localhost kullanın."))
    local = host == "localhost" or host.endswith(".localhost")
    if (parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password
            or (parsed.scheme == "http" and not local)):
        raise ValueError(t("The target address must use https://; http:// is accepted only for localhost and *.localhost.",
                           "Hedef adres https:// olmalı; http:// yalnız localhost ve *.localhost için kabul edilir."))
    return url


def validate_run(raw):
    if not isinstance(raw, dict):
        raise ValueError(t("Invalid experiment data.", "Geçersiz deney verisi."))
    base_url = _required_text(raw.get("base_url"), t("CLIProxyAPI address", "CLIProxyAPI adresi"), 200)
    valid, _ = valid_gateway(base_url)
    if not valid:
        raise ValueError(t("The address must be :8317/v1 on a Tailscale IP.", "Adres Tailscale IP'sinde :8317/v1 olmalı."))
    cleaned = {
        "base_url": base_url,
        "api_key": _required_text(raw.get("api_key"), t("Client key", "İstemci anahtarı"), 1000),
        "model": _required_text(raw.get("model"), "Model", 200),
        "scenario": _required_text(raw.get("scenario"), t("Scenario", "Senaryo"), 12000),
        "question": _required_text(raw.get("question"), t("Question", "Soru"), 4000),
    }
    mode = raw.get("mode")
    if mode not in ("interview", "world", "browser"):
        raise ValueError(t("Choose an experiment method.", "Bir deney yöntemi seçin."))
    steps = raw.get("steps", 1)
    if type(steps) is not int or not 1 <= steps <= 6:
        raise ValueError(t("Rounds or steps must be between 1 and 6.", "Grup turu 1 ile 6 arasında olmalı."))
    cleaned.update(mode=mode, steps=steps)
    if mode == "browser":
        cleaned["target_url"] = valid_target(raw.get("target_url"))
        allow_writes = raw.get("allow_writes", False)
        if type(allow_writes) is not bool:
            raise ValueError(t("Invalid write permission setting.", "Yazma izni seçimi geçersiz."))
        cleaned["allow_writes"] = allow_writes
    personas = raw.get("personas")
    if not isinstance(personas, list) or not 1 <= len(personas) <= 8:
        raise ValueError(t("Enter 1 to 8 personas.", "1 ile 8 persona girin."))
    cleaned["personas"] = []
    for item in personas:
        if not isinstance(item, dict):
            raise ValueError(t("Invalid persona.", "Geçersiz persona."))
        cleaned["personas"].append({
            "name": _required_text(item.get("name"), t("Persona name", "Persona adı"), 80),
            "role": _required_text(item.get("role"), t("Persona role", "Persona rolü"), 150),
            "profile": _required_text(item.get("profile"), t("Persona profile", "Persona profili"), 4000),
        })
    names = [p["name"].casefold() for p in cleaned["personas"]]
    if len(set(names)) != len(names):
        raise ValueError(t("Persona names must be different.", "Persona adları farklı olmalı."))
    images = raw.get("images", [])
    if mode == "browser" and images:
        raise ValueError(t("Uploaded images are not used when browsing a site.", "Tarayıcı gezintisinde yüklenen görseller kullanılmaz."))
    if not isinstance(images, list) or len(images) > 4:
        raise ValueError(t("Upload at most four images.", "En fazla dört görsel yükleyin."))
    cleaned["images"] = []
    for item in images:
        if not isinstance(item, dict):
            raise ValueError(t("Invalid image.", "Geçersiz görsel."))
        name = _required_text(item.get("name"), t("Image name", "Görsel adı"), 120)
        data = item.get("data")
        if not isinstance(data, str) or not data.startswith("data:") or ";base64," not in data:
            raise ValueError(t("Invalid image format.", "Görsel biçimi geçersiz."))
        header, encoded = data.split(",", 1)
        mime = header[5:].split(";", 1)[0]
        if mime not in IMAGE_TYPES or len(encoded) > MAX_IMAGE * 2:
            raise ValueError(t("Upload only PNG, JPEG, WebP or GIF images under 5 MB.", "Yalnız 5 MB altı PNG, JPEG, WebP veya GIF yükleyin."))
        try:
            binary = base64.b64decode(encoded, validate=True)
            if len(binary) > MAX_IMAGE:
                raise ValueError(t("The image exceeds the 5 MB limit.", "Görsel 5 MB sınırını aşıyor."))
            with Image.open(BytesIO(binary)) as image:
                if image.format != IMAGE_TYPES[mime]:
                    raise ValueError(t("The image content does not match its file type.", "Görsel içeriği dosya türüyle eşleşmiyor."))
                image.verify()
        except (binascii.Error, UnidentifiedImageError, OSError) as exc:
            raise ValueError(t("Could not read the image.", "Görsel okunamadı.")) from exc
        cleaned["images"].append({"name": name, "data": data})
    return cleaned


class State:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = Lock()
        self.api_key = None
        self.catalog = {}
        self.jobs = {}

    def connection_key(self, supplied):
        key = supplied or self.api_key or ""
        return _required_text(key, t("Client key", "İstemci anahtarı"), 1000)

    def catalog_key(self, base_url, api_key):
        return sha256((self.token + base_url.rstrip("/") + api_key).encode()).hexdigest()

    def start_job(self, payload):
        with self.lock:
            if any(job["status"] in ACTIVE for job in self.jobs.values()):
                raise ValueError(t("An experiment is already running. Wait for it to finish or cancel it.",
                                   "Bir deney zaten çalışıyor. Bitmesini bekleyin veya iptal edin."))
            job_id = secrets.token_urlsafe(12)
            self.jobs[job_id] = {"status": "queued", "events": [], "result": None, "process": None,
                                 "vnc_url": None, "timer": None}
            while len(self.jobs) > 12:
                oldest = next(iter(self.jobs))
                if oldest != job_id:
                    del self.jobs[oldest]
        Thread(target=self._work, args=(job_id, payload), daemon=True).start()
        return job_id

    def cancel(self, job_id, message, statuses=ACTIVE):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job["status"] in statuses:
                job["status"] = "canceled"
                job["events"].append(message)
                if job["process"]:
                    _kill_group(job["process"], signal.SIGTERM)
            return job["status"]

    def resume(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job["status"] != "waiting_login":
                raise ValueError(t("The experiment is not waiting for a login.", "Deney giriş beklemiyor."))
            try:
                job["process"].stdin.write("continue\n")
                job["process"].stdin.flush()
            except (AttributeError, OSError) as exc:
                raise ValueError(t("The experiment process is no longer running.", "Deney süreci artık çalışmıyor.")) from exc
            job["timer"].cancel()
            job["status"] = "running"
            job["events"].append(t("Login complete; agents are browsing the site…", "Giriş tamamlandı; ajanlar siteyi geziyor…"))
            return job["status"]

    def _work(self, job_id, payload):
        set_lang(payload.get("lang"))  # job events and the login timeout speak the language the job started in
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("OPENAI_BASE_URL", None)
        env["PYTHONUNBUFFERED"] = "1"
        # Browser profile, VNC password file and TinyTroupe logs all land here and go with the job.
        workdir = tempfile.mkdtemp(prefix="tinytroupe-job-")
        env["TMPDIR"] = workdir
        password = None
        if payload["mode"] == "browser":
            # VNC auth reads only 8 characters; alphanumerics keep the URL fragment unambiguous.
            password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            payload["vnc_password"] = password
        process = None
        try:
            process = subprocess.Popen(
                [str(PYTHON), str(HERE / "web_worker.py")],
                cwd=workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True,
            )
            with self.lock:
                job = self.jobs[job_id]
                job["process"] = process
                if job["status"] == "canceled":
                    return
                job["status"] = "running"
            # stdin stays open: a browser job reads "continue" from it after the manual login.
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
            del payload
            for line in process.stdout:
                if not line.startswith(EVENT_PREFIX):
                    continue
                try:
                    event = json.loads(line[len(EVENT_PREFIX):])
                except json.JSONDecodeError:
                    continue
                with self.lock:
                    if self.jobs[job_id]["status"] == "canceled":
                        continue
                    if event.get("type") == "result":
                        self.jobs[job_id]["result"] = event.get("data")
                        self.jobs[job_id]["status"] = "done"
                    elif event.get("type") == "error":
                        self.jobs[job_id]["status"] = "failed"
                        self.jobs[job_id]["events"].append(event.get("message", t("The experiment could not be completed.", "Deney tamamlanamadı.")))
                    elif event.get("type") == "progress":
                        self.jobs[job_id]["events"].append(event.get("message", t("Working…", "Çalışıyor…")))
                    elif event.get("type") == "waiting_login" and password:
                        job = self.jobs[job_id]
                        job["status"] = "waiting_login"
                        job["vnc_url"] = f"{VNC_URL}#autoconnect=1&resize=scale&password={password}"
                        job["events"].append(event.get("message", t("Waiting for login…", "Giriş bekleniyor…")))
                        job["timer"] = Timer(LOGIN_TIMEOUT, self.cancel, (
                            job_id, t("Login was not completed within 15 minutes; the experiment was stopped.",
                                      "Giriş 15 dakika içinde tamamlanmadı; deney durduruldu."), ("waiting_login",)))
                        job["timer"].daemon = True
                        job["timer"].start()
            process.wait()
            with self.lock:
                if self.jobs[job_id]["status"] in ACTIVE:
                    self.jobs[job_id]["status"] = "failed"
                    self.jobs[job_id]["events"].append(t(
                        "The model run could not be completed. Check the connection and model compatibility.",
                        "Model işlemi tamamlanamadı. Bağlantıyı ve model uyumluluğunu kontrol edin."))
        except Exception:
            with self.lock:
                if self.jobs[job_id]["status"] != "canceled":
                    self.jobs[job_id]["status"] = "failed"
                    self.jobs[job_id]["events"].append(t("The experiment could not be started.", "Deney başlatılamadı."))
        finally:
            if process:
                # Cancel, timeout, crash or success: nothing from this job (Xvfb, VNC, Chromium) outlives it.
                _kill_group(process, signal.SIGKILL)
                process.wait()
                try:
                    process.stdin.close()
                except OSError:
                    pass
            shutil.rmtree(workdir, ignore_errors=True)
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["process"] = None
                    job["vnc_url"] = None
                    if job["timer"]:
                        job["timer"].cancel()


def _kill_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _headers(self, content_type, length):
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")

        def _send(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, changing=False):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                return False
            if self.headers.get("Origin") not in (None, origin):
                return False
            return not changing or self.headers.get("X-App-Token") == state.token

        def _json(self):
            size = self.headers.get("Content-Length", "")
            if not size.isdigit() or int(size) > MAX_BODY:
                raise ValueError(t("Invalid request size.", "İstek boyutu geçersiz."))
            return json.loads(self.rfile.read(int(size)))

        def do_GET(self):
            set_lang(self.headers.get("X-Lang"))
            if not self._allowed():
                return self._send(403, {"error": t("Access denied.", "Erişim reddedildi.")})
            if self.path == "/api/settings":
                with state.lock:
                    return self._send(200, {"key_available": bool(state.api_key)})
            if self.path == "/":
                body = (HERE / "web.html").read_text(encoding="utf-8").replace("__APP_TOKEN__", state.token).encode()
                kind = "text/html; charset=utf-8"
            elif self.path in ("/web.css", "/web.js"):
                body = (HERE / self.path.lstrip("/")).read_bytes()
                kind = "text/css; charset=utf-8" if self.path.endswith(".css") else "text/javascript; charset=utf-8"
            elif self.path in ("/assets/focus-group-logo.webp", "/assets/persona-hero.webp"):
                body = (HERE / "web_assets" / self.path.removeprefix("/assets/")).read_bytes()
                kind = "image/webp"
            elif self.path.startswith("/api/jobs/"):
                job_id = self.path.removeprefix("/api/jobs/")
                with state.lock:
                    job = state.jobs.get(job_id)
                    if job:
                        return self._send(200, {k: job[k] for k in ("status", "events", "result", "vnc_url")})
                return self._send(404, {"error": t("Experiment not found.", "Deney bulunamadı.")})
            else:
                return self._send(404, {"error": t("Page not found.", "Sayfa bulunamadı.")})
            self.send_response(200)
            self._headers(kind, len(body))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            set_lang(self.headers.get("X-Lang"))
            if not self._allowed(changing=True):
                return self._send(403, {"error": t("Access denied.", "Erişim reddedildi.")})
            try:
                if self.path.startswith("/api/jobs/") and self.path.endswith("/continue"):
                    status = state.resume(self.path.removeprefix("/api/jobs/").removesuffix("/continue"))
                    if status is None:
                        return self._send(404, {"error": t("Experiment not found.", "Deney bulunamadı.")})
                    return self._send(200, {"status": status})
                body = self._json()
                if self.path == "/api/settings/key":
                    key = _required_text(body.get("api_key"), t("Client key", "İstemci anahtarı"), 1000)
                    with state.lock:
                        state.api_key = key
                        state.catalog.clear()
                    return self._send(200, {"key_available": True})
                if self.path == "/api/models":
                    base = _required_text(body.get("base_url"), t("CLIProxyAPI address", "CLIProxyAPI adresi"), 200)
                    with state.lock:
                        key = state.connection_key(body.get("api_key"))
                    models = fetch_models(base, key)
                    with state.lock:
                        state.catalog[state.catalog_key(base, key)] = set(models)
                    return self._send(200, {"models": models})
                if self.path == "/api/run":
                    with state.lock:
                        body["api_key"] = state.connection_key(body.get("api_key"))
                    payload = validate_run(body)
                    payload["lang"] = lang()
                    with state.lock:
                        models = state.catalog.get(state.catalog_key(payload["base_url"], payload["api_key"]), set())
                    if payload["model"] not in models:
                        raise ValueError(t("Load the model list first and pick a model from it.", "Önce model listesini yükleyip listeden bir model seçin."))
                    return self._send(202, {"job_id": state.start_job(payload)})
                return self._send(404, {"error": t("Action not found.", "İşlem bulunamadı.")})
            except (ValueError, json.JSONDecodeError, TypeError, AttributeError) as exc:
                return self._send(400, {"error": str(exc)[:200]})
            except HTTPError as exc:
                message = (t("The key or connection was rejected.", "Anahtar veya bağlantı reddedildi.") if exc.code in (401, 403)
                           else t(f"Could not get the model list (HTTP {exc.code}).", f"Model listesi alınamadı (HTTP {exc.code})."))
                return self._send(502, {"error": message})
            except (URLError, TimeoutError):
                return self._send(502, {"error": t("Could not connect to CLIProxyAPI.", "CLIProxyAPI bağlantısı kurulamadı.")})

        def do_DELETE(self):
            set_lang(self.headers.get("X-Lang"))
            if not self._allowed(changing=True):
                return self._send(403, {"error": t("Access denied.", "Erişim reddedildi.")})
            if self.path == "/api/settings/key":
                with state.lock:
                    state.api_key = None
                    state.catalog.clear()
                return self._send(200, {"key_available": False})
            job_id = self.path.removeprefix("/api/jobs/") if self.path.startswith("/api/jobs/") else ""
            status = state.cancel(job_id, t("Experiment canceled.", "Deney iptal edildi."))
            if status is None:
                return self._send(404, {"error": t("Experiment not found.", "Deney bulunamadı.")})
            return self._send(200, {"status": status})

    return Handler


def main():
    state = State()
    # In Docker: 0.0.0.0:8765, published as 127.0.0.1:8765 so the Host check below still matches.
    host = os.environ.get("PLAYGROUND_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, int(os.environ.get("PLAYGROUND_PORT", "0"))), make_handler(state))
    address = f"http://127.0.0.1:{server.server_port}/"
    print(t(f"TinyTroupe web app: {address}", f"TinyTroupe web uygulaması: {address}"))
    print(t("Press Ctrl+C to stop. The client key is never saved to a file.", "Kapatmak için Ctrl+C. İstemci anahtarı dosyaya kaydedilmez."))
    if host == "127.0.0.1":
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(t("Stopped.", "Kapatıldı."))
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
