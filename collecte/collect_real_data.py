#!/usr/bin/env python3
"""Read-only collection. Python 3.10+, standard library, no trading engine.

Raw vendor archives and their SHA-256 sidecars remain unchanged. Candle rows
are extracted, never reconstructed. No prices, trades, fills, or returns are
simulated. Download progress is committed after every verified archive.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

BASE = "https://data.binance.vision/data/futures/um"
TF_MS = {"4h": 14_400_000, "1d": 86_400_000}
DAY_MS = 86_400_000
HEADERS = {"User-Agent": "RangeAgents-ReadOnlyCollector/1.0", "Accept-Encoding": "identity"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ms(value: str) -> int:
    return int(datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc).timestamp()) * 1000


def iso(value: int | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def safe_file(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError("Chemin sortant du jeu de donnees.")
    return p


def load_plan(path: Path) -> dict:
    p = json.loads(path.read_text(encoding="utf-8-sig"))
    if p.get("purpose") != "PUBLIC_MARKET_DATA_COLLECTION_ONLY":
        raise ValueError("Plan de collecte uniquement requis.")
    symbols = p["symbols"]
    if not symbols or len(symbols) > 50 or len(set(symbols)) != len(symbols):
        raise ValueError("Entre 1 et 50 symboles uniques requis.")
    if any(not re.fullmatch(r"[A-Z0-9]{2,25}USDT", s) for s in symbols):
        raise ValueError("Symbole USD-M/USDT invalide.")
    if not p["timeframes"] or not set(p["timeframes"]).issubset(TF_MS):
        raise ValueError("Seules les structures 4h et 1d sont prises en charge.")
    a, b = date.fromisoformat(p["data_start"]), date.fromisoformat(p["end_exclusive"])
    first_this_month = datetime.now(timezone.utc).date().replace(day=1)
    if a >= b or a.day != 1 or b.day != 1 or b > first_this_month:
        raise ValueError("Structures : mois complets passes, debut et fin au premier du mois.")
    ta, tb = date.fromisoformat(p["transaction_start"]), date.fromisoformat(p["transaction_end_exclusive"])
    if not a <= ta < tb <= b:
        raise ValueError("Dates de transactions hors periode de collecte.")
    output = Path(p["output"])
    if output.is_absolute() or ".." in output.parts:
        raise ValueError("Dossier de sortie relatif sans '..' requis.")
    return p


def months(a: str, b: str):
    d, stop = date.fromisoformat(a), date.fromisoformat(b)
    while d < stop:
        yield d.strftime("%Y-%m")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def days(a: str, b: str):
    d, stop = date.fromisoformat(a), date.fromisoformat(b)
    while d < stop:
        yield d.isoformat()
        d += timedelta(days=1)


def wanted(p: dict, task: str) -> list[dict]:
    items = []
    for s in p["symbols"]:
        if task == "structures":
            for tf in p["timeframes"]:
                for m in months(p["data_start"], p["end_exclusive"]):
                    name = f"{s}-{tf}-{m}.zip"
                    items.append(dict(symbol=s, tf=tf, month=m, kind="klines", name=name,
                                      url=f"{BASE}/monthly/klines/{s}/{tf}/{name}"))
        else:
            for d in days(p["transaction_start"], p["transaction_end_exclusive"]):
                name = f"{s}-aggTrades-{d}.zip"
                items.append(dict(symbol=s, day=d, kind="aggTrades", name=name,
                                  url=f"{BASE}/daily/aggTrades/{s}/{name}"))
    return items


class RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlparse(newurl)
        if u.scheme != "https" or u.netloc != "data.binance.vision" or not u.path.startswith("/data/futures/um/"):
            raise ValueError("Redirection vers une source non approuvee : arret.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(RestrictedRedirect())


def download(url: str, target: Path, max_bytes: int, retries: int = 3) -> dict:
    if not url.startswith(BASE + "/"):
        raise ValueError("Seules les archives publiques officielles USD-M sont autorisees.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    for attempt in range(retries):
        try:
            with OPENER.open(Request(url, headers=HEADERS, method="GET"), timeout=35) as r:
                total = 0
                with temp.open("wb") as out:
                    while True:
                        block = r.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > max_bytes:
                            raise ValueError("Fichier trop volumineux pour la limite de securite.")
                        out.write(block)
                if total == 0:
                    raise ValueError("Reponse vide.")
                declared = r.headers.get("Content-Length")
                if declared and total != int(declared):
                    raise ValueError("Telechargement incomplet (Content-Length).")
                proof = dict(retrieved_at_utc=now(), bytes=total,
                             etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"))
            temp.replace(target)
            return proof
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, HTTPError) and exc.code in (400, 401, 403, 404, 451):
                raise
            if attempt + 1 == retries:
                raise
            delay = 2 ** attempt
            if isinstance(exc, HTTPError) and exc.code in (429, 503):
                raw = exc.headers.get("Retry-After", "")
                if raw.isdigit():
                    delay = min(120, max(delay, int(raw)))
            print(f"Nouvelle tentative dans {delay}s : {exc}", flush=True)
            time.sleep(delay)
        finally:
            if temp.exists():
                temp.unlink()
    raise RuntimeError("Echec de telechargement.")


def read_vendor_checksum(path: Path, name: str) -> str:
    fields = path.read_text(encoding="utf-8-sig").strip().split()
    if not fields or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise ValueError("Checksum vendeur invalide.")
    if len(fields) > 1 and PurePosixPath(fields[1].lstrip("*")).name != name:
        raise ValueError("Le checksum concerne un autre fichier.")
    return fields[0].lower()


def obtain(item: dict, root: Path, previous: dict | None, retries: int) -> dict:
    archive = root / "archives" / item["name"]
    sidecar = archive.with_name(archive.name + ".CHECKSUM")
    if previous and archive.exists() and sidecar.exists():
        expected = read_vendor_checksum(sidecar, archive.name)
        if (expected == previous["sha256"] and digest(archive) == expected
                and digest(sidecar) == previous["checksum_file_sha256"]):
            return {**previous, "cache_reverified_at_utc": now()}
        raise ValueError("Archive ou checksum local modifie : arret sans remplacement silencieux.")
    download(item["url"] + ".CHECKSUM", sidecar, 64 * 1024, retries)
    expected = read_vendor_checksum(sidecar, archive.name)
    if archive.exists():
        if digest(archive) != expected:
            raise ValueError("Archive existante incompatible avec le checksum : arret.")
        retrieval = {"reverified_at_utc": now(), "bytes": archive.stat().st_size}
    else:
        retrieval = download(item["url"], archive, 8 * 1024**3, retries)
    if digest(archive) != expected:
        archive.rename(archive.with_name(archive.name + ".INVALID_SHA256"))
        raise ValueError("SHA256 invalide : archive isolee, jamais utilisee.")
    return {**item, **retrieval, "verified": True, "sha256": expected,
            "path": str(archive.relative_to(root)).replace("\\", "/"),
            "checksum_path": str(sidecar.relative_to(root)).replace("\\", "/"),
            "checksum_file_sha256": digest(sidecar), "checksum_verified_at_utc": now()}


def source_rows(path: Path):
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        if len(members) != 1 or not members[0].filename.endswith(".csv") or members[0].file_size > 50 * 1024**3:
            raise ValueError("Archive inattendue : un CSV unique est requis.")
        with z.open(members[0]) as raw:
            rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            for number, row in enumerate(rows, 1):
                if not row:
                    raise ValueError(f"Ligne CSV vide : {path.name}:{number}")
                if number == 1 and row[0].strip().lower().replace(" ", "_") in {
                    "open_time", "opentime", "agg_trade_id", "aggregate_trade_id", "aggregated_trade_id"
                }:
                    continue
                yield number, row


def positive(value: str) -> Decimal:
    try:
        x = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Valeur decimale invalide.") from exc
    if not x.is_finite() or x <= 0:
        raise ValueError("Prix/quantite non strictement positif ou non fini.")
    return x


@contextmanager
def atomic_gzip(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    try:
        with temp.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
                with io.TextIOWrapper(gz, encoding="utf-8", newline="") as txt:
                    yield txt
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def export_structures(p: dict, root: Path, receipts: dict) -> list[dict]:
    tables = []
    a, b = ms(p["data_start"]), ms(p["end_exclusive"])
    for symbol in p["symbols"]:
        for tf in p["timeframes"]:
            # A missing channel is not an empty market series. Keep it absent.
            if not any(r.get('symbol')==symbol and r.get('tf')==tf for r in receipts.values()):
                continue
            step = TF_MS[tf]
            path = root / "structures" / f"{symbol}-{tf}.csv.gz"
            first = previous = None
            count = 0
            gaps = []
            with atomic_gzip(path) as out:
                writer = csv.writer(out, lineterminator="\n")
                writer.writerow(["timestamp_ms", "open", "high", "low", "close"])
                for item in wanted({**p, "symbols": [symbol], "timeframes": [tf]}, "structures"):
                    proof = receipts.get(item["name"])
                    if not proof:
                        continue
                    archive = safe_file(root, proof["path"])
                    month_start = ms(item["month"] + "-01")
                    d = date.fromisoformat(item["month"] + "-01")
                    month_end = ms(date(d.year + (d.month == 12), d.month % 12 + 1, 1).isoformat())
                    for number, row in source_rows(archive):
                        if len(row) != 12:
                            raise ValueError(f"Schema bougie inattendu : {archive.name}:{number}")
                        ts, close_ts = int(row[0]), int(row[6])
                        if not month_start <= ts < month_end or ts % step or close_ts != ts + step - 1:
                            raise ValueError(f"Horodatage USD-M/millisecondes inattendu : {archive.name}:{number}")
                        o, h, l, c = map(positive, row[1:5])
                        if not l <= min(o, c) <= max(o, c) <= h:
                            raise ValueError(f"OHLC incoherent : {archive.name}:{number}")
                        if previous is not None and ts <= previous:
                            raise ValueError("Doublon ou horodatage non croissant, sans correction automatique.")
                        if previous is not None and ts != previous + step:
                            gaps.append({"start_ms": previous + step, "end_exclusive_ms": ts,
                                         "missing_bars": (ts - previous) // step - 1})
                        if first is None:
                            first = ts
                        previous = ts
                        # Strings are preserved exactly; no new market values are computed.
                        writer.writerow([ts, *row[1:5]])
                        count += 1
            if first is None or first > a:
                gaps.insert(0, {"start_ms": a, "end_exclusive_ms": first or b,
                                "missing_bars": ((first or b) - a) // step})
            if previous is not None and previous + step < b:
                gaps.append({"start_ms": previous + step, "end_exclusive_ms": b,
                             "missing_bars": (b - previous - step) // step})
            tables.append({"symbol": symbol, "tf": tf,
                           "path": str(path.relative_to(root)).replace("\\", "/"),
                           "rows": count, "expected_rows": (b - a) // step,
                           "first_ms": first, "last_ms": previous,
                           "first_open_utc": iso(first), "last_open_utc": iso(previous),
                           "gaps": len(gaps), "gap_intervals": gaps,
                           "missing_bars": sum(g["missing_bars"] for g in gaps),
                           "sha256": digest(path)})
    return tables


def export_transactions(item: dict, proof: dict, root: Path) -> dict:
    path = root / "events" / f'{item["symbol"]}-aggTrades-{item["day"]}.jsonl.gz'
    a, b = ms(item["day"]), ms(item["day"]) + DAY_MS
    previous_id = previous_ts = first = None
    count = gap_count = missing_ids = 0
    gap_examples = []
    with atomic_gzip(path) as out:
        for number, row in source_rows(safe_file(root, proof["path"])):
            if len(row) != 7:
                raise ValueError(f"Schema aggTrades inattendu : {item['name']}:{number}")
            seq, ts, first_trade, last_trade = int(row[0]), int(row[5]), int(row[3]), int(row[4])
            price, qty = positive(row[1]), positive(row[2])
            if not a <= ts < b or first_trade > last_trade or seq < 0:
                raise ValueError("Horodatage/identifiants transactionnels invalides.")
            if row[6].lower() not in ("true", "false"):
                raise ValueError("Indicateur buyer_maker invalide.")
            if previous_id is not None:
                if seq <= previous_id or ts < previous_ts:
                    raise ValueError("Transaction dupliquee/non ordonnee : arret.")
                if seq > previous_id + 1:
                    gap_count += 1
                    missing_ids += seq - previous_id - 1
                    if len(gap_examples) < 100:
                        gap_examples.append({"after": previous_id, "before": seq})
            if first is None:
                first = ts
            # These are the vendor's numbers, NOT a simulated event or assumed fill.
            # Only actual fields are emitted. No quote, mark price or funding is fabricated.
            record = {"ts": ts, "symbol": item["symbol"], "kind": "trade",
                      "price": float(price), "qty": float(qty), "seq": seq,
                      "source": "binance_public_aggTrades"}
            if not math.isfinite(record["price"]) or not math.isfinite(record["qty"]):
                raise ValueError("Valeur incompatible avec le format evenement V2.")
            out.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
            previous_id, previous_ts = seq, ts
            count += 1
    if count == 0:
        raise ValueError("Archive de transactions vide.")
    return {"symbol": item["symbol"], "kind": "aggTrades", "day": item["day"],
            "path": str(path.relative_to(root)).replace("\\", "/"), "rows": count,
            "first_ms": first, "last_ms": previous_ts,
            "requested_start_ms": a, "requested_end_ms": b,
            "first_utc": iso(first), "last_utc": iso(previous_ts),
            "aggregate_id_gap_count": gap_count, "missing_aggregate_ids": missing_ids,
            "aggregate_id_gap_examples": gap_examples,
            "sha256": digest(path), "archive_proof": proof}



@contextmanager
def dataset_lock(root: Path):
    """Refuse concurrent writers instead of racing over manifests and .part files."""
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".collection.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("Collecte deja en cours ou verrou apres arret brutal. Ne pas lancer deux collectes ensemble. "
                         "Si aucun collecteur ne tourne, supprimer uniquement .collection.lock puis relancer.") from exc
    try:
        import os
        with handle:
            json.dump({"pid": os.getpid(), "started_at_utc": now()}, handle)
        yield
    finally:
        lock.unlink(missing_ok=True)


def initialize(root: Path, p: dict) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    identity = {k: p[k] for k in ("symbols", "timeframes", "data_start", "end_exclusive")}
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        if m.get("synthetic") is not False or m.get("collection_plan_identity") != identity:
            raise ValueError("Jeu existant incompatible : choisir un dossier vide, ne pas melanger les donnees.")
        return m
    m = {"schema_version": 2, "synthetic": False, "real_data_only": True,
         "source": "Binance public USD-M futures archives", "created_at_utc": now(),
         "collection_plan_identity": identity, "data_start": p["data_start"],
         "start": p["data_start"], "end_exclusive": p["end_exclusive"],
         "collection_status": "NOT_STARTED", "structures": [], "events": [],
         "structure_archives": [], "transaction_archives": [],
         "generated_market_values": False, "interpolated_market_values": False,
         "event_precision": "aggTrades when collected; not individual raw fills or a full order book",
         "unavailable_channels": ["bid_ask_history", "mark_price_history", "funding_settlements", "historical_contract_rules"],
         "top50_historical_universe_collected": False,
         "strategy_simulation_run": False, "live_orders_sent": False}
    save_json(path, m)
    return m


def plan_summary(p: dict) -> dict:
    return {"purpose": p["purpose"], "symbols": p["symbols"], "timeframes": p["timeframes"],
            "structure_start_utc": p["data_start"], "structure_end_exclusive_utc": p["end_exclusive"],
            "monthly_structure_archives_requested": len(wanted(p, "structures")),
            "transaction_start_utc": p["transaction_start"],
            "transaction_end_exclusive_utc": p["transaction_end_exclusive"],
            "daily_aggtrade_archives_requested": len(wanted(p, "transactions")),
            "remote_availability_verified": False, "market_data_downloaded_by_plan_command": False}


def collect(p: dict, root: Path, task: str, retries: int) -> int:
    m = initialize(root, p)
    key = "structure_archives" if task == "structures" else "transaction_archives"
    saved = {r["name"]: r for r in m[key]}
    request = wanted(p, task)
    new_count = 0
    m["collection_status"] = "IN_PROGRESS"
    save_json(root / "manifest.json", m)
    error = None
    try:
        for index, item in enumerate(request, 1):
            print(f"[{index}/{len(request)}] {item['name']}", flush=True)
            previous = saved.get(item["name"])
            proof = obtain(item, root, previous, retries)
            saved[item["name"]] = proof
            new_count += previous is None
            m[key] = list(saved.values())
            if task == "transactions":
                old = next((r for r in m["events"] if r.get("day") == item["day"] and r.get("symbol") == item["symbol"]), None)
                if old and safe_file(root, old["path"]).exists():
                    if digest(safe_file(root, old["path"])) != old["sha256"]:
                        raise ValueError("Fichier transactionnel local modifie : arret.")
                else:
                    record = export_transactions(item, proof, root)
                    m["events"] = [r for r in m["events"] if (r.get("day"), r.get("symbol")) != (item["day"], item["symbol"])] + [record]
                    print(f"  {record['rows']:,} observations reelles ; {record['aggregate_id_gap_count']} discontinuites d'ID", flush=True)
            save_json(root / "manifest.json", m)
        if task == "structures":
            m["structures"] = export_structures(p, root, saved)
            for t in m["structures"]:
                print(f"  {t['symbol']} {t['tf']} : {t['rows']} bougies, {t['missing_bars']} manquantes", flush=True)
            if any(t["missing_bars"] for t in m["structures"]):
                raise ValueError("Bougies manquantes : fichiers conserves, periode non declaree complete.")
        elif any(r.get("aggregate_id_gap_count", 0) for r in m["events"]):
            raise ValueError("Discontinuites d'identifiants observees : audit requis, aucune interpolation.")
    except (Exception, KeyboardInterrupt) as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "at_utc": now()}
        print(f"ARRET : {error['message'] or error['type']}", file=sys.stderr, flush=True)
    if error and task == "structures" and saved:
        # Preserve authentic, already verified partial receipts for observation;
        # do not replace a failed download by generated or interpolated prices.
        try:
            m["structures"] = export_structures(p, root, saved)
            error["partial_authentic_export"] = True
        except Exception as export_error:
            error["partial_export_error"] = type(export_error).__name__ + ": " + str(export_error)
    m[key] = list(saved.values())
    m[task + "_status"] = "INCOMPLETE" if error else "COLLECTED_AND_CHECKED_FOR_REQUESTED_SCOPE"
    m["collection_status"] = m[task + "_status"]
    m["last_run"] = {"task": task, "ended_at_utc": now(), "error": error,
                     "requested_archives": len(request), "new_verified_archives": new_count,
                     "verified_archives_for_task": len(saved)}
    save_json(root / "manifest.json", m)
    save_json(root / "collection_report.json", {
        "source": m["source"], "synthetic": False, "generated_market_values": False,
        "strategy_simulation_run": False, "live_orders_sent": False,
        "last_run": m["last_run"], "structures": m["structures"],
        "transaction_days": [{k: r.get(k) for k in ("symbol", "day", "rows", "first_utc", "last_utc", "aggregate_id_gap_count")}
                             for r in m["events"]],
        "not_complete_market_history": True, "unavailable_channels": m["unavailable_channels"]})
    print("Manifest :", root / "manifest.json")
    print("Rapport  :", root / "collection_report.json")
    return 2 if error else 0


def verify(root: Path) -> int:
    path = root / "manifest.json"
    if not path.exists():
        raise ValueError("Aucun manifeste : aucune collecte a verifier.")
    m = json.loads(path.read_text(encoding="utf-8"))
    if m.get("synthetic") is not False:
        raise ValueError("Jeu synthetique ou provenance ambigue refuse.")
    checked = 0
    for key in ("structure_archives", "transaction_archives", "structures", "events"):
        for r in m.get(key, []):
            if digest(safe_file(root, r["path"])) != r["sha256"]:
                raise ValueError("Integrite invalide : " + r["path"])
            if "checksum_path" in r:
                cp = safe_file(root, r["checksum_path"])
                if digest(cp) != r["checksum_file_sha256"] or read_vendor_checksum(cp, r["name"]) != r["sha256"]:
                    raise ValueError("Checksum vendeur modifie.")
            checked += 1
    print(json.dumps({"verified_existing_files": checked, "synthetic": False,
                      "structure_status": m.get("structures_status", "NOT_COLLECTED"),
                      "transaction_status": m.get("transactions_status", "NOT_COLLECTED"),
                      "new_market_data_downloaded": 0}, indent=2))
    return 0 if checked else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Donnees reelles uniquement. Aucun moteur de trading/simulation.")
    ap.add_argument("task", choices=("plan", "structures", "transactions", "verify"))
    ap.add_argument("--plan", type=Path, default=Path(__file__).with_name("collection_plan.json"))
    ap.add_argument("--retries", type=int, choices=range(1, 6), default=3)
    args = ap.parse_args()
    try:
        p = load_plan(args.plan)
        root = args.plan.resolve().parent / p["output"]
        if args.task == "plan":
            print(json.dumps(plan_summary(p), indent=2, ensure_ascii=False))
            return 0
        with dataset_lock(root):
            if args.task == "verify":
                return verify(root)
            return collect(p, root, args.task, args.retries)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ARRET CONTROLE : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print("Python 3.10 ou plus recent requis.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
