"""Недоверенный текст (новости, документы, цитаты из них) в запросе к модели — данные, а не команды.

Общий для агента и сервисов 3–4 (app/services/); ничего не импортирует, поэтому не связывает сервисы между собой.
- looks_like_injection — строка похожа на попытку дать инструкции ИИ («игнорируй предыдущие инструкции»…);
- wrap — текст в теге <untrusted_…>: строки-инструкции выброшены, угловые скобки заменены, тег не закрыть изнутри.
"""
import re

INJECTION_PATTERNS = [
    r"игнорир\w* (все )?(предыдущ|прошл)\w* инструкц",
    r"ignore (all )?(previous|prior) instructions",
    r"системн\w* (промпт|инструкц)",
    r"system prompt",
    r"для (автоматических|ии|ai)[- ]?(систем|моделей|ассистент)",
    r"присвой\w* .{0,40}приоритет",
    r"ты\s*[-—]\s*(теперь|больше не)",
    r"you are now",
]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


def looks_like_injection(text):
    t = _norm(text)
    return any(re.search(p, t) for p in INJECTION_PATTERNS)


def wrap(tag, text):
    """Текст для модели внутри <tag>…</tag>: без строк-инструкций и без угловых скобок."""
    lines = [ln for ln in str(text or "").splitlines() if not looks_like_injection(ln)]
    body = "\n".join(lines).replace("<", "‹").replace(">", "›")
    return f"<{tag}>\n{body}\n</{tag}>"
