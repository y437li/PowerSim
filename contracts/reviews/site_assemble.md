# Review record: `site_assemble`

**Contract:** `contracts/serving/site_assemble.md` v1.0.0
**Tests:** `tests/serving/test_serving_site_assemble.py`
**Required reviewer:** backend-reviewer (gate)
**Advisory reviewer:** frontend-engineer (wizard-form input shape — consulted pre-contract; green-lit)
**Task:** #6

## Pre-contract consultations

- **frontend-engineer (2026-06-13):** green-lit the proposed input/response shapes.
  Confirmed: `tariff_region` string sufficient (no 12×24 table needed from wizard);
  `costs`/`forecast` omitted from stage ①; `site_config` always present in response.
  Follow-up F1/F2/F3 answers recorded in contract §3.2–§3.3.

## Open for backend-reviewer

Awaiting backend-reviewer verdict (APPROVE / REQUEST_CHANGES).
