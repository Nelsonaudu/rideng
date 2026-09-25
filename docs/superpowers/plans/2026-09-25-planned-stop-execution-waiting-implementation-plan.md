# Batch 9 Planned Stop Execution and Waiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pre-planned intermediate stops executable during an in-progress RideNG trip with verified physical arrival, Abuja waiting charges, explicit extensions, rider warnings, and auditable timeout termination.

**Architecture:** Keep the existing top-level trip state machine unchanged and add a subordinate intermediate-stop execution subsystem. Persist one bounded location-verification state and one waiting state per intermediate stop, derive waiting charges from server-authorized time intervals, and schedule rider warnings through a transactional notification outbox. Reuse extracted generic location-validation primitives from Batch 8 while keeping pickup and stop persistence separate.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, Alembic, unittest, Decimal currency arithmetic.

**Spec:** `docs/superpowers/specs/2026-09-25-planned-stop-execution-waiting-design.md`

## Global Constraints

- Batch 9 operates planned `TripStop` rows with `stop_type == "intermediate"` only; post-match add/remove-stop negotiation is Batch 10.
- The top-level trip remains `in_progress` while intermediate stops execute.
- Only the active assigned driver may mutate stop state; the owning rider may read current-stop state.
- The authoritative current stop is resolved by the server from the lowest-sequence incomplete intermediate stop; consequential writes never accept an arbitrary stop ID.
- Abuja launch waiting policy is exactly: 180 free seconds, ₦75.00 per paid minute, driver exit right at 600 seconds from verified arrival, and explicit 300-second extensions.
- Waiting is billed by elapsed whole seconds using Decimal arithmetic; fractional microseconds are truncated, never rounded upward.
- Paid time accrues only inside an explicitly authorized interval; time after `authorized_until` is non-billable until a new extension is accepted.
- Extensions never roll over automatically and cannot be stacked twice from one decision boundary.
- Intermediate-stop arrival uses the Batch 8 B+ limits: max 50 m accuracy, 100 m uncertainty-aware arrival envelope, max 15 s sample age, 5 s future skew, two confirming samples separated by 3–10 s, mocked locations rejected, implausible movement rejected.
- Device `captured_at` is validation input only; server time sets authoritative `TripStop.arrived_at`, wait boundaries, departure, and termination.
- Raw transient driver latitude/longitude must not appear in `TripEvent` or notification-outbox payloads.
- Rider warning cadence is: arrival immediately, +2 min free-wait warning, +3 min paid-wait notice, +8 min two-minute exit warning, +9 min one-minute exit warning, +10 min exit-right notice; extensions add immediate, one-minute-remaining, and boundary notices.
- Notification delivery failure never changes billing, stop state, trip state, or exit-right timing.
- Timeout termination uses `Trip.status = "terminated"`, reason `intermediate_stop_wait_timeout`, closes the active `DriverAssignment` as `completed`, and clears `Trip.active_assignment_id`.
- Batch 9 records gross waiting facts only; final partial-trip base-fare settlement, commission, payout, and refund logic remain out of scope.
- Consequential stop actions use `Idempotency-Key`, PostgreSQL row locking, and first-valid-commit-wins semantics.

## Review Focus

- **Exact time boundaries:** 179/180 seconds and 599/600 seconds must behave correctly; Task 5 pins the free/paid and exit-right inclusivity rules.
- **No intermediate stops:** a trip with only pickup and destination must return no current intermediate stop without breaking normal `/complete`; Task 6 pins this.
- **Stale assignment evidence:** a rematched/old driver must not read their old verification as authority or mutate waiting state; Tasks 4 and 6 pin this.
- **Delayed extension gaps:** a driver extending after an authorization boundary must never back-bill the gap; Task 5 pins this with a 10:00→11:30 freeze-gap case.
- **Notification dedupe/cancellation races:** retries, early departure, and termination must not leave duplicate or future warnings active; Tasks 3 and 5 pin dedupe and cancellation behavior.

---

## File Structure

### New files

- `backend/app/models/trip_stop_location_verification.py` — bounded per-stop B+ location evidence.
- `backend/app/models/trip_stop_wait_state.py` — policy snapshot, authorized intervals, accrued seconds, and final waiting outcome.
- `backend/app/models/notification_outbox.py` — scheduled/cancelled/delivered notification intents with a unique dedupe key.
- `backend/app/services/location_verification.py` — reusable stateless sample validation and arrival-confirmation primitives shared by pickup and intermediate stops.
- `backend/app/services/notification_outbox.py` — schedule/cancel helpers for authoritative notification intents.
- `backend/app/services/trip_stop_location.py` — current-stop resolution plus intermediate-stop location verification and atomic arrival activation.
- `backend/app/services/trip_stop_waiting.py` — pure waiting math plus depart/extend/terminate state transitions.
- `backend/app/schemas/trip_stops.py` — location request and current-stop/action response models.
- `backend/app/api/routes/trip_stops.py` — current-stop location/read/depart/extend/end-trip endpoints.
- `backend/tests/test_location_verification.py` — generic location primitive tests.
- `backend/tests/test_trip_stop_models.py` — model/policy/schema invariants.
- `backend/tests/test_notification_outbox.py` — warning schedule, dedupe, and cancellation tests.
- `backend/tests/test_trip_stop_location.py` — current-stop ordering and B+ stop-arrival tests.
- `backend/tests/test_trip_stop_waiting.py` — waiting math, extensions, departure, and termination tests.
- `backend/tests/test_trip_stop_api.py` — auth, OpenAPI, idempotency, state conflicts, privacy, and read-role tests.
- `backend/alembic/versions/d7a91c4f2e60_add_trip_stop_execution_waiting.py` — Batch 9 persistence migration, down-revision `888e1769cccb`.

### Modified files

- `backend/app/services/ride_policy.py` — add the approved Abuja intermediate-stop waiting policy object without changing existing ride pricing behavior.
- `backend/app/services/pickup_location.py` — consume shared location primitives while preserving all existing Batch 8 behavior and public interfaces.
- `backend/app/models/__init__.py` — register the three new models.
- `backend/app/api/router.py` — register the Batch 9 trip-stop router.
- `backend/app/models/trip_stop.py` — preserve current columns; document/use `paid_wait_started_at` as a denormalized audit marker only.
- `backend/tests/test_pickup_location.py` — retain the Batch 8 suite as regression coverage after extraction.

---

### Task 1: Lock the Abuja stop-waiting policy and pure waiting mathematics

**Files:**
- Modify: `backend/app/services/ride_policy.py`
- Create: `backend/app/services/trip_stop_waiting.py`
- Create: `backend/tests/test_trip_stop_waiting.py`
- Modify: `backend/tests/test_ride_policy.py`

**Interfaces:**
- Produces: `IntermediateStopWaitingPolicy`, `ABUJA_INTERMEDIATE_STOP_WAIT_POLICY`, `WaitStateLike` (a structural Protocol so pure meter tests do not depend on ORM models), `WaitMeterSnapshot`, `calculate_wait_meter(*, state: WaitStateLike, now: datetime) -> WaitMeterSnapshot`, and `gross_wait_charge(*, billable_seconds, rate_per_minute) -> Decimal`.
- Consumes: existing `ABUJA_RIDE_TIMING_POLICY` values for 180/600/300 seconds so timing has one source of truth.

- [ ] **Step 1: Write failing policy tests**

Add tests asserting:

```python
self.assertEqual(policy.free_wait_seconds, 180)
self.assertEqual(policy.wait_rate_per_minute, Decimal("75.00"))
self.assertEqual(policy.driver_exit_right_seconds, 600)
self.assertEqual(policy.extension_seconds, 300)
```

Also assert the new policy's timing values match `ABUJA_RIDE_TIMING_POLICY.stop_free_wait_seconds`, `.stop_control_seconds`, and `.stop_extension_seconds`.

- [ ] **Step 2: Run the policy tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ride_policy -v
```

Expected: FAIL because `ABUJA_INTERMEDIATE_STOP_WAIT_POLICY` does not exist.

- [ ] **Step 3: Implement the policy interface**

In `ride_policy.py`, add:

```python
@dataclass(frozen=True)
class IntermediateStopWaitingPolicy:
    free_wait_seconds: int
    wait_rate_per_minute: Decimal
    driver_exit_right_seconds: int
    extension_seconds: int
```

Create `ABUJA_INTERMEDIATE_STOP_WAIT_POLICY` with ₦75.00 and the existing timing-policy values.

- [ ] **Step 4: Write failing pure-meter tests**

In `test_trip_stop_waiting.py`, cover:

- depart at 2:59 → 0 billable seconds / ₦0;
- exactly 3:00 → 0 billable seconds;
- depart at 5:00 → 120 seconds / ₦150.00;
- 90 paid seconds → ₦112.50;
- no extension and query at 20:00 → cap at 420 seconds / ₦525.00;
- delayed extension gap 10:00→11:30 remains non-billable;
- elapsed microseconds do not round a partial second upward.

- [ ] **Step 5: Run the pure-meter tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_waiting -v
```

Expected: FAIL because the meter interfaces do not exist.

- [ ] **Step 6: Implement the pure meter interfaces**

Create:

```python
class WaitStateLike(Protocol):
    arrived_at: datetime
    free_wait_ends_at: datetime
    driver_exit_right_at: datetime
    current_paid_window_started_at: datetime | None
    authorized_until: datetime | None
    accrued_billable_seconds: int
    wait_rate_per_minute: Decimal

@dataclass(frozen=True)
class WaitMeterSnapshot:
    billable_seconds: int
    gross_wait_charge: Decimal
    free_wait_ends_at: datetime
    driver_exit_right_at: datetime
    authorized_until: datetime | None
    exit_right_available: bool
    extension_available: bool

def gross_wait_charge(
    *,
    billable_seconds: int,
    rate_per_minute: Decimal,
) -> Decimal: ...

def calculate_wait_meter(
    *,
    state: WaitStateLike,
    now: datetime,
) -> WaitMeterSnapshot: ...
```

Use whole elapsed seconds and cap the live interval at `authorized_until`.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ride_policy tests.test_trip_stop_waiting -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add app/services/ride_policy.py app/services/trip_stop_waiting.py tests/test_ride_policy.py tests/test_trip_stop_waiting.py
git commit -m "feat: add intermediate stop waiting policy"
```

---

### Task 2: Extract reusable B+ location primitives without changing pickup behavior

**Files:**
- Create: `backend/app/services/location_verification.py`
- Modify: `backend/app/services/pickup_location.py`
- Create: `backend/tests/test_location_verification.py`
- Modify: `backend/tests/test_pickup_location.py`

**Interfaces:**
- Produces: `ArrivalLocationPolicy`, `LocationSample`, `LocationValidationResult`, `ArrivalConfirmationResult`, `validate_location_sample(...) -> LocationValidationResult`, and `advance_arrival_confirmation(...) -> ArrivalConfirmationResult`.
- Consumes: Batch 8 pickup state fields; no database model dependency is allowed in the generic module.
- Compatibility: existing pickup exceptions, `ABUJA_PICKUP_LOCATION_POLICY`, `process_pickup_location_observation`, and all Batch 8 result semantics remain callable exactly as before.

- [ ] **Step 1: Write failing generic-location tests**

Cover exact replay, sample-ID conflict, stale/future timestamps, poor accuracy, mocked location, reported-speed rejection, impossible movement, out-of-order samples, uncertainty-aware arrival qualification, two-sample 3–10 second confirmation, and >10-second candidate reset.

- [ ] **Step 2: Run generic tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_location_verification -v
```

Expected: FAIL because `location_verification.py` does not exist.

- [ ] **Step 3: Implement stateless validation interfaces**

Define:

```python
@dataclass(frozen=True)
class ArrivalLocationPolicy:
    arrival_radius_m: float
    max_horizontal_accuracy_m: float
    max_sample_age_seconds: int
    max_future_skew_seconds: int
    min_confirmation_separation_seconds: int
    max_confirmation_separation_seconds: int
    max_plausible_speed_mps: float

@dataclass(frozen=True)
class LocationSample:
    sample_id: UUID
    latitude: Decimal
    longitude: Decimal
    horizontal_accuracy_m: Decimal
    captured_at: datetime
    reported_speed_mps: Decimal | None = None
    is_mocked: bool | None = None
```

`validate_location_sample` accepts the prior stored sample fields, target coordinates, `now`, and policy; it returns replay status plus distance-to-target without mutating ORM state.

`advance_arrival_confirmation` accepts candidate count/timestamp plus validated distance/accuracy and returns the next candidate state and `newly_verified`.

- [ ] **Step 4: Refactor pickup service to consume the generic primitives**

Keep pickup-specific progress-anchor logic and assignment reset in `pickup_location.py`. Replace duplicated replay/sample/arrival-candidate calculations with the new generic helpers.

- [ ] **Step 5: Run Batch 8 regression and generic tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_location_verification tests.test_pickup_location tests.test_pickup_location_api tests.test_trip_location_authorization -v
```

Expected: all tests pass with unchanged pickup API behavior.

- [ ] **Step 6: Commit**

```powershell
git add app/services/location_verification.py app/services/pickup_location.py tests/test_location_verification.py tests/test_pickup_location.py
git commit -m "refactor: share B plus location verification primitives"
```

---

### Task 3: Add Batch 9 persistence models and migration

**Files:**
- Create: `backend/app/models/trip_stop_location_verification.py`
- Create: `backend/app/models/trip_stop_wait_state.py`
- Create: `backend/app/models/notification_outbox.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/d7a91c4f2e60_add_trip_stop_execution_waiting.py`
- Create: `backend/tests/test_trip_stop_models.py`

**Interfaces:**
- Produces ORM classes `TripStopLocationVerificationState`, `TripStopWaitState`, and `NotificationOutbox`.
- Consumes: `TripStop`, `Trip`, `DriverAssignment`, `User`, and the policy snapshot from Task 1.

- [ ] **Step 1: Write failing model metadata tests**

Assert:

- one primary-key/unique row per `stop_id` for location verification and wait state;
- assignment/trip/stop foreign keys exist;
- wait-state nonnegative constraints exist for accrued seconds and extension count;
- `wait_rate_per_minute >= 0`;
- notification status is constrained to `pending|delivered|cancelled|failed`;
- notification `dedupe_key` is unique.

- [ ] **Step 2: Run model tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_models -v
```

Expected: import failure for the new models.

- [ ] **Step 3: Implement `TripStopLocationVerificationState`**

Use one row per stop with the spec fields:

```text
stop_id, trip_id, assignment_id,
last_sample_id,
last_latitude, last_longitude,
last_horizontal_accuracy_m,
last_distance_to_stop_m,
last_sample_captured_at,
last_sample_received_at,
arrival_candidate_count,
last_arrival_candidate_at,
arrival_verified_at,
created_at, updated_at
```

- [ ] **Step 4: Implement `TripStopWaitState`**

Use one row per stop with:

```text
stop_id, trip_id, assignment_id,
free_wait_seconds,
wait_rate_per_minute,
driver_exit_right_seconds,
extension_seconds,
arrived_at,
free_wait_ends_at,
driver_exit_right_at,
current_paid_window_started_at,
authorized_until,
accrued_billable_seconds,
extension_count,
final_billable_seconds,
final_wait_charge,
closed_at,
close_reason,
created_at, updated_at
```

A closed row must not retain an active paid-window start/authorization pair.

- [ ] **Step 5: Implement `NotificationOutbox`**

Required fields:

```text
id, user_id, trip_id, stop_id,
notification_type, dedupe_key,
scheduled_for, payload, status,
created_at, delivered_at, cancelled_at
```

Use JSONB for `payload`.

- [ ] **Step 6: Register all models**

Update `app/models/__init__.py` and `__all__`.

- [ ] **Step 7: Create the migration**

Create `d7a91c4f2e60_add_trip_stop_execution_waiting.py` with:

```text
revision = "d7a91c4f2e60"
down_revision = "888e1769cccb"
```

Create all three tables, indexes, uniqueness, checks, and foreign keys matching the ORM models.

- [ ] **Step 8: Run model tests and migration compile**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_models -v
.\.venv\Scripts\python.exe -m py_compile app\models\trip_stop_location_verification.py app\models\trip_stop_wait_state.py app\models\notification_outbox.py alembic\versions\d7a91c4f2e60_add_trip_stop_execution_waiting.py
```

Expected: tests pass and compile emits no output.

- [ ] **Step 9: Apply and inspect migration**

Run:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Expected: `d7a91c4f2e60 (head)`.

Use SQLAlchemy inspector to verify the three tables, required columns, foreign keys, unique constraints, and checks.

- [ ] **Step 10: Commit**

```powershell
git add app/models/__init__.py app/models/trip_stop_location_verification.py app/models/trip_stop_wait_state.py app/models/notification_outbox.py alembic/versions/d7a91c4f2e60_add_trip_stop_execution_waiting.py tests/test_trip_stop_models.py
git commit -m "feat: add trip stop waiting persistence"
```

---

### Task 4: Build the transactional notification-outbox scheduling service

**Files:**
- Create: `backend/app/services/notification_outbox.py`
- Create: `backend/tests/test_notification_outbox.py`

**Interfaces:**
- Consumes: `NotificationOutbox`, stop/trip/rider identifiers, policy snapshot, and authoritative timestamps.
- Produces:

```python
def schedule_stop_arrival_notifications(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    arrived_at: datetime,
    policy: IntermediateStopWaitingPolicy,
) -> list[NotificationOutbox]: ...

def schedule_wait_extension_notifications(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    extension_number: int,
    extension_started_at: datetime,
    extension_seconds: int,
    wait_rate_per_minute: Decimal,
) -> list[NotificationOutbox]: ...

def cancel_pending_stop_notifications(
    *,
    db: Session,
    stop_id: UUID,
    now: datetime,
) -> int: ...

def schedule_wait_ended_notification(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    stopped_at: datetime,
    final_wait_charge: Decimal,
) -> NotificationOutbox: ...
```

- [ ] **Step 1: Write failing schedule tests**

Assert the initial six notification intents are scheduled at arrival, +2, +3, +8, +9, +10 minutes with deterministic unique dedupe keys and payloads containing no `latitude` or `longitude`.

- [ ] **Step 2: Add extension/dedupe/cancellation tests**

Assert:

- extension notice at extension start;
- one-minute-remaining notice at `extension_end - 60s`;
- boundary notice at extension end;
- extension number participates in the dedupe key;
- repeating scheduling for the same dedupe key does not create duplicates;
- cancelling a stop changes only pending future intents to `cancelled`;
- already delivered/failed intents are not rewritten;
- cancellation followed by a retry remains stable.

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_notification_outbox -v
```

Expected: FAIL because the service is missing.

- [ ] **Step 4: Implement the outbox helpers**

Use database state, not external push calls. Do not implement a push worker in Batch 9.

- [ ] **Step 5: Run tests and verify GREEN**

Run the same unittest command; expect all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app/services/notification_outbox.py tests/test_notification_outbox.py
git commit -m "feat: add stop waiting notification outbox"
```

---

### Task 5: Implement authoritative current-stop arrival and waiting lifecycle

**Files:**
- Create: `backend/app/services/trip_stop_location.py`
- Modify: `backend/app/services/trip_stop_waiting.py`
- Create: `backend/tests/test_trip_stop_location.py`
- Expand: `backend/tests/test_trip_stop_waiting.py`

**Interfaces:**
- Consumes Tasks 1–4.
- Produces:

```python
def get_current_intermediate_stop(
    *,
    db: Session,
    trip_id: UUID,
    lock: bool = False,
) -> TripStop | None: ...

@dataclass(frozen=True)
class StopLocationResult:
    replayed: bool
    stop_id: UUID
    stop_sequence: int
    distance_to_stop_m: float
    arrival_candidate_count: int
    arrival_verified: bool
    arrival_newly_verified: bool

def process_current_stop_location(
    *,
    db: Session,
    trip: Trip,
    assignment: DriverAssignment,
    rider_id: UUID,
    sample: LocationSample,
    now: datetime | None = None,
) -> StopLocationResult: ...

@dataclass(frozen=True)
class StopActionResult:
    stop_id: UUID
    stop_sequence: int
    billable_seconds: int
    gross_wait_charge: Decimal
    extension_count: int
    trip_status: str

def depart_current_stop(...) -> StopActionResult: ...
def extend_current_stop_wait(...) -> StopActionResult: ...
def terminate_at_current_stop(...) -> StopActionResult: ...
```

- [ ] **Step 1: Write failing current-stop ordering tests**

Cover:

- lowest-sequence incomplete intermediate stop is current;
- pickup and destination are ignored;
- departed Stop 1 makes Stop 2 current;
- a trip with no intermediate stops returns `None`;
- a prior stop cannot reopen.

- [ ] **Step 2: Write failing stop-location B+ tests**

Cover the complete spec list: two samples verify, one does not, accuracy/stale/future/mocked/impossible/out-of-order rejected, replay safe, sample-ID conflict rejected, old assignment rejected/reset, and Stop 1 evidence cannot verify Stop 2.

- [ ] **Step 3: Run stop-location tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_location -v
```

Expected: FAIL because the stop-location service is missing.

- [ ] **Step 4: Implement current-stop resolution and location processing**

`process_current_stop_location` must:

- require `trip.status == "in_progress"`;
- resolve and lock the current intermediate stop;
- create/lock per-stop verification state;
- scope state to `assignment.id`;
- use generic B+ helpers from Task 2;
- on newly verified arrival, set `TripStop.arrived_at = now`, leave `TripStop.paid_wait_started_at = None`, create `TripStopWaitState` from Task 1 policy, schedule initial outbox notices, create privacy-safe `intermediate_stop_arrived` event, and redact transient exact driver coordinates after durable activation;
- never commit internally; the caller owns the transaction.

- [ ] **Step 5: Write failing waiting lifecycle tests**

Add tests for:

- depart at 2:59, 3:00, 5:00;
- exactly 10:00 exit right available, 9:59 rejected;
- delayed 11:30 extension does not bill 10:00→11:30;
- each extension is exactly 300 seconds;
- same decision boundary cannot be consumed twice;
- later extension boundary can be renewed;
- departure closes state, clears active interval, sets `TripStop.departed_at`, cancels future notices, and schedules final charge notice;
- termination closes state, sets trip `terminated`, sets assignment `completed`, clears `active_assignment_id`, leaves later stops untouched, and emits reason `intermediate_stop_wait_timeout`;
- notification scheduling/cancellation is part of the same uncommitted unit of work.

- [ ] **Step 6: Implement lifecycle transitions**

`depart_current_stop`, `extend_current_stop_wait`, and `terminate_at_current_stop` must accept explicit `now` for deterministic tests, lock the current stop/wait state, finalize intervals using Task 1 math, set `TripStop.paid_wait_started_at = state.free_wait_ends_at` on the first consequential mutation that observes `billable_seconds > 0` (otherwise leave it `NULL`), emit privacy-safe events with the effective paid boundary where relevant, mutate outbox state through Task 4 helpers, and never call `db.commit()`.

- [ ] **Step 7: Run service tests and Batch 8 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_location tests.test_trip_stop_waiting tests.test_notification_outbox tests.test_pickup_location -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add app/services/trip_stop_location.py app/services/trip_stop_waiting.py tests/test_trip_stop_location.py tests/test_trip_stop_waiting.py
git commit -m "feat: add intermediate stop execution service"
```

---

### Task 6: Add authenticated current-stop APIs

**Files:**
- Create: `backend/app/schemas/trip_stops.py`
- Create: `backend/app/api/routes/trip_stops.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_trip_stop_api.py`

**Interfaces:**
- Consumes Task 5 services and existing `require_roles` / `execute_idempotently`.
- Produces endpoints:

```text
POST /api/v1/trips/{trip_id}/stops/current/location
GET  /api/v1/trips/{trip_id}/stops/current
POST /api/v1/trips/{trip_id}/stops/current/depart
POST /api/v1/trips/{trip_id}/stops/current/extend-wait
POST /api/v1/trips/{trip_id}/stops/current/end-trip
```

- [ ] **Step 1: Write failing OpenAPI contract tests**

Assert all five paths exist, all are OAuth2 protected, write endpoints are POST, read is GET, location has a request body, and consequential actions document 200 responses.

- [ ] **Step 2: Write failing authorization/state tests**

Cover:

- active driver may write;
- owning rider may GET but cannot write;
- unrelated rider/driver receives 403;
- stale/rematched driver receives 403/409 and cannot mutate;
- trip not `in_progress` returns 409;
- no current intermediate stop returns 404 for stop operations/read;
- no-intermediate-stop trip can still use existing trip completion behavior unchanged.

- [ ] **Step 3: Write failing idempotency/race tests**

Cover:

- same depart key replays without duplicate event/outbox;
- same extend key replays one extension;
- different key at already-consumed extension boundary returns 409;
- same end-trip key replays termination;
- Continue vs End Trip first-success state prevents the other from becoming authoritative;
- duplicate extension attempts create one authoritative extension.

Mock transaction interleaving only at service boundaries where unit tests cannot create true PostgreSQL concurrency; add a database-backed sequential-lock test if the existing test harness supports it.

- [ ] **Step 4: Write failing privacy/read tests**

Assert route responses, `TripEvent.event_data`, and `NotificationOutbox.payload` do not expose driver `latitude` or `longitude`. Assert GET returns current waiting phase, billable seconds, gross wait charge, authorized-until/exit-right fields, stop sequence, and role-safe itinerary metadata.

- [ ] **Step 5: Run API tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_api -v
```

Expected: FAIL because schemas/routes are missing.

- [ ] **Step 6: Implement schemas**

Create:

```python
class CurrentStopLocationRequest(BaseModel): ...
class CurrentStopLocationResponse(BaseModel): ...
class CurrentStopStateResponse(BaseModel): ...
class StopActionResponse(BaseModel): ...
```

Use the same sample fields and validation ranges as Batch 8 location input. Current-stop responses expose server-derived state only.

- [ ] **Step 7: Implement route authorization helpers**

In `trip_stops.py`, lock trip and active assignment for writes, verify the active assigned driver, and for GET permit `require_roles("rider", "driver")` followed by ownership/active-assignment checks.

- [ ] **Step 8: Implement the five routes**

- Location route: sample-level replay/conflict protection through Task 5; commit once.
- GET route: calculate live snapshot from authoritative state without mutation.
- Depart/extend/end routes: require `Idempotency-Key`, call `execute_idempotently`, commit once, and map service errors to 403/404/409/422 according to the spec.

- [ ] **Step 9: Register the router**

Include `trip_stops.router` in `app/api/router.py` with tag `Trip Stops`.

- [ ] **Step 10: Run API and regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_api tests.test_trip_stop_location tests.test_trip_stop_waiting tests.test_trip_state tests.test_pickup_location tests.test_ride_cancellation -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```powershell
git add app/schemas/trip_stops.py app/api/routes/trip_stops.py app/api/router.py tests/test_trip_stop_api.py
git commit -m "feat: add current intermediate stop API"
```

---

### Task 7: Final integration, privacy, migration, and repository gates

**Files:**
- Modify only files required by failures discovered in this task; do not broaden scope.
- Test: complete `backend/tests` suite.

**Interfaces:**
- Consumes all Batch 9 tasks.
- Produces a release-ready Batch 9 branch/tree with no additional feature scope.

- [ ] **Step 1: Run the focused Batch 9 suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trip_stop_models tests.test_location_verification tests.test_notification_outbox tests.test_trip_stop_location tests.test_trip_stop_waiting tests.test_trip_stop_api -v
```

Expected: all Batch 9 tests pass.

- [ ] **Step 2: Run the complete backend suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Expected: zero failures and zero errors.

- [ ] **Step 3: Verify migration head**

Run:

```powershell
.\.venv\Scripts\python.exe -m alembic current
```

Expected: `d7a91c4f2e60 (head)`.

- [ ] **Step 4: Verify OpenAPI directly**

Use `app.openapi()` to assert all five Batch 9 paths, OAuth2 security, request bodies, and 200 responses are present.

- [ ] **Step 5: Verify privacy invariant from code/test fixtures**

Search the Batch 9 event/outbox construction paths and assert tests cover that no raw transient driver `latitude`/`longitude` is serialized into durable event/outbox payloads.

- [ ] **Step 6: Check diffs**

Run:

```powershell
git diff --check
git status --short --untracked-files=all
```

Expected: no whitespace errors and only intentional Batch 9 files.

- [ ] **Step 7: Review staged set before final commit**

Stage only approved Batch 9 files; run:

```powershell
git diff --cached --check
git status --short
```

Expected: clean staged diff.

- [ ] **Step 8: Run the full backend suite once more on the staged tree**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Expected: zero failures and zero errors.

- [ ] **Step 9: Final implementation commit**

```powershell
git commit -m "feat: add planned stop execution and waiting"
```

Push only after confirming the commit succeeded and repository policy/workflow permits the selected integration method.

---

## Plan Self-Review

- **Spec coverage:** Every approved design area is assigned: market policy/meter (Task 1), B+ reuse (Task 2), persistence (Task 3), rider warnings/outbox (Task 4), stop sequencing/arrival/wait/termination (Task 5), API/auth/idempotency/read model (Task 6), and full verification/privacy/migration gates (Task 7).
- **Scope boundary:** No post-match itinerary mutation, financial settlement, production push provider, Marketplace Integrity scoring, destination waiting, or destination-arrival verification is introduced.
- **Type consistency:** Tasks consistently use `TripStopLocationVerificationState`, `TripStopWaitState`, `NotificationOutbox`, `LocationSample`, `StopLocationResult`, `StopActionResult`, and `WaitMeterSnapshot`.
- **Review Focus coverage:** Exact boundaries and delayed-gap billing are in Task 5; no-stop behavior and stale driver API behavior are in Task 6; outbox dedupe/cancellation is in Tasks 3–4.
- **Proportion:** The plan specifies interfaces, test assertions, commands, and architectural decisions without transcribing full implementation bodies.
