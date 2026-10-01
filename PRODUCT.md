# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two roles, both real users of the live app (not just of its output):

- **Operator (primary):** the finance/operations person at Lyon AG who re-uploads the monthly SAE Compras and Ventas exports, the Facturación export, and the Contabilidad consolidated ledger each session; classifies providers into the closed category catalog, assigns vendedores to clients, and names/classifies cuentas contables as they appear.
- **Dirección (leadership):** enters the app directly — via the live Streamlit Cloud URL, not only a downloaded report — to read the dashboards, margin, and drill-downs for themselves.

## Product Purpose

Replaces what used to be two standalone Google Colab scripts (Compras, Ventas) plus a manually cross-checked accounting Excel with one persistent, interactive web app. It parses the SAE Compras/Ventas exports, the Facturación export, and the Contabilidad ledger; automatically reconciles the ledger against the SAE to separate spend that already passed through purchasing from spend that didn't (Gasto de Empresa); classifies everything against a closed category catalog; and gives Dirección a real-time, drillable operating picture — margin, cost coverage, provider concentration, spend outside the purchasing process — without waiting for someone to assemble it by hand. Success is Dirección opening the app on their own and trusting what they see.

## Positioning

No spreadsheet or from-scratch BI tool at Lyon AG turns three separately-maintained Excel exports (SAE Compras, SAE Ventas, the Contabilidad ledger) into one reconciled, drillable picture the way this does — specifically, automatically detecting which ledger spend already passed through the SAE purchasing process versus which didn't, using conservative name-matching (no RFC or provider code exists in either source), while refusing to count anything as an expense until a human has explicitly classified the account. That combination — automatic reconciliation plus "nothing counts until a human says so" — is the mechanism a plain spreadsheet or generic dashboard wouldn't give them.

## Operating Context

- Monthly cadence: at the start of a working session the operator re-uploads the SAE Compras export, the SAE Ventas export, the Facturación export, and (separately) the Contabilidad ledger. None of these source files persist between sessions — by deliberate, repeated product decision, nothing uploaded should live in the app's memory once the session ends.
- The Contabilidad ledger (a single Excel the accounting department maintains and periodically hands to the operator) also does not persist — this reverses an earlier design in the project's history that did persist it; the current rule applies to every uploaded source file without exception.
- What *does* persist (SQLite locally, or Postgres/Supabase in the cloud deployment): the provider→category classification catalog, the client→vendedor assignment catalog, the cuenta-contable→categoría/naturaleza/trato catalog, and an events/audit log. These are human decisions, never source data.
- Deployment is Streamlit Cloud with a fixed URL, backed by Supabase Postgres in production. Local SQLite remains the fallback/dev path, not how the operator or Dirección use it day to day.
- Real client and provider identities appear throughout the data (CONALITEG, ~54% of revenue, is a named recurring example) — these are real legal/financial identities, not synthetic sample data, so source files and the local database are gitignored and never committed.
- All UI copy, labels, and business terminology are in Spanish, matching how the business already talks about this work (SAE, Facturación, Conciliación, Gasto de Empresa, Cuenta Contable, etc.) — this is not a bilingual product.

## Capabilities and Constraints

- Closed catalog of 19 spend categories (`core/catalogos.py: CATALOGO_CATEGORIAS`). Cannot be freely extended; adding one needs explicit user permission and must go at the end of the list, since color assignment is positional.
- No RFC or provider code exists in either the SAE or the Contabilidad ledger. The only cross-reference between them is a normalized provider-name match, kept deliberately conservative — a false-positive match would hide real spend from view.
- A cuenta contable counts toward operating cost and margin only once a human has explicitly set its naturaleza to "Gasto operativo." It is never inferred automatically from the account-number prefix alone, even though a one-click shortcut exists that proposes that split for the user to confirm.
- Drill-down navigation happens inline within a page (session-state flags + a stop-and-rerender pattern), not through separate routed pages or URL query params.
- A self-contained executive HTML report can be generated and downloaded for sharing outside the app.
- The SAE and Contabilidad source files arrive genuinely dirty — inconsistent header rows, Spanish month-name variants, stray text landing in amount columns, missing account or provider fields — and the app is expected to absorb that as normal input, surfacing warnings rather than silently dropping or silently miscounting rows.

## Brand Commitments

- Name: **LYON AG**, rendered as a wordmark in the app's sidebar. The company operates from "planta QUMA."
- Existing logo asset at `assets/lion.svg`.
- Corporate color anchors already established in code — blue `#1F4E79` for Lyon/primary, green for Ventas, red for Compras, purple for Gastos de Empresa — recorded here only as an existing commitment to preserve; the full palette, typography, and component system belong in DESIGN.md, not here.

## Evidence on Hand

- Real SAE Compras/Ventas exports and a real Contabilidad ledger exist locally for development (`muestras/`, `contabilidad 2026.xlsx`, `example csv/`) — all gitignored, never committed, and containing real client and provider names and amounts.
- No public marketing copy, testimonials, case studies, or external-facing claims exist or are needed: this is an internal operating tool for Lyon AG, not a customer-facing product, and none should be invented.

## Product Principles

1. Nothing counts as expense or classification until a human has explicitly said so — no silent defaults, no categories inferred from patterns alone.
2. Uploaded source files never persist between sessions; only human decisions (classifications, catalogs) persist.
3. Every number the app shows should be traceable and drillable down to its underlying document or movement, not left as an unexplained aggregate.
4. Real financial and personal-name data never leaves the user's control — never committed to the repository, always gitignored.
5. Dirección is a direct audience of the live app, not only a recipient of a static report — screens must stand on their own for someone who did not build them and cannot ask a question mid-read.
