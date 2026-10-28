# Data Import (CSV)

**Scope:** the admin CSV import at `/admin/data-import/` — five entities
(products, suppliers, warehouses, movements, purchase orders), the preview
contract, and the exact behavior of the import commit.

Source of truth: `app/services/data_import_service.py` (`IMPORT_GUIDE`,
`EXPECTED_COLUMNS`, `COLUMN_ALIASES`, `FK_CHECK_FIELDS`, `MAX_PREVIEW_ROWS`) and
`app/routes/admin/data_import_routes.py` (the importers). The column tables
rendered on the page come from the same `IMPORT_GUIDE`.

---

## 1. Access & scope

| Route | Method | Purpose |
|---|---|---|
| `/admin/data-import/` | GET | Hub, one tab per entity (`?tab=products`) |
| `/admin/data-import/preview/<entity>` | POST | Validate a CSV, write nothing |
| `/admin/data-import/upload/<entity>` | POST | Import a CSV (file upload, or `confirm=true` replay of previewed content) |

`<entity>` is one of `products`, `suppliers`, `warehouses`, `movements`,
`purchase_orders`.

- Login is required; the page and both endpoints are restricted to the write
  roles (`admin`, `manager`). A `viewer` gets 403.
- The preview is read-only: it never inserts or updates a row.
- Preview insights are advisory. FK warnings, `fk_matches`, duplicate groups and
  the will-create list do not block the import and do not change what the
  importer writes. The only preview flag carried into the import is the
  create-missing checkbox (section 7).
- Import-commit behavior is unchanged by the preview reports — they describe
  outcomes, they do not alter them.

---

## 2. File rules

- **Encoding:** UTF-8. Invalid UTF-8 is rejected with a flash
  ("File is not valid UTF-8…"), never silently repaired.
- **Size:** 5 MB maximum (`MAX_CONTENT_LENGTH_MB`, default `5`). The preview
  route checks the body length itself and returns **413** with a JSON error;
  the upload route flashes the limit message and redirects back to the tab.
- **Header row required.** A file with no header is reported as empty/malformed.
- **Header matching is case-insensitive** and surrounding spaces are stripped,
  then aliases are applied. `Product_Name`, ` product_name ` and `product_name`
  are all the same header.
- **Extra columns are allowed** and ignored — except `po_number` on purchase
  orders, which the importer reads when present.
- **Values are trimmed** of surrounding whitespace before validation/import.
  Internal whitespace is kept as-is.
- Comma-separated (standard `csv` module); the whole file is imported, while
  preview validation is capped (section 5.4).

---

## 3. Canonical headers & aliases

Only **functional** aliases are listed: each maps to a column that exists in the
entity's expected set. Anything else in the header is an ignored extra column.

### Products

Natural keys: `sku`, `supplier_name`.

| Canonical column | Aliases |
|---|---|
| `sku` | — |
| `name` | `product_name` |
| `unit_price` | `price` |
| `current_stock` | `stock` |
| `reorder_point` | `reorder` |
| `category` | — |
| `supplier_name` | `supplier`, `supplier_id` |

### Suppliers

Natural key: `supplier_name`.

| Canonical column | Aliases |
|---|---|
| `supplier_name` | `name` |
| `location` | — |
| `lead_days` | — |

`email` is unsupported as a supplier column: it maps to `contact_email`, which
does not exist in the schema, so the cell is ignored. `contact_email` is
unsupported for the same reason — it is not a column on `suppliers`.

### Warehouses

Natural key: `warehouse_name`.

| Canonical column | Aliases |
|---|---|
| `warehouse_name` | `name` |
| `location` | — |

### Movements

Natural key: `product_sku`.

| Canonical column | Aliases |
|---|---|
| `product_sku` | `product_id` |
| `quantity` | `qty` |
| `movement_type` | `type` |
| `reason` | — |

### Purchase orders

Natural keys: `supplier_name`, `product_sku`.

| Canonical column | Aliases |
|---|---|
| `supplier_name` | `supplier_id` |
| `product_sku` | `product_id` |
| `quantity` | `qty` |
| `status` | — |

### Legacy ID columns

`supplier_id` and `product_id` are **legacy aliases**, not replacement natural
keys: they are mapped onto `supplier_name` / `product_sku` and resolved the same
way. A bare numeric value in such a cell resolves **only when it matches an
existing active id** — a number that is not an existing active id is treated as
an unknown natural key (warned in preview, and NULL-supplier/skipped at import
exactly like a misspelled name). A soft-deleted id does not resolve.

---

## 4. Value rules

- A cell that cannot be cast to its numeric type **skips the row** with
  `invalid_number` — it is reported, never silently dropped.
- Blank numeric cells fall back to the importer default (table below).
- Checks run in a fixed order per entity; the **first failing check wins** and
  produces exactly one error entry for that row.

| Entity | Field | Type | Blank default |
|---|---|---|---|
| products | `unit_price` | float | 0 |
| products | `current_stock` | int | 0 |
| products | `reorder_point` | int | 10 |
| suppliers | `lead_days` | int | 0 |
| movements | `quantity` | int | 0 (then rejected as not positive) |
| purchase_orders | `quantity` | int | 0 (then rejected as not positive) |

**Products** — `sku` and `name` are required (`missing_required` when blank).
Blank `category` becomes `General`. Blank `supplier_name` means no supplier
(`supplier_id` NULL).

**Suppliers** — `supplier_name` is required. `location` is optional (stored as
`''`). `initials` are derived from the name (first letters of the first two
words, max 10 chars).

**Warehouses** — `warehouse_name` is required; `location` is optional.

**Movements** — `product_sku` must resolve to an active product
(`fk_product_not_found`). `quantity` must be a positive integer: 0 and negative
values are skipped with `quantity_not_positive`. `movement_type` is upper-cased
and must be one of `IN`, `OUT`, `ADJUSTMENT`, `RETURN` (`invalid_movement_type`
otherwise; blank is invalid). `reason` is stored as the movement reference.

**Purchase orders** — `supplier_name` and `product_sku` are required and
`quantity` must be positive. `status` is lower-cased and must be one of `draft`,
`approved`, `in_transit`, `received`, `cancelled`; any other value (including
blank) becomes `draft`.

---

## 5. Preview behavior

`POST /admin/data-import/preview/<entity>` accepts `csv_content` (and optional
`create_missing=true`) and returns `{"success": true, "preview": {...}}`.

| Preview key | Meaning |
|---|---|
| `valid` | `false` when the file cannot be previewed (missing columns, empty, unparseable CSV, `db_unavailable`) |
| `errors` | Blocking messages (plain strings) |
| `warnings` / `warning_count` | Non-blocking FK and possible-typo advisories; list capped at 50, count uncapped |
| `fk_matches` / `fk_match_count` / `fk_exact_match_count` / `fk_normalized_match_count` / `fk_numeric_match_count` | FK match report (5.1) |
| `duplicates` / `duplicate_count` | In-file duplicate natural keys (5.2) |
| `will_create` / `will_create_count` | Suppliers the armed import will auto-create (5.3) |
| `rows` / `row_count` | The first **50** parsed rows (display only) |
| `total_row_count` / `rows_truncated` | Rows actually scanned (capped) and whether the cap was hit (5.4) |

Warnings are **non-blocking**: `valid` stays `true`, the preview renders, and
Confirm & Import stays enabled.

### 5.1 FK match report

Built for the FK-checked entities only (products → `supplier_name`; movements →
`product_sku`; purchase orders → both). Suppliers and warehouses have no FK
fields, so the report is empty. Three buckets, mutually exclusive per cell:

- **exact** — the raw cell equals the spelling stored in the DB. Counted only;
  exact matches are never listed (there is nothing to fix).
- **normalized** — the natural key matched after case/whitespace
  normalization. Listed with the raw cell → normalized value, `error_code`
  `fk_normalized_match`, so spelling drift is visible.
- **numeric ID fallback** — a bare decimal matched an existing active id.
  Listed with the existing id, `error_code` `fk_numeric_match`.

`fk_match_count = exact + normalized + numeric`. The `fk_matches` list is capped
at **50** entries; all counts are uncapped. The preview table also shows the
badge `N matches (X exact, Y normalized, Z numeric)`.

Like the FK warnings, the match report is row-heuristic: a row that later fails
a required-field or numeric check can still contribute a match, because the
report resolves references before the importer runs those checks.

### 5.2 Duplicate report

Checked for products, suppliers and warehouses only (natural keys in
`DUPLICATE_KEY_FIELDS`). Values are trimmed and grouped case-insensitively;
internal whitespace is **not** collapsed.

| Repeat | Reported as | Import outcome |
|---|---|---|
| products, same spelling | warning | later rows **update** the earlier product |
| suppliers, same spelling | info | later rows are **skipped** as `already_exists` |
| warehouses, same spelling | info | later rows are **skipped** as `already_exists` |
| any casing variant | warning | the first occurrence of each distinct spelling creates a **separate** row; repeats follow the exact-repeat outcome |
| movements / purchase orders | not flagged | no in-file duplicate semantics |

`duplicate_count` counts **distinct** groups and is uncapped; the `duplicates`
list is capped at 50 groups, and each group's list of later row numbers at 50.
Duplicate reporting is advisory — it never blocks an import.

### 5.3 Create-missing report

Only when `create_missing=true` (the checkbox on the products / purchase orders
tabs). Unknown creatable supplier references become a `will_create` list (one
entry per normalized name, first-seen spelling) instead of a not-found warning;
over-length names keep their warning (section 7). List capped at 50,
`will_create_count` uncapped. Names of at least 4 characters within 0.85
similarity of an existing supplier also get an advisory `fk_possible_typo` hint —
the supplier is still created. See section 7 for the overcount heuristics.

### 5.4 Caps and truncation

- The preview parses and validates at most **10,000** data rows
  (`MAX_PREVIEW_ROWS`). When the file has more, `rows_truncated` is `true` and
  `total_row_count` reports the cap (10,000), not the true file size.
- Duplicate detection, FK validation and the will-create list run on the capped
  rows only. The import itself is **not** capped — it processes the whole file.
- The preview table renders the first **50** rows; `row_count` is that displayed
  count.
- If the FK caches cannot be built, the preview still returns the parsed rows,
  appends `db_unavailable: …` to `errors`, sets `valid: false`, and skips FK
  validation, the match report and the will-create list.

---

## 6. Import behavior per entity

All importers resolve FKs from a cache built once per import and run the whole
batch under a PostgreSQL advisory lock (movements excepted — see below). One bad
row cannot poison the batch: batch inserters wrap each row in a SAVEPOINT, and
movements commit per row.

- **products** — exact-SKU upsert: `ON CONFLICT (sku) WHERE deleted_at IS NULL`
  updates `name`, `unit_price`, `current_stock`, `reorder_point`, `category` and
  `supplier_id`; a new SKU inserts. An update counts as `imported`.
- **suppliers** — exact active-name lookup first; an existing name is skipped as
  `already_exists` (info). Otherwise insert. There is no update path.
- **warehouses** — `INSERT … ON CONFLICT (warehouse_name) DO NOTHING`; a
  conflict is skipped as `already_exists` (info).
- **movements** — one row at a time through `MovementRepository.record`, each in
  its own committed transaction (no batch lock). The stock guard applies per
  row: an `OUT`/`ADJUSTMENT` that would drive stock negative is skipped with
  `stock_violation`. Large files are proportionally slower.
- **purchase orders** — inserted as `draft`, then walked through
  `sp_po_transition` for the requested status: `approved` → approved;
  `in_transit` → approved, in_transit; `received` → approved, in_transit,
  received (received also records an `IN` movement and decrements `on_order`).
  `cancelled` is accepted as a value but no transition is issued, so that row
  stays `draft`. A blank `po_number` is generated as `PO-YYYYMMDD-NNNN`.

First failing check wins: `skipped` equals `len(errors)` while the retained
detail is under its cap.

---

## 7. Create missing suppliers

Opt-in checkbox on the **products** and **purchase orders** tabs only; off by
default. It never creates products — a bare SKU is no natural name for one.

| Entity | Unchecked | Checked |
|---|---|---|
| products | unknown supplier → product imports with `supplier_id` **NULL** (warning) | unknown supplier auto-created when the trimmed name is ≤ **150** chars; the product links to it |
| purchase orders | unknown supplier → row **skipped** (`fk_supplier_not_found`) | unknown supplier auto-created when the trimmed name is ≤ 150 chars |

- Names longer than 150 chars (`VARCHAR(150)`) cannot be created: the warning is
  kept, and the products row still imports with a NULL supplier / the purchase
  order row is skipped.
- A blank supplier cell never creates anything.
- Purchase orders resolve the **product first**: an unknown `product_sku` skips
  the row **before** any supplier is created, so no orphan suppliers appear.
- A created supplier stores the trimmed raw name (never the lowercased form),
  `location = ''`, `lead_days = 0`, and derived initials.
- Name reuse follows soft delete: a name held only by a **soft**-**deleted**
  supplier becomes a fresh **active** row; the soft-deleted row is untouched.
- Preview `will_create` may **overcount** (documented heuristic): products rows
  that later fail the blank sku/name check are still listed; names over 150
  chars are listed though they cannot be created; rows beyond the 10,000-row
  preview cap are not scanned; purchase-order rows with an unknown product still
  list their supplier even though the import skips the row first.

---

## 8. Duplicates

- **Exact repeat** vs **case variant** are different things: the duplicate
  report groups case-insensitively, but the import and the unique indexes are
  case-sensitive.
- Unique indexes are case-sensitive: `products_sku_live_key` on `products (sku)`,
  `uq_suppliers_name_live` on `suppliers (name)` (both partial, active rows
  only), and `UNIQUE (warehouse_name)` on warehouses. `ACME` and `Acme` are
  therefore two rows, not a conflict.
- **Internal whitespace is not collapsed**: `Acme Corp` and `Acme  Corp` are
  different names and different duplicate groups.
- Duplicate detection is advisory. It never blocks the import and never changes
  the outcome — it only predicts it.
- **Preview-only caveat:** a **direct** upload (posting the file straight to
  `/admin/data-import/upload/<entity>` without the preview/confirm round-trip)
  bypasses the preview reports entirely — no FK warnings, no
  `fk_normalized_match` / `fk_numeric_match` listing, no duplicate groups and no
  `will_create` list are produced. Alias mapping and value trimming still apply;
  the import still reports skipped rows, but none of these preview reports are
  produced. Use Preview Import to get them.

---

## 9. Results & limits

Every importer returns:

```json
{"imported": 0, "skipped": 0, "errors": [], "error_counts": {}}
```

| Key | Meaning |
|---|---|
| `imported` | Rows written (upserts that update count too) |
| `skipped` | Rows not imported |
| `errors` | Per-row detail, at most **200** entries (`_MAX_RETAINED_ERRORS`); each has `row`, `field`, `value`, `error_code`, `severity`, `reason` |
| `error_counts` | Full tally per `error_code`, uncapped |

Error codes: `missing_required`, `invalid_number`, `quantity_not_positive`,
`invalid_movement_type`, `fk_product_not_found`, `fk_supplier_not_found`,
`already_exists` (info), `stock_violation`, `db_error`.

**Flash budget:** one status line; when rows were skipped, `Skipped N row(s).`
plus at most **10** detail lines (`_MAX_REASON_LINES`, each clipped to 140
chars), then one grouped **tail** line built from the full `error_counts`
tally — e.g. `…and 42 more: 30× invalid_number, 12× fk_product_not_found.` The
grouped tail stays correct even when `errors` was truncated at 200.

**Rate limits:** 30 previews/min and 10 imports/min (Flask-Limiter). File size:
5 MB.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Missing required columns: …` | The header row lacks canonical columns (or their aliases). Extra columns are fine; check the file matches the selected tab. |
| `File is not valid UTF-8…` | Re-save the CSV as UTF-8 (Excel: "CSV UTF-8"). Invalid bytes are rejected, not repaired. |
| 413 / "File exceeds the 5 MB size limit" | Split the file; the limit is 5 MB per upload. |
| "Your session has expired" + redirect to login | Session ended (sessions end when the browser closes; there is no remember-me cookie) or the CSRF token is stale. Sign in again. |
| 429 / rate-limited | More than 30 previews/min or 10 imports/min. Wait a minute and retry. |
| `db_unavailable: …` in preview errors | The FK caches could not be built. Parsed rows are still shown, but FK validation and match counts did not run; retry once the DB recovers. |
| Preview valid, but rows skipped on import | The preview only checks headers, FK existence, duplicates and create-missing. Numbers, the stock guard, PO transitions and DB constraints are checked at import. |
| "No rows were imported." | Every row was skipped — read the skipped-row lines and the grouped tail. |
