# Guide — Adding More Questions to EIAF

This guide shows how to teach EIAF new questions **without writing any code**.
Everything below is configuration: YAML files in `backend/config`,
`backend/semantic`, and `backend/schema_registry`. The layer code in
`backend/layers/` never changes — that's the whole point of the architecture
(PRD §6.2).

> **After every change, restart the server** — config is loaded once at startup.
> ```powershell
> uvicorn backend.main:app --port 8080
> ```

---

## Easiest way: the wizard

Instead of editing the files by hand, run the guided wizard — it asks a few
plain-language questions and writes all the YAML for you (preserving the existing
comments), then runs the consistency checker automatically:

```powershell
python -m backend.add_question
```

It prompts for the question text, a keyword or two, the table/column/aggregation,
the wording, and which roles may ask it — most prompts have a sensible default you
can accept with Enter. The only thing it can't do is create your database table;
it reminds you which table and columns the new question expects.

Prefer to understand exactly what changes, or need an edge case the wizard
doesn't cover? The manual scenarios below show every file. To re-check config you
edited by hand at any time:

```powershell
python -m backend.check_config
```

---

## How question recognition works (30-second model)

A request flows through the pipeline. The first two layers decide *what* you
asked:

```
"How much sales did I do this week?"
        │
   ┌────▼─────┐   matches an intent pattern  → intent  = sales_amount
   │  Intent  │   matches a period pattern   → period  = this_week
   └────┬─────┘   (no match on either → INTENT_NOT_FOUND — it never guesses)
        │
 ┌──────▼────────┐  looks up intent          → entity  = sales
 │ Orchestration │                              metric  = total_sales
 └──────┬────────┘
        ▼  ... Semantic → Service → Data → Response
```

So a question is recognized only when it matches **one intent pattern AND one
period pattern**. Then the metric/filter must be **declared** in the semantic
config and **mapped** to a column in the schema registry, or later layers will
(correctly) reject it.

The relevant files:

| File | Role |
|------|------|
| [backend/config/intent_patterns.yaml](../backend/config/intent_patterns.yaml) | phrases → intent + period |
| [backend/config/orchestration.yaml](../backend/config/orchestration.yaml) | intent → `{entity, metric}` |
| [backend/semantic/entities/sales.yaml](../backend/semantic/entities/sales.yaml) | which metrics/filters are *allowed* |
| [backend/schema_registry/mappings.yaml](../backend/schema_registry/mappings.yaml) | metric/dimension → physical column |
| [backend/config/settings.yaml](../backend/config/settings.yaml) | period window definitions (days) |
| [backend/config/response_templates.yaml](../backend/config/response_templates.yaml) | answer wording + period labels |

---

## Scenario 1 — New phrasing of an existing question

**Goal:** also recognize *"What was my turnover this week?"* and *"How much did
I earn this month?"*

Patterns are **case-insensitive regular expressions**; `\b` is a word boundary
(so `\bsales\b` matches "sales" but not "wholesaler").

Edit only [intent_patterns.yaml](../backend/config/intent_patterns.yaml):

```yaml
intents:
  - name: sales_amount
    description: "Total sales amount over a time period."
    patterns:
      - '\bsales\b'
      - '\bsold\b'
      - '\bsell\b'
      - '\brevenue\b'
      - '\bturnover\b'         # ← new
      - '\bearn(ed|ings)?\b'   # ← new: earn / earned / earnings
```

That's it — the period (`this week`, `this month`, …) is already recognized.

> **Tip:** keep patterns reasonably specific. The Intent Layer is intentionally
> strict — if a sentence has no sales keyword, it returns `INTENT_NOT_FOUND`
> rather than misclassifying it.

---

## Scenario 2 — New time period (e.g. "yesterday")

Periods are validated at three points, so add the value in three places.

**a)** Teach the phrase — [intent_patterns.yaml](../backend/config/intent_patterns.yaml):
```yaml
periods:
  - value: yesterday          # ← new block
    patterns:
      - '\byesterday\b'
  - value: today
    patterns:
      - '\btoday\b'
  # ... existing this_week / this_month ...
```

**b)** Define the rolling window — [settings.yaml](../backend/config/settings.yaml):
```yaml
periods:
  today: { days: 0 }
  yesterday: { days: 1 }      # ← new: data from the last 1 day
  this_week: { days: 7 }
  this_month: { days: 30 }
```

**c)** Allow it as a filter — [sales.yaml](../backend/semantic/entities/sales.yaml):
```yaml
filters:
  period:
    - today
    - yesterday               # ← new
    - this_week
    - this_month
```

If you skip (b) or (c), the question is *recognized* but then **rejected** at the
Semantic Layer with `SEMANTIC_VALIDATION_FAILED` — that's the governance working
as designed, not a bug.

---

## Scenario 3 — Whole new metric / question type (e.g. "average sale")

**Goal:** answer *"What's my average sale this month?"* This is the full §6.2
extensibility path — still four config files, still zero code.

**a)** New intent — [intent_patterns.yaml](../backend/config/intent_patterns.yaml):
```yaml
intents:
  - name: sales_amount
    patterns: [ '\bsales\b', '\bsold\b', '\bsell\b', '\brevenue\b' ]
  - name: average_sale       # ← new intent
    description: "Average value of a sale over a period."
    patterns:
      - '\baverage\b'
      - '\bavg\b'
```

**b)** Map intent → metric — [orchestration.yaml](../backend/config/orchestration.yaml):
```yaml
intents:
  sales_amount:
    entity: sales
    metric: total_sales
  average_sale:              # ← new
    entity: sales
    metric: avg_sale
```

**c)** Declare the metric — [sales.yaml](../backend/semantic/entities/sales.yaml):
```yaml
metrics:
  - total_sales
  - avg_sale                 # ← new
```

**d)** Map metric → column + aggregation — [mappings.yaml](../backend/schema_registry/mappings.yaml):
```yaml
metrics:
  total_sales:
    table: customers
    column: purchase_amount
    aggregation: SUM
  avg_sale:                  # ← new
    table: customers
    column: purchase_amount
    aggregation: AVG
```

Supported aggregations: `SUM`, `COUNT`, `AVG`, `MIN`, `MAX`.

**(e) Wording + formatting** — [response_templates.yaml](../backend/config/response_templates.yaml).
Each metric has its own entry under `metrics:` with a `template` and a `format`
(`currency` → ₹63,000, or `number` → 1,00,000). Add one for the new metric:
```yaml
metrics:
  total_sales:
    template: "This {period_possessive} total sales are {value}."
    format: currency
  avg_sale:                  # ← new
    template: "Your average sale {period} is {value}."
    format: currency
```
Template placeholders: `{value}` (the formatted number), `{period}` (e.g.
"this month"), `{period_possessive}` (e.g. "month's"). A metric with no entry
here is rejected with `INTERNAL_ERROR`, so every question declares its wording.

---

## Adding a brand-new entity (beyond sales)

Same shape, one level up. To add e.g. an `orders` entity:

1. Create `backend/semantic/entities/orders.yaml` (its own metrics/filters).
2. Add `orders` metrics to [mappings.yaml](../backend/schema_registry/mappings.yaml).
3. Grant access in [roles.yaml](../backend/config/roles.yaml):
   ```yaml
   roles:
     admin:
       allowed_entities:
         - sales
         - orders            # ← new
   ```
4. Add the intent + orchestration mapping as in Scenario 3.

A new table usually has its **own** date column (e.g. `order_date`, not
`purchase_date`). Point the metric at it with a per-metric `date_column` in
[mappings.yaml](../backend/schema_registry/mappings.yaml):
```yaml
metrics:
  orders_today:
    table: orders
    column: id
    aggregation: COUNT
    date_column: order_date   # ← this metric's period filter uses order_date
```
If omitted, the period filter falls back to the global `dimensions.period` column.

The Service Layer's RBAC check is a real config lookup, so an entity a role isn't
granted is rejected with `RBAC_DENIED`.

---

## Verifying your change

1. **Check the config first** — this catches a misspelled or forgotten value
   *before* you start the server and tells you exactly which file to fix:
   ```powershell
   python -m backend.check_config
   ```
   Fix any `ERROR` lines until it prints `OK: N question(s) wired consistently`.
2. Restart: `uvicorn backend.main:app --port 8080`
3. Open http://127.0.0.1:8080/ and ask the new question.
4. Watch the **pipeline strip**: all-green means it flowed end-to-end; a red
   chip tells you which layer rejected it (and why, via the error code).

| If you see… | It means… | Fix |
|-------------|-----------|-----|
| `INTENT_NOT_FOUND` | no intent/period pattern matched | add/adjust patterns (Scenario 1/2a) |
| `ENTITY_NOT_REGISTERED` | intent maps to a metric not declared in semantic config | Scenario 3b/3c |
| `SEMANTIC_VALIDATION_FAILED` | metric or period not allowed for the entity | Scenario 2c / 3c |
| `DATA_LAYER_FAILURE` | column/aggregation mapping wrong, or DB issue | check Scenario 3d + that data exists |

---

## Why it's safe to let non-engineers edit these files

- The LLM (future) never sees this config and never emits SQL.
- A bad pattern can only cause `INTENT_NOT_FOUND` — it can't reach the database.
- A metric/filter not declared in semantic config is rejected before the Data
  Layer — it can never run.
- Physical column names live **only** in the schema registry, so renaming a DB
  column is a one-line change here (see acceptance test §8.3).
