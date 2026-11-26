"""One isolated TinyTroupe run; receives its inputs over stdin."""

import json
import os
import sys
from time import monotonic
from urllib.parse import urlsplit


PREFIX = "@@TINY_PLAYGROUND@@"


def emit(kind, **data):
    print(PREFIX + json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


def spoken(actions):
    lines = []
    for item in actions or []:
        action = item.get("action", item)
        if action.get("type") == "TALK" and action.get("content"):
            lines.append(str(action["content"]).strip())
    return "\n".join(lines) or "(Sözlü yanıt gelmedi.)"


def run(payload):
    gateway = payload.pop("base_url")
    os.environ["OPENAI_BASE_URL"] = gateway
    gateway_host = urlsplit(gateway).hostname or ""
    os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), gateway_host]))
    secret = payload.pop("api_key")
    os.environ["OPENAI_API_KEY"] = secret
    started = monotonic()

    from tinytroupe import config_manager, utils
    from tinytroupe.agent import TinyPerson
    from tinytroupe.environment import TinyWorld

    config_manager.update("api_type", "openai")
    config_manager.update("model", payload["model"])
    config_manager.update("vision_model", payload["model"])
    config_manager.update("timeout", 180)
    config_manager.update("max_attempts", 2)
    config_manager.update("cache_api_calls", False)
    config_manager.update("enable_memory_consolidation", False)
    config_manager.update("enable_continuous_contextual_semantic_memory_retrieval", False)
    original_extract = utils.extract_json

    def extract_json_preserving_turkish(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return original_extract(value)

    utils.extract_json = extract_json_preserving_turkish
    TinyPerson.clear_agents()
    TinyWorld.clear_environments()
    TinyPerson.communication_display = False
    TinyWorld.communication_display = False
    agents = []
    for person in payload["personas"]:
        emit("progress", message=f"{person['name']} hazırlanıyor…")
        agent = TinyPerson(person["name"])
        agent.include_persona_definitions({
            "occupation": person["role"],
            "professional_context": person["profile"],
        })
        agent.listen(payload["scenario"], communication_display=False)
        for image in payload["images"]:
            agent.see(images=image["data"], description=image["name"])
        agents.append(agent)

    results = []
    if payload["mode"] == "interview":
        for agent in agents:
            emit("progress", message=f"{agent.name} yanıtlıyor…")
            agent.listen(payload["question"], communication_display=False)
            reply = spoken(agent.act(return_actions=True, communication_display=False))
            results.append({"label": agent.name, "reply": reply})
            emit("progress", message=f"{agent.name} tamamlandı.")
    elif payload["mode"] == "world":
        world = TinyWorld("Çalışma grubu", agents)
        world.make_everyone_accessible()
        world.broadcast(payload["question"])
        for step in range(1, payload["steps"] + 1):
            emit("progress", message=f"Grup turu {step}/{payload['steps']} çalışıyor…")
            for actions_by_agent in world.run(1, return_actions=True,
                                              randomize_agents_order=False, parallelize=False):
                for agent_name, actions in actions_by_agent.items():
                    results.append({"label": f"Tur {step} · {agent_name}", "reply": spoken(actions)})
            emit("progress", message=f"Grup turu {step} tamamlandı.")
    else:
        from tinytroupe.agent.mental_faculty import TinyToolUse
        from local_browser import LocalBrowserTool, guard, launch_browser, start_display, stop_display

        target = payload["target_url"]
        emit("progress", message="Sanal tarayıcı ekranı hazırlanıyor…")
        display = start_display(payload.pop("vnc_password"))
        playwright = browser = None
        try:
            playwright, browser = launch_browser()
            # service_workers can only be set at creation, so it covers the login phase too.
            context = browser.new_context(locale="tr-TR", no_viewport=True, service_workers="block")
            page = context.new_page()
            page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            emit("waiting_login", message="Tarayıcı ekranında giriş yapın, ardından 'Girişi tamamladım'a basın.")
            if sys.stdin.readline().strip() != "continue":
                raise RuntimeError("Giriş beklenirken uygulama bağlantısı kesildi.")
            context.cookies()  # one round trip so tabs opened or closed during readline() are registered
            if page.is_closed():
                page = context.pages[0] if context.pages else context.new_page()
            for other in context.pages:
                if other != page:
                    other.close()
            blocked = []
            guard(context, target, payload["allow_writes"], blocked)
            context.on("page", lambda extra: extra.close())  # the tool only watches the first page
            for agent in agents:
                emit("progress", message=f"{agent.name} siteyi geziyor…")
                blocked.clear()
                # Also drops sockets opened while logging in, before the guard existed.
                page.goto(target, wait_until="domcontentloaded", timeout=20_000)
                tool = LocalBrowserTool(
                    page, target, payload["allow_writes"], payload["steps"],
                    progress=lambda message: emit("progress", message=f"{agent.name}: {message}"),
                )
                agent.add_mental_faculty(TinyToolUse([tool]))
                agent.listen(payload["question"] + " Sitedeki ekranları kendin incele; bulgularını anlat.", communication_display=False)
                tool.observe(agent)
                answers = []
                for _ in range(payload["steps"] * 3):
                    actions = agent.act(until_done=False, n=1, return_actions=True,
                                        communication_display=False)
                    reply = spoken(actions)
                    if reply != "(Sözlü yanıt gelmedi.)":
                        answers.append(reply)
                    if tool.actions_used >= payload["steps"] or any(
                        item.get("action", item).get("type") == "DONE" for item in actions or []
                    ):
                        break
                agent.listen("Gezinme adımları bitti. Gördüğün arayüzü değerlendir; eksik veya belirsiz bulduğun noktaları Türkçe ve kısa anlat.", communication_display=False)
                for _ in range(3):
                    actions = agent.act(until_done=False, n=1, return_actions=True,
                                        communication_display=False)
                    reply = spoken(actions)
                    if reply != "(Sözlü yanıt gelmedi.)":
                        answers.append(reply)
                        break
                results.append({"label": agent.name, "reply": "\n\n".join(answers) or "(Sözlü yanıt gelmedi.)",
                                "trace": [item.get("action") or item.get("url", "") for item in tool.history],
                                "blocked_requests": list(blocked)})
                emit("progress", message=f"{agent.name} gezintiyi tamamladı.")
        finally:
            if browser:
                browser.close()
            if playwright:
                playwright.stop()
            stop_display(display)

    return {"model": payload["model"], "mode": payload["mode"],
            "elapsed_seconds": round(monotonic() - started, 1), "results": results}


if __name__ == "__main__":
    try:
        emit("result", data=run(json.loads(sys.stdin.readline())))
    except Exception as exc:
        message = str(exc).replace(os.environ.get("OPENAI_API_KEY", "\0"), "[gizli]")
        emit("error", message=f"{type(exc).__name__}: {message[:240]}")
