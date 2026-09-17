# Pickup Location Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-authoritative, multi-sample pickup progress and arrival verification for RideNG.

**Architecture:** The driver submits authenticated location observations. RideNG validates sample quality, freshness, ordering, device spoof signals, movement plausibility, proximity, and repeated observations. PostgreSQL stores only bounded rolling verification state while TripEvent stores privacy-minimized verification outcomes.

**Tech Stack:** Python, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic, Pydantic v2, unittest.

**Spec:** `docs/superpowers/specs/2026-09-16-ride-engine-design.md`

## Global Constraints

- Arrival requires two acceptable observations.
- Arrival candidate radius begins at 100 metres.
- Maximum horizontal accuracy is 50 metres.
- Arrival samples must be separated by 3–10 seconds.
- Location samples older than 15 seconds cannot prove pickup state.
- Samples more than 5 seconds in the future are rejected.
- Implausible movement above 55 m/s is rejected.
- Progress verification requires meaningful movement toward pickup.
- Client applications cannot directly create trusted verification events.
- Verification must be scoped to the current active driver assignment.
- Raw coordinates must not be written to permanent TripEvent history.
- Rematching must invalidate verification evidence from the previous assignment.
- Verification thresholds must remain policy configuration rather than route constants.

---

### Task 1: Rolling Verification Persistence

**Files:**
- Create: `backend/app/models/trip_location_verification.py`
- Modify: `backend/app/models/__init__.py`
- Create: Alembic migration

**Produces:**

`TripLocationVerificationState`

One row per trip containing:
- active assignment ID
- last accepted sample
- progress anchor
- arrival candidate count
- progress verification timestamp
- arrival verification timestamp

- [ ] Create model.
- [ ] Register model.
- [ ] Generate Alembic migration.
- [ ] Apply migration.
- [ ] Verify database table.

---

### Task 2: B+ Verification Engine

**Files:**
- Create: `backend/app/services/pickup_location.py`
- Create: `backend/tests/test_pickup_location.py`

**Produces:**

```python
process_pickup_location_observation(...)
has_verified_pickup_progress(...)
has_verified_pickup_arrival(...)
redact_transient_location_state(...)