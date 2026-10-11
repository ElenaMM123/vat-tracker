# VAT and GST Rates Tracker

Live, auto-updating standard VAT and GST rates for 33 jurisdictions across Europe and
Asia-Pacific (the EU-27, the UK, Norway, Switzerland, and Singapore, Australia and New
Zealand), with an email alert when a rate changes.

Live table: https://elenamihaimarginean.github.io/vat-gst-rates-tracker/

## What it does

- Shows a current table of standard rates, served as a static page on GitHub Pages.
- Runs a daily job that detects rate changes, records them, and sends alerts: an email to
  subscribers (via Buttondown) and a GitHub Release for anyone watching the repository.

It runs entirely on GitHub Actions and GitHub Pages. No server and no database.

## How it works

```
European rates (EC TEDB via VATNode) ─┐
                                      ├─> daily GitHub Action ─> commit when a rate changed ─┬─> GitHub Pages table
Asia-Pacific GST (manual)             ┘                                                      ├─> email alert (Buttondown)
                                                                                            └─> GitHub Release
```

- European rates come from the [VATNode dataset](https://github.com/vatnode/eu-vat-rates-data),
  which is sourced from the European Commission's Taxes in Europe Database (TEDB) and checked
  daily. The job fetches the current JSON from its CDN.
- Asia-Pacific GST (Singapore, Australia, New Zealand) is maintained in
  `data/manual_rates.json`.
- Each run writes `data/rates.json` and commits it only when a rate actually changed, so the
  commit history of that file is a dated record of every change.
- The data source carries no per-country effective date, so the documented effective date of
  each current rate is seeded in `data/known_effective.json`. Once a rate changes, the observed
  change date takes over automatically.

## Repository layout

```
.
├── index.html                      The live table (served by GitHub Pages)
├── assets/og-image.png             Social preview image (link/share card)
├── data/
│   ├── rates.json                  Generated snapshot, committed when a rate changes
│   ├── manual_rates.json           Asia-Pacific GST rates
│   └── known_effective.json        Effective date of each current standard rate
├── scripts/
│   └── update_rates.py             Fetch, merge, diff, and format alerts (standard library only)
└── .github/workflows/
    └── update-rates.yml            Daily schedule, commit, release, and email on change
```

## Data sources

- European rates: European Commission Taxes in Europe Database, via the VATNode dataset (checked daily).
- Asia-Pacific GST: the national tax authorities (Singapore IRAS, Australia ATO, New Zealand Inland Revenue), maintained by hand in `data/manual_rates.json`.

## Running locally

```bash
python3 scripts/update_rates.py      # fetch, diff, and rewrite data/rates.json
python3 -m http.server               # then open http://localhost:8000
```

## Adjusting scope

- European country: edit the `EUROPE` dictionary in `scripts/update_rates.py`.
- Non-European country: add an entry to `data/manual_rates.json`.
- Effective dates: edit `data/known_effective.json`.
- Schedule: edit the `cron` line in `.github/workflows/update-rates.yml` (07:30 UTC, just
  after the source's daily refresh).

## Author

Built by Sorina Elena Mihai-Marginean.
[GitHub](https://github.com/elenamihaimarginean) · [LinkedIn](https://www.linkedin.com/in/sorina-elena-mihai-marginean/)

---

Standard rates only. For reference, not tax advice.
