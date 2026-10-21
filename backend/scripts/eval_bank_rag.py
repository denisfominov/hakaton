"""Контрольные вопросы к 9 материалам аналитики банка: TF-IDF против e5 и гибрида (docs/REVIEW.md, docs/b/RAG_EVAL.md).

    cd backend
    python -m scripts.eval_bank_rag
    python -m scripts.eval_bank_rag --questions data/overnight/f/questions_50.json

Без --questions — 15 вопросов, написанных людьми (документ, где ответ, — по чтению материалов). Метрики на уровне
документа: попадание в первую позицию (hit@1), в первые три (hit@3), средний обратный ранг (MRR).

С --questions — вопросы с ожидаемой страницей (scripts/overnight_bank_claims.py, ответ проверен по тексту страницы).
Метрики ещё и на уровне страницы. Правила проверки (лекции 4, 5 и 7 курса ML):
- вопросы делятся на настроечную (dev) и проверочную (test) части по странице: вопросы одной страницы — всегда в
  одной части. Пороги и параметры поиска (B1, B4) подбираем только на dev; test смотрим один раз после настройки
  (--part test);
- рядом — случайный выбор страницы и документа (точка отсчёта);
- разброс — бутстрэп по страницам: 95% интервал, на 50 вопросах один вопрос — это 2 п.п.
Вопросы составлены моделью по тексту страницы — оценка оптимистичная для поиска по словам; вопросы людей (15) —
проверка на другой формулировке.
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUESTIONS = [
    ("Какой прогноз Альфа-Банка по ключевой ставке на конец 2026 года?", "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"),
    ("Что происходит с доходностями ОФЗ после сентябрьского решения ЦБ?", "Бонд_Бриф_14092026.pdf"),
    ("Какой прогноз роста ВВП на 2026 год после слабого первого полугодия?", "ALFA-macro_stat1H26.pdf"),
    ("Подтверждают ли данные по рынку труда охлаждение экономики?", "ALFA-7M26.pdf"),
    ("Почему потребление на пике и что будет с розничными продажами во втором полугодии?", "ALFA-consumption.pdf"),
    ("Почему меняются цены на золото и что влияет на спрос на золото?", "Gold_digest_August26.pdf"),
    ("Какая недельная инфляция в конце августа и будет ли дефляция?", "Inflation_tracker_02.pdf"),
    ("Какую стратегию на долговом рынке банк предлагает на третий квартал?", "FI_Strategy_3Q26_22072026.pdf"),
    ("Какие ожидания по результатам российских производителей стали и ценам на прокат?",
     "ALFA_Russian_Steels_1К21PreviewUpdate_15Apr2021.pdf"),
    ("Как корпоративное кредитование и бюджет влияют на решения ЦБ по ставке?", "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"),
]

# те же темы, но без ключевых слов документов: проверка устойчивости к перефразированию (сильная сторона эмбеддингов)
PARAPHRASES = [
    ("Будут ли деньги в экономике дорогими до конца года?", "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"),
    ("Насколько охотно люди сейчас тратят деньги в магазинах?", "ALFA-consumption.pdf"),
    ("Как чувствуют себя компании, выплавляющие металл?", "ALFA_Russian_Steels_1К21PreviewUpdate_15Apr2021.pdf"),
    ("Стоит ли держать драгоценный металл как защиту сбережений?", "Gold_digest_August26.pdf"),
    ("Дорожают ли товары в магазинах прямо сейчас, неделя к неделе?", "Inflation_tracker_02.pdf"),
]


def evaluate(method, k=5, questions=None):
    from app import bank_rag

    hit1 = hit3 = rr = 0.0
    rows = []
    questions = questions or QUESTIONS
    for q, gold in questions:
        docs = []
        for h in bank_rag.search(q, k=k * 3, method=method):
            if h["doc"] not in docs:
                docs.append(h["doc"])
        rank = docs.index(gold) + 1 if gold in docs else None
        hit1 += rank == 1
        hit3 += bool(rank and rank <= 3)
        rr += 1 / rank if rank else 0
        rows.append((q, gold, rank, docs[:3]))
    n = len(questions)
    return {"hit@1": round(hit1 / n, 2), "hit@3": round(hit3 / n, 2), "mrr": round(rr / n, 3)}, rows


def part_of(doc, page):
    """dev или test по хешу страницы: вопросы одной страницы не попадают в обе части (утечка через соседей)."""
    return "dev" if int(hashlib.md5(f"{doc}|{page}".encode()).hexdigest(), 16) % 2 == 0 else "test"


def ranked(hits):
    """Порядок документов и страниц без повторов из выдачи поиска."""
    docs, pages = [], []
    for h in hits:
        if h["doc"] not in docs:
            docs.append(h["doc"])
        if (h["doc"], h["page"]) not in pages:
            pages.append((h["doc"], h["page"]))
    return docs, pages


def evaluate_pages(method, questions, k=5):
    """[{doc_rank, page_rank, ...}] по каждому вопросу; ранг None — не найден в выдаче."""
    from app import bank_rag
    rows = []
    for q in questions:
        docs, pages = ranked(bank_rag.search(q["question"], k=k * 3, method=method))
        gold = (q["doc"], q["page"])
        rows.append({"doc": q["doc"], "page": q["page"], "doc_rank": docs.index(q["doc"]) + 1 if q["doc"] in docs else None,
                     "page_rank": pages.index(gold) + 1 if gold in pages else None})
    return rows


def metrics(rows):
    n = len(rows) or 1
    hit = lambda key, k: sum(1 for r in rows if r[key] and r[key] <= k) / n  # noqa: E731
    return {"doc_hit@1": hit("doc_rank", 1), "doc_hit@3": hit("doc_rank", 3), "page_hit@1": hit("page_rank", 1),
            "page_hit@3": hit("page_rank", 3), "page_hit@5": hit("page_rank", 5),
            "page_mrr": sum(1 / r["page_rank"] for r in rows if r["page_rank"]) / n}


def bootstrap(rows, key, n_iter=2000, seed=2026):
    """95% интервал метрики: выборки страниц с возвращением (вопросы одной страницы — вместе)."""
    groups = {}
    for r in rows:
        groups.setdefault((r["doc"], r["page"]), []).append(r)
    keys = sorted(groups)
    rng = random.Random(seed)
    vals = []
    for _ in range(n_iter):
        sample = [r for g in (rng.choice(keys) for _ in keys) for r in groups[g]]
        vals.append(metrics(sample)[key])
    vals.sort()
    return vals[int(0.025 * n_iter)], vals[int(0.975 * n_iter) - 1]


def random_baseline(n_pages, n_docs):
    """Случайная страница / документ: вероятность попасть в первые k."""
    return {"doc_hit@1": 1 / n_docs, "doc_hit@3": min(1.0, 3 / n_docs), "page_hit@1": 1 / n_pages,
            "page_hit@3": 3 / n_pages, "page_hit@5": 5 / n_pages}


def report_pages(path, part):
    from app import bank_rag
    questions = json.loads(Path(path).read_text(encoding="utf-8"))
    for q in questions:
        q["part"] = part_of(q["doc"], q["page"])
    chosen = [q for q in questions if part == "all" or q["part"] == part]
    idx_pages = {(c["doc"], c["page"]) for c in bank_rag._ensure()["chunks"]}
    print(f"вопросов {len(chosen)} ({part}); всего dev {sum(q['part'] == 'dev' for q in questions)}, "
          f"test {sum(q['part'] == 'test' for q in questions)}; страниц в индексе {len(idx_pages)}, "
          f"документов {len({d for d, _p in idx_pages})}")
    cols = ["doc_hit@1", "doc_hit@3", "page_hit@1", "page_hit@3", "page_hit@5", "page_mrr"]
    print("| Способ | " + " | ".join(cols) + " | page_hit@3, 95% интервал |")
    print("|---" * (len(cols) + 2) + "|")
    base = random_baseline(len(idx_pages), len({d for d, _p in idx_pages}))
    print("| случайный выбор | " + " | ".join(f"{base[c]:.2f}" if c in base else "—" for c in cols) + " | — |")
    per_doc = {}
    for method in ("tfidf", "e5", "hybrid"):
        rows = evaluate_pages(method, chosen)
        m = metrics(rows)
        lo, hi = bootstrap(rows, "page_hit@3")
        print(f"| {method} | " + " | ".join(f"{m[c]:.2f}" for c in cols) + f" | {lo:.2f}–{hi:.2f} |")
        for r in rows:
            d = per_doc.setdefault(r["doc"], {})
            d.setdefault(method, []).append(bool(r["page_rank"] and r["page_rank"] <= 3))
    print("\npage_hit@3 по документам (вопросов: tfidf / e5 / hybrid):")
    for doc, d in sorted(per_doc.items()):
        n = len(d["tfidf"])
        print(f"| {doc} | {n} | " + " | ".join(f"{sum(d[m])}/{n}" for m in ("tfidf", "e5", "hybrid")) + " |")


def main():
    from app import embeddings

    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", help="JSON с вопросами и ожидаемой страницей (scripts/overnight_bank_claims.py)")
    ap.add_argument("--part", default="dev", choices=["dev", "test", "all"],
                    help="dev — для настройки; test — один раз после настройки; all — базовый замер до настроек")
    args = ap.parse_args()
    if not embeddings.available():
        print("веса e5 не найдены: python -m scripts.download_embeddings", file=sys.stderr)
    if args.questions:
        return report_pages(args.questions, args.part)
    for name, qs in (("контрольные (10)", QUESTIONS), ("перефразированные (5)", PARAPHRASES)):
        print(name)
        for method in ("tfidf", "e5", "hybrid"):
            m, rows = evaluate(method, questions=qs)
            print(f"  {method}: {m}")
            for q, gold, rank, top in rows:
                print(f"     {'✓' if rank == 1 else rank or '✗'}  {q[:58]} -> {', '.join(d[:22] for d in top)}")


if __name__ == "__main__":
    main()
