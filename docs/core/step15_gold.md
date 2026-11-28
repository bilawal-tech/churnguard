# Step 15: Gold (churn features + label)

Run in WSL from the project root after Silver:

    python -m gold.run
    python -m gold.verify_gold

Gold reads Silver Parquet and writes one table to `data/gold/churn_features`.
The cohort is customers active on 2026-07-28. `churned_60d` marks a
`CHURNED` status beginning from 2026-07-29 through 2026-09-26, inclusive.

Features cover 7/30-day usage, usage change against the preceding 28-day weekly
average, recharge, packages, offers, home-tower outages/health, and profile
attributes. Event inputs are limited to dates before the cutoff; tower outages
are clipped to the 30 days before the cutoff. Missing numeric values are zero,
missing categories are `unknown`, and missing days-since values are 999.
Offer acceptances are reconstructed from pre-cutoff offer events rather than
the full-period offer summary. Package renewals are counted from pre-cutoff
package events rather than the full-period `subscriptions.n_renewals`.

Label/status history columns and other post-cutoff outcomes are never emitted
as features. `group` is not a feature.
