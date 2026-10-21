"""Сервис 4 — объяснение для руководителя (C20.6). Задача 3 брифа.

Вход: только MatchResult (сервис 3) и роль читателя (по желанию: {"key", "label", "focus"}). Выход: Interpretation
(app/schemas/contracts.py). Сервис не видит профиль, новости и правила напрямую (tests/test_service_boundaries.py),
поэтому не может добавить сведений, которых нет в результате сопоставления.

- С моделью: одна из шести разрешённых LLM через llm_client (задача роутера «interpret», промпт interpretation).
  Вход — в теге <untrusted_match>: в нём цитаты новостей, это данные, а не команды. После ответа код проверяет
  каждое утверждение: ссылки только на элементы входа (news:, p:, link:, assumption:, score), числа и названия — только
  из входа; утверждение без опоры отбрасывается. Неопределённость не может быть ниже посчитанной по входу.
- Без модели (выключена, нет бюджета, ошибка) — то же объяснение по шаблону из MatchResult, mode = template.
"""
import json
import re

from .. import llm_client, prompts
from ..llm_errors import LLMError
from ..schemas.contracts import Interpretation
from ..untrusted import wrap

LEVELS = ["low", "medium", "high"]
LEVEL_LABEL = {"critical": "критическая", "high": "высокая", "medium": "средняя", "low": "низкая"}
NUM = re.compile(r"\d+(?:[.,]\d+)?")
# служебные слова, которые модель пишет с заглавной внутри фразы («…банке. Цитата: …») — не названия
GENERIC = {"Цитата", "Допущение", "Связь", "Риск", "Возможность", "Факт", "Рекомендация", "Итог", "Вывод", "Важно",
           "Компания", "Новость", "Событие", "Значимость", "Неопределённость", "Неопределенность"}


def refs_allowed(match):
    return ({f"news:{n['event_id']}" for n in match["news"]} | set(match["facts_used"])
            | {f"link:{i}" for i in range(len(match["links"]))}
            | {f"assumption:{i}" for i in range(len(match["assumptions"]))} | {"score"})


def match_text(match, role=None):
    """Вход модели — только результат сопоставления (и роль). Пронумерованные связи и допущения — для ссылок."""
    s = match["score"]
    lines = [f"TITLE [news:{match['news'][0]['event_id']}]: {match['title']}"]
    for n in match["news"][:4]:
        lines.append(f"NEWS [news:{n['event_id']}] {n['source']}, {n['published_at'][:10]}: {n.get('summary') or ''}")
    lines.append(f"SCORE [score]: приоритет {s['priority']}/100 ({s['priority_level']}), тип влияния {s['impact_type']}, "
                 f"срочность {s['urgency_level']}; {match['explanation']}")
    for f in match.get("profile_facts") or []:
        lines.append(f"FACT [{f['id']}] {f['label']}: {f['value']}")
    for i, x in enumerate(match["links"]):
        lines.append(f"LINK [link:{i}] факт {x['fact_id']}; цитата: «{x['news_quote']}»; {x['explanation']}")
    for i, x in enumerate(match["assumptions"]):
        lines.append(f"ASSUMPTION [assumption:{i}] {x['text']} (почему допущение: {x['reason']})")
    lines.append(f"LLM_LINKS: {match['llm']['status']}" + (f" — {match['llm'].get('reason')}" if match["llm"].get("reason") else ""))
    out = wrap("untrusted_match", "\n".join(lines))
    if role:
        out += f"\nРОЛЬ: {role.get('label')} — акцент: {role.get('focus', '')}"
    return out


def computed_uncertainty(match):
    """Неопределённость по входу: проверены ли связи, сколько изданий, сколько допущений."""
    reasons, level = [], 0
    if match["llm"]["status"] in ("not_checked", "failed"):
        reasons.append("связи с профилем не проверены моделью")
        level = max(level, 1)
    if not match["links"]:
        reasons.append("в тексте новости нет дословной связи с фактами профиля")
        level = max(level, 2 if match["score"]["relevance"] < 25 else 1)
    if len({n["source"] for n in match["news"]}) < 2:
        reasons.append("событие подтверждает одно издание")
        level = max(level, 1)
    if match["assumptions"]:
        reasons.append(f"допущений: {len(match['assumptions'])}")
    return LEVELS[level], reasons


def _st(text, kind, refs):
    return {"text": text, "kind": kind, "refs": refs}


def template(match, role=None, trace=None):
    """Объяснение без модели — только из элементов MatchResult."""
    s, news0 = match["score"], f"news:{match['news'][0]['event_id']}"
    facts = {f["id"]: f for f in match.get("profile_facts") or []}
    happened = [_st(match["title"] + (f". {match['news'][0]['summary']}" if match["news"][0].get("summary") else ""),
                    "fact", [news0])]
    if len(match["news"]) > 1:
        happened.append(_st(f"О событии пишут {len({n['source'] for n in match['news']})} издания: "
                            + ", ".join(sorted({n["source"] for n in match["news"]})), "fact",
                            [f"news:{n['event_id']}" for n in match["news"]]))
    why = [_st(f"{facts[x['fact_id']]['label'] if x['fact_id'] in facts else x['fact_id']}: {x['explanation']} "
               f"Цитата: «{x['news_quote']}».", "link", [f"link:{i}", x["fact_id"], news0])
           for i, x in enumerate(match["links"])]
    why += [_st(f"Допущение: {x['text']}", "assumption", [f"assumption:{i}"] + x["fact_ids"])
            for i, x in enumerate(match["assumptions"])]
    if not why:
        why.append(_st(match["explanation"], "fact", ["score"] + match["facts_used"][:3]))
    level = s["priority_level"]
    todo_text = {"critical": "Разобрать влияние в ближайшие дни: проверить, какие договоры, расчёты и планы оно задевает.",
                 "high": "Оценить влияние на неделе: проверить затронутые расчёты и планы.",
                 "medium": "Отслеживать развитие: вернуться к событию, если появятся новые публикации.",
                 "low": "Держать в поле зрения: прямого влияния по данным не видно."}[level]
    if role:
        todo_text = f"{role.get('label')}: {todo_text[0].lower()}{todo_text[1:]}"
    todo = [_st(todo_text, "recommendation", ["score"])]
    unc_level, reasons = computed_uncertainty(match)
    not_known = ["прямой связи новости с фактами профиля в тексте нет"] if not match["links"] else []
    return Interpretation.model_validate({
        "profile_id": match["profile_id"], "event_id": match["event_id"], "role": (role or {}).get("key"),
        "headline": f"{match['title']} — значимость {LEVEL_LABEL[level]} ({s['priority']}/100)",
        "what_happened": happened, "why_it_matters": why, "what_to_do": todo,
        "uncertainty": {"level": unc_level, "reasons": reasons}, "not_known": not_known, "mode": "template",
        "llm": trace or {"status": "not_checked", "reason": "объяснение по шаблону, без языковой модели"}}).model_dump()


def _stem_set(text):
    return {w.lower()[:5] for w in re.findall(r"[\wА-Яа-яЁё-]{3,}", text or "")}


def new_names(text, stems, first_too=False):
    """Слова с заглавной буквы (названия, организации), которых нет во входе. Обычно — внутри фразы; в разделе
    «что произошло» (факты новости) — и первое слово: там новое название — это новый факт."""
    out = set()
    for chunk in re.split(r"[.!?:;—«»()\n]+", text):
        for w in re.findall(r"[\w-]+", chunk)[0 if first_too else 1:]:
            if len(w) >= 3 and w[0].isupper() and w not in GENERIC and w.lower()[:5] not in stems:
                out.add(w)
    return out


def check(out, match, role=None):
    """Проверка ответа модели кодом. Возвращает (разделы, отброшено)."""
    allowed_refs = refs_allowed(match)
    source = json.dumps(match, ensure_ascii=False) + (json.dumps(role, ensure_ascii=False) if role else "")
    nums, stems = {n.replace(",", ".") for n in NUM.findall(source)}, _stem_set(source)
    kinds = {"what_happened": {"fact"}, "why_it_matters": {"link", "assumption", "fact", "uncertainty"},
             "what_to_do": {"recommendation"}}
    sections, dropped = {}, 0
    for key, ok_kinds in kinds.items():
        items = []
        for x in (out.get(key) or [])[:6]:
            if not isinstance(x, dict) or not str(x.get("text") or "").strip():
                dropped += 1
                continue
            text, refs = str(x["text"]).strip(), [r for r in x.get("refs") or [] if r in allowed_refs]
            new_nums = {n.replace(",", ".") for n in NUM.findall(text)} - nums
            if not refs or new_nums or new_names(text, stems, first_too=key == "what_happened"):
                dropped += 1  # нет опоры на вход, число или название не из входа
                continue
            kind = x.get("kind") if x.get("kind") in ok_kinds else sorted(ok_kinds)[0]
            if key == "why_it_matters" and kind == "link" and not any(r.startswith("link:") for r in refs):
                kind = "assumption"  # «связь» без подтверждённой связи — допущение
            items.append({"text": text, "kind": kind, "refs": refs})
        sections[key] = items
    return sections, dropped


def interpret(match, role=None, conn=None, use_llm=True):
    """Interpretation по результату сопоставления. Без модели или при ошибке — шаблон."""
    if not (use_llm and llm_client.enabled()):
        reason = ("языковая модель выключена — объяснение по шаблону" if not llm_client.enabled()
                  else "объяснение моделью не запрашивалось — по шаблону")
        return template(match, role, {"status": "not_checked", "reason": reason})
    prompt = prompts.get("interpretation")
    messages = [{"role": "system", "content": prompt.text}, {"role": "user", "content": match_text(match, role)}]
    try:
        out, usage = llm_client.chat_json(
            messages, task="interpret", purpose="interpretation", conn=conn, max_tokens=1200, temperature=0.2,
            prompt_version=prompt.id,
            cache={"event_id": match["event_id"], "profile_id": f"{match['profile_id']}|{(role or {}).get('key', '')}"})
    except LLMError as e:
        return template(match, role, {"status": "failed", "prompt": prompt.id, "reason": f"{e} — объяснение по шаблону"})
    out = out if isinstance(out, dict) else {}
    sections, dropped = check(out, match, role)
    base = template(match, role)
    if not sections.get("why_it_matters"):
        sections["why_it_matters"] = base["why_it_matters"]  # модель не дала проверяемых утверждений — шаблон
    for key in ("what_happened", "what_to_do"):
        sections[key] = sections.get(key) or base[key]
    computed, reasons = computed_uncertainty(match)
    model_level = (out.get("uncertainty") or {}).get("level")
    level = max(computed, model_level if model_level in LEVELS else computed, key=LEVELS.index)
    model_reasons = [str(r) for r in (out.get("uncertainty") or {}).get("reasons") or [] if str(r).strip()][:4]
    headline = str(out.get("headline") or "").strip()
    if not headline or {n for n in NUM.findall(headline)} - {n for n in NUM.findall(json.dumps(match, ensure_ascii=False))}:
        headline = base["headline"]
    return Interpretation.model_validate({
        "profile_id": match["profile_id"], "event_id": match["event_id"], "role": (role or {}).get("key"),
        "headline": headline, **sections,
        "uncertainty": {"level": level, "reasons": list(dict.fromkeys(reasons + model_reasons))},
        "not_known": [str(x) for x in out.get("not_known") or [] if str(x).strip()][:5] or base["not_known"],
        "mode": "llm",
        "llm": {"status": "cached" if usage.get("cached") else "done", "model": usage.get("model"), "prompt": prompt.id,
                "cost_rub": usage.get("cost_rub", 0.0), "dropped": dropped,
                "mock": llm_client.provider() == "mock"}}).model_dump()
