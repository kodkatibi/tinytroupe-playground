"""Browser tool, request policy and the Docker-only virtual display for browser experiments."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, Error as PlaywrightError
from tinytroupe.tools import TinyTool


DISPLAY = ":99"
VNC_ORIGIN = "http://127.0.0.1:6080"  # noVNC page as the Mac browser opens it (compose publishes 6080)
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# Chromium answers *.localhost itself; send them to the ports the Mac publishes so URLs stay as typed.
LOCALHOST_RULES = "--host-resolver-rules=MAP localhost host.docker.internal, MAP *.localhost host.docker.internal"


def allowed_request(method, url, target_host, allow_writes, main_navigation):
    """Best-effort policy: page changes stay on the target host; read-only mode passes only read methods."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if main_navigation and host != target_host:
        return False
    return allow_writes or method.upper() in READ_METHODS


def guard(context, target_url, allow_writes, blocked):
    target_host = urlsplit(target_url).hostname

    def check(route):
        request = route.request
        try:
            main = request.is_navigation_request() and request.frame.parent_frame is None
        except PlaywrightError:
            main = True  # a popup's first request comes before its frame exists; it is top-level
        if allowed_request(request.method, request.url, target_host, allow_writes, main):
            route.continue_()
        else:
            blocked.append(f"{request.method} {urlsplit(request.url).path}")
            route.abort()

    def close_socket(socket):
        blocked.append(f"WS {urlsplit(socket.url).path}")
        socket.close()

    context.route("**/*", check)
    if not allow_writes:
        context.route_web_socket("**/*", close_socket)


class LocalBrowserTool(TinyTool):
    def __init__(self, page, target_url, allow_writes, max_actions, progress=None):
        super().__init__("web-browser", "Hedef web sitesini tarayıcıda inceler.", real_world_side_effects=allow_writes)
        self.page = page
        self.target_url = target_url
        self.target_host = urlsplit(target_url).hostname
        self.allow_writes = allow_writes
        self.controls = []
        self.history = []
        self.actions_used = 0
        self.max_actions = max_actions
        self.progress = progress or (lambda _: None)

    def actions_definitions_prompt(self):
        return (
            '  - BROWSER_CLICK: Ekrandaki numaralı bir öğeye tıkla. content JSON: {"index": 1}.\n'
            '  - BROWSER_FILL: Numaralı metin alanına değer gir. content JSON: {"index": 1, "value": "metin"}.\n'
            '  - BROWSER_BACK: Tarayıcıda önceki sayfaya dön. content boş olabilir.\n'
        )

    def actions_constraints_prompt(self):
        writes = ("  - Veri değiştiren işlemler gerçek etki doğurabilir; görevin gerektirmediği değişikliği yapma.\n"
                  if self.allow_writes else
                  "  - Sitede yalnız okuma yapabilirsin; form gönderimi ve veri değişikliği engellenir.\n")
        return (
            '  - Yalnız son gözlemde listelenen öğe numaralarını kullan. Her işlemden sonra yeni ekranı oku.\n'
            + writes +
            '  - Bulduğun belirsizlikleri TALK ile anlat; görmediğin bilgiyi uydurma.\n'
        )

    def observe(self, agent):
        # Redirects skip the request guard, so re-check the host before anything reaches the model.
        if urlsplit(self.page.url).hostname != self.target_host:
            self.page.goto(self.target_url, wait_until="domcontentloaded", timeout=20_000)
            if urlsplit(self.page.url).hostname != self.target_host:
                raise RuntimeError("Hedef adres site dışına yönlendiriyor; oturum düşmüş olabilir.")
            agent.see(description="Sayfa hedef site dışına çıktı; hedef adrese geri dönüldü.")
        body = self.page.locator("body").inner_text(timeout=10_000)[:5500]
        controls = []
        labels = []
        for element in self.page.locator("a, button, input, textarea, select, [role='button']").all():
            if len(controls) >= 40:
                break
            try:
                if not element.is_visible(timeout=500):
                    continue
                label = (element.get_attribute("aria-label") or element.inner_text(timeout=500)
                         or element.get_attribute("placeholder") or "").strip().replace("\n", " ")[:100]
                if not label:
                    continue
                controls.append(element)
                labels.append(f"{len(controls)}. {label}")
            except PlaywrightError:
                continue
        self.controls = controls
        snapshot = f"Tarayıcı sayfası: {self.page.url}\n\nEkran metni:\n{body}\n\nTıklanabilir alanlar:\n" + "\n".join(labels)
        screenshot = self.page.screenshot(type="jpeg", quality=60, timeout=10_000)
        uri = "data:image/jpeg;base64," + base64.b64encode(screenshot).decode("ascii")
        agent.see(images=uri, description=snapshot)
        self.history.append({"url": self.page.url, "controls": labels, "text": body[:1500]})

    def _process_action(self, agent, action):
        kind = action.get("type")
        if kind not in {"BROWSER_CLICK", "BROWSER_FILL", "BROWSER_BACK"}:
            return False
        if self.actions_used >= self.max_actions:
            agent.see(description="Tarayıcı adımı sınırına ulaştın; şimdi gözlemlerini TALK ile anlat.")
            return True
        try:
            if kind == "BROWSER_BACK":
                self.page.go_back(wait_until="domcontentloaded", timeout=10_000)
                detail = "Geri dönüldü"
            else:
                content = action.get("content")
                spec = json.loads(content) if isinstance(content, str) else content
                index = spec.get("index") if isinstance(spec, dict) else None
                if type(index) is not int or not 1 <= index <= len(self.controls):
                    raise ValueError("Geçersiz öğe numarası.")
                element = self.controls[index - 1]
                if kind == "BROWSER_CLICK":
                    element.click(timeout=7_000)
                    detail = f"{index} numaralı öğeye tıklandı"
                else:
                    value = spec.get("value")
                    if not isinstance(value, str) or len(value) > 500:
                        raise ValueError("Metin alanı değeri geçersiz.")
                    element.fill(value, timeout=7_000)
                    detail = f"{index} numaralı alan dolduruldu"
            self.actions_used += 1
            self.page.wait_for_timeout(400)
            self.history.append({"action": detail})
            self.progress(f"{self.actions_used}/{self.max_actions} · {detail}")
            self.observe(agent)
        except (ValueError, PlaywrightError, TypeError, json.JSONDecodeError) as exc:
            agent.see(description=f"Tarayıcı işlemi yapılamadı: {str(exc)[:120]}")
            self.history.append({"error": type(exc).__name__})
        return True


def start_display(password):
    """Xvfb + password-protected x11vnc + Origin-checked websockify for one job."""
    if not shutil.which("Xvfb"):
        raise RuntimeError("Tarayıcı deneyi yalnız Docker kurulumunda çalışır; README'deki Docker adımlarını izleyin.")
    secret = Path(tempfile.gettempdir()) / "vnc-password"  # TMPDIR is the job's own directory
    descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(password + "\n")
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    processes = [subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x960x24", "-nolisten", "tcp"], **quiet)]
    try:
        for _ in range(50):
            if Path("/tmp/.X11-unix/X" + DISPLAY[1:]).exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Sanal ekran başlatılamadı.")
        processes.append(subprocess.Popen(
            ["x11vnc", "-display", DISPLAY, "-localhost", "-rfbport", "5900",
             "-passwdfile", f"rm:{secret}", "-forever", "-shared", "-quiet"], **quiet))
        processes.append(subprocess.Popen(
            ["websockify", "--web", "/usr/share/novnc",
             "--auth-plugin", "websockify.auth_plugins.ExpectOrigin", "--auth-source", VNC_ORIGIN,
             "6080", "localhost:5900"], **quiet))
    except BaseException:
        stop_display(processes)
        raise
    os.environ["DISPLAY"] = DISPLAY
    return processes


def stop_display(processes):
    for process in reversed(processes):
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def launch_browser():
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(
            headless=False, args=[LOCALHOST_RULES, "--window-position=0,0", "--window-size=1280,960"])
    except Exception:
        playwright.stop()
        raise
    return playwright, browser
