#!/usr/bin/env python3
"""
Fetch current standard VAT/GST rates, merge European (TEDB-backed) data with the
manually maintained GST jurisdictions, diff against the last committed snapshot,
and write data/rates.json.

Design notes:
- European rates come from the VATNode dataset, which is sourced from the
  European Commission's Taxes in Europe Database (TEDB) and checked daily.
- Singapore, Australia and New Zealand are GST, not in that dataset, so they
  live in data/manual_rates.json and are merged in here.
- The source does not expose a per-country "effective date". When a rate changes,
  the script stamps last_changed = today; otherwise it seeds the documented
  effective date of the current rate from data/known_effective.json (applied only
  while the live rate still matches the seeded value).
- Stdlib only. No dependencies to install.

Exit behaviour: always writes data/rates.json. When run inside GitHub Actions it
writes outputs to $GITHUB_OUTPUT (changed, headline, subject, summary, email_md)
so the workflow can decide whether to commit, release and email.
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone

VATNODE_URL = "https://cdn.jsdelivr.net/gh/vatnode/eu-vat-rates-data@main/data/eu-vat-rates-data.json"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
RATES_PATH = os.path.join(DATA_DIR, "rates.json")
MANUAL_PATH = os.path.join(DATA_DIR, "manual_rates.json")
KNOWN_PATH = os.path.join(DATA_DIR, "known_effective.json")

# European jurisdictions in scope: EU-27 plus UK, Norway, Switzerland.
# code -> (display name, region). Region is used only for grouping in the UI.
EUROPE = {
    "AT": ("Austria", "EU"),
    "BE": ("Belgium", "EU"),
    "BG": ("Bulgaria", "EU"),
    "HR": ("Croatia", "EU"),
    "CY": ("Cyprus", "EU"),
    "CZ": ("Czechia", "EU"),
    "DK": ("Denmark", "EU"),
    "EE": ("Estonia", "EU"),
    "FI": ("Finland", "EU"),
    "FR": ("France", "EU"),
    "DE": ("Germany", "EU"),
    "GR": ("Greece", "EU"),
    "HU": ("Hungary", "EU"),
    "IE": ("Ireland", "EU"),
    "IT": ("Italy", "EU"),
    "LV": ("Latvia", "EU"),
    "LT": ("Lithuania", "EU"),
    "LU": ("Luxembourg", "EU"),
    "MT": ("Malta", "EU"),
    "NL": ("Netherlands", "EU"),
    "PL": ("Poland", "EU"),
    "PT": ("Portugal", "EU"),
    "RO": ("Romania", "EU"),
    "SK": ("Slovakia", "EU"),
    "SI": ("Slovenia", "EU"),
    "ES": ("Spain", "EU"),
    "SE": ("Sweden", "EU"),
    "GB": ("United Kingdom", "Europe (non-EU)"),
    "NO": ("Norway", "Europe (non-EU)"),
    "CH": ("Switzerland", "Europe (non-EU)"),
}

# VATNode normalises Greece to GR, but guard against the TEDB-internal EL just in case.
CODE_ALIASES = {"EL": "GR"}


def today_iso():
    return date.today().isoformat()


def fetch_vatnode():
    req = urllib.request.Request(VATNODE_URL, headers={"User-Agent": "vat-tracker"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def previous_index(prev):
    """Map code -> previous country record, for diffing and last_changed carryover."""
    if not prev:
        return {}
    return {c["code"]: c for c in prev.get("countries", [])}


def build():
    prev = load_json(RATES_PATH)
    prev_idx = previous_index(prev)
    manual = load_json(MANUAL_PATH) or {"countries": {}}
    known = (load_json(KNOWN_PATH) or {}).get("rates", {})

    vatnode = fetch_vatnode()
    raw = vatnode.get("rates", {})
    # Re-key with aliases applied.
    source_rates = {}
    for code, rec in raw.items():
        source_rates[CODE_ALIASES.get(code, code)] = rec

    countries = []
    changes = []
    today = today_iso()

    # European countries from the TEDB-backed feed.
    for code, (name, region) in EUROPE.items():
        rec = source_rates.get(code)
        if rec is None or rec.get("standard") is None:
            # Country missing from the feed this run: carry the previous value forward
            # rather than dropping it, so a transient source gap never blanks the table.
            if code in prev_idx:
                carried = dict(prev_idx[code])
                carried["stale"] = True
                countries.append(carried)
            continue
        standard = round(float(rec["standard"]), 2)
        currency = rec.get("currency")
        old = prev_idx.get(code)
        last_changed = old.get("last_changed") if old else None
        if old is not None and old.get("standard") != standard:
            last_changed = today
            changes.append((name, "VAT", old.get("standard"), standard))
        # No observed change date yet: seed the documented effective date of the
        # current rate, but only while the live rate still matches the seed.
        if last_changed is None:
            ke = known.get(code)
            if ke is not None and abs(float(ke.get("standard", -1)) - standard) < 1e-9:
                last_changed = ke.get("since")
        countries.append({
            "code": code,
            "name": name,
            "type": "VAT",
            "standard": standard,
            "currency": currency,
            "region": region,
            "last_changed": last_changed,
            "source": "VATNode / EC TEDB",
        })

    # GST jurisdictions, hand maintained.
    for code, rec in manual.get("countries", {}).items():
        standard = round(float(rec["standard"]), 2)
        old = prev_idx.get(code)
        last_changed = rec.get("last_changed")
        if old is not None and old.get("standard") != standard:
            # A manual edit to the rate also counts as a change worth notifying.
            changes.append((rec["name"], rec.get("type", "GST"), old.get("standard"), standard))
            last_changed = last_changed or today
        countries.append({
            "code": code,
            "name": rec["name"],
            "type": rec.get("type", "GST"),
            "standard": standard,
            "currency": rec.get("currency"),
            "region": rec.get("region", "Asia-Pacific"),
            "last_changed": last_changed,
            "source": "manual",
        })

    countries.sort(key=lambda c: c["name"])

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_version": vatnode.get("version"),
        "sources": {
            "europe": vatnode.get("url", VATNODE_URL),
            "gst": "data/manual_rates.json",
        },
        "count": len(countries),
        "countries": countries,
    }
    return out, changes, prev


def rates_differ(new, prev):
    """True if any standard rate differs from the previous snapshot (ignores timestamps)."""
    if prev is None:
        return True
    # First real run after seeding: commit once to replace the seeded placeholder
    # provenance with live source metadata, even if every rate happened to match.
    if str(prev.get("source_version", "")).startswith("seed"):
        return True
    old_idx = {c["code"]: c.get("standard") for c in prev.get("countries", [])}
    new_idx = {c["code"]: c.get("standard") for c in new.get("countries", [])}
    return old_idx != new_idx


def fmt_rate(v):
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:g}"


def pts_phrase(old, new):
    p = abs(round(float(new) - float(old), 2))
    ptxt = str(int(p)) if p == int(p) else f"{p:g}"
    unit = "point" if abs(p - 1.0) < 1e-9 else "points"
    return f"{ptxt} {unit}"


def move_verb(old, new, past=False):
    up = float(new) > float(old)
    if past:
        return "raised" if up else "cut"
    return "raises" if up else "cuts"


def describe_change(name, typ, old, new):
    return (f"{name} {move_verb(old, new, past=True)} its standard {typ} by "
            f"{pts_phrase(old, new)}, from {fmt_rate(old)}% to {fmt_rate(new)}%")


def write_github_output(changed, summary, headline, subject, email_md):
    out_file = os.environ.get("GITHUB_OUTPUT")
    if not out_file:
        return
    with open(out_file, "a", encoding="utf-8") as f:
        f.write(f"changed={'true' if changed else 'false'}\n")
        f.write(f"headline={headline}\n")
        f.write(f"subject={subject}\n")
        # Multiline outputs use the heredoc syntax GitHub Actions expects.
        f.write("summary<<EOF\n")
        f.write(summary + "\n")
        f.write("EOF\n")
        f.write("email_md<<EOF_MD\n")
        f.write(email_md + "\n")
        f.write("EOF_MD\n")


def main():
    out, changes, prev = build()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RATES_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    changed = rates_differ(out, prev)
    site = "https://elenamihaimarginean.github.io/vat-gst-rates-tracker/"
    if changes:
        n = len(changes)
        summary = "VAT/GST rate changes detected:\n" + "\n".join(
            f"{name}: standard {typ} {fmt_rate(old)}% → {fmt_rate(new)}% "
            f"({move_verb(old, new, past=True)} {pts_phrase(old, new)})"
            for (name, typ, old, new) in changes
        )
        headline = "; ".join(
            f"{name} {fmt_rate(old)}%→{fmt_rate(new)}%" for (name, typ, old, new) in changes
        )
        if len(headline) > 100:
            headline = f"{n} rate changes"

        if n == 1:
            name, typ, old, new = changes[0]
            subject = (f"{name} {move_verb(old, new)} standard {typ} by "
                       f"{pts_phrase(old, new)} to {fmt_rate(new)}%")
            email_md = (
                f"**{describe_change(name, typ, old, new)}.**\n\n"
                f"See all current standard rates across {out['count']} jurisdictions on "
                f"[the live tracker]({site})."
            )
        else:
            subject = f"{n} standard VAT/GST rate changes"
            bullets = "\n".join(
                f"- **{name}**: standard {typ} {fmt_rate(old)}% → {fmt_rate(new)}% "
                f"({move_verb(old, new, past=True)} {pts_phrase(old, new)})"
                for (name, typ, old, new) in changes
            )
            email_md = (
                f"**{n} standard rates changed:**\n\n"
                f"{bullets}\n\n"
                f"See all current standard rates across {out['count']} jurisdictions on "
                f"[the live tracker]({site})."
            )
    elif changed:
        summary = "Rate set changed (country added or removed)."
        headline = "rate set updated"
        subject = "Tracked jurisdictions updated"
        email_md = f"The set of tracked jurisdictions changed. See [the live tracker]({site})."
    else:
        summary = "No rate changes."
        headline = "no change"
        subject = "No change"
        email_md = summary

    print(summary)
    print(f"Wrote {RATES_PATH} with {out['count']} jurisdictions.")
    write_github_output(changed, summary, headline, subject, email_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
