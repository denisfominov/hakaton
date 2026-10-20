"""JSON-схемы контрактов (docs/CONTRACTS.md) → backend/app/schemas/json/<Имя>.schema.json.

    cd backend
    python -m scripts.export_contracts           # записать
    python -m scripts.export_contracts --check   # только проверить, что файлы совпадают с моделями (тест делает то же)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas.contracts import CONTRACTS, CONTRACTS_VERSION  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "app" / "schemas" / "json"


def rendered():
    out = {}
    for name, model in CONTRACTS.items():
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"alpha-intelligence/{name}",
                  "x-contracts-version": CONTRACTS_VERSION, **model.model_json_schema()}
        out[f"{name}.schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = rendered()
    stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            sys.exit("схемы устарели: " + ", ".join(stale) + " — python -m scripts.export_contracts")
        print("схемы совпадают с моделями")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
    print(f"записано {len(files)} схем в {OUT}")


if __name__ == "__main__":
    main()
