# Corvella Pay Disputes — Source Data Specification

Nov 14, 2026 · Adrieli Dal'Toé

## Purpose and scope

This document specifies the synthetic source data that the PySpark generator produces: which files each source system sends, their columns, when they arrive, and the rules that make the data behave similar to the real process. It is the contract between the generator and the pipeline: the ingestion job and the dbt sources are built against it.

The sources are the seven listed in the [solution design](solution_design.md#source-data), which selected them to answer the 17 business questions in the [business context](business_context.md#business-questions). The solution design explains *why* each source exists; this document defines *exactly what* the generator writes.

How the data reaches the pipeline is described in [ADR-002](architecture_decision_records/adr-002-generate-once-replay.md): the generator writes the full history once, grouped by arrival time, into the `source_history` volume, and the replay job copies it into the `inbox` volume one month, day or hour at a time.

## Conventions

These apply to every source unless its section says otherwise.

| Topic | Rule |
| --- | --- |
| History window | 24 months, from 2024-11-01 to 2026-10-31 (parameters `start_date`, `end_date`). The end date is the simulated "today": nothing arrives after it. |
| Warm-up | Payments start 120 days before the window (from 2024-07-04), so disputes received in the first months link to payments that exist. Warm-up files are released with the first backfill batch. |
| Scale | About 1% of Corvella Pay's volume (parameter `scale`, default 0.01) |
| Reproducibility | A fixed `seed` (default 42). The same parameters always produce identical files. Random values are derived from a hash of the record's key and the seed, not from `rand()`, so the output doesn't depend on how Spark partitions the data. |
| Time zone | All timestamps are UTC, written as ISO 8601 with a `Z` suffix (`2026-08-14T15:32:07Z`). Business days, business hours and the ledger day follow US Eastern time; their UTC values are stored. |
| Business days | Monday to Friday, US Eastern time. Bank holidays are ignored (simplification). |
| Money | Two decimal places, US dollars only. In JSON, amounts are strings (`"100.00"`) so no value passes through a floating-point type; bronze casts them to `DECIMAL(18,2)`. |
| Card data | Only `card_bin` (first six digits) and `card_last4`. The full card number is never generated. |
| Personal data | Names and emails are obviously fake (`cardholder_004812@example.com`) and exist only so column masks can be tested. |
| JSON files | JSON Lines (one object per line), UTF-8. Missing values are `null`, not absent keys. |
| CSV files | UTF-8, comma-separated, header row, `.` as decimal separator, empty field for null. |
| IDs | A prefix plus a code built from a sequence number, so IDs never collide: `pay_8F3K2Q7A1B`, `mer_00412`. Prefixes: `pay_` payment, `evt_` gateway event, `mer_` merchant, `dsp_` dispute, `ntf_` dispute notification, `alr_` alert, `ale_` alert event, `act_` case action, `acm_` account manager, `ops_` Disputes Operations analyst. |

## How the sources connect

```mermaid
---
title: Disputes reach the payment only through the settlement line
---
flowchart LR
    merchants["<b>Merchants</b><br/>KYC system"]
    gateway["<b>Gateway events</b><br/>payment_id"]
    settlement["<b>Settlement lines</b><br/>payment_id +<br/>acquirer_reference"]
    disputes["<b>Dispute notifications</b><br/>acquirer_reference"]
    alerts["<b>Early alerts</b><br/>acquirer_reference"]
    cases["<b>Case actions</b><br/>dispute_id"]
    balances["<b>Merchant balances</b><br/>merchant_id"]

    gateway -- merchant_id --> merchants
    settlement -- payment_id --> gateway
    disputes -- acquirer_reference --> settlement
    alerts -- acquirer_reference --> settlement
    cases -- dispute_id --> disputes
    balances -- merchant_id --> merchants
```

The networks identify a transaction by its `acquirer_reference`, which the acquirer assigns at settlement. The gateway never sees it. That's why disputes and alerts can only be linked to a payment through the settlement lines.

## Files and delivery

| # | Source | Inbox folder | Format | One file per | Arrives |
| --- | --- | --- | --- | --- | --- |
| 1 | Payment gateway | `gateway_events` | JSON Lines | Hour | 5 minutes after the hour it covers |
| 2 | Acquirer | `settlement_files` | CSV | Business day | 10:00 UTC on the settlement date |
| 3 | Card networks | `dispute_notifications` | JSON Lines | Network batch, 4 per business day | 14:00, 16:00, 18:00 and 20:00 UTC |
| 4 | Card networks | `early_alerts` | JSON Lines | Network batch, 4 per day (every day) | 02:00, 08:00, 14:00 and 20:00 UTC |
| 5 | Case system | `case_actions` | JSON Lines | Hour, 8:00–20:00 US Eastern | 5 minutes after the hour it covers |
| 6 | Know Your Customer system | `merchants` | JSON Lines | Day (only merchants created or changed that day) | 05:00 UTC the next day |
| 7 | Internal ledger | `merchant_balances` | CSV | Day | 06:00 UTC the next day |

**File names** carry the source and the arrival time, so the replay job can release files up to any simulated hour without opening them: `<source>_<YYYYMMDD>T<HH>.<ext>`, for example `gateway_events_20260814T16.json` or `settlement_20260817T10.csv`. The settlement file keeps the acquirer's own name in its `file_name` column.

**Folder layout**, the same in `source_history` and `inbox`:

```
/Volumes/<catalog>/landing/<source_history | inbox>/
    gateway_events/arrival_date=2026-08-14/gateway_events_20260814T16.json
    settlement_files/arrival_date=2026-08-17/settlement_20260817T10.csv
    ...
```

`arrival_date` is the UTC date of arrival. A late file goes in the folder of the day it actually arrives, not the day its data refers to.

## Source 1: Payment gateway events

One event stream for every step a payment takes in the gateway. A payment (`payment_id`) has one authorization and then, depending on the outcome, a capture, a void, refunds, or nothing.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| event_id | STRING | no | evt_4M9Q2K7D1X | Unique ID of the event |
| event_type | STRING | no | authorization | `authorization`, `capture`, `void` or `refund` |
| event_ts | TIMESTAMP | no | 2026-08-14T15:32:07Z | When the event happened in the gateway |
| payment_id | STRING | no | pay_8F3K2Q7A1B | Links every event of the same payment |
| merchant_id | STRING | no | mer_00412 | The merchant selling |
| amount | DECIMAL(18,2) | no | 100.00 | Authorized, captured, voided or refunded amount, always positive |
| currency | STRING | no | USD | Always `USD` |
| channel | STRING | auth only | card_not_present | `card_present` or `card_not_present` |
| card_brand | STRING | auth only | visa | `visa` or `mastercard` |
| card_type | STRING | auth only | credit | `credit`, `debit` or `prepaid` |
| card_bin | STRING | auth only | 411111 | First six digits of the card |
| card_last4 | STRING | auth only | 4242 | Last four digits |
| issuer_country | STRING | auth only | US | Country of the buyer's bank |
| mcc | STRING | auth only | 5651 | Merchant category code at the time of the payment |
| risk_score | DECIMAL(5,4) | auth only | 0.1200 | Corvella Pay's fraud score, 0 to 1 |
| status | STRING | auth only | approved | `approved` or `declined` |
| response_code | STRING | auth only | 00 | Issuer's answer (see generation rules) |
| decline_type | STRING | yes | null | `soft` or `hard`, only when declined |
| auth_code | STRING | yes | 834201 | Six-digit approval code, only when approved |
| capture_type | STRING | yes | null | `full` or `partial`, only on captures |
| refund_reason | STRING | yes | null | Only on refunds: `customer_return`, `duplicate_charge`, `service_cancelled`, `goodwill` or `dispute_alert` |

"auth only" means the column is filled on authorizations and null on the other event types; the payment's attributes come from its authorization.

**Generation rules**

- **Volume:** about 5,000 payments a day on average, growing 10% a year, with a weekly pattern (online payments dip on weekends, restaurants peak on Friday and Saturday) and a +20% season from mid-November to December.
- **Authorization:** 92% approved. Declines are 60% soft (`51` insufficient funds, `91` issuer unavailable) and 40% hard (`05` do not honor, `14` invalid card, `54` expired card, `43` stolen card). Approved authorizations have response code `00`.
- **Channel by segment:** e-commerce and subscriptions are card-not-present; restaurants and retail are 90% card-present.
- **Ticket size:** log-normal by segment, with means of about $85 (e-commerce), $35 (subscriptions), $45 (restaurants) and $60 (retail), between $1 and $5,000.
- **Cards:** Visa 65%, Mastercard 35%; credit 55%, debit 40%, prepaid 5%; issuer country US 95%. BINs come from a fixed pool of about 200 fictional BINs (Visa starts with 4, Mastercard with 51–55).
- **Capture:** card-present and subscription payments are captured in the same second as the authorization. E-commerce captures 0 to 5 days later, when the order ships; 3% are partial. Restaurants capture within 6 hours, with a tip of 0% to 25% added, so the captured amount can exceed the authorized one.
- **After approval:** 1% of approved payments are voided before capture, and 0.5% are never captured and simply expire, with no event.
- **Refunds:** 3% of captured payments get a refund 1 to 30 days after capture, 30% of them partial. Refunds triggered by an early alert use `refund_reason = dispute_alert` (see Source 4).
- **Risk score:** mostly low (beta distribution, mean 0.12), and higher on payments that later turn out to be fraud disputes, so the score carries some signal.

## Source 2: Acquirer settlement files

One CSV per business day, with one line per settled sale, refund or adjustment.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| file_name | STRING | no | acq_settlement_20260817.csv | The acquirer's name for the file |
| line_number | INT | no | 1834 | Position of the line in the file |
| settlement_date | DATE | no | 2026-08-17 | Day the money moved |
| acquirer_reference | STRING | no | 24692166229000012345678 | 23-digit reference the networks use for this transaction |
| payment_id | STRING | no | pay_8F3K2Q7A1B | Corvella Pay's payment reference |
| transaction_type | STRING | no | sale | `sale`, `refund` or `adjustment` |
| gross_amount | DECIMAL(18,2) | no | 100.00 | Transaction amount; negative for refunds, 0 for adjustments |
| interchange_fee | DECIMAL(18,2) | no | 2.10 | Paid to the buyer's bank |
| network_fee | DECIMAL(18,2) | no | 0.14 | Paid to the card network |
| acquirer_fee | DECIMAL(18,2) | no | 0.20 | Paid to the acquirer |
| net_amount | DECIMAL(18,2) | no | 97.56 | gross_amount − the three fees |
| currency | STRING | no | USD | Always `USD` |

**Generation rules**

- **Settlement date:** captures are batched at 23:00 US Eastern; a batch settles on the next business day (80%) or the one after (20%). Monday's file therefore holds Friday's, Saturday's and Sunday's batches.
- **Acquirer reference:** one per sale line, unique; refund and adjustment lines carry the reference of the sale they belong to.
- **Fees on sales:** interchange of 2.00% + $0.10 for credit, 0.80% + $0.15 for debit, 1.50% + $0.15 for prepaid; network fee 0.14%; acquirer fee 0.20%. Each fee is rounded to the cent, half up.
- **Refund lines:** the settled refund amount as a negative `gross_amount`, with zero fees. Voids never reach settlement.
- **Adjustments:** about 0.05% of sales get an adjustment line in a later file (1 to 10 business days later): `gross_amount` 0 and a fee correction of a few cents, positive or negative.

## Source 3: Dispute notifications

One event per notice a network sends about a dispute. The notices of one dispute share its `dispute_id`; replaying them in order gives the dispute's status history from the network's side.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| notification_id | STRING | no | ntf_2H7K9P4Q1M | Unique ID of the notice |
| dispute_id | STRING | no | dsp_K82J1A6T3W | Same for every notice of the dispute, across rounds |
| acquirer_reference | STRING | no | 24692166229000012345678 | The disputed transaction, as the network knows it |
| network | STRING | no | visa | `visa` or `mastercard` |
| notification_type | STRING | no | chargeback_opened | `chargeback_opened`, `pre_arbitration_opened`, `arbitration_opened`, `dispute_won` or `dispute_lost` |
| reason_code | STRING | opened only | 13.1 | Network's reason code (see the reason code seed) |
| amount | DECIMAL(18,2) | no | 100.00 | Disputed amount on `*_opened`; amount returned to the merchant on `dispute_won`; 0 on `dispute_lost` |
| respond_by | DATE | opened only | 2026-10-21 | Deadline to respond to this round |
| received_ts | TIMESTAMP | no | 2026-09-21T14:00:00Z | When the notice arrived (the batch time) |
| cardholder_name | STRING | yes | Cardholder 004812 | Only on `chargeback_opened`; personal data |
| cardholder_email | STRING | yes | cardholder_004812@example.com | Only on `chargeback_opened`; personal data |

The network sends no notice when a dispute is accepted or expires. Those outcomes come from the case actions and the deadline: a dispute is **accepted** when a `merchant_accepted` or `auto_accepted` action exists, and **expired** when `respond_by` passes without an `evidence_submitted` action for that round.

**Generation rules**

- **Which sales are disputed:** each settled sale has a dispute probability built from its merchant's segment (subscriptions highest, restaurants and retail lowest), its risk tier, a per-merchant factor, and a portfolio trend calibrated to the targets below. A payment has at most one dispute, and a fully refunded payment is never disputed.
- **When:** the chargeback arrives 1 to 120 days after the sale: about 60% within 30 days, 85% within 60 days, the rest up to 120. Notices only arrive on business days.
- **Amount:** the full sale amount in 92% of disputes, part of it in 8% (mostly `processing_error`).
- **Reason category by segment:** e-commerce mostly `fraud` and `merchandise_not_received`; subscriptions mostly `subscription_cancelled`; restaurants and retail mostly `processing_error` and `fraud`. The reason code is then picked from the network's codes for that category.
- **Deadline:** `respond_by` is the received date + 30 days, for every round.
- **First round outcomes**, as shares of disputes received:

  | Outcome | Share | Rule |
  | --- | --- | --- |
  | Auto-accepted | about 12% | Every dispute under the auto-accept limit ($25), on the day it arrives |
  | Accepted by the merchant | about 13% | Merchant decides 2 to 15 days after being notified |
  | Expired | about 18% | No evidence submitted by `respond_by` (see Source 5 for where they stall) |
  | Fought | about 57% | `dispute_won` or `dispute_lost` arrives 20 to 45 days after the evidence is submitted |

- **Win rate of fought disputes:** about 45% overall, varying by reason category: `processing_error` 60%, `merchandise_not_received` 55%, `not_as_described` 40%, `subscription_cancelled` 35%, `fraud` 30%.
- **Second round:** 15% of won disputes get a `pre_arbitration_opened` 10 to 30 days after the win, with a new `respond_by`. The merchant accepts 40% of them and fights the rest, winning half. 3% of lost pre-arbitrations go to `arbitration_opened`, decided 30 to 60 days later.

## Source 4: Early alerts

Alerts the networks send before a chargeback, giving the merchant a chance to refund first. One row per alert event.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| alert_event_id | STRING | no | ale_7C2N5R8V4J | Unique ID of the alert event |
| alert_id | STRING | no | alr_3T6W1K9H2P | Same for every event of the alert |
| acquirer_reference | STRING | no | 24692166229000012345678 | The transaction the cardholder is unhappy with |
| network | STRING | no | visa | `visa` or `mastercard` |
| alert_type | STRING | no | alert_received | `alert_received`, `alert_refunded` or `alert_expired` |
| amount | DECIMAL(18,2) | no | 100.00 | Amount the cardholder is contesting |
| alert_ts | TIMESTAMP | no | 2026-09-03T08:00:00Z | When the event arrived (the batch time) |

**Generation rules**

- **Volume:** about 4 alerts a day, on sales 1 to 60 days old.
- **Refunded (60%):** the merchant refunds within 24 to 72 hours. The gateway gets a refund event with `refund_reason = dispute_alert`, the network sends `alert_refunded`, and no chargeback follows.
- **Expired (40%):** `alert_expired` 72 hours after the alert. 80% of expired alerts become a chargeback 3 to 20 days later, with the same `acquirer_reference`.

## Source 5: Case actions

The event export from the Disputes Operations case system: one row per action on a case. One case per dispute; the actions of every round belong to the same case.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| action_id | STRING | no | act_9D4F7L2S6B | Unique ID of the action |
| dispute_id | STRING | no | dsp_K82J1A6T3W | The dispute the case belongs to |
| stage | STRING | no | first_chargeback | Round the action belongs to: `first_chargeback`, `pre_arbitration` or `arbitration` |
| action_type | STRING | no | merchant_notified | `case_opened`, `merchant_notified`, `evidence_received`, `evidence_submitted`, `merchant_accepted` or `auto_accepted` |
| action_ts | TIMESTAMP | no | 2026-09-22T13:40:00Z | When the action was taken |
| actor | STRING | no | ops_007 | An analyst (`ops_001` to `ops_012`), `merchant` or `system` |

**Generation rules**

- **Case opened:** by `system`, within 1 hour of the chargeback notice arriving. Disputes under $25 also get `auto_accepted` at the same time, and nothing else.
- **Merchant notified:** by an analyst, 0 to 3 business days after opening (median 1), with a 5% tail of up to 10 days when the queue is backed up.
- **Evidence received:** from the merchant, for disputes the merchant fights: 3 to 25 days after notification, 20% of them after the internal 20-day limit.
- **Evidence submitted:** by an analyst, 1 to 5 business days after the evidence arrives, and only if that is on or before `respond_by`.
- **Accepted:** `merchant_accepted` by `merchant`, 2 to 15 days after notification.
- **Where expired disputes stall:** 55% were notified but no evidence ever arrived, 30% had evidence arrive too late to submit, and 15% were never notified at all. That's what question 3 measures.
- **Working hours:** analyst and merchant actions happen between 8:00 and 20:00 US Eastern on business days; `system` actions happen at any time.

## Source 6: Merchants (Know Your Customer system)

A daily change extract: one row for each merchant created or changed that day, with all of its current attributes. A merchant changed twice in one day appears twice, each row with its own `updated_at`.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| merchant_id | STRING | no | mer_00412 | Unique ID of the merchant |
| legal_name | STRING | no | Northwind Apparel LLC | Registered business name |
| mcc | STRING | no | 5651 | Merchant category code |
| segment | STRING | no | ecommerce | `ecommerce`, `subscriptions`, `restaurants` or `retail` |
| risk_tier | STRING | no | medium | `low`, `medium` or `high` |
| reserve_rate | DECIMAL(5,4) | no | 0.0500 | Share of sales held in reserve |
| status | STRING | no | active | `active`, `suspended` or `closed` |
| account_manager_id | STRING | no | acm_014 | Merchant Success manager (drives row filters) |
| contact_email | STRING | no | owner_00412@example.com | Personal data |
| onboarding_date | DATE | no | 2025-03-02 | Day the merchant went live |
| updated_at | TIMESTAMP | no | 2026-08-10T15:00:00Z | When this version took effect (the business change time) |

**Generation rules**

- **Portfolio:** about 300 active merchants at the start of the warm-up and about 400 at the end of the window. About 0.5 merchants are onboarded per day and about 0.35 close per day, so the history has roughly 650 merchants in total. Segment mix by merchant: e-commerce 40%, subscriptions 20%, restaurants 20%, retail 20%. Merchant size (share of payments) is skewed: the largest 10% of merchants process about half the volume.
- **Risk tier and reserve:** low (reserve 0%), medium (5%) or high (10%). New merchants start at medium in most cases.
- **Changes (type 2):** Risk reviews tiers weekly, on Mondays: each week about 1% of merchants move one tier up or down, and the reserve rate follows the tier. Segment and MCC change rarely (about 5 merchants over the whole history). Status moves to `suspended` or `closed` as described in "Behaviors" below.
- **Corrections (type 1):** about 10 legal names get a typo fixed during the history, with no other attribute changing.
- **Late-arriving dimension:** a new merchant's first payments happen on its onboarding date, but its record only arrives in the next morning's extract.
- **Backdated changes:** 2% of changes appear in an extract 1 to 3 days after their `updated_at`.

## Source 7: Merchant balances (internal ledger)

End-of-day balance per merchant, for every merchant that is active or still has money held.

| Column | Type | Null | Example | Meaning |
| --- | --- | --- | --- | --- |
| balance_date | DATE | no | 2026-09-21 | Ledger day (US Eastern) |
| merchant_id | STRING | no | mer_00412 | The merchant |
| available_balance | DECIMAL(18,2) | no | 1240.18 | Money owed to the merchant and not yet paid out; negative when debits exceed credits |
| reserve_balance | DECIMAL(18,2) | no | 7310.50 | Money held back as reserve |
| written_off_amount | DECIMAL(18,2) | no | 0.00 | Loss Corvella Pay absorbed that day because the balance and reserve didn't cover the debits |

**Generation rules.** The generator keeps a simple ledger per merchant and day:

- **Credits:** settled sales minus Corvella Pay's fees (2.9% + $0.30 card-not-present, 2.6% + $0.10 card-present), and amounts recovered on won disputes.
- **Debits:** refunds; on each chargeback, the disputed amount plus the dispute fee from the policy seed.
- **Payouts:** each business day, a positive available balance is paid out, minus the reserve contribution (the reserve rate times that day's settled sales). Payouts are not a source file; they only move the balance.
- **Reserve release:** reserve contributions are released into the available balance after 90 days.
- **Losses:** when a merchant's available balance is negative and it is suspended or closed, the reserve covers it first. Any remainder is written off that day in `written_off_amount`, and the available balance goes back to 0.

## Behaviors the generator must build in

These carry the business problems into the data, so the pipeline and the dashboards have something real to show.

| Behavior | How it appears | Target |
| --- | --- | --- |
| Rising dispute rate | The portfolio trend factor in Source 3 | Monitoring dispute rate (M1) about 0.31% through October 2025, rising steadily to about 0.46% by October 2026 |
| Merchants drifting toward the limits | About 5% of merchants get a dispute factor that grows over 60 to 120 days. They are picked among merchants with at least 200 settled sales per 30 days, so they are not labeled low volume (M3) and show up in M5. Risk reacts late: their tier goes up 30 to 60 days after they reach 0.75%, and a third of them end up suspended and then closed. | At the end of the window, about 10 merchants in the M5 watch band (0.75% ≤ M3 < 1.5%); 3 merchants reaching the band above Visa's limit (M3 ≥ 1.5%) in the last quarter |
| Unrecovered losses | Closed merchants keep receiving disputes on their past sales for up to 120 days, which their reserve doesn't fully cover | Written-off amount of about $19,000 over the last 12 months |
| Missed deadlines | The case action timing in Source 5 | Expiry rate (M6) about 18% of closed disputes |
| Late arrivals | Disputes 1 to 120 days after the sale; 0.5% of gateway hourly files arrive 1 to 48 hours late; 2% of settlement files arrive one business day late; 1% of case action files arrive the next morning; 2% of merchant changes are backdated | As listed |
| Status changes over months | Second rounds and arbitration in Source 3; tier and status changes in Source 6 | As listed |

## Data quality traps

Deliberate defects, so the dbt tests and the matching logic have something to catch. Each one is rare enough not to distort the metrics.

| Trap | Source | Rate | What should catch it |
| --- | --- | --- | --- |
| Duplicate events, resent in a later file with the same ID | Gateway, dispute notifications | 0.1% of gateway events, 0.5% of notifications | Deduplication on the event ID in silver |
| Disputes whose `acquirer_reference` matches no settlement line | Dispute notifications | 0.3% of disputes | The unmatched-disputes list (99.5% link target) |
| Settlement adjustments | Settlement files | 0.05% of sales | Settlement models that treat them as corrections, not sales |
| Late settlement file | Settlement files | 2% of business days | Freshness check; dispute rates marked preliminary |
| Payments before their merchant exists | Gateway, merchants | Every new merchant's first day | The unknown-merchant row in `dim_merchant` |

## Reference data

Reason codes, merchant categories and policy thresholds are **dbt seeds**, not generated files (see the solution design). The generator reads the same seed files from `dbt/seeds/`, so both always use the same codes and limits.

| Seed | Columns | Content |
| --- | --- | --- |
| `reason_codes` | network, reason_code, reason_category, description, valid_from, valid_to | About 10 codes per network across the five categories (`fraud`, `merchandise_not_received`, `not_as_described`, `subscription_cancelled`, `processing_error`) |
| `merchant_categories` | mcc, description, segment | The MCCs the generator uses, about 5 per segment |
| `policy_thresholds` | threshold_name, value, valid_from, valid_to | `watch_line` 0.0075, `network_merchant_limit` 0.0150, `acquirer_portfolio_line` 0.0050, `auto_accept_limit` 25.00, `dispute_fee` 15.00 |

## Volumes

At 1% scale, over the 24-month window (the warm-up adds about 15% to the payment sources):

| Source | Per day | Over 24 months |
| --- | --- | --- |
| Gateway events | about 9,700 (5,000 payments) | about 7.1 million |
| Settlement lines | about 6,600 per file | about 3.4 million |
| Dispute notifications | 14 to 21 new disputes, about 25 notices | about 19,000 notices (about 12,500 disputes) |
| Early alerts | about 4 alerts, 8 events | about 6,000 events |
| Case actions | about 50 | about 40,000 |
| Merchants | a few changed rows | about 1,200 rows (about 650 merchants) |
| Merchant balances | about 400 | about 300,000 |

In total, about 11 million rows, in line with the solution design's estimate of 12 million rows and 1 GB in Delta.

## Questions each source answers

A check that the spec covers the business questions:

| Source | Business questions |
| --- | --- |
| Dispute notifications | 1, 3, 5–7, 9–13, 15–17 |
| Case actions | 1–4, 9, 13, 17 |
| Settlement lines (sales and the link to disputes) | 5–7, 9, 11, 12, 15, 16 |
| Gateway events (refunds after alerts, payment attributes) | 12, 14 |
| Early alerts | 14 |
| Merchants | 5–8, 12, 15, 16 |
| Merchant balances | 8, 9 |

## Acceptance checks

The generator's tests confirm, on the generated history:

- Every ID column is unique where the spec says so, and every reference resolves, except the deliberate traps.
- No full card numbers exist, and every amount has at most two decimals.
- Every file sits in the folder of its arrival date, and nothing arrives after `end_date`.
- M1 by month, M6, the number of merchants in the M5 watch band and the written-off amount fall within ±10% of the targets above.
- Running the generator twice with the same parameters produces identical files.
