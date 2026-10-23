# Jazz Package Reference Data (Scraping Notes)

Project: ChurnGuard v2. Snapshot date: 2026-10-10.

## Why

The simulator's `packages_master` should be close to real market packages. Dummy prices would make any later comparison with other networks misleading, so one network's public package data was collected once as a reference snapshot. Our own packages get our own names and IDs; Jazz names are not reused.

## Source

- Network: Jazz (official site), public prepaid pages only.
- Listing page: `https://jazz.com.pk/prepaid/data`
- Detail pages: `https://jazz.com.pk/prepaid/<package-slug>`
- `robots.txt` of jazz.com.pk was checked (no disallow rules, sitemap listed). Website terms were not treated as covered by robots.txt, so the scrape was kept small: one snapshot, a 2 second pause between detail pages.
- Prices on the site include tax. We store them as `price_incl_tax`.

## Method (4 scripts in `tools/`)

| Script | Reads | Writes |
|---|---|---|
| `check_source.py` | robots.txt and one test page | nothing (prints only) |
| `scrape_jazz_step1.py` | listing page from the internet | `data/reference/jazz_raw/prepaid_data.html` |
| `scrape_jazz_step2.py` | `prepaid_data.html` | `data/reference/jazz_listing.csv` (96 cards), 3 sample detail pages |
| `scrape_jazz_step3.py` | `jazz_listing.csv` | remaining `jazz_raw/detail_*.html`, `data/reference/jazz_packages.csv` |

Run every script from the project root, for example `python tools/scrape_jazz_step3.py`.

## Numbers

- Cards on the listing page: 96 (many are not packages: insurance, tunes, call settings).
- Cards with a price: 42.
- Candidates fetched: 33 (price between Rs 20 and Rs 3000, no per-minute rates, no roaming or Hajj bundles).
- Rows in `jazz_packages.csv`: 33.

## Files

| File | Content | Used later |
|---|---|---|
| `data/reference/jazz_raw/prepaid_data.html` | copy of the listing page | evidence only |
| `data/reference/jazz_raw/detail_*.html` (33) | copy of each package page | evidence only |
| `data/reference/jazz_listing.csv` | all 96 cards: name, price, link | intermediate |
| `data/reference/jazz_packages.csv` | 33 packages: price, validity, data, minutes, SMS, quota line, `needs_review`, date | yes, source for `packages_master` |

`data/` is in `.gitignore`. The cleaned final file will be kept in `config/reference/operator_packages.csv` with a short `SOURCE.txt`, so it travels with the project.

## `jazz_packages.csv` columns

`name`, `url`, `price_incl_tax`, `validity_text`, `validity_days`, `data_mb`, `jazz_min`, `other_net_min`, `sms`, `quota_line`, `needs_review`, `collected_date`.

Conversion rules: 1 GB = 1024 MB; Monthly = 30 days, Weekly = 7, Daily = 1.

## Known limits

- The quota is one text line on the page, so some lines are unclear. Example: Monthly Freedom reads "100 GB Data 750 Other Network Min 3000 Jazz Min SMS", where the SMS count is not stated clearly. Such rows get `needs_review = True` and are fixed by hand.
- Several packages are regional (city or province offers). They are kept in the file and can be filtered later.
- Prices change often (a price increase was reported for May 2026), so this is a dated snapshot, not live data.
- Customers in the simulator are still synthetic. Real package data does not make the usage data real.
- Only the `/prepaid/data` listing was scraped. Other listing pages (all-in-one, price plans) were not.

## Status and next steps

1. Review rows with `needs_review = True` and fix them by hand.
2. Save the cleaned file as `config/reference/operator_packages.csv`.
3. Write `simulator/masters/packages.py` to build `packages_master` (our own names and `package_id`) from that file.
4. Later: a separate `competitor_offers` table from other networks for the solution phase, kept apart from `packages_master`.