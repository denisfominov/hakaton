from backend.analysis.bank import BankAnalytics, load_source
from backend.bank.search import AlfaBankAnalytics

KEY_RATE = ("\u0411\u0430\u043d\u043a \u0420\u043e\u0441\u0441\u0438\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443 \u043d\u0430 \u0443\u0440\u043e\u0432\u043d\u0435 14% \u0433\u043e\u0434\u043e\u0432\u044b\u0445. \u0420\u0435\u0433\u0443\u043b\u044f\u0442\u043e\u0440 \u0443\u0436\u0435\u0441\u0442\u043e\u0447\u0438\u043b \u0440\u0438\u0442\u043e\u0440\u0438\u043a\u0443 \u0438 "
            "\u043d\u0435 \u0441\u043f\u0435\u0448\u0438\u0442 \u0441\u043d\u0438\u0436\u0430\u0442\u044c \u0441\u0442\u0430\u0432\u043a\u0443, \u043a\u0440\u0435\u0434\u0438\u0442\u044b \u0434\u043b\u044f \u0431\u0438\u0437\u043d\u0435\u0441\u0430 \u043e\u0441\u0442\u0430\u044e\u0442\u0441\u044f \u0434\u043e\u0440\u043e\u0433\u0438\u043c\u0438. ") * 2
STEEL = ("\u0426\u0435\u043d\u044b \u043d\u0430 \u0441\u0442\u0430\u043b\u044c \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u044e\u0442 \u0440\u0430\u0441\u0442\u0438, \u0440\u043e\u0441\u0441\u0438\u0439\u0441\u043a\u0438\u0435 \u043c\u0435\u0442\u0430\u043b\u043b\u0443\u0440\u0433\u0438 \u0443\u0432\u0435\u043b\u0438\u0447\u0430\u0442 \u0432\u044b\u0440\u0443\u0447\u043a\u0443 \u0438 \u043f\u0440\u0438\u0431\u044b\u043b\u044c \u0431\u043b\u0430\u0433\u043e\u0434\u0430\u0440\u044f \u044d\u043a\u0441\u043f\u043e\u0440\u0442\u0443 "
         "\u0441\u0442\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u043a\u0430\u0442\u0430 \u0438 \u0432\u044b\u0441\u043e\u043a\u0438\u043c \u0446\u0435\u043d\u0430\u043c \u043d\u0430 \u043c\u0435\u0442\u0430\u043b\u043b. ") * 2
GOLD = ("\u0417\u043e\u043b\u043e\u0442\u043e \u0437\u0430\u043c\u0435\u0442\u043d\u043e \u0432\u044b\u0440\u043e\u0441\u043b\u043e \u0437\u0430 \u0430\u0432\u0433\u0443\u0441\u0442, \u0446\u0435\u043d\u0430 \u0443\u043d\u0446\u0438\u0438 \u043f\u043e\u0434\u043d\u044f\u043b\u0430\u0441\u044c \u043f\u043e\u0441\u043b\u0435 \u0441\u043b\u0430\u0431\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0445 \u043f\u043e \u0437\u0430\u043d\u044f\u0442\u043e\u0441\u0442\u0438 \u0432 \u0421\u0428\u0410, "
        "\u0446\u0435\u043d\u0442\u0440\u0430\u043b\u044c\u043d\u044b\u0435 \u0431\u0430\u043d\u043a\u0438 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u044e\u0442 \u043f\u043e\u043a\u0443\u043f\u0430\u0442\u044c \u0437\u043e\u043b\u043e\u0442\u043e. ") * 2


def bank_folder(tmp_path):
    for name, page in [("ALFA-Macro_Insights-Policy_Rate_11Sep", KEY_RATE), ("Gold_digest_August26", GOLD),
                       ("ALFA_Russian_Steels_1\u041a21PreviewUpdate_15Apr2021", STEEL)]:
        (tmp_path / f"{name}.ocr.txt").write_text(f"{page}\f{page}", encoding="utf-8")
    return tmp_path


def test_finds_document_on_topic(tmp_path):
    found = AlfaBankAnalytics(bank_folder(tmp_path)).search("\u0426\u0411 \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b \u043a\u043b\u044e\u0447\u0435\u0432\u0443\u044e \u0441\u0442\u0430\u0432\u043a\u0443", ["key_rate"])
    assert found and found[0].document == "key_rate_0911"
    assert found[0].published_at.date().isoformat() == "2026-09-11" and "key_rate" in found[0].factors


def test_outdated_document_is_marked_and_ranked_lower(tmp_path):
    source = AlfaBankAnalytics(bank_folder(tmp_path))
    steel = source.search("\u0446\u0435\u043d\u044b \u043d\u0430 \u0441\u0442\u0430\u043b\u044c \u0438 \u043c\u0435\u0442\u0430\u043b\u043b", [])
    assert steel[0].document == "steel_1q21" and steel[0].title.endswith("(\u0434\u0430\u043d\u043d\u044b\u0435 2021 \u0433\u043e\u0434\u0430)")
    flags = {p.document_id: flag for p, flag in zip(source.passages, source.outdated)}
    assert flags == {"key_rate_0911": False, "gold_2608": False, "steel_1q21": True}
    penalized = source._score("\u0446\u0435\u043d\u044b \u043d\u0430 \u0441\u0442\u0430\u043b\u044c \u0438 \u043c\u0435\u0442\u0430\u043b\u043b", [])
    source.outdated = [False] * len(source.passages)
    plain = source._score("\u0446\u0435\u043d\u044b \u043d\u0430 \u0441\u0442\u0430\u043b\u044c \u0438 \u043c\u0435\u0442\u0430\u043b\u043b", [])
    steel = [i for i, p in enumerate(source.passages) if p.document_id == "steel_1q21"]
    assert all(penalized[i] < plain[i] for i in steel)


def test_unrelated_query_returns_nothing_and_limits_hold(tmp_path):
    source = AlfaBankAnalytics(bank_folder(tmp_path))
    assert source.search("\u0444\u0443\u0442\u0431\u043e\u043b\u044c\u043d\u044b\u0439 \u043a\u043b\u0443\u0431 \u0432\u044b\u0438\u0433\u0440\u0430\u043b \u0447\u0435\u043c\u043f\u0438\u043e\u043d\u0430\u0442", []) == []
    unfiltered = AlfaBankAnalytics(bank_folder(tmp_path), min_score=0.0)
    found = unfiltered.search("\u0446\u0435\u043d\u044b \u0440\u043e\u0441\u0442", ["key_rate", "commodities:gold", "commodities:metals"], limit=5)
    assert 0 < len(found) <= 5
    assert max(sum(1 for p in found if p.document == d) for d in {p.document for p in found}) <= 2


def test_empty_folder_and_teammate_interface(tmp_path):
    assert AlfaBankAnalytics(tmp_path).search("\u043a\u043b\u044e\u0447\u0435\u0432\u0430\u044f \u0441\u0442\u0430\u0432\u043a\u0430", ["key_rate"]) == []
    assert isinstance(AlfaBankAnalytics(tmp_path), BankAnalytics)
    assert load_source("backend.bank.search:AlfaBankAnalytics").name == "alfa_bank"
