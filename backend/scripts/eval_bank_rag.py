"""Контрольные вопросы к 9 материалам аналитики банка: TF-IDF против e5 и гибрида (docs/REVIEW.md).

    cd backend
    python -m scripts.eval_bank_rag

Для каждого вопроса известен документ, где ответ (по чтению материалов). Метрики на уровне документа: попадание
в первую позицию (hit@1), в первые три (hit@3), средний обратный ранг (MRR).
"""
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


def main():
    from app import embeddings

    if not embeddings.available():
        print("веса e5 не найдены: python -m scripts.download_embeddings", file=sys.stderr)
    for name, qs in (("контрольные (10)", QUESTIONS), ("перефразированные (5)", PARAPHRASES)):
        print(name)
        for method in ("tfidf", "e5", "hybrid"):
            m, rows = evaluate(method, questions=qs)
            print(f"  {method}: {m}")
            for q, gold, rank, top in rows:
                print(f"     {'✓' if rank == 1 else rank or '✗'}  {q[:58]} -> {', '.join(d[:22] for d in top)}")


if __name__ == "__main__":
    main()
