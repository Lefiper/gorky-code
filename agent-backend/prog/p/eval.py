"""Оценка ASR-сервиса на вашем наборе.

Манифест — TSV с заголовком: path <TAB> text <TAB> must_contain
  path          путь к аудиофайлу (относительно манифеста или абсолютный)
  text          эталонный транскрипт
  must_contain  необязательно: ключевые слова через '|' (дата, время, имя),
                которые обязаны оказаться в распознанном тексте

Пример:
  python eval.py data/manifest.tsv --engines whisper gigaam
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import httpx
import jiwer


def norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load(manifest: Path):
    with manifest.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        p = Path(r["path"])
        r["path"] = p if p.is_absolute() else manifest.parent / p
        r["must"] = [norm(x) for x in (r.get("must_contain") or "").split("|") if x.strip()]
    return rows


def run_engine(rows, url: str, engine: str | None):
    results = []
    with httpx.Client(timeout=120) as client:
        for r in rows:
            with r["path"].open("rb") as f:
                resp = client.post(
                    f"{url}/v1/transcribe",
                    files={"file": (r["path"].name, f)},
                    params={"engine": engine} if engine else None,
                )
            if resp.status_code != 200:
                print(f"  ! {r['path'].name}: HTTP {resp.status_code}", file=sys.stderr)
                results.append({"hyp": "", "latency_ms": None})
                continue
            j = resp.json()
            results.append({"hyp": j["text"], "latency_ms": j["latency_ms"], "engine": j["engine"]})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--engines", nargs="*", default=[None])
    ap.add_argument("--out", type=Path, default=Path("eval_results.csv"))
    args = ap.parse_args()

    rows = load(args.manifest)
    summary, details = [], []

    for eng in args.engines:
        print(f"Engine: {eng or 'default'}")
        res = run_engine(rows, args.url, eng)
        refs = [norm(r["text"]) for r in rows]
        hyps = [norm(x["hyp"]) for x in res]
        pairs = [(a, b) for a, b in zip(refs, hyps) if a]
        wer = jiwer.wer([a for a, _ in pairs], [b if b else "<empty>" for _, b in pairs])

        keyed = [(r, h) for r, h in zip(rows, hyps) if r["must"]]
        key_ok = sum(all(k in h for k in r["must"]) for r, h in keyed)
        lats = sorted(x["latency_ms"] for x in res if x["latency_ms"] is not None)
        p50 = lats[len(lats) // 2] if lats else None
        p95 = lats[int(len(lats) * 0.95) - 1] if lats else None

        summary.append((res[0].get("engine", eng or "default"), wer, key_ok, len(keyed), p50, p95))
        for r, x, h in zip(rows, res, hyps):
            details.append({
                "engine": eng or "default", "file": r["path"].name,
                "ref": norm(r["text"]), "hyp": h, "latency_ms": x["latency_ms"],
                "key_ok": all(k in h for k in r["must"]) if r["must"] else "",
            })

    print("\n{:<28}{:>8}{:>14}{:>10}{:>10}".format("engine", "WER", "keys ok", "p50 ms", "p95 ms"))
    for name, wer, ok, total, p50, p95 in summary:
        keys = f"{ok}/{total}" if total else "-"
        print(f"{name:<28}{wer:>8.1%}{keys:>14}{p50 or '-':>10}{p95 or '-':>10}")

    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(details[0].keys()))
        w.writeheader()
        w.writerows(details)
    print(f"\nПо-фразные результаты: {args.out}")


if __name__ == "__main__":
    main()
