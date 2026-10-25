from types import SimpleNamespace

from backend.analysis import bank, tools
from backend.bank.search import AlfaBankAnalytics
from backend.config import Settings, get_settings

KEY_RATE = ("\u0411\u0430\u043d\u043a \u0420\u043e\u0441\u0441\u0438\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443 \u043d\u0430 \u0443\u0440\u043e\u0432\u043d\u0435 14% \u0433\u043e\u0434\u043e\u0432\u044b\u0445. \u0420\u0435\u0433\u0443\u043b\u044f\u0442\u043e\u0440 \u0443\u0436\u0435\u0441\u0442\u043e\u0447\u0438\u043b \u0440\u0438\u0442\u043e\u0440\u0438\u043a\u0443 \u0438 "
            "\u043d\u0435 \u0441\u043f\u0435\u0448\u0438\u0442 \u0441\u043d\u0438\u0436\u0430\u0442\u044c \u0441\u0442\u0430\u0432\u043a\u0443, \u043a\u0440\u0435\u0434\u0438\u0442\u044b \u0434\u043b\u044f \u0431\u0438\u0437\u043d\u0435\u0441\u0430 \u043e\u0441\u0442\u0430\u044e\u0442\u0441\u044f \u0434\u043e\u0440\u043e\u0433\u0438\u043c\u0438. ") * 2


def test_bank_search_is_the_default_source():
    assert Settings.model_fields["bank_analytics"].default == "backend.bank.search:AlfaBankAnalytics"


def test_agent_tool_gets_bank_passages_with_page_reference(tmp_path, monkeypatch):
    folder = tmp_path / "bank"
    folder.mkdir()
    (folder / "ALFA-Macro_Insights-Policy_Rate_11Sep.ocr.txt").write_text(f"{KEY_RATE}\f{KEY_RATE}", encoding="utf-8")
    monkeypatch.setenv("COMPANY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BANK_ANALYTICS", "backend.bank.search:AlfaBankAnalytics")
    get_settings.cache_clear()
    bank.get_source.cache_clear()
    try:
        source = bank.get_source()
        assert isinstance(source, AlfaBankAnalytics)
        found = tools.bank_analytics(SimpleNamespace(bank=source), "\u0411\u0430\u043d\u043a \u0420\u043e\u0441\u0441\u0438\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443", ["key_rate"])
        assert found and found[0]["id"].startswith("key_rate_0911:p")
        assert found[0]["source"] == {"kind": "alfa_analytics", "ref": found[0]["id"]}
        assert found[0]["title"].startswith("\u041a\u043b\u044e\u0447\u0435\u0432\u0430\u044f \u0441\u0442\u0430\u0432\u043a\u0430 \u0426\u0411 \u0420\u0424")
    finally:
        get_settings.cache_clear()
        bank.get_source.cache_clear()
