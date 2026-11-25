# Source data — Generator Plan

How the PySpark generator that writes the source data is built, and the steps to build it. What the generator must produce is defined in the [source data spec](spec.md); this plan only says how and in what order.

Each step is small enough to review on its own. Before its code is written, the step gets a step spec here (the rule IDs it covers, the classes and functions with their inputs and outputs, and the tests with the cases each covers) and waits for approval. The step ends with a commit and a stop for review. Tick a step when it is merged.

## Code layout

```
src/corvella/generator/
├── __main__.py              entry point: wires everything together (python -m corvella.generator)
├── scenario.py              GenerationScenario (frozen), ScenarioBuilder, ScenarioPresets
├── orchestrator.py          GenerationRun: runs the business rules, then the source generators
├── core/
│   ├── keyed_random.py      KeyedRandom: random values from a hash of (key, seed, salt)
│   ├── identifiers.py       IdFactory: prefixed IDs, capture batch IDs, acquirer references
│   └── calendar.py          BusinessCalendar: business days, US Eastern hours, ledger day
├── reference/
│   └── seed_reader.py       SeedReader: reads the dbt seeds in dbt/seeds/
├── business_rules/          what happens in the business; nothing here is written as a file
│   ├── merchants.py         merchant population, version timeline, drift, closures
│   ├── payments.py          payment volume, authorization, capture, void, expiry, settlement
│   ├── refunds.py           refunds of settled payments
│   ├── alerts.py            early alerts and the refunds they trigger
│   ├── disputes.py          disputed sales, rounds, outcomes, case timing
│   └── balances.py          daily balance, reserve and write-offs per merchant
├── sources/                 how each source system delivers what happened
│   ├── base.py              SourceGenerator: select columns → assign arrival → apply traps → write
│   ├── factory.py           SourceGeneratorFactory: source name → generator with its strategies
│   ├── gateway.py           authorizations, captures, voids, refunds (Sources 1 to 4)
│   ├── settlement.py        Source 5
│   ├── dispute_notifications.py   Source 6
│   ├── early_alerts.py      Source 7
│   ├── case_actions.py      Source 8
│   ├── merchants.py         Source 9
│   └── merchant_balances.py Source 10
├── arrival.py               ArrivalPolicy and one class per delivery schedule
├── traps.py                 DataQualityTrap and one class per trap
└── writers.py               FileWriter, JsonLinesWriter, CsvWriter

tests/generator/
├── conftest.py              local SparkSession and the small test scenario
├── core/, reference/, business_rules/, sources/   one test file per module
└── test_acceptance.py       the spec's acceptance checks, on the test scenario
```

**Two layers.** A fact usually shows up in several sources. One payment appears in the authorization, capture and settlement files, and later in a dispute notification and the case actions. `business_rules/` decides each fact once and keeps the result as an internal table per entity (merchants, payments, refunds, alerts, disputes, balances), including hidden facts that no file shows, such as a merchant's drift factor. `sources/` only projects those tables into each source's columns and delivers them: file schedule, lateness, traps and format. Business rules live in the first layer, delivery rules in the second.

**Design patterns.**

| Pattern | Where |
| --- | --- |
| Builder, with a Director | `ScenarioBuilder` and `ScenarioPresets` (`full_history`, `test_run`) |
| Template Method | `SourceGenerator.run()` fixes the four delivery steps; each source writes only its column selection |
| Strategy | `ArrivalPolicy`, `DataQualityTrap` and `FileWriter`, passed into each source generator |
| Factory | `SourceGeneratorFactory`, a registry that wires each source to its strategies |

Inside the business rules, each generation rule is a `DataFrame -> DataFrame` function chained with `.transform()`, so it can be tested on a few rows. All objects work on whole DataFrames; no class or function runs per row.

**Generating month by month.** The business rules run one **sale month** at a time: payments of that month and everything that follows from them (refunds, alerts, disputes, even when they happen up to 120 days later). Merchants are generated once, for the whole window, before the first month; balances are calculated once, after the last month, from all the other tables. Each result is saved as a Delta table in the `landing` schema (`generator_<entity>`). The sources then write their files one **arrival month** at a time, reading those tables. A file can hold events from several sale months (a March notification batch has disputes on sales from November to March), so files are written only after all the months are generated, and each file is written exactly once.

## Steps

**Phase A: foundations**

- [x] **1. Seeds.** `reason_codes`, `merchant_categories` and `policy_thresholds` in `dbt/seeds/`, with a properties file giving the column types and tests. Done when `dbt seed` loads them in dev.
- [x] **2. Spark test setup.** PySpark as a dev dependency, Java in CI, and `tests/generator/conftest.py` with a local SparkSession. Done when a trivial Spark test passes locally and in CI.
- [ ] **3. Scenario.** `scenario.py`: the frozen scenario, the builder with its cross-field checks, and the two presets. Done when tests cover every check in `build()`.
- [ ] **4. Keyed random values.** `core/keyed_random.py`: uniform numbers, integers in a range and weighted choices, all derived from a hash of the record's key, the seed and a salt. Done when tests show the same inputs give the same values whatever the partitioning, and the shares are close to the weights.
- [ ] **5. Identifiers.** `core/identifiers.py`: the ID prefixes, capture batch IDs and acquirer references with their check digit. Done when tests check each format and that IDs don't collide.
- [ ] **6. Business calendar.** `core/calendar.py`: business days, US Eastern working hours, the ledger day, adding business days. Done when tests pass, including the daylight saving changes.
- [ ] **7. Seed reader.** `reference/seed_reader.py`: loads the seeds and looks up a threshold valid on a date. Done when tests read the real seed files.

**Phase B: delivery**

- [ ] **8. File writers.** `writers.py`: JSON Lines and CSV, file names from the arrival time, `arrival_date=` folders, amounts as strings in JSON, nulls written as the conventions say. Done when tests write and read back files in a temporary folder.
- [ ] **9. Arrival policies.** `arrival.py`: hourly files, business-day files, network batches and next-day files, each with its lateness rule. Done when tests check the file times and the share of late files.
- [ ] **10. Duplicate trap.** `traps.py`: the `DataQualityTrap` interface and `DuplicateResend` (an event sent again in a later file with the same ID). The other traps are added with their source. Done when tests check the rate and that the copy lands in a later file.
- [ ] **11. Source generator base and factory.** `sources/base.py` and `sources/factory.py`. Done when a test runs a fake source through the four steps.

**Phase C: business rules and sources**

- [ ] **12. Merchant population.** `business_rules/merchants.py`: about 1,150 merchants, segments and MCCs from the seed, onboarding dates over the window.
- [ ] **13. Merchant timeline.** Tier, reserve and status changes, 2% backdated changes, the drifting merchants (picked and scheduled as in [Behaviors the generator must build in](spec.md#behaviors-the-generator-must-build-in)), Risk's late reaction and closures. Risk's reaction follows each merchant's planned drift, not the disputes actually generated, so merchants don't depend on disputes.
- [ ] **14. Merchants source (Source 9).** Daily change extract, 05:00 UTC the next day.
- [ ] **15. Payment volume and authorizations.** `business_rules/payments.py`: payments per merchant per day (growth, weekly pattern, season), card data, amounts, approvals, declines and risk engine blocks.
- [ ] **16. Payment paths and settlement.** Capture, void, expiry, batches closed at 23:00 US Eastern, settlement date, fees and acquirer reference. Payments start only after their merchant exists in the KYC data (with the first-day trap) and stop when it closes.
- [ ] **17. Gateway authorizations source (Source 1).**
- [ ] **18. Gateway captures and voids sources (Sources 2 and 3).**
- [ ] **19. Refunds.** `business_rules/refunds.py`: ordinary refunds after settlement, never more than the captured amount.
- [ ] **20. Early alerts.** `business_rules/alerts.py`: alerts on sales 1 to 60 days old, the refunds they trigger (`reason = dispute_alert`), and which expired alerts later become chargebacks.
- [ ] **21. Gateway refunds and early alerts sources (Sources 4 and 7).**
- [ ] **22. Settlement source (Source 5).** Sale and refund lines, plus the adjustment trap and the late file trap.
- [ ] **23. Disputed sales.** `business_rules/disputes.py`: dispute probability (segment, tier, merchant factor, drift, portfolio trend), timing, amount and reason codes, plus the chargebacks that follow expired alerts and the unmatched acquirer reference trap.
- [ ] **24. First round outcomes and case timing.** Auto-accepted, accepted, expired (with where they stall) and fought, with the win rates by reason category.
- [ ] **25. Pre-arbitration and arbitration.**
- [ ] **26. Dispute notifications source (Source 6).** Network batches on business days, with the duplicate trap.
- [ ] **27. Case actions source (Source 8).**
- [ ] **28. Merchant balances (Source 10).** `business_rules/balances.py` and its source: daily balance and reserve, disputes debited, closed merchants and written-off amounts.

**Phase D: running it**

- [ ] **29. Orchestrator and entry point.** `orchestrator.py` and `__main__.py`: business rules by sale month into the `generator_` tables, then files by arrival month into `source_history`. Done when the test scenario runs end to end locally.
- [ ] **30. Acceptance tests.** `tests/generator/test_acceptance.py`: every structural check in the [spec's acceptance checks](spec.md#acceptance-checks) (IDs, references, card data, payment paths, folders, reproducibility) on the test scenario. The metric targets need the full history, so they are checked in step 31.
- [ ] **31. Generator job.** A job in the Asset Bundle that runs the generator on serverless compute, then a full run in dev. Done when the metric targets (M1 by month, M6, the M5 watch band, the written-off amount) are within ±10%, with the results recorded here, and the [rule coverage command](../../../README.md#checks) for `SRC` lists no untested rule and no unknown ID. Rules tested in another component (for example SRC-6.3, tested by the silver dbt models) are listed here as pending until that component tests them.
