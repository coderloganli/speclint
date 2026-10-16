# Invoices API Reference

The Invoices API lets you create, list, retrieve, update, and void invoices for your customers. All endpoints accept and return JSON, and every request must be made over HTTPS.

**Base URL:** `https://api.ledgerly.example/v2`

> **Note:** This reference covers API version `2026-09-01`. If you're still on an older version, see [Versioning](#versioning) for what changed.

## Authentication

Authenticate by passing your secret API key as a Bearer token in the `Authorization` header:

```http
Authorization: Bearer sk_live_YOUR_SECRET_KEY
```

Keys prefixed with `sk_test_` operate on test data only and never move real money. Keep your secret keys out of client-side code and version control; if a key leaks, roll it immediately from the dashboard.

Requests without a valid key return `401 Unauthorized`.

## The invoice object

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier, prefixed with `inv_`. |
| `customer_id` | string | The customer being billed. |
| `status` | string | One of `draft`, `open`, `paid`, or `void`. |
| `currency` | string | Three-letter ISO 4217 code, lowercase (e.g. `usd`). |
| `line_items` | array | The items on the invoice. See below. |
| `amount_due` | integer | Total in the smallest currency unit (cents for `usd`). |
| `due_date` | string | ISO 8601 date, e.g. `2026-11-01`. |
| `memo` | string \| null | Free-text note shown to the customer. |
| `metadata` | object | Up to 20 key-value pairs for your own use. |
| `created_at` | string | ISO 8601 timestamp in UTC. |
| `voided_at` | string \| null | When the invoice was voided, if ever. |

Each entry in `line_items` has a `description` (string), `quantity` (integer), and `unit_amount` (integer, smallest currency unit).

## Endpoints

### Create an invoice

```
POST /invoices
```

Creates a new invoice in `draft` status. Drafts can be edited freely until you finalize them.

**Body parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `customer_id` | string | Yes | ID of an existing customer. |
| `currency` | string | Yes | ISO 4217 currency code. |
| `line_items` | array | Yes | At least one line item. |
| `due_date` | string | No | Defaults to 30 days from creation. |
| `memo` | string | No | Maximum 500 characters. |
| `metadata` | object | No | Arbitrary key-value pairs. |

**Example request**

```bash
curl https://api.ledgerly.example/v2/invoices \
  -H "Authorization: Bearer sk_test_..." \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 8f14e45f-ceea-467a-9575-6f1d2c3b9a10" \
  -d '{
    "customer_id": "cus_9s6XKzkNRiz8i3",
    "currency": "usd",
    "line_items": [
      { "description": "Consulting, October", "quantity": 12, "unit_amount": 15000 }
    ],
    "due_date": "2026-11-07"
  }'
```

**Example response** — `201 Created`

```json
{
  "id": "inv_1Nv0FGQ9RKHgCVdK",
  "customer_id": "cus_9s6XKzkNRiz8i3",
  "status": "draft",
  "currency": "usd",
  "line_items": [
    { "description": "Consulting, October", "quantity": 12, "unit_amount": 15000 }
  ],
  "amount_due": 180000,
  "due_date": "2026-11-07",
  "memo": null,
  "metadata": {},
  "created_at": "2026-10-08T14:22:31Z",
  "voided_at": null
}
```

> **Tip:** Send an `Idempotency-Key` header on every `POST`. If a network error forces you to retry, the same key guarantees you won't create a duplicate invoice. Keys expire after 24 hours.

### List invoices

```
GET /invoices
```

Returns invoices sorted by `created_at`, newest first.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `customer_id` | string | — | Only return invoices for this customer. |
| `status` | string | — | Filter by status. |
| `created_after` | string | — | ISO 8601 timestamp, exclusive. |
| `limit` | integer | `20` | Between 1 and 100. |
| `cursor` | string | — | Cursor from a previous response. See [Pagination](#pagination). |

**Example request**

```bash
curl "https://api.ledgerly.example/v2/invoices?status=open&limit=2" \
  -H "Authorization: Bearer sk_test_..."
```

**Example response** — `200 OK`

```json
{
  "data": [
    { "id": "inv_1Nv0FGQ9RKHgCVdK", "status": "open", "amount_due": 180000 },
    { "id": "inv_1Nu8ZbQ9RKHgCVdA", "status": "open", "amount_due": 42500 }
  ],
  "has_more": true,
  "next_cursor": "eyJpZCI6Imludl8xTnU4WmJROVJLSGdDVmRBIn0"
}
```

List items are abbreviated here for readability; the API returns full invoice objects.

### Retrieve an invoice

```
GET /invoices/{id}
```

Returns a single invoice. Returns `404` if no invoice with that ID exists in your account.

```bash
curl https://api.ledgerly.example/v2/invoices/inv_1Nv0FGQ9RKHgCVdK \
  -H "Authorization: Bearer sk_test_..."
```

The response is an [invoice object](#the-invoice-object).

### Update an invoice

```
PATCH /invoices/{id}
```

Updates the fields you send and leaves everything else unchanged. Draft invoices accept any body parameter from [Create an invoice](#create-an-invoice). Once an invoice is `open`, only `memo`, `due_date`, and `metadata` can change.

To finalize a draft, set `status` to `open`. This is the only status transition allowed through `PATCH`.

```bash
curl -X PATCH https://api.ledgerly.example/v2/invoices/inv_1Nv0FGQ9RKHgCVdK \
  -H "Authorization: Bearer sk_test_..." \
  -H "Content-Type: application/json" \
  -d '{ "status": "open", "memo": "Thank you for your business." }'
```

Returns the updated invoice object.

### Void an invoice

```
POST /invoices/{id}/void
```

Marks an `open` invoice as `void`. Voiding is permanent: the invoice stays in your records for auditing but can no longer be paid or edited.

```bash
curl -X POST https://api.ledgerly.example/v2/invoices/inv_1Nv0FGQ9RKHgCVdK/void \
  -H "Authorization: Bearer sk_test_..."
```

Returns the invoice with `status` set to `void` and `voided_at` populated.

> **Warning:** You can't void a `paid` invoice — issue a refund instead. Drafts can't be voided either; just delete them from the dashboard.

## Pagination

List endpoints use cursor-based pagination. When `has_more` is `true`, pass the returned `next_cursor` as the `cursor` query parameter to fetch the next page:

```bash
curl "https://api.ledgerly.example/v2/invoices?limit=2&cursor=eyJpZCI6Imludl8xTnU4WmJROVJLSGdDVmRBIn0" \
  -H "Authorization: Bearer sk_test_..."
```

Cursors are opaque. Don't parse or construct them, and keep the other query parameters identical across pages, or results may be inconsistent.

## Errors

The API uses conventional HTTP status codes. Error responses share a common shape:

```json
{
  "error": {
    "type": "invalid_request",
    "code": "invoice_not_editable",
    "message": "Line items cannot be changed on an open invoice.",
    "param": "line_items"
  }
}
```

| Status | Type | When it happens |
|--------|------|-----------------|
| `400` | `invalid_request` | A parameter is missing, malformed, or out of range. |
| `401` | `authentication_error` | The API key is missing, invalid, or revoked. |
| `403` | `permission_error` | The key lacks permission for this action. |
| `404` | `not_found` | The invoice or customer doesn't exist. |
| `409` | `conflict` | The invoice's status doesn't allow this operation, or an idempotency key was reused with a different body. |
| `429` | `rate_limited` | Too many requests. See [Rate limits](#rate-limits). |
| `500`, `503` | `api_error` | Something went wrong on our end. Retry with backoff. |

Match on `code` rather than `message` in your error handling — messages are written for humans and may change without notice.

## Rate limits

Each API key may make up to **100 requests per second** in live mode and **25 per second** in test mode. Every response includes these headers:

- `X-RateLimit-Limit` — your per-second allowance
- `X-RateLimit-Remaining` — requests left in the current window
- `Retry-After` — seconds to wait (only on `429` responses)

When you hit a `429`, back off exponentially with jitter before retrying. If you consistently need more headroom, contact support.

## Versioning

The API is versioned by date. Pin a version per request with the `Ledgerly-Version` header; otherwise your account's default version applies.

```http
Ledgerly-Version: 2026-09-01
```

We add new endpoints, optional parameters, and response fields without bumping the version, so build your client to ignore fields it doesn't recognize. Breaking changes always ship in a new dated version.

**Changes in `2026-09-01`**

1. `amount_due` is now an integer in the smallest currency unit, replacing the decimal `total` field.
2. Voiding moved from `DELETE /invoices/{id}` to `POST /invoices/{id}/void`.
3. List endpoints switched from offset to cursor pagination; the `page` parameter is gone.

Older versions remain supported for at least 12 months after a successor is released.
