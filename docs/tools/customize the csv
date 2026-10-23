## Update: parsing and cleaning (final)

### What went wrong first

The first parser (`scrape_jazz_step3.py`) kept only the last piece of the quota text. Example: Weekly Super Max showed only "1000 SMS" instead of 30 GB, 1000 Jazz mins, 150 other network mins and 1000 SMS. Ten rows also had no price and some validity texts were messy. Its output (`jazz_packages.csv`) is not used.

### Fix

- `tools/parse_jazz.py` re-parses the saved HTML files (no new download) and writes `data/reference/jazz_packages_v2.csv`.
- Parsing was still weak for about 12 rows (for example "15 GB" without the word "Data", "12GBs Generic", "On-Net", "All-Net", "SM" typo). These rows were corrected by hand from the page text.
- Result: `config/reference/operator_packages.csv`, 29 packages. This is the only file used to build `packages_master`.

### Packages left out (4)

- We5 Super, We5 Social, We5 GupShup: family bundles shared by 5 people, not a single-customer package.
- Super Woman Bundle: healthcare services and unlimited minutes only 8 AM to 6 PM, which does not fit the quota model.

### Interpretation rules (marked "assumed" in the `note` column)

- "Jazz Mins & SMS": SMS count taken equal to the minutes.
- Handset or mobile insurance and other add-ons are ignored.
- "x + 6 days" validity is taken as 7 days; "Weekly X Plus" validity is assumed weekly (7 days).
- `region` is guessed from the package name; Lajawab Haftawar and MONTHLY bachat are marked `check`.
- 1 GB = 1024 MB; prices include tax.

### What the 29 packages look like

About 21 are combo bundles (data plus minutes plus SMS), 5 are social (TikTok, YouTube, Instagram, Snapchat, WhatsApp), 2 are voice only and 1 is night-only data. Validity: 1, 3, 7, 30 and one 90 day package (to verify). Jazz sells few single-type packages, so `packages_master` keeps the real structure instead of the earlier plan of 40 packages by type. The `packages.count` value in `config.yaml` is no longer used.

### Files kept in `tools/`

`scrape_jazz_step1.py`, `scrape_jazz_step2.py`, `scrape_jazz_step3.py`, `parse_jazz.py`. `check_source.py` was deleted.

### Next step

Write `simulator/masters/packages.py` to build `packages_master` from `operator_packages.csv`, with our own package names and `package_id`.