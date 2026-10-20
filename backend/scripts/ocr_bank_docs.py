"""Текст из аналитических PDF Альфа-Банка (приложение 2 кейса), если в PDF нет текстового слоя.

Материалы кейса — картинки страниц, поэтому pypdf текста не находит. Скрипт распознаёт страницы и кладёт рядом
файл <имя>.ocr.txt: страницы разделены символом \\f, первая строка — «# заголовок» (самый крупный шрифт первой
страницы), без юридической оговорки внизу страниц, e-mail аналитиков и подписей осей графиков. bank_rag.py берёт
этот текст вместо пустого PDF, а ссылки в ответе агента по-прежнему указывают на исходный PDF и страницу.

Движки:
- mac — встроенное распознавание macOS (Apple Vision, на устройстве, без загрузки моделей; поддерживает русский).
  Страница распознаётся полосами с перекрытием и в 2× масштабе: так Vision не теряет строки в плотных абзацах.
- vl  — разрешённая кейсом модель Qwen3-VL-30B-A3B-Instruct через шлюз (LLM_PROVIDER, роль vision).
OCR — подготовка данных, сервис в рантайме его не выполняет; результат подключается тем же томом BANK_DOCS_DIR.

    cd backend
    uv run --with "pypdf[image]==5.1.0" --with ocrmac python -m scripts.ocr_bank_docs ../путь/к/pdf --out data/bank
"""
import argparse
import base64
import io
import re
import shutil
import sys
import tempfile
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
HEADER_PHRASES = ("центр макроэкономического анализа", "альфа-банк", "alfa-bank", "alfa bank", "аналитический обзор",
                  "аналитик", "директор", "руководитель", "департамент")
DISCLAIMER = ("все права защищены", "исключительной собственностью", "несанкционированное копирование",
              "частично или полностью", "исключительно для информационных", "индивидуальной инвестиционной",
              "генеральная лицензия цб")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё]{3,}")
DATE = re.compile(r"\b\d{1,2} (?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w* 20\d\d"
                  r"|\b\d{1,2}\.\d{1,2}\.20\d\d\b|\b(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|"
                  r"декабр)\w* 20\d\d", re.IGNORECASE)


def page_images(pdf):
    from pypdf import PdfReader

    for page in PdfReader(str(pdf)).pages:
        imgs = list(page.images)
        if not imgs:
            yield None
            continue
        # страница-картинка: берём самое большое изображение
        yield max((i.image for i in imgs), key=lambda im: im.width * im.height).convert("RGB")


# ---------- движок mac ----------

def ocr_mac(img, band=0.16, step=0.12, scale=2):
    """Строки страницы [(top, x, width, height, text)] в долях страницы, top — от верхнего края."""
    from ocrmac import ocrmac
    from PIL import Image

    W, H = img.size
    lines, top = [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "band.png"
        while top < 1.0:
            y0, y1 = int(top * H), int(min(1.0, top + band) * H)
            crop = img.crop((0, y0, W, y1)).resize((W * scale, (y1 - y0) * scale), Image.LANCZOS)
            crop.save(path)
            for text, _conf, (x, y, w, h) in ocrmac.OCR(str(path), language_preference=["ru-RU", "en-US"]).recognize():
                band_h = (y1 - y0) / H
                abs_top = (y0 + (1 - y - h) * (y1 - y0)) / H
                # запас до края полосы: строка, разрезанная краем, распознаётся с ошибками — берём целую из соседней
                margin = min((1 - y - h) * band_h if y0 > 0 else 1.0, y * band_h if y1 < H else 1.0)
                lines.append((abs_top, x, w, h * band_h, text.strip(), margin))
            top += step
    lines.sort()
    out = []
    for ln in lines:  # одна и та же строка из соседних полос: оставляем прочитанную дальше от края полосы
        dup = next((o for o in out[-8:] if abs(ln[0] - o[0]) < 0.008 and abs(ln[1] - o[1]) < 0.08), None)
        if dup:
            if ln[5] > dup[5]:
                out[out.index(dup)] = ln
            continue
        out.append(ln)
    return [ln[:5] for ln in out]


def order_columns(lines):
    """Порядок чтения: между строками во всю ширину — сначала левая колонка, потом правая."""
    result, segment = [], []

    def flush():
        left = [ln for ln in segment if ln[1] < 0.5]
        right = [ln for ln in segment if ln[1] >= 0.5]
        two_columns = len(left) >= 3 and len(right) >= 3 and all(ln[2] < 0.5 for ln in segment)
        result.extend(left + right if two_columns else segment)
        segment.clear()

    for ln in lines:
        if ln[2] >= 0.6:
            flush()
            result.append(ln)
        else:
            segment.append(ln)
    flush()
    return result


def clean(lines, first_page):
    """Убираем оговорку, e-mail, номер страницы и подписи осей; находим заголовок по размеру шрифта."""
    kept, title = [], None
    stop = False
    for top, x, w, h, text in lines:
        low = text.lower()
        if stop or any(p in low for p in DISCLAIMER):
            stop = True  # оговорка — всегда в конце страницы
            continue
        if EMAIL.search(text) or PHONE.search(text) or re.fullmatch(r"\d{1,3}", text.strip()):
            continue
        if len(WORD.findall(text)) < 2 and len(text) < 25 and not re.search(r"\d{4}", text):
            continue  # подписи осей и легенды графиков
        kept.append((top, x, w, h, text))
    date = None
    if first_page:
        body_h = sorted(ln[3] for ln in kept)[len(kept) // 2] if kept else 0
        candidates = [ln for ln in kept if ln[0] < 0.35 and not any(p in ln[4].lower() for p in HEADER_PHRASES)
                      and 8 <= len(ln[4]) and len(ln[4].split()) <= 14 and not DATE.search(ln[4])]
        if candidates:
            big = max(candidates, key=lambda ln: ln[3])
            if big[3] > body_h * 1.25:
                title = big[4]
                # заголовок и подзаголовок: соседняя строка тоже набрана крупнее основного текста
                prev = [ln for ln in candidates if 0 < big[0] - ln[0] < 0.06 and ln[3] > body_h * 1.1]
                nxt = [ln for ln in candidates if 0 < ln[0] - big[0] < 0.06 and ln[3] > body_h * 1.1]
                if prev:
                    title = f"{prev[-1][4]}: {title}"
                elif nxt:
                    title = f"{title}: {nxt[0][4]}"
        # дата выпуска — в шапке первой страницы (в тексте ниже встречаются даты погашения облигаций и т.п.)
        date = next((m.group(0) for ln in kept if ln[0] < 0.3 for m in [DATE.search(ln[4])] if m), None)
    return [ln[4] for ln in kept], title, date


# ---------- движок vl ----------

def ocr_vl(img):
    """Разрешённая мультимодальная модель (Qwen3-VL) переписывает страницу в текст."""
    from app import llm_client

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    text, _usage = llm_client.vision(base64.b64encode(buf.getvalue()).decode(),
                                     "Перепиши весь текст страницы аналитического обзора по-русски, сохраняя абзацы и "
                                     "цифры. Без пояснений, графики не описывай.", purpose="bank_ocr")
    return [(i / 1000, 0.0, 1.0, 0.01, t.strip()) for i, t in enumerate(text.splitlines()) if t.strip()]


def process(pdf, engine):
    pages, title, date = [], None, None
    for n, img in enumerate(page_images(pdf), 1):
        if img is None:
            pages.append("")
            continue
        lines = ocr_mac(img) if engine == "mac" else ocr_vl(img)
        text_lines, page_title, page_date = clean(order_columns(lines), first_page=(n == 1))
        title, date = title or page_title, date or page_date
        pages.append("\n".join(text_lines))
        print(f"  стр. {n}: {len(text_lines)} строк", file=sys.stderr)
    head = (f"# {title}\n" if title else "") + (f"@date {date}\n" if date else "")
    return head + "\f".join(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка с PDF")
    ap.add_argument("--out", default="data/bank", help="куда положить PDF и .ocr.txt (BANK_DOCS_DIR)")
    ap.add_argument("--engine", choices=["mac", "vl"], default="mac")
    ap.add_argument("--force", action="store_true", help="распознать заново, даже если .ocr.txt уже есть")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(src.glob("*.pdf")):
        target = out / pdf.name
        if target.resolve() != pdf.resolve():
            shutil.copy2(pdf, target)
        txt = out / f"{pdf.stem}.ocr.txt"
        if txt.exists() and not args.force:
            print(f"{pdf.name}: уже распознан", file=sys.stderr)
            continue
        print(f"{pdf.name}: распознаём ({args.engine})", file=sys.stderr)
        txt.write_text(process(pdf, args.engine), encoding="utf-8")
    print(f"готово: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
