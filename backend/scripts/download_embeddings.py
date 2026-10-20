"""Скачать веса локальной модели эмбеддингов multilingual-e5-small (ONNX) для RAG и смысловой близости.

Это не генеративная модель: ограничение кейса на шесть LLM к ней не относится (ответ организаторов). Лицензия MIT,
страница модели: https://huggingface.co/intfloat/multilingual-e5-small (проверено 2026-10-20, ревизия зафиксирована).
По умолчанию — компактный вариант int8 (~118 МБ + токенизатор 17 МБ); --full — полная точность fp32 (~470 МБ).

    cd backend
    python -m scripts.download_embeddings [--out data/embeddings/multilingual-e5-small] [--full]

Файлы проверяются по sha256. Без весов сервис работает на TF-IDF (запасной режим).
"""
import argparse
import hashlib
import sys
from pathlib import Path

import httpx

REPO = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
FILES = {  # путь в репозитории -> (имя у нас, sha256 или None для маленьких json)
    "onnx/model_qint8_avx512_vnni.onnx": ("model.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    "onnx/tokenizer.json": ("tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
    "onnx/config.json": ("config.json", None),
}
FULL = {"onnx/model.onnx": ("model.onnx", "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665")}


def download(path, target, sha):
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{path}"
    h = hashlib.sha256()
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
                h.update(chunk)
    if sha and h.hexdigest() != sha:
        tmp.unlink()
        sys.exit(f"{path}: sha256 не совпадает — файл не сохранён")
    tmp.rename(target)
    print(f"{path} -> {target} ({target.stat().st_size / 1e6:.1f} МБ)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/embeddings/multilingual-e5-small")
    ap.add_argument("--full", action="store_true", help="полная точность fp32 вместо int8")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = {**FILES, **(FULL if args.full else {})}
    if args.full:
        files.pop("onnx/model_qint8_avx512_vnni.onnx")
    for path, (name, sha) in files.items():
        target = out / name
        if target.exists() and sha and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
            print(f"{name}: уже скачан", file=sys.stderr)
            continue
        download(path, target, sha)
    (out / "REVISION").write_text(f"{REPO}@{REVISION} {'fp32' if args.full else 'int8'}\n", encoding="utf-8")
    print(f"готово: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
