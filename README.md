# API Service

FastAPI backend for Thesis Format Tool Pro.

## Commands

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Structure

```text
app/main.py              FastAPI app factory and middleware
app/api/router.py        Aggregates all route modules
app/api/routes           Stable route import surface
app/api/*.py             Route implementations
app/core                 Settings and auth/security helpers
app/db                   Supabase REST client
app/schemas              Pydantic response/request models
app/services             R2, payOS, and docx formatting services
app/utils                Shared utility helpers
```

## Endpoints

```text
GET /health
GET /ready
GET /api/v1/me
GET /api/v1/documents
POST /api/v1/documents/upload
POST /api/v1/documents/{document_id}/analyze
POST /api/v1/documents/{document_id}/annotate
POST /api/v1/documents/{document_id}/annotated-download-token
GET /api/v1/documents/{document_id}/annotated-download?token=...
POST /api/v1/documents/{document_id}/fix
POST /api/v1/documents/{document_id}/download-token
GET /api/v1/documents/{document_id}/download?token=...
POST /api/v1/documents/{document_id}/checkout
GET /api/v1/documents/{document_id}/payment-status?orderCode=...
GET /api/v1/wallet
POST /api/v1/wallet/topup
GET /api/v1/wallet/topup-status?orderCode=...
POST /api/v1/payments/payos/webhook
```

`/api/v1/me` requires:

```http
Authorization: Bearer <supabase_access_token>
```

Set `SUPABASE_JWT_SECRET` before testing protected routes.

`/ready` checks required production env groups without printing secret values.
It returns HTTP 503 when Supabase, R2, payOS, public app URL, or CORS settings
are missing. LibreOffice render availability is optional.

The upload route also needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the R2 environment variables from `.env.example`.

Environment loading order is:

1. repo root `.env`
2. `services/api/.env` if present

Values in `services/api/.env` override the root file.

`GET /api/v1/documents?limit=20` requires the authorization header and returns
only documents owned by the current user. Results are ordered newest first and
the limit is constrained to 1-50.

`POST /api/v1/documents/upload` requires:

```http
Authorization: Bearer <supabase_access_token>
```

```text
multipart/form-data:
file=<valid .docx, max 20MB>
document_type=<active document template key>
```

`POST /api/v1/documents/{document_id}/analyze` requires the same authorization header. It downloads the original file from R2, analyzes formatting with `configs/school_config.json`, stores raw findings in Supabase for precise annotation, uploads a compact grouped `report.json` to R2, and returns grouped findings plus `preview_comments`.

Advanced findings such as color/highlight/underline, character density, equation layout, image wrapping/width, table overflow, header/footer, page-number issues, caption numbering, and generated list consistency are manual-review only. They are reported and annotated, but `/fix` does not modify them.

Analyze output is normalized through a central fixability matrix. Only whitelisted formatting issues receive `fixability_scope=safe_auto_fix`; structural/review issues are forced to `manual_review` even if a rule accidentally marks them auto-fixable.

Manual-review issues also include `repair` guidance with Word steps, verification checks, and a clear reason why `/fix` will not touch that issue. The same guidance is aggregated in `summary.manual_repair_guidance`, `issue_groups[].manual_repair_guidance`, and top-level `manual_repair_guidance` for frontend overview panels.

Render verification is optional and runs during analyze when LibreOffice (`soffice`) is available in the backend runtime. It renders the Word file to a temporary PDF with an isolated LibreOffice profile, inspects blank pages, edge overflow, and suspicious caption page breaks, then deletes the temporary PDF. If LibreOffice or PDF reader libraries are missing, analyze still succeeds with `render_verification.status=skipped`. `/ready` reports both optional checks: `libreoffice_render` and `pdf_render_reader`.

`POST /api/v1/documents/{document_id}/annotate` requires the same authorization header and an analyzed document. It creates a separate Word review file with hybrid comments, uploads `annotated-report.docx` to R2, saves `documents.annotated_file_key`, and never overwrites the original or fixed file. No payment is required. Repeated style/format findings may be grouped into one representative comment, while structural and manual-review findings are anchored to their own locator when possible.

`POST /api/v1/documents/{document_id}/annotated-download-token` requires the same authorization header and an existing annotated file. It creates a short-lived one-time token with `kind=annotated`.

`GET /api/v1/documents/{document_id}/annotated-download?token=...` requires the same authorization header. It validates ownership, token hash, expiry, and usage state, then returns the annotated Word review file as an attachment.

Compatibility aliases remain available for existing clients:

```text
POST /api/v1/documents/{document_id}/annotated-report
GET /api/v1/documents/{document_id}/annotated-report/download
```

`POST /api/v1/documents/{document_id}/fix` requires the same authorization header and document ownership. It does not charge the user. It downloads the original file from R2, writes a separate clean fixed `.docx`, strips comments/highlights from the output, verifies visible text did not change, uploads `fixed.docx` to R2, saves `fixed_file_key` and `fixed_at`, and updates document status to `fixed`.

By default, `/fix` runs `fix_mode=safe_all` for every safe formatting group. Clients may narrow the run with:

```json
{
  "fix_mode": "safe_scope",
  "fix_scope": ["page_setup", "paragraph_format"]
}
```

Supported `fix_scope` keys are `page_setup`, `front_matter_heading`, `list_item`, `caption_format`, `table_cell_format`, `header_footer_format`, `paragraph_format`, and `heading_format`. The response includes `applied_fix_scope`, `available_fix_scope`, selected `safe_fix_rules`, `skipped_safe_fix_rules`, analyzer-only rules that were blocked from auto-fix, per-rule change counts, and safety checks. Safe auto-fix currently covers conservative style-level fixes, page setup, front-matter heading formatting, body paragraph formatting, list item formatting, caption formatting, table-cell font/size, header/footer font/size, and basic heading formatting.

After saving and cleaning the fixed file, the backend runs a post-fix analyzer gate. The gate fails the fix before upload if any selected safe formatting issue remains. Manual-review findings and safe findings outside a narrowed `safe_scope` are reported in `post_fix_validation`, but they do not block the fixed file.

Expanded safe fixing is intentionally narrow. Table structure/width, image layout, caption numbering, TOC/list generation, page-number section logic, and header/footer layout remain analyzer/annotator-only manual-review issues.

Style-level fixing uses `style_fix_mode=conservative_exclusive_style`: the backend updates a paragraph style only when that style is used exclusively by one safe context such as body paragraphs, list items, captions, or headings. If a style is shared with cover pages, TOC, front matter, tables, header/footer, or unknown content, style-level fixing is skipped and the paragraph-level safe fixer remains the fallback.

`POST /api/v1/documents/{document_id}/download-token` requires the same authorization header, document ownership, and an existing fixed file. This is the fixed-file charge point: the backend calls `purchase_document_with_wallet`. If the document was already purchased, it creates a new token without charging again. If the wallet balance is insufficient, it returns HTTP 402 with `reason=insufficient_wallet_balance`, `balance_vnd`, `required_amount`, `deficit_vnd`, and `topup_url`. On success it creates a short-lived one-time token with `kind=fixed` and stores only `token_hash` in Supabase.

`GET /api/v1/documents/{document_id}/download?token=...` requires the same authorization header. It validates ownership, existing wallet purchase, token hash, expiry, and usage state, then returns the fixed `.docx` as an attachment.

`GET /api/v1/wallet` returns the current user's wallet balance.

`POST /api/v1/wallet/topup` creates a `wallet_topups` row, calls payOS, and returns a checkout URL/QR for adding funds to the wallet. The optional `return_to` field must be a relative path beginning with `/`.

`GET /api/v1/wallet/topup-status?orderCode=...` reconciles a wallet top-up against payOS and returns the latest top-up status.

`POST /api/v1/documents/{document_id}/checkout` remains as a legacy/backward-compatible per-document checkout endpoint. The frontend fixed-file flow no longer calls it.

An unexpired pending checkout is reused instead of creating multiple open payOS
orders for the same document.

`GET /api/v1/documents/{document_id}/payment-status` requires authorization and
ownership. It reconciles pending orders against payOS and is the source of truth
for the frontend return flow.

`POST /api/v1/payments/payos/webhook` is called by payOS. It verifies `signature`
with `PAYOS_CHECKSUM_KEY`, validates amount/currency, deduplicates repeated
events, and first tries to match a legacy document order. If no order exists,
it matches `wallet_topups` by `provider_order_code` and calls
`credit_wallet_topup` for paid top-ups. A paid order/top-up is never downgraded.

Payment routes require `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, `PAYOS_CHECKSUM_KEY`, and `APP_PUBLIC_BASE_URL`.

Download token expiry is configured by `DOWNLOAD_TOKEN_TTL_MINUTES`.
Download token use is consumed with an atomic `used_at is null` update so two
concurrent requests cannot reuse the same token.

Browser download responses expose the `Content-Disposition` CORS header so the
frontend can preserve backend-provided `.docx` filenames.

## Verification

```powershell
cd E:\ProjectAndriod\thesis-format-tool-pro\services\api
..\.venv\Scripts\python.exe -m unittest discover -s tests
..\.venv\Scripts\python.exe -m compileall app tests
```

Expire stale pending orders from a scheduled Cloud Run Job or equivalent:

```powershell
..\.venv\Scripts\python.exe scripts\expire_pending_orders.py
```

## Supabase Verification

Run the live Supabase diagnostic without printing secrets:

```powershell
cd E:\ProjectAndriod\thesis-format-tool-pro\services\api
..\.venv\Scripts\python.exe scripts\check_supabase_setup.py
```

If live `document_templates.config_json` is behind local `configs\school_config.json`, sync template config:

```powershell
..\.venv\Scripts\python.exe scripts\check_supabase_setup.py --sync-template-config
```

To smoke-test authenticated RLS/Data API behavior, pass a real Supabase access token:

```powershell
..\.venv\Scripts\python.exe scripts\check_supabase_setup.py --access-token "<supabase_access_token>"
```
