import base64
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))


class WebAppTests(unittest.TestCase):
    def test_models_are_loaded_from_authenticated_gateway(self):
        from web_app import fetch_models

        class Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        body = json.dumps({"data": [{"id": "z-model"}, {"id": "a-model"}]}).encode()
        with patch("web_app.build_opener") as builder:
            builder.return_value.open.return_value = Response(body)
            models = fetch_models("http://100.64.0.1:8317/v1/", "sample-key")
        self.assertEqual(models, ["a-model", "z-model"])
        request = builder.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://100.64.0.1:8317/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer sample-key")

    def test_run_requires_a_selected_model_and_valid_persona(self):
        from web_app import validate_run

        good = {
            "base_url": "http://100.64.0.1:8317/v1/", "api_key": "sample-key",
            "model": "a-model", "scenario": "Alışveriş", "question": "Ne düşünürsün?",
            "mode": "interview", "steps": 1,
            "personas": [{"name": "Ayşe", "role": "Müşteri", "profile": "Fiyatı inceler"}],
            "images": [],
        }
        self.assertEqual(validate_run(good)["model"], "a-model")
        with self.assertRaises(ValueError):
            validate_run({**good, "model": ""})
        with self.assertRaises(ValueError):
            validate_run({**good, "personas": [{"name": "", "role": "Müşteri", "profile": "X"}]})

    def test_run_rejects_non_image_upload(self):
        from web_app import validate_run

        fake = "data:image/png;base64," + base64.b64encode(b"not an image").decode()
        payload = {
            "base_url": "http://100.64.0.1:8317/v1/", "api_key": "sample-key",
            "model": "a-model", "scenario": "Alışveriş", "question": "Ne düşünürsün?",
            "mode": "interview", "steps": 1,
            "personas": [{"name": "Ayşe", "role": "Müşteri", "profile": "Fiyatı inceler"}],
            "images": [{"name": "fake.png", "data": fake}],
        }
        with self.assertRaises(ValueError):
            validate_run(payload)

    def test_browser_mode_takes_any_valid_target_without_screens(self):
        from web_app import validate_run

        payload = {
            "base_url": "http://100.64.0.1:8317/v1/", "api_key": "sample-key",
            "model": "a-model", "scenario": "Ürün listesini incele", "question": "İlk neyi fark ettin?",
            "mode": "browser", "steps": 3, "images": [],
            "personas": [{"name": "Ayşe", "role": "Mağaza sahibi", "profile": "Fiyatları elle kontrol eder"}],
            "target_url": "http://app.localhost:3000/products",
        }
        cleaned = validate_run(payload)
        self.assertEqual(cleaned["images"], [])
        self.assertIs(cleaned["allow_writes"], False)
        custom = validate_run({**payload, "target_url": "https://example.com/", "allow_writes": True})
        self.assertIs(custom["allow_writes"], True)
        for bad in ({"target_url": ""}, {"allow_writes": "yes"},
                    {"images": [{"name": "x.png", "data": "data:image/png;base64,AA=="}]}):
            with self.assertRaises(ValueError):
                validate_run({**payload, **bad})

    def test_target_url_rules(self):
        from web_app import valid_target

        for good in ("http://localhost:3000/", "http://app.localhost:3000/products", "https://example.com/a?b=1"):
            self.assertEqual(valid_target(good), good)
        for bad in ("http://example.com/", "http://127.0.0.1:13000/", "https://[::1]/", "https://user:pw@example.com/",
                    "ftp://example.com/", "javascript:alert(1)", "file:///etc/passwd", "https://example.com:99999/"):
            with self.assertRaises(ValueError, msg=bad):
                valid_target(bad)
        with self.assertRaisesRegex(ValueError, "localhost kullanın"):
            valid_target("http://127.0.0.1:13000/")

    def test_browser_request_policy(self):
        from local_browser import allowed_request

        host = "app.localhost"
        self.assertTrue(allowed_request("GET", "http://app.localhost:3000/products", host, False, True))
        self.assertTrue(allowed_request("GET", "http://api.localhost:13000/api/products", host, False, False))
        self.assertTrue(allowed_request("GET", "https://cdn.example.com/app.js", host, False, False))
        self.assertFalse(allowed_request("POST", "http://api.localhost:13000/api/products", host, False, False))
        self.assertTrue(allowed_request("POST", "http://api.localhost:13000/api/products", host, True, False))
        self.assertFalse(allowed_request("GET", "https://example.com/", host, False, True))
        self.assertFalse(allowed_request("GET", "https://example.com/", host, True, True))
        self.assertFalse(allowed_request("GET", "file:///etc/passwd", host, True, False))


class JobStateTests(unittest.TestCase):
    def setUp(self):
        from web_app import State

        self.state = State()
        self.process = MagicMock(pid=4242)
        self.timer = MagicMock()
        self.state.jobs["job"] = {"status": "waiting_login", "events": [], "result": None,
                                  "process": self.process, "vnc_url": "http://x", "timer": self.timer}

    def test_waiting_login_blocks_a_second_job(self):
        with self.assertRaises(ValueError):
            self.state.start_job({})

    def test_continue_only_from_waiting_login(self):
        self.assertEqual(self.state.resume("job"), "running")
        self.process.stdin.write.assert_called_once_with("continue\n")
        self.timer.cancel.assert_called_once()
        with self.assertRaises(ValueError):
            self.state.resume("job")
        self.assertIsNone(self.state.resume("missing"))

    @patch("web_app.os.killpg")
    def test_cancel_kills_the_process_group(self, killpg):
        import signal

        self.assertEqual(self.state.cancel("job", "Deney iptal edildi."), "canceled")
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        self.assertEqual(self.state.jobs["job"]["events"][-1], "Deney iptal edildi.")

    @patch("web_app.os.killpg")
    def test_login_timeout_leaves_a_resumed_job_alone(self, killpg):
        self.state.resume("job")
        self.assertEqual(self.state.cancel("job", "süre doldu", ("waiting_login",)), "running")
        killpg.assert_not_called()

    def test_continue_endpoint_requires_the_app_token(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        from web_app import make_handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/jobs/job/continue"
        with self.assertRaises(HTTPError) as denied:
            urlopen(Request(url, method="POST"), timeout=5)
        self.assertEqual(denied.exception.code, 403)
        self.assertEqual(self.state.jobs["job"]["status"], "waiting_login")
        with urlopen(Request(url, method="POST", headers={"X-App-Token": self.state.token}), timeout=5) as response:
            self.assertEqual(json.load(response)["status"], "running")

    def test_keychain_key_stays_server_side_and_can_be_cleared(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        from web_app import make_handler

        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/api/settings/key"
        request = Request(base, data=json.dumps({"api_key": "sample-key"}).encode(),
                          headers={"Content-Type": "application/json", "X-App-Token": self.state.token})
        with urlopen(request, timeout=5) as response:
            self.assertEqual(json.load(response), {"key_available": True})
        with urlopen(base.removesuffix("/key"), timeout=5) as response:
            settings = json.load(response)
        self.assertEqual(settings, {"key_available": True})
        self.assertNotIn("sample-key", json.dumps(settings))
        with urlopen(Request(base, method="DELETE", headers={"X-App-Token": self.state.token}), timeout=5) as response:
            self.assertEqual(json.load(response), {"key_available": False})
        with self.assertRaises(HTTPError) as denied:
            urlopen(Request(base, data=b'{}', method="POST"), timeout=5)
        self.assertEqual(denied.exception.code, 403)

    def test_server_uses_keychain_key_when_browser_sends_no_key(self):
        self.state.api_key = "sample-key"
        self.assertEqual(self.state.connection_key(""), "sample-key")
        self.assertEqual(self.state.connection_key("manual-key"), "manual-key")
        self.state.api_key = None
        with self.assertRaisesRegex(ValueError, "İstemci anahtarı"):
            self.state.connection_key("")


class MacKeychainTests(unittest.TestCase):
    def test_keychain_setup_uses_interactive_prompt(self):
        from mac_keychain import save_key

        with patch("mac_keychain.subprocess.run") as run:
            save_key()
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["security", "add-generic-password"])
        self.assertEqual(command[-1], "-w")
        self.assertNotIn("-A", command)

    def test_keychain_startup_posts_key_only_to_loopback(self):
        from mac_keychain import inject_key

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        calls = []

        def opener(request, timeout):
            calls.append(request)
            return Response(b'<meta name="app-token" content="test-token">') if len(calls) == 1 else Response(b'{"key_available": true}')

        inject_key("secret", opener=opener)
        self.assertEqual(calls[0].full_url, "http://127.0.0.1:8765/")
        self.assertEqual(calls[1].full_url, "http://127.0.0.1:8765/api/settings/key")
        self.assertEqual(calls[1].get_header("X-app-token"), "test-token")
        self.assertEqual(json.loads(calls[1].data), {"api_key": "secret"})


class SettingsBrowserTests(unittest.TestCase):
    def test_address_and_model_survive_reload_without_storing_key_in_browser(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from playwright.sync_api import sync_playwright
        from web_app import State, make_handler

        state = State()
        state.api_key = "sample-key"
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with patch("web_app.fetch_models", return_value=["model-a", "model-b"]):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True,
                    executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                try:
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{server.server_port}/")
                    page.get_by_role("link", name="Ayarlar", exact=True).click(timeout=3000)
                    page.locator("#base-url").fill("http://100.64.0.1:8317/v1/")
                    page.locator("#load-models").click()
                    page.locator("#model").select_option("model-b")
                    page.reload()
                    page.wait_for_function("document.querySelector('#model').value === 'model-b'")
                    self.assertEqual(page.locator("#base-url").input_value(), "http://100.64.0.1:8317/v1/")
                    self.assertEqual(page.locator("#model").input_value(), "model-b")
                    self.assertEqual(page.evaluate("Object.values(localStorage).join(' ')").find("sample-key"), -1)
                finally:
                    browser.close()


if __name__ == "__main__":
    unittest.main()
