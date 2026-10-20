"""Промпты агента — отдельные файлы с версиями: app/prompts/<имя>@v<N>.txt.

Новая версия — новый файл (старые остаются для воспроизводимости). Используется последняя версия, если в .env не
закреплена другая: PROMPT_AGENT_ANSWER=v1. Версия промпта попадает в трассировку агента, в ответ и в ключ кэша.
"""
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def id(self):
        return f"{self.name}@{self.version}"

    def render(self, **values):
        return Template(self.text).safe_substitute(**values)


@lru_cache(maxsize=None)
def _versions(name):
    out = {}
    for p in DIR.glob(f"{name}@v*.txt"):
        m = re.fullmatch(rf"{re.escape(name)}@(v\d+)\.txt", p.name)
        if m:
            out[m.group(1)] = p.read_text(encoding="utf-8").strip()
    if not out:
        raise KeyError(f"нет промпта {name} в {DIR}")
    return out


def get(name):
    versions = _versions(name)
    pinned = os.getenv(f"PROMPT_{name.upper()}")
    version = pinned if pinned in versions else max(versions, key=lambda v: int(v[1:]))
    return Prompt(name, version, versions[version])


def catalog():
    return [{"name": p.stem.split("@")[0], "version": p.stem.split("@")[1]} for p in sorted(DIR.glob("*@v*.txt"))]
