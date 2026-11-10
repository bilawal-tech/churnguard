# ChurnGuard v2 - Event Schemas (consolidated)

Source: Claude Docs "ChurnGuard v2 - Phase 1 Schema and Simulator Design" (v1.1, with section 10 additions) plus the decisions made later. Where the old doc and the newer decisions disagree, the newer decision is used and marked **[naya]**. Items still undecided are marked **[tay karna hai]**. Items settled in Step 4 are marked **[tay hua]**.

## 0. Old doc vs newer decisions (naya hi sahi)

| Cheez | Old doc | Ab |
|---|---|---|
| tower_id | T0001 | T01001 (shehar ka block: Karachi T01xxx, Lahore T02xxx, Islamabad_Rawalpindi T03xxx ...) |
| customer_id | C000123 | C0000001 (width 7) |
| Geography | Pilot sirf Lahore, ~60-100 towers | 8 shehar, 110 towers, 25 teams, 30,000 customers |
| zone | Gulberg, DHA ... (Lahore zones) | NE / NW / SE / SW (shehar ke markaz se), jaise Karachi-NW |
| zone in customer_events | section 10 mein tha | **[tay hua]** nahi rakha, zone hamesha tower_id se tower_master se join hota hai |
| tower_metrics volume | 400 towers, ~1.7M | 110 x 24 x 180 = ~0.48M events |
| Package minutes | quota_voice_min | 4 fields: quota_onnet_min, quota_offnet_min, quota_anynet_min, quota_intl_min |
| Packages | ~40 rows, ids like PKG_D1_1GB | 29 (Jazz CSV se), id P_<TYPE>_<DAYS>D_<4 hex>, types social/voice/data/combo, + region, night_only |
| Team fields | contact, team_size | built masters mein nahi hain (team_id, region, city, zone, base_lat, base_lon) |
| Dirty data | ~1-2% | nulls 1.5%, duplicates 0.5%, late 1.5% (max 48 ghante) |
| field_team_status_events | optional, hourly | team movement abhi nahi (fixed base), is liye nahi banega |
| Profile aur customer ki values | **[tay karna hai]** | **[tay hua]** age_band, gender, language_pref, arpu_band, acquisition_channel, device_type ki taqseem neeche section 3 mein |
| Customer burst | pehle 7 din, 20,000 | decaying burst, config key `customers.burst_decay` (0.8) |

## 1. Common envelope (har event mein)

| Field | Type | Note |
|---|---|---|
| event_id | string | seed se deterministic, dedupe key. 20 hex characters: SHA-256 (seed, topic, customer_id, aur zaroorat par ek extra hissa: profile_version ya usage ka band index) ka shuru ka hissa |
| event_time | timestamp | simulated, ISO-8601 +05:00. Customer aur profile events mein signup band ka shuru, usage mein us band ka shuru |
| schema_version | string | "1.0" |
| source | string | "simulator" |

`ingest_time` consumer lagata hai, Kafka schema mein nahi hota.

## 2. Reference masters (seedha S3, Kafka se nahi)

Har record mein schema_version aur source hote hain. Output local: `data/raw/<master>/<master>.jsonl`.

### tower_master (raw/tower_master/) - 110 rows
tower_id (string), region (string), city (string), zone (string), lat, lon (float), tower_type (3G/4G/5G), capacity_users (int), neighbor_tower_ids (list[string], usi shehar ke qareebi 3), install_date (date).

### packages_master (raw/packages_master/) - 29 rows
package_id, name, package_type (social/voice/data/combo), price_pkr, validity_days, quota_onnet_min, quota_offnet_min, quota_anynet_min, quota_intl_min, quota_sms, quota_data_mb, quota_social_mb, night_only (bool), region (list: ["all"] ya shehar), auto_renew_allowed (bool), min_balance_required (= price).

### field_teams_master (raw/field_teams_master/) - 25 rows
team_id (FT<shehar no><team no>, jaise FT0101), region, city, zone, base_lat, base_lon (markaz se ~8 km, fixed).

### event_calendar (config/)
Pakistan ke events (14 August, Ramadan, Eid, cricket). Chand wali tareekhein official calendar se verify karni hain.

## 3. Event topics

Kafka key aur S3 partition har topic ke naam ke saath. Topics ki setting: 6 partitions, replication 1, retention 30 din.

### customer_events (key=customer_id, partition signup_month=)
Ek customer ka ek hi event, signup ke waqt. Step 4 mein bana (`simulator/customers/events.py`).

| Field | Type | Note |
|---|---|---|
| customer_id | string | C0000001 (numbering 1 se shuru) |
| signup_date | date | signup band ki tareekh |
| region, city | string | dono mein shehar ka wahi naam (jaise Islamabad_Rawalpindi), tower_master ke mutabiq |
| zone | - | **[tay hua]** is event mein nahi. Customer ka tower badalta rehta hai (usage_events ka tower_id har band alag), is liye zone tower_id se tower_master se join hoga. Customer ke paas sirf home_tower_id hai |
| segment | string | prepaid (88%) / postpaid (12%) (simulator state mein `plan_type`) |
| acquisition_channel | string | **[tay hua]** retailer 55%, online 15%, campaign 15%, referral 10%, other 5% |
| device_type | string | **[tay hua]** smartphone_android 62%, smartphone_ios 8%, feature_phone 30%. Value `device_type_for(cfg, n)` se aati hai (seed se, hamesha wahi), usage generator bhi yahi use karta hai |
| initial_balance | float | PKR. Prepaid 50 se 500 (chhote zyada), postpaid 0. Pehle int likha tha, ab float (jaise 83.46), Silver mein cast hoga |
| home_tower_id | string | tower_master se link, usi shehar ka tower |

### profile_events (key=customer_id, partition signup_month=)
Ek customer ka ek record, signup ke waqt (version 1). Step 4 mein bana.

| Field | Type | Note |
|---|---|---|
| customer_id | string | |
| profile_version | int | abhi 1 |
| age_band | string | **[tay hua]** 18-24 (25%), 25-34 (35%), 35-44 (22%), 45-54 (12%), 55+ (6%) |
| gender | string | **[tay hua]** male 60%, female 40% |
| phone_masked | string | 0334-xxxx09 style, pattern `03dd-xxxxdd`. Shuru se hi masked, asli number kabhi nahi banta |
| cnic_masked | string | xxxxx-xxxxx45-7 style, pattern `xxxxx-xxxxxdd-d`. Aakhri digit mard ke liye toh, aurat ke liye jufft |
| language_pref | string | **[tay hua]** Urdu 65%, English 25%, Regional 10% |
| arpu_band | string | **[tay hua]** low (300 PKR mahine se kam), mid (300 se 800), high (800 se zyada). Signup ke waqt ka andaza: prepaid 44/40/16, postpaid 10/40/50, overall ~40/40/20. Asli ARPU baad mein usage aur recharge se banega |

### usage_events (key=customer_id, partition event_date=)
Har ACTIVE customer, har din, har time band (Night 0-6, Morning 6-12, Afternoon 12-18, Evening 18-24) ka ek summary. Step 4 mein pehla sada version bana (`simulator/usage/`), asli rules Steps 5 se 7 mein.

| Field | Type | Note |
|---|---|---|
| customer_id | string | |
| event_date | date | simulated din |
| time_band | string | Night / Morning / Afternoon / Evening |
| tower_id | string | **[tay hua]** 85% bands mein home tower, 15% mein home tower ke 3 qareebi (usi shehar) mein se ek. Qareebi tower na ho to home tower |
| calls_onnet_min, calls_offnet_min, calls_intl_min | int | anynet sirf package quota hai, usage mein alag field nahi (doc ke mutabiq). Chhote average par zyada tar 0, kabhi 1 (Poisson) |
| sms_count | int | |
| data_mb_whatsapp, data_mb_social, data_mb_video, data_mb_browsing, data_mb_other | float | 2 decimal tak. Feature phone ka data sirf data_mb_other mein (din ka 5 se 20 MB) |
| dropped_calls | int | **[tay hua]** calls = (onnet + offnet + intl minutes) / 3, har call ke girne ka base chance 1.5% (code constant `BASE_DROP_RATE`). Step 5 mein tower health se barhega (DEGRADED ~3x, CRITICAL ~8x) |
| active_package_ids | list[string] | Step 7 se pehle khali list |
| spend_from_package | float | Step 7 se pehle null |
| spend_from_balance | float | PKR, Step 7 se pehle null |

Usage kitna hota hai (**[tay hua]**):
- Persona device ke hisaab se: feature_phone sirf call_heavy (65%) ya sms_heavy (35%), smartphone call_heavy (15%), whatsapp_only (43%), data_heavy (42%). Overall ~30/10/30/30.
- Roz ka average (onnet, offnet, intl min, SMS, data MB): call_heavy 40/30/1/5/300, sms_heavy 8/6/0.1/40/150, whatsapp_only 6/4/0.2/3/500, data_heavy 10/8/0.3/3/1500.
- Din ka hissa bands mein: Night 10%, Morning 30%, Afternoon 25%, Evening 35%.
- Customer ka apna fixed factor (0.5x se 1.8x) aur har band par ~25% upar neeche noise.
- Naya customer usi band se usage dena shuru karta hai jis mein signup hua.

### recharge_events (key=customer_id, partition event_date=)
customer_id, event_date, amount_pkr (int), channel (retailer / app / easypaisa / jazzcash / card), balance_before, balance_after (float). Recharge ki ginti aur average gap curated zone mein banenge.

### package_events (key=customer_id, partition event_date=)
customer_id, event_date, subscription_id, action (PURCHASE / AUTO_RENEW / EXPIRE / QUOTA_EXHAUSTED / ADDON_PURCHASE / AUTO_RENEW_OFF), package_id (packages_master se link), price_pkr, validity_days, balance_after.

### offer_events (key=customer_id, partition event_date=)
customer_id, event_date, offer_id, offer_type, action (SENT / ACCEPTED / EXPIRED), group (treatment / control), trigger_rule (balance / usage_mix / weekend / event), campaign_name (nullable, jaise Eid). Control group aur frequency cap zaroori.

### lifecycle_events (key=customer_id, partition event_date=)
customer_id, event_date, from_status, to_status (ACTIVE / SUSPENDED / CHURNED / REACTIVATED), churn_reason (nullable, ground truth, model feature kabhi nahi), inactivity_days (nullable). Churn_reason ki values ki list doc mein nahi hai **[tay karna hai]**. At-risk chhupi state hai, publish nahi hoti.

### network_events (key=region, partition event_date=)
Outage ka start aur end (ground truth).
outage_id, region, tower_id (nullable, null = poore region ka outage), status (START / END), severity (int 1-3), affected_pct (float), cause (nullable: power cut, fibre cut, hardware, congestion).

### tower_metrics_events (key=tower_id, partition event_date=)
Har tower ka har ghante ek snapshot.
tower_id, event_date, signal_strength_dbm (float), load_pct (float, connected users / capacity), dropped_call_rate (float), avg_data_speed_mbps (float), status (HEALTHY / DEGRADED / CRITICAL / DOWN).

### complaint_events (baad mein)
Semi/unstructured text, key=customer_id, tower_id ke saath. Baad ke phase mein design hoga.

### Solution layer ke topics (simulator nahi banata)
- **tower_alert_events:** tower_id, lat, lon, city, region, predicted_or_actual_status, risk_score, last_hour_metrics, affected_customers, nearest_team_id, severity.
- **tower_reassignment_events:** sirf schema, banenge nahi (customer_id, old_tower_id, new_tower_id, reason).

## 4. Tower health states (config thresholds)

| State | Condition | Asar |
|---|---|---|
| HEALTHY | signal achha, load < 70% | normal |
| DEGRADED | signal -95 dBm se kam ya load >= 85% | dropped calls barhte hain, speed girti hai |
| CRITICAL | signal -105 dBm se kam ya load >= 100% | bohat dropped calls |
| DOWN | tower band | us ke customers ka usage ruk jata hai |

~70% failures se pehle signal 2-12 ghante dheere girta hai, ~30% achanak (power cut, fibre cut). Shor aur overlap jaan boojh kar: kuch DEGRADED towers khud theek ho jate hain, kuch HEALTHY achanak gir jate hain.

## 5. S3 raw layout (bucket churnguard-data-bilawal, ap-south-1)

| Prefix | Partition |
|---|---|
| raw/customer_events/, raw/profile_events/ | signup_month= |
| raw/usage_events/, recharge_events, package_events, lifecycle_events, offer_events, network_events, tower_metrics_events | event_date= (simulated din) |
| raw/tower_master/, packages_master/, field_teams_master/ | koi nahi (static) |

Consumers bari gzip files likhte hain (batching 5000 records ya 60 seconds), chhoti files nahi.

## 6. Simulator ki customer state (SQLite, publish nahi hoti)

Persona (call-heavy, SMS-heavy, WhatsApp-only, data-heavy), price sensitivity, balance, active subscriptions (package_id, baqi quota, expiry, auto_renew), home tower, at-risk flag, last_active. Persona aur price sensitivity seed se dobara ban jate hain (alag column ki zaroorat nahi). Abhi `customer_state` table mein: customer_id, plan_type, status, status_since, balance, home_tower_id, last_active, at_risk.

**[tay hua]** `city` ka column nahi rakha: city home_tower_id se tower_master se mil jati hai aur kabhi badalti nahi. `device_type` aur usage ka per-customer factor bhi SQLite mein nahi, seed se dobara ban jate hain (`device_type_for`, `persona_for`, `customer_factor`). Persona ab device ke hisaab se chuni jati hai (feature phone sirf call_heavy ya sms_heavy).