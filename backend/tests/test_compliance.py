"""Соответствие правилам кейса (слайды 12, 18): только разрешённые LLM, без внешних AI-сервисов и готовых агентов."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# SDK внешних AI-сервисов, готовые агентные и мультиагентные фреймворки, локальный запуск произвольных LLM
FORBIDDEN = ["openai", "anthropic", "langchain", "langgraph", "llama-index", "llama_index", "autogen", "crewai",
             "semantic-kernel", "haystack", "transformers", "vllm", "ollama", "litellm", "google-generativeai",
             "gigachat", "yandex-cloud-ml-sdk", "mistralai", "cohere"]


def test_no_forbidden_packages_in_lock():
    pinned = {line.split("==")[0].strip().lower() for line in (ROOT / "requirements.lock").read_text().splitlines()
              if "==" in line and not line.startswith("#")}
    assert not pinned & set(FORBIDDEN), pinned & set(FORBIDDEN)


def test_no_forbidden_imports_in_code():
    bad = []
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(?:from|import)\s+([\w.]+)", line)
            if m and m.group(1).split(".")[0].replace("_", "-") in FORBIDDEN + [f.replace("-", "_") for f in FORBIDDEN]:
                bad.append(f"{path.name}:{n}: {line.strip()}")
    assert not bad, bad


def test_allow_list_is_exactly_the_case_list():
    from app import llm_client

    assert set(llm_client.ALLOWED_MODELS) == {"google/gemma-4-26b-a4b-it", "z-ai/glm-5.3-flash",
                                              "qwen/qwen3.6-35b-a3b", "deepseek/deepseek-v4.1-flash",
                                              "qwen/qwen3-vl-30b-a3b-instruct", "moonshotai/kimi-k2.6"}
    assert {v["label"] for v in llm_client.ALLOWED_MODELS.values()} == {
        "Gemma 4 26B A4B", "GLM-5.3-Flash", "Qwen3.6 35B A3B", "DeepSeek-V4.1-Flash", "Qwen3-VL-30B-A3B-Instruct",
        "Kimi-K2.6"}, "названия кейса остаются подписями и псевдонимами"
