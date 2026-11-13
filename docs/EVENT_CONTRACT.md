# Detection / OCR event contract

The camera + OCR (ANPR) pipeline is **not** part of this repository. It runs as a
separate service on the gate hardware and posts normalized events to this
application over HTTPS.

> **Open item:** the OCR/detection code lives in a different GitHub repository and
> its URL has not been supplied yet. Until that URL is provided, the integration
> is limited to the contract below plus the reference client
> `backend/detection_client.py`. Nothing in this repository guesses at the
> detector's internals.

## Endpoint

```
POST {TRANSPORT_API_URL}/api/events
Content-Type: application/json
X-Device-Key: <device API key from the server's DEVICE_API_KEYS allowlist>
X-Idempotency-Key: <optional caller-supplied UUID/token, max 128 printable chars>
```

The device key is compared against the allowlist in constant time. Requests
without a valid key receive `401 {"error": "Invalid device API key"}`. A server
with no configured keys rejects all ingestion with `503`. `X-Idempotency-Key`
(stripped before API responses and audit logs) makes network retries safe;
repeated identical deliveries or duplicate camera detections within
`EVENT_DEDUP_WINDOW_SECONDS` (default `30` s) return the existing event with
`200 {"event": {...}, "deduplicated": true}`.

## Payload

```json
{
  "bus_number": "BUS-001",
  "direction": "IN",
  "gate": "Gate 1",
  "camera_id": "gate-1-entry",
  "confidence": 0.96,
  "timestamp": "2026-11-12T09:15:00Z"
}
```

| Field | Type | Rules |
| --- | --- | --- |
| `bus_number` | string | 1–20 chars, normalized to uppercase; letters, digits, spaces, `.`, `-`, `_` only. Unknown plates are still accepted and are flagged. |
| `direction` | string | Exactly `IN` or `OUT` (case-insensitive on input). `IN` means the bus entered the campus, `OUT` means it left. |
| `gate` | string | 1–60 chars, free text (e.g. `"Gate 1"`). |
| `camera_id` | string | 1–60 chars, identifies the camera that produced the read (e.g. `"gate-1-entry"`). |
| `confidence` | number | `0.0`–`1.0`, the OCR/ANPR confidence of the plate read. |
| `timestamp` | string | ISO-8601 date-time. Naive values are interpreted as UTC. Timestamps more than 5 minutes in the future are rejected. |

Unknown extra fields are rejected with `400` so typos in the detector are caught
early instead of being silently ignored.

## Responses

| Status | Body | Meaning |
| --- | --- | --- |
| `201` | `{"event": {...}}` | Stored. The event includes the computed `flagged` boolean and `flag_reasons` list. |
| `200` | `{"event": {...}, "deduplicated": true}` | Existing event matched via `X-Idempotency-Key` or sliding `EVENT_DEDUP_WINDOW_SECONDS` window. |
| `400` | `{"error": "Validation failed", "details": [...]}` | The payload or `X-Idempotency-Key` did not satisfy the contract. |
| `401` | `{"error": "Invalid device API key"}` | Missing or wrong device key. |
| `429` | `{"error": "Too many requests…"}` | `EVENT_RATE_LIMIT` exceeded (keyed by device key or IP). |
| `503` | `{"error": "Device ingestion is not configured"}` | No device keys configured on the server. |

## Flag rules (computed server side)

| Reason | Rule |
| --- | --- |
| `unregistered_plate` | No registered bus matches the canonical `plate_key` (alphanumeric normalization of `bus_number`) in the `buses` table. Matching buses canonicalize `bus_number` to the registered value. |
| `low_ocr_confidence` | `confidence` is below `OCR_CONFIDENCE_THRESHOLD` (default `0.75`). |
| `long_overstay` | The bus's latest prior `IN` event has no closing `OUT` event ordered by `(timestamp, _id)` before this event and is older than `OVERSTAY_HOURS` (default `12`). |

Every ingested event is also written to the audit log with the actor
`device-client`.

## Reference client

`backend/detection_client.py` posts one event using `DEVICE_API_KEY` and
`TRANSPORT_API_URL` from the environment (the key is never printed):

```bash
export TRANSPORT_API_URL=https://transport.example.edu
export DEVICE_API_KEY='<key from DEVICE_API_KEYS>'
python3 -m backend.detection_client \
  --bus-number BUS-001 --direction IN --gate "Gate 1" \
  --camera-id gate-1-entry --confidence 0.96
```

A detector can also post a batch by looping over its own detections and calling
the endpoint once per event, or by writing JSON files and using `--event-json`.

## Wiring the real detector

1. Run the OCR service so it can reach this API over HTTPS.
2. Give the detector one of the keys listed in the server's `DEVICE_API_KEYS`
   (separate keys per camera group make revocation easier).
3. Map the detector's plate read to `bus_number`, its lane to `gate`, its
   camera identifier to `camera_id`, its score to `confidence` (normalised to
   `0.0`–`1.0`) and its capture time to `timestamp` (ISO-8601, UTC preferred).
4. Confirm the direction semantics: `IN` = entering the campus, `OUT` = leaving.
   "Currently Inside" is derived from the latest event per bus.
5. Verify with `GET /api/stats` (entries today, buses inside) and
   `GET /api/events?date=YYYY-MM-DD`.
