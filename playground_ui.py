"""A small Jupyter form for trying TinyTroupe with custom inputs."""

import base64
from datetime import datetime
from json import JSONDecodeError, loads
from os import environ
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import ipywidgets as widgets
from IPython import get_ipython
from IPython.display import clear_output, display

from i18n import t
from start import valid_gateway


HERE = Path(__file__).resolve().parent


def _spoken(actions):
    lines = []
    for item in actions or []:
        action = item.get("action", item)
        if action.get("type") == "TALK" and action.get("content"):
            lines.append(action["content"].strip())
    return "\n".join(lines) or t("(No spoken reply.)", "(Sözlü yanıt gelmedi.)")


class Playground:
    def __init__(self):
        gateway = environ.get("OPENAI_BASE_URL", "").strip()
        valid, _ = valid_gateway(gateway)
        if not valid or not environ.get("OPENAI_API_KEY", "").strip():
            raise RuntimeError(t("Enter the CLIProxyAPI address and client key with start.py first.",
                                 "Önce start.py ile CLIProxyAPI adresini ve istemci anahtarını girin."))

        self.model = widgets.Text(
            value=environ.get("TINY_TROUPE_MODEL", "gpt-6-luna"),
            description="Model", layout=widgets.Layout(width="100%"),
            style={"description_width": "110px"},
        )
        self.scenario = widgets.Textarea(
            value=t("You are making a decision about a product or service.", "Bir ürün veya hizmet hakkında karar veriyorsun."),
            description=t("Scenario", "Senaryo"), layout=widgets.Layout(width="100%", height="95px"),
            style={"description_width": "110px"},
        )
        self.question = widgets.Textarea(
            value=t("What did you notice first? What would you check before deciding?",
                    "İlk neyi fark ettin? Karar vermeden önce neyi kontrol edersin?"),
            description=t("Question", "Soru"), layout=widgets.Layout(width="100%", height="95px"),
            style={"description_width": "110px"},
        )
        self.images = widgets.FileUpload(
            accept="image/png,image/jpeg,image/webp,image/gif", multiple=True,
            description=t("Choose images", "Görsel seç"), button_style="",
        )
        self.mode = widgets.Dropdown(
            options=[(t("Independent interviews", "Bağımsız görüşme"), "interview"),
                     (t("TinyWorld group conversation", "TinyWorld grup konuşması"), "world")],
            description=t("Method", "Yöntem"), style={"description_width": "110px"},
        )
        self.steps = widgets.IntSlider(
            value=2, min=1, max=6, description=t("Group rounds", "Grup turu"),
            style={"description_width": "110px"},
        )
        self.save = widgets.Checkbox(value=False, description=t("Save replies to a local Markdown report", "Yanıtları yerel Markdown raporuna kaydet"))
        self.add_button = widgets.Button(description=t("Add persona", "Persona ekle"), icon="plus")
        self.run_button = widgets.Button(description=t("Run", "Çalıştır"), button_style="primary", icon="play")
        self.persona_box = widgets.VBox()
        self.output = widgets.Output()
        self.chat_output = widgets.Output()
        self.rows = []
        self.last_agents = []
        self.last_world = None

        self.add_button.on_click(lambda _: self._add_persona())
        self.run_button.on_click(self._run)
        self.mode.observe(self._show_steps, names="value")
        self._add_persona(*t(("Alex", "Customer", "Compares products before deciding."),
                              ("Ayşe", "Müşteri", "Ürünleri karşılaştırarak karar veriyor.")))
        self._show_steps()

    def _add_persona(self, name="", role="", profile=""):
        name_input = widgets.Text(value=name, placeholder=t("Name", "Ad"), description=t("Name", "Ad"))
        role_input = widgets.Text(value=role, placeholder=t("Role", "Rol"), description=t("Role", "Rol"))
        profile_input = widgets.Textarea(
            value=profile, placeholder=t("Preferences, goals, constraints", "Tercihleri, hedefleri, koşulları"),
            description=t("Profile", "Profil"), layout=widgets.Layout(width="100%", height="80px"),
        )
        remove_button = widgets.Button(description=t("Remove", "Sil"), icon="trash")
        row = widgets.VBox([widgets.HBox([name_input, role_input, remove_button]), profile_input])
        record = (name_input, role_input, profile_input, row)
        self.rows.append(record)

        def remove(_):
            self.rows.remove(record)
            self.persona_box.children = tuple(item[3] for item in self.rows)

        remove_button.on_click(remove)
        self.persona_box.children = tuple(item[3] for item in self.rows)

    def _show_steps(self, change=None):
        self.steps.layout.display = "" if self.mode.value == "world" else "none"

    def _inputs(self):
        model = self.model.value.strip()
        scenario = self.scenario.value.strip()
        question = self.question.value.strip()
        personas = [(name.value.strip(), role.value.strip(), profile.value.strip())
                    for name, role, profile, _ in self.rows]
        if not model or not scenario or not question or not personas:
            raise ValueError(t("Model, scenario, question and at least one persona are required.",
                               "Model, senaryo, soru ve en az bir persona gerekli."))
        if any(not name or not role or not profile for name, role, profile in personas):
            raise ValueError(t("Every persona needs a name, role and profile.", "Her personanın adı, rolü ve profili dolu olmalı."))
        if len({name.casefold() for name, _, _ in personas}) != len(personas):
            raise ValueError(t("Persona names must be different.", "Persona adları farklı olmalı."))

        images = []
        for uploaded in self.images.value:
            mime = uploaded.get("type", "")
            if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                raise ValueError(t("Upload only PNG, JPEG, WebP or GIF images.", "Yalnız PNG, JPEG, WebP veya GIF görseli yükleyin."))
            content = bytes(uploaded["content"])
            if not content:
                raise ValueError(t("Empty images cannot be uploaded.", "Boş görsel yüklenemez."))
            uri = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
            images.append((uploaded["name"], uri))
        return model, scenario, question, personas, images

    def _configure_model(self, model):
        from tinytroupe import config_manager, utils

        config_manager.update("api_type", "openai")
        config_manager.update("model", model)
        config_manager.update("vision_model", model)
        config_manager.update("timeout", 180)
        config_manager.update("max_attempts", 2)
        config_manager.update("cache_api_calls", False)
        # Basic experiments avoid embedding calls that this gateway may not expose.
        config_manager.update("enable_memory_consolidation", False)
        config_manager.update("enable_continuous_contextual_semantic_memory_retrieval", False)

        if not hasattr(utils, "_playground_original_extract_json"):
            utils._playground_original_extract_json = utils.extract_json

        def extract_json_preserving_turkish(value):
            if isinstance(value, str):
                try:
                    return loads(value)
                except JSONDecodeError:
                    pass
            return utils._playground_original_extract_json(value)

        utils.extract_json = extract_json_preserving_turkish

    def _save_report(self, model, scenario, question, personas, images, results, elapsed):
        output_dir = HERE / "runs"
        output_dir.mkdir(exist_ok=True)
        stamp = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y%m%d-%H%M%S-%f")
        path = output_dir / t(f"experiment-{stamp}.md", f"deney-{stamp}.md")
        lines = [t("# TinyTroupe experiment", "# TinyTroupe deneyi"), "",
                 t(f"Model: {model} · Time: {elapsed:.1f} s", f"Model: {model} · Süre: {elapsed:.1f} sn"), "",
                 f"{t('Method', 'Yöntem')}: {self.mode.label}", "", t("## Scenario", "## Senaryo"), "", scenario, "",
                 t("## Question", "## Soru"), "", question, "", t("## Personas", "## Personalar"), ""]
        for name, role, profile in personas:
            lines.extend([f"- **{name}** — {role}: {profile}"])
        lines.extend(["", t("## Images", "## Görseller"), "",
                      ", ".join(name for name, _ in images) if images else t("None", "Yok"), "",
                      t("## Replies", "## Yanıtlar"), ""])
        for label, reply in results:
            lines.extend([f"### {label}", "", reply, ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _run(self, _):
        with self.output:
            clear_output(wait=True)
            self.run_button.disabled = True
            started = monotonic()
            try:
                model, scenario, question, personas, images = self._inputs()
                self._configure_model(model)
                from tinytroupe.agent import TinyPerson
                from tinytroupe.environment import TinyWorld
                from tinytroupe.ui import AgentChatJupyterWidget

                TinyPerson.clear_agents()
                TinyWorld.clear_environments()
                if hasattr(TinyPerson, "_image_description_cache"):
                    TinyPerson._image_description_cache.clear()
                TinyPerson.communication_display = False
                TinyWorld.communication_display = False
                agents = []
                for name, role, profile in personas:
                    agent = TinyPerson(name)
                    agent.include_persona_definitions({
                        "occupation": role, "professional_context": profile,
                    })
                    agent.listen(scenario, communication_display=False)
                    for filename, uri in images:
                        agent.see(images=uri, description=filename)
                    agents.append(agent)

                results = []
                world = None
                if self.mode.value == "interview":
                    for agent in agents:
                        agent.listen(question, communication_display=False)
                        reply = _spoken(agent.act(return_actions=True,
                                                  communication_display=False))
                        results.append((agent.name, reply))
                        print(f"{agent.name}: {reply}\n")
                else:
                    world = TinyWorld(t("Working group", "Çalışma grubu"), agents)
                    world.make_everyone_accessible()
                    world.broadcast(question)
                    for step, actions_by_agent in enumerate(
                        world.run(self.steps.value, return_actions=True,
                                  randomize_agents_order=False, parallelize=False), start=1
                    ):
                        for agent_name, actions in actions_by_agent.items():
                            reply = _spoken(actions)
                            label = t(f"Round {step} · {agent_name}", f"Tur {step} · {agent_name}")
                            results.append((label, reply))
                            print(f"{label}: {reply}\n")

                elapsed = monotonic() - started
                print(t(f"Time: {elapsed:.1f} s", f"Süre: {elapsed:.1f} sn"))
                if self.save.value:
                    report = self._save_report(model, scenario, question,
                                               personas, images, results, elapsed)
                    print(t(f"Report: {report}", f"Rapor: {report}"))

                self.last_agents = agents
                self.last_world = world
                shell = get_ipython()
                if shell is not None:
                    shell.user_ns["last_agents"] = agents
                    shell.user_ns["last_world"] = world
                with self.chat_output:
                    clear_output(wait=True)
                    print(t("You can keep chatting with these agents:", "Bu ajanlarla sohbet etmeye devam edebilirsiniz:"))
                    AgentChatJupyterWidget(agents).display()
            except Exception as error:
                print(t("Run error", "Çalıştırma hatası") + f": {type(error).__name__}: {str(error)[:220]}")
            finally:
                self.run_button.disabled = False

    def display(self):
        display(widgets.VBox([
            widgets.HTML(t("<h2>TinyTroupe workspace</h2><p>Change the inputs and press Run. The model is only called when you press the button.</p>",
                         "<h2>TinyTroupe çalışma alanı</h2><p>Girdileri değiştirin ve Çalıştır'a basın. Model çağrısı yalnız düğmeye basınca yapılır.</p>")),
            self.model, self.scenario, self.question,
            widgets.HTML(t("<h3>Personas</h3>", "<h3>Personalar</h3>")), self.persona_box, self.add_button,
            widgets.HTML(t("<h3>Images and method</h3>", "<h3>Görsel ve yöntem</h3>")), self.images,
            widgets.HBox([self.mode, self.steps]), self.save, self.run_button,
            self.output, self.chat_output,
        ], layout=widgets.Layout(width="100%")))


def show():
    playground = Playground()
    playground.display()
    return playground
