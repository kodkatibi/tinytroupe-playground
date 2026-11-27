"""English by default, Turkish on request: per request/job from the web UI, or PLAYGROUND_LANG=tr for the CLI tools."""

import os
import threading


_current = threading.local()  # each HTTP request and each job runs in its own thread


def set_lang(code):
    _current.code = "tr" if code == "tr" else "en"


def lang():
    return getattr(_current, "code", "tr" if os.environ.get("PLAYGROUND_LANG") == "tr" else "en")


def t(en, tr):
    return tr if lang() == "tr" else en
