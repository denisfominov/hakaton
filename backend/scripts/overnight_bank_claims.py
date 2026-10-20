"""Этап (f): сырьё для B1/B4 — тезисы и числа аналитики банка по страницам и контрольные вопросы с ожидаемой страницей.

Материалы банка — картинки страниц без текстового слоя, поэтому каждая страница идёт в мультимодальную модель
(Qwen3-VL, единственная модель для изображений): тезисы и числа со страницы + 2 кандидата в контрольные вопросы.
Вопрос остаётся, только если его ответ дословно (или все его числа) есть в распознанном тексте этой страницы
(<имя>.ocr.txt) — проверка без модели. Итог — до 50 вопросов, по документам по кругу.

    cd backend
    LLM_PROVIDER=gateway LLM_TIMEOUT=300 LLM_MAX_OUTPUT_TOKENS=4000 caffeinate -i python -m scripts.overnight_bank_claims

Лимит этапа 50 ₽. Файлы — data/overnight/f/ (не в git: производные от материалов банка, PDF тоже не в git).
"""
import argparse
import base64
import json
import re
import sys
from collections import defaultdict

from scripts import batch_runner, case_env

STAGE_CAP = 50.0
OUT = batch_runner.WORK / "f"
N_QUESTIONS = 50
PROMPT = (
    "Это страница аналитического материала банка. Выпиши со страницы ключевые утверждения и числа — только то, что "
    "прямо написано или показано на странице (текст, таблицы, подписи графиков). Не додумывай.\n"
    "Затем предложи 2 контрольных вопроса по этой странице: ответ на каждый — число или короткая фраза (до 6 слов), "
    "дословно написанная на странице.\n"
    'Ответ — только JSON: {"claims": [{"text": "...", "numbers": ["..."]}], '
    '"questions": [{"q": "...", "answer": "..."}]}. Утверждений — не больше 8.'
)
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def norm(text):
    text = (text or "").lower().replace(" ", " ").replace("ё", "е")
    text = re.sub(r"(\d)\s+(\d{3})\b", r"\1\2", text)  # 1 234 -> 1234
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    return re.sub(r"\s+", " ", text).strip()


def nums(text):
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUM.findall(norm(text))}


def verified(answer, page_text):
    a, p = norm(answer).strip(" .«»\"'"), norm(page_text)
    if len(a) >= 2 and a in p:
        return "дословно"
    an = nums(answer)
    if an and len(a) <= 40 and an <= nums(page_text):
        return "числа"
    return None


def _png(raw, w, h, channels):
    """PNG из несжатых пикселей стандартной библиотекой (Pillow в окружении проекта нет)."""
    import struct
    import zlib
    stride = w * channels
    rows = b"".join(b"\x00" + raw[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", w, h, 8, {1: 0, 3: 2}[channels], 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def page_jpeg_b64(page, side=1600):
    """Самая большая картинка страницы -> JPEG (длинная сторона 1600) через sips (macOS) -> base64."""
    import subprocess
    import tempfile
    from pathlib import Path
    xo = page["/Resources"].get("/XObject")
    xo = xo.get_object() if xo is not None else {}
    imgs = [xo[k].get_object() for k in xo if xo[k].get_object().get("/Subtype") == "/Image"]
    if not imgs:
        return None
    o = max(imgs, key=lambda o: int(o["/Width"]) * int(o["/Height"]))
    w, h = int(o["/Width"]), int(o["/Height"])
    raw = o.get_data()
    channels = len(raw) // (w * h)
    if channels not in (1, 3) or int(o.get("/BitsPerComponent", 8)) != 8:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "p.png", Path(tmp) / "p.jpg"
        src.write_bytes(_png(raw, w, h, channels))
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", "-Z", str(side), str(src),
                        "--out", str(dst)], check=True, capture_output=True)
        return base64.b64encode(dst.read_bytes()).decode()


def pages_of(pdf):
    from pypdf import PdfReader
    ocr = pdf.with_name(pdf.stem + ".ocr.txt")
    texts = ocr.read_text(encoding="utf-8", errors="ignore").split("\f") if ocr.exists() else []
    out = []
    for i, page in enumerate(PdfReader(str(pdf)).pages):
        b64 = page_jpeg_b64(page)
        if b64:
            out.append((i + 1, b64, texts[i] if i < len(texts) else ""))
    return out


def worker(job):
    from app import llm_client
    text, usage = llm_client.vision(job["image"], PROMPT, purpose="bank_claims", max_tokens=3000)
    data = llm_client.parse_json(text)
    claims = [c for c in (data.get("claims") or []) if isinstance(c, dict) and c.get("text")][:8]
    qs = [q for q in (data.get("questions") or []) if isinstance(q, dict) and q.get("q") and q.get("answer")][:2]
    page_nums = nums(job["ocr"])
    claim_nums = [n for c in claims for n in nums(" ".join(str(x) for x in (c.get("numbers") or [])) + " " + c["text"])]
    for q in qs:
        q["verified"] = verified(str(q["answer"]), job["ocr"])
    return {"doc": job["doc"], "page": job["page"], "claims": claims, "questions": qs,
            "claim_numbers": len(claim_nums), "claim_numbers_in_ocr": sum(1 for n in claim_nums if n in page_nums),
            "ocr_chars": len(job["ocr"]), "cost_rub": usage.get("cost_rub"), "ms": usage.get("ms")}


def compile_outputs():
    rows = sorted(batch_runner.read_jsonl(OUT / "results.jsonl"), key=lambda r: (r["doc"], r["page"]))
    claims = [{"doc": r["doc"], "page": r["page"], **c} for r in rows for c in r["claims"]]
    (OUT / "claims.json").write_text(json.dumps(claims, ensure_ascii=False, indent=1))
    by_doc = defaultdict(list)
    for r in rows:
        for q in r["questions"]:
            if q.get("verified"):
                by_doc[r["doc"]].append({"doc": r["doc"], "page": r["page"], "question": q["q"],
                                         "expected_answer": q["answer"], "check": q["verified"]})
    picked, k = [], 0
    while len(picked) < N_QUESTIONS and any(len(v) > k for v in by_doc.values()):
        for doc in sorted(by_doc):
            if len(by_doc[doc]) > k and len(picked) < N_QUESTIONS:
                picked.append(by_doc[doc][k])
        k += 1
    (OUT / "questions_50.json").write_text(json.dumps(picked, ensure_ascii=False, indent=1))
    total_q = sum(len(r["questions"]) for r in rows)
    cn = sum(r["claim_numbers"] for r in rows)
    summary = {"pages": len(rows), "docs": len({r["doc"] for r in rows}), "claims": len(claims),
               "claim_numbers": cn, "claim_numbers_found_in_ocr": round(sum(r["claim_numbers_in_ocr"] for r in rows) / cn, 3)
               if cn else None, "questions_proposed": total_q,
               "questions_verified": sum(len(v) for v in by_doc.values()), "questions_kept": len(picked),
               "cost_rub": round(sum(r["cost_rub"] or 0 for r in rows), 2)}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compile-only", action="store_true")
    args = ap.parse_args()
    conn, tmp = case_env.prepare("alpha.db")
    from app import config, llm_client
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.compile_only:
        if llm_client.provider() != "gateway":
            sys.exit("нужен LLM_PROVIDER=gateway")
        jobs = []
        for pdf in sorted(config.BANK_DOCS_DIR.glob("*.pdf")):
            for page, b64, ocr in pages_of(pdf):
                jobs.append((f"{pdf.name}|{page}", {"doc": pdf.name, "page": page, "image": b64, "ocr": ocr}))
        print(f"страниц {len(jobs)}")
        batch_runner.run("f", jobs, worker, stage_cap=STAGE_CAP, every=120)
    print(json.dumps(compile_outputs(), ensure_ascii=False))
    case_env.cleanup(conn, tmp)


if __name__ == "__main__":
    main()
