# Albiruni ERP — notes for Claude

## Customers are in India AND Saudi Arabia

Every company in the system is registered in one country — today India (IN) or
Saudi Arabia (SA) — and its tax rules follow from that
(`backend/app/domain/regimes.py`). Never build anything that assumes India:

- **Tax:** India uses GST (CGST + SGST within a state, IGST between states,
  GSTIN, HSN, TDS, GSTR-1, NIC e-invoice, e-way bill). Saudi Arabia uses one
  VAT line (15% standard; zero-rated / exempt / out of scope with a ZATCA
  reason), VAT and CR numbers, ZATCA e-invoicing (QR code, UBL XML) and
  bilingual Arabic/English invoices. Zakat is a yearly Finance calculation,
  not an invoice tax.
- **Money and dates:** currency comes from the company (INR, SAR); India
  rounds invoice totals to the rupee, Saudi Arabia keeps halalas; the
  financial year starts in `company.fy_start_month` (April in India, usually
  January in Saudi Arabia). Indian lakh/crore formatting is for INR only.
- **New modules** (Purchasing, Finance, HR/payroll…) must ask the regime what
  to do — input tax, withholding tax, returns, payroll rules all differ by
  country. Add what's needed to `Regime` instead of writing `if India`.
- **Tests:** cover both an Indian and a Saudi company for anything that
  touches tax, numbering, currency or documents.

A company's country is fixed once it has issued a sales document; a move to
another country is a new company, and old documents keep their rules.

## Working here

- Backend: FastAPI + SQLAlchemy 2 + Postgres, Alembic migrations in
  `backend/alembic/versions` (run at startup). Tests:
  `CRM_TEST_DB=1 DATABASE_URL=... .venv/bin/python -m unittest discover -s tests`
  and `MIGRATION_TEST_DB=... .venv/bin/python -m unittest tests.test_migrations`.
- Frontend: React + Vite + TypeScript in `frontend/`; check with
  `npx tsc --noEmit -p tsconfig.app.json`, `npx oxlint src`, `npx vite build`.
- Actions that change business records go through the audited tool gateway
  (`backend/app/toolgateway`).
