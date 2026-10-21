"""C9: самопроверка сама добавляет шаги по тому, чего не хватило, у каждого шага — причина, и найденное видно в ответе
(агентная логика, требование 4; критерии 09, 10)."""
from app import agent, agent_tools


def checks(res):
    return [s for s in res["trace"] if s["kind"] == "check"]


def added(res):
    return [(t, w) for s in checks(res) for t, w in zip(s.get("extra") or [], s.get("why") or [])]


def test_single_outlet_is_not_searched_upfront(conn, profiles):
    ctx = agent.Ctx(conn, profiles["uralmet"], agent.pipeline.find_result(conn, profiles["uralmet"], "demo-05"))
    assert "search_news" not in [t for t, _a, _w in agent.heuristic_plan(ctx)], "подтверждения ищет самопроверка"


def test_no_confirmation_leads_to_search_and_honest_gap(conn, profiles):
    res = agent.run(conn, profiles["uralmet"], "demo-05", use_llm=False, save=False)
    steps = added(res)
    assert steps[0] == ("search_news", "одно издание — ищем подтверждения в других изданиях")
    assert all(w for _t, w in steps), "у каждого добавленного шага есть причина"
    tools = [s.get("tool") for s in res["trace"] if s["kind"] == "tool"]
    assert "search_news" in tools, "добавленный шаг выполнен"
    # в том же сюжете других изданий нет — честный пробел, а не «подтверждение» посторонней новостью
    assert agent.NO_CONFIRMATION in res["result"]["data_gaps"]
    assert not any(w["text"].startswith("Сюжет освещают") for w in res["result"]["answers"]["what_happened"])


def test_found_confirmation_is_shown_in_answer(conn, profiles, monkeypatch):
    # поиск нашёл публикацию того же сюжета в другом издании и постороннюю с похожими словами заголовка
    tool = agent_tools.TOOLS["search_news"]
    found = [{"id": "x1", "title": "Тот же сюжет", "source": "Другое издание", "date": "2026-10-20", "url": None,
              "same_thread": True},
             {"id": "x2", "title": "Совпали только слова", "source": "Постороннее издание", "date": "2026-10-20",
              "url": None, "same_thread": False}]

    def fake(ctx, query="", limit=5):  # как настоящий инструмент: источники регистрируются, иначе пункт не пройдёт проверку
        for h in found:
            ctx.source(f"news:{h['source']}", type="news", title=h["source"], url=None)
        ctx.data.setdefault("related", []).extend(found)
        return found, f"связанных публикаций: {len(found)}"

    monkeypatch.setattr(tool, "fn", fake)
    res = agent.run(conn, profiles["uralmet"], "demo-05", use_llm=False, save=False)
    assert ("search_news", "одно издание — ищем подтверждения в других изданиях") in added(res)
    conf = [w for w in res["result"]["answers"]["what_happened"] if w["text"].startswith("Сюжет освещают")]
    assert conf and conf[0]["text"] == "Сюжет освещают и другие издания: Другое издание."
    assert conf[0]["kind"] == "fact" and conf[0]["sources"] == ["news:Другое издание"]
    assert agent.NO_CONFIRMATION not in res["result"]["data_gaps"]


def test_question_outside_templates_triggers_text_search(conn, profiles):
    res = agent.run(conn, profiles["uralmet"], "demo-09", "Кто ещё из металлургов пострадал?", use_llm=False, save=False)
    assert ("search_news_rag", "вопрос вне типовых — ищем ответ в текстах новостей") in added(res)
    typed = agent.run(conn, profiles["uralmet"], "demo-09", "Какие риски для нас?", use_llm=False, save=False)
    assert not any(w.startswith("вопрос вне типовых") for _t, w in added(typed))
