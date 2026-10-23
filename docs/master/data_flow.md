config.yaml ──► common.py (config padhna, ID, seed)
                    │
     ┌──────────────┼──────────────────┐
     ▼              ▼                  ▼
 towers.py     packages.py       field_teams.py
     │              ▲                  │
     │      operator_packages.csv      │
     │      (Jazz scraping se)         │
     └──────────────┼──────────────────┘
                    ▼
            run_masters.py
                    │
                    ▼
   data/raw/tower_master | packages_master | field_teams_master
                    │
                    ▼  (baad mein, Step 12)
                  S3 raw




 Packages path (scraping)  

 Jazz ki website
   ▼ scrape_jazz_step1/2/3.py
HTML files aur jazz_listing.csv
   ▼ parse_jazz.py
jazz_packages_v2.csv
   ▼ maunally cleaning
config/reference/operator_packages.csv
   ▼ packages.py
packages_master               