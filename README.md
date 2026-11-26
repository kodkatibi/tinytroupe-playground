# TinyTroupe Playground

**English** · [Türkçe](README.tr.md)

A local web UI for running TinyTroupe persona experiments on a Mac. You set the personas, scenario, question and images for each run. There are three methods: independent interviews, group conversation, and **Siteyi gez** ("browse the site"), where agents browse a real website in a browser.

The interface is in Turkish. UI labels below are quoted as they appear on screen, with an English gloss.

## Setup with Docker (recommended)

With Docker Desktop running, in the project folder:

```bash
docker compose up --build -d
```

Then open `http://127.0.0.1:8765/` in your browser. `localhost:8765` does not work: the app only accepts this exact address. Stop it with `docker compose down`.

- The app (`8765`) and the browser screen (`6080`) are published on the Mac only on `127.0.0.1`.
- The container does not mount the project folder. If the code changed, rebuild with `docker compose up --build -d`.
- The browser profile, VNC password file and TinyTroupe logs live in a per-experiment temporary folder in the container's in-memory `/tmp`. When an experiment finishes, is canceled or fails, that folder and all of the experiment's processes are deleted.

## CLIProxyAPI and models

This version only accepts a CLIProxyAPI `:8317/v1` address on Tailscale (`http://100.x.x.x:8317/v1/`). Docker Desktop routes the container's outbound traffic through the Mac, so the Tailscale address is reachable from the container too.

In the **Ayarlar** (Settings) tab, enter the CLIProxyAPI address and the client key. The address and your chosen model are remembered in this browser. The client key is not the management key, and it is never saved to browser storage. **Modelleri yükle** (Load models) makes an authenticated `/v1/models` request. Pick a model from the list, then start the experiment. Personas, scenario, images, and in browser mode the page text and screenshots, are sent to the selected model.

To avoid typing the key on every launch, use macOS Keychain. The first time, in a Mac terminal in this folder:

```bash
python3 mac_keychain.py set
```

The `security` command prompts for the key interactively, so the key never appears in command-line arguments. On later launches, instead of `docker compose up`:

```bash
python3 mac_keychain.py start
```

This starts the Docker app, reads the key from Keychain, and hands it to the app's memory over `127.0.0.1:8765` only. The key is never written to the Docker image, Compose environment variables or browser storage. The in-memory copy is gone when the app stops. You can clear the in-memory copy from the Settings tab; to delete the Keychain entry, run `python3 mac_keychain.py forget`. Without Keychain, you can type the key in the Settings tab for the open page.

**Local security boundary:** this is a single-user local tool. Any other local process on the Mac that can reach `127.0.0.1:8765` can start model requests with the loaded key, though it cannot read the key itself. Don't leave the app running on a shared or untrusted Mac, and run `docker compose down` when you're done.

You can watch results on screen and download them as Markdown. Experiment inputs are not saved automatically, and the downloaded report never contains the key. A model showing up in the list does not guarantee it works with TinyTroupe's structured responses and image calls. Synthetic answers are not real user interviews.

## Browse the site: browser experiments

This method only works with the Docker setup.

1. Enter the site's address in **Hedef adres** (Target address):
   - For a local site running on the Mac, use the same address you use on the Mac, for example `http://app.localhost:3000/`. The browser in the container routes `localhost` and `*.localhost` to the ports the Mac publishes; the address, cookies and Host header stay the same.
   - `http://` is accepted only for `localhost` and `*.localhost`. Every other site must use `https://`.
   - `127.0.0.1` and `::1` are rejected: inside the container they point at the container itself, not the Mac. Use `localhost` instead.
2. Start the experiment. A **Tarayıcı ekranını aç** (Open browser screen) link appears in the results section. It opens noVNC in a new tab; the per-experiment password is in the link's `#` fragment and stops working when the experiment ends.
3. Log in to the site yourself in that browser, then go back to the app tab and press **Girişi tamamladım** (I've logged in). If you don't continue within 15 minutes, the experiment stops.
4. When you continue, other tabs are closed, the guard rules are installed, and the first tab reopens at the target address. Personas use this session one after another. You can watch the browsing from the same link (**Ajanları izle**, Watch the agents).

**The read-only guard (the default) is best effort:**
- Requests other than GET/HEAD/OPTIONS and WebSocket connections are blocked. Service workers stay disabled for the whole session.
- Navigation stays on the target host. If a redirect leaves the site, the browser returns to the target address before the page is sent to the model.
- Endpoints that change data on GET cannot be blocked. Pages that read data with POST (e.g. GraphQL) may break in this mode.

If you check **Veri değiştiren isteklere izin ver** (Allow requests that change data), agents can change real data, and one persona's changes carry over to the next. Navigation still stays on the target host in this mode.

On a live site, page text and screenshots go to the model provider through CLIProxyAPI. Use a separate test account on live environments.

## Troubleshooting

- **The page returns 403:** use `http://127.0.0.1:8765/` instead of `localhost:8765`.
- **noVNC says "password check failed" or won't connect:** reopen the link from this experiment's results box. An old tab's password does not work for a new experiment. Open noVNC at the `127.0.0.1:6080` address in the link, not at `localhost:6080`.
- **Pasting a password:** paste it into the clipboard field in noVNC's left panel, then press `Ctrl+V` in the remote browser. The VNC clipboard only carries Latin-1: ASCII passwords work, but characters such as `ş`, `ğ`, `ı` get garbled. Type those on the keyboard.
- **A local site won't open:** first check that the site opens on the Mac at the same address. The container reaches ports the Mac listens on through `host.docker.internal`.
- **The browser looks frozen while agents think:** the guard rules only run while an agent is performing a browser action. Background requests wait while the model is responding; this is expected.
- **Model error:** models that are in the list but don't fit TinyTroupe's format can fail; try another model.

## Local setup without Docker

The interview and group methods also work without Docker. With Python 3.12, in the project folder:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
python3 start.py
```

The app opens on a random port on `127.0.0.1`. `python3 start.py --notebook` opens the older Jupyter UI; that also needs `.venv/bin/python -m pip install jupyterlab`.

## Development

```bash
.venv/bin/python -m unittest test_web_app.py
docker compose run --rm -T --workdir /tmp playground python -m unittest discover -s /app -p test_web_app.py
```

TinyTroupe is pinned to the `v0.7.0` commit in `requirements.txt`; the `tinytroupe` package on PyPI is a placeholder. To move to a newer TinyTroupe, update the commit URL and `constraints.txt`, then rerun the tests and all three methods.
