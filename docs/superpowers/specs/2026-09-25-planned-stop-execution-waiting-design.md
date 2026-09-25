# RideNG Batch 9 Planned Stop Execution and Waiting Design

**Status:** Approved Design  
**Date:** 2026-09-25  
**Initial Market:** Abuja, Nigeria  
**Scope:** Planned intermediate-stop execution and waiting only

## 1. Purpose

Batch 9 makes RideNG's already-created planned intermediate stops operational during an active trip.

It adds:

- ordered execution of planned intermediate stops;
- backend-verified arrival at the current intermediate stop;
- a server-controlled waiting meter;
- 3 minutes of free waiting;
- paid waiting at the approved Abuja launch rate;
- a driver exit right after 10 minutes;
- renewable 5-minute voluntary waiting extensions;
- rider warning and notification scheduling;
- privacy-safe audit events;
- idempotent, concurrency-safe stop actions;
- auditable trip termination when a driver exercises the intermediate-stop waiting exit right.

Batch 9 does **not** add or remove stops after matching. Post-match itinerary changes are deferred to Batch 10.

---

## 2. Product Scope

RideNG already accepts up to four planned intermediate stops before matching. Those stops are part of routing, fare calculation, duration estimates, driver earnings, and pre-acceptance disclosure.

Batch 9 operates only stops that:

- were planned before matching;
- have `stop_type == "intermediate"`;
- belong to the authoritative trip;
- occur while the trip is `in_progress`.

Pickup and final destination remain outside the Batch 9 waiting flow.

The top-level trip state machine remains:

    matched
      ↓
    driver_arriving
      ↓
    driver_arrived
      ↓
    in_progress
      ↓
    completed

Intermediate-stop execution is a subordinate state machine inside `in_progress`. RideNG does not add top-level trip statuses such as `waiting_at_stop`.

---

## 3. Abuja Waiting Policy

The approved Abuja MVP launch policy is:

    free_wait_seconds          = 180
    wait_rate_per_minute       = ₦75.00
    driver_exit_right_seconds  = 600
    extension_seconds          = 300

This means:

- the first 3 minutes at an intermediate stop are free;
- paid waiting begins after the free period;
- the rider-facing rate is ₦75 per paid minute;
- billing is calculated by seconds, not rounded-up whole minutes;
- the driver gains the right to end the trip at 10 minutes;
- the driver may voluntarily continue waiting in explicit 5-minute extensions;
- extensions do not roll over automatically;
- there is no waiting surge multiplier in V1.

The ₦75/minute value is an approved Abuja launch policy derived from the Nigerian market review. It is not represented as a universally published Nigerian industry rate.

The policy must remain server-controlled and configurable by market. Route code must not scatter these values as independent constants.

---

## 4. Policy Snapshotting

Waiting terms are snapshotted when an intermediate-stop arrival becomes authoritative.

If RideNG changes Abuja waiting policy later, a stop already underway continues under the policy shown for that stop.

Each stop wait state therefore records the effective policy values, including:

- free-wait seconds;
- waiting rate per minute;
- driver exit-right seconds;
- extension seconds.

A policy change cannot silently alter an active stop.

---

## 5. Stop Execution State Machine

Planned intermediate stops execute strictly by sequence.

Example:

    Pickup
      ↓
    Stop 1
      ↓
    Stop 2
      ↓
    Stop 3
      ↓
    Destination

The authoritative current intermediate stop is the lowest-sequence planned intermediate stop for the trip that has not departed.

Rules:

- the client does not choose an arbitrary stop to operate;
- Stop 2 cannot be operated while Stop 1 remains incomplete;
- an already-departed stop cannot reopen;
- a late request for a previous stop cannot mutate the current stop;
- after the final intermediate stop departs, there is no current intermediate stop and the trip continues toward destination;
- destination completion remains governed by the existing trip `/complete` transition.

The API uses a server-resolved `current` stop concept rather than accepting arbitrary stop identifiers for consequential actions.

---

## 6. Intermediate-Stop Arrival Verification

A driver tap alone cannot start an intermediate-stop waiting clock.

Because verified arrival can lead to rider charges, RideNG requires backend-verified physical presence at the authoritative current stop.

### 6.1 Shared verification principles

Batch 9 reuses the proven Batch 8 anti-spoofing principles through reusable internal location-verification logic.

Pickup verification and intermediate-stop verification may share validation algorithms, but they do not share one mutable persistence row.

For V1, intermediate-stop arrival uses the same conservative B+ policy:

    maximum horizontal accuracy     50 m
    arrival envelope                100 m
    maximum sample age              15 s
    future skew tolerance           5 s
    required confirmation samples   2
    sample separation               3–10 s
    mocked location                 rejected
    implausible movement            rejected

Arrival qualification remains uncertainty-aware:

    distance_to_stop + horizontal_accuracy <= arrival_radius

A single location sample is insufficient.

### 6.2 Assignment and stop scope

Verification is valid only for:

- the active assignment;
- the active driver;
- the authoritative trip;
- the authoritative current intermediate stop.

Evidence from:

- a previous assignment;
- a previous stop;
- a future stop;
- a stale trip state

cannot authorize waiting.

### 6.3 Server-authoritative arrival time

The device `captured_at` timestamp is validation input only.

When the B+ rule succeeds, RideNG sets the authoritative stop arrival time from server time.

That server-accepted time becomes the origin for:

- the free-wait period;
- the paid-wait boundary;
- the driver's exit-right boundary;
- the rider warning schedule.

A client cannot manipulate the waiting clock by changing its device clock.

---

## 7. TripStopLocationVerificationState

Batch 9 introduces bounded rolling location state for each intermediate stop.

Conceptually:

    TripStopLocationVerificationState

    stop_id                     one per stop
    trip_id
    assignment_id

    last_sample_id
    last_latitude
    last_longitude
    last_horizontal_accuracy_m
    last_distance_to_stop_m
    last_sample_captured_at
    last_sample_received_at

    arrival_candidate_count
    last_arrival_candidate_at
    arrival_verified_at

    created_at
    updated_at

This state is not an append-only GPS history.

It stores only the bounded evidence required to verify arrival.

After arrival is verified and the durable outcome is recorded, exact transient driver coordinates are redacted. The verification outcome may remain.

Raw transient driver latitude/longitude must not be copied into `TripEvent` or notification payloads.

---

## 8. Atomic Arrival Activation

When the current intermediate-stop arrival becomes verified, one database transaction must:

1. confirm the active assignment and trip state;
2. confirm that the stop is still the authoritative current intermediate stop;
3. set `TripStop.arrived_at` from server time;
4. set the location verification outcome;
5. create `TripStopWaitState` with the policy snapshot;
6. create privacy-safe audit data;
7. create the rider notification intents for the waiting timeline;
8. redact transient verification coordinates where appropriate;
9. commit atomically.

RideNG must not commit a verified stop arrival without its waiting state and notification schedule.

---

## 9. TripStopWaitState

Waiting policy and meter state live in a dedicated one-to-one operational record rather than overloading `TripStop`.

Conceptually:

    TripStopWaitState

    stop_id                     one per TripStop
    trip_id
    assignment_id

    free_wait_seconds
    wait_rate_per_minute
    driver_exit_right_seconds
    extension_seconds

    arrived_at
    free_wait_ends_at
    driver_exit_right_at

    current_paid_window_started_at
    authorized_until
    accrued_billable_seconds

    extension_count
    final_billable_seconds
    final_wait_charge

    closed_at
    close_reason

    created_at
    updated_at

`TripStop` remains the itinerary/execution record.

`TripStopWaitState` remains the authoritative waiting policy and meter record.

`TripEvent` remains the append-only audit trail.

---

## 10. Waiting Meter Semantics

### 10.1 Initial window

At authoritative arrival:

    00:00–03:00   free
    03:00–10:00   authorized paid waiting
    10:00          driver exit right available

The maximum initial paid interval is 7 minutes.

At ₦75/minute:

    7 minutes × ₦75 = ₦525

### 10.2 Second-based billing

Internally:

    gross_wait_charge
      =
    billable_seconds
      ×
    wait_rate_per_minute / 60

Examples:

    90 billable seconds
      = 1.5 minutes
      = ₦112.50

    120 billable seconds
      = 2 minutes
      = ₦150.00

The implementation uses decimal arithmetic appropriate for currency and produces a two-decimal gross waiting amount.

### 10.3 Interval-derived, not tick-driven

RideNG does not update the database once per second.

The wait state records closed billable time plus at most one authorized open interval.

For an open interval:

    effective_end =
        min(server_now, authorized_until)

    current_interval_seconds =
        max(
            0,
            effective_end - current_paid_window_started_at
        )

    billable_seconds =
        accrued_billable_seconds
        + current_interval_seconds

This makes billing deterministic across process restarts and worker delays.

---

## 11. Authorization Windows and Charge Freezing

Paid waiting accrues only inside explicitly authorized windows.

If the initial paid window ends at 10:00 and the driver takes no action:

    10:00 onward
      time passes
      but no additional waiting charge accrues

The meter freezes automatically at `authorized_until`.

Example:

    arrival                 12:00:00
    free wait ends          12:03:00
    initial window ends     12:10:00
    driver does nothing     until 12:20:00

    billable time           12:03–12:10
                            = 420 seconds

    gross waiting charge    = ₦525

There is no retroactive billing for a gap after an authorization window expires.

---

## 12. Driver Actions

After verified arrival, the driver may use consequential stop actions.

### 12.1 Continue Trip

`Continue Trip` is valid any time after verified stop arrival.

It:

- finalizes the waiting meter through server time, capped by the current authorization window;
- marks the current stop departed with server time;
- closes the wait state;
- cancels future pending warning intents for that stop;
- creates the final stop waiting outcome event;
- makes the next intermediate stop authoritative, if one exists.

Examples:

    depart at 00:40
      → billable 0
      → charge ₦0

    depart at 05:00
      → 3 minutes free
      → 2 minutes billable
      → charge ₦150

### 12.2 Keep Waiting 5 More Minutes

An extension becomes available only at a valid waiting decision boundary.

The extension:

- is exactly 300 seconds;
- starts when the server accepts the extension;
- creates a new authorized paid interval;
- increments `extension_count`;
- creates new rider notification intents;
- is idempotent.

There is no automatic rollover.

If the prior window ended at 10:00 and the driver extends at 10:20:

    10:00–10:20   not billable
    10:20–15:20   newly authorized paid window

The gap is never back-billed.

Extensions are renewable. Batch 9 does not impose a hard extension-count cap.

### 12.3 End Trip At This Stop

The driver gains the exit right at the initial 10-minute threshold.

Once that right exists, the driver may terminate at any later time, including during a voluntary extension.

The driver does not need rider approval to exercise this right.

The driver UI should require a confirmation step before the termination request is submitted.

---

## 13. Intermediate-Stop Trip Termination

Ending the trip because of excessive intermediate-stop waiting is not modeled as rider cancellation or driver cancellation.

It is an auditable trip termination.

The authoritative reason is:

    intermediate_stop_wait_timeout

The operation must:

1. verify the active driver and active assignment;
2. verify the trip is `in_progress`;
3. verify the current stop has a backend-verified arrival;
4. verify the initial 10-minute exit right has been earned;
5. finalize billable time only inside authorized windows;
6. close the wait state;
7. close the current stop;
8. set `Trip.status = "terminated"`;
9. clear/close the active assignment as required by trip termination policy;
10. cancel pending warning intents;
11. create structured audit events;
12. commit atomically.

No later stop becomes active.

### 13.1 Partial-trip fare settlement

Batch 9 does **not** determine the final partial-trip base fare after termination.

It records ledger-ready facts:

- original agreed fare;
- completed stop sequence;
- termination stop;
- billable waiting seconds;
- gross waiting charge;
- extension count;
- termination time;
- termination reason.

The future financial-ledger batch determines final fare settlement, driver earnings, commission, refunds, cash accounting, and payout.

---

## 14. Rider Warning Cadence

Rider warnings are part of the authoritative Batch 9 behavior.

For each intermediate stop:

    00:00  Arrival notice
           "Your driver has arrived.
            You have 3 minutes of free waiting."

    02:00  Free-wait warning
           "1 minute of free waiting remains.
            After that, waiting costs ₦75/min."

    03:00  Paid-wait notice
           "Paid waiting has started at ₦75/min."

    08:00  Exit-right warning
           "Your driver may end the trip
            at this stop in 2 minutes."

    09:00  Final warning
           "1 minute remains before your
            driver may end the trip."

    10:00  Exit-right notice
           "Your driver may now end the trip
            here or choose to continue waiting."

When the driver accepts a five-minute extension:

- the rider receives an immediate extension notice;
- the rider receives a one-minute-remaining extension warning;
- the rider receives an extension-boundary notice when the new decision point is reached.

When the stop closes, the rider receives immediate confirmation of the final stop waiting charge.

---

## 15. Live Rider and Driver State

Push notifications are supplementary.

The authoritative rider/driver screen derives from server state.

The rider may see:

    Stop 2 of 3

    Waiting time         6:42
    Free waiting         3:00
    Paid waiting         3:42
    Current wait charge  ₦277.50

    Driver exit right    in 3:18

The displayed timer may update locally between refreshes, but the backend remains authoritative for:

- current phase;
- billable seconds;
- gross wait charge;
- exit-right availability;
- extension availability;
- stop closure.

When a stop departs:

Driver:

    "Stop completed — continue to Stop 3."

Rider:

    "Waiting ended.
     Final Stop 2 waiting charge: ₦277.50."

---

## 16. Notification Outbox

Batch 9 introduces a transactional notification outbox.

The stop/waiting engine creates and cancels notification intents.

Delivery transport is separate from trip-state correctness.

Conceptually:

    NotificationOutbox

    id
    user_id
    trip_id
    stop_id

    notification_type
    dedupe_key
    scheduled_for
    payload

    status
      pending
      delivered
      cancelled
      failed

    created_at
    delivered_at
    cancelled_at

A unique dedupe key should make scheduling idempotent, including extension-generation identifiers where the same notification type can occur more than once.

### 16.1 Transactional scheduling

Stop-arrival activation creates the initial warning schedule in the same transaction as the authoritative stop arrival and wait state.

Stop departure, termination, or extension updates the relevant pending intents in the same transaction as the stop-state mutation.

For example, departure at 7:13 atomically:

- finalizes the waiting amount;
- marks the stop departed;
- cancels pending 8/9/10-minute warnings;
- schedules an immediate "waiting ended" notice;
- creates the audit event.

### 16.2 Delivery failure

Notification delivery failure does not change:

- trip state;
- stop state;
- billable seconds;
- waiting charge;
- exit-right timing.

The rider's liability is determined by the agreed policy and authoritative stop state, not by third-party push-provider success.

Delivery status remains useful operational evidence.

---

## 17. API Shape

Batch 9 uses server-resolved current-stop endpoints:

    POST /trips/{trip_id}/stops/current/location
    GET  /trips/{trip_id}/stops/current
    POST /trips/{trip_id}/stops/current/depart
    POST /trips/{trip_id}/stops/current/extend-wait
    POST /trips/{trip_id}/stops/current/end-trip

The write endpoints are driver-authorized.

The current-stop read endpoint may be exposed to the active driver and owning rider with role-appropriate response data.

The client does not supply an arbitrary stop ID for consequential current-stop actions.

### 17.1 Idempotency

The following require `Idempotency-Key`:

- depart;
- extend wait;
- end trip at stop.

Location observations use sample-level replay/conflict protection analogous to Batch 8.

---

## 18. Authorization and Validation Order

Every consequential stop write validates:

    authenticated user
      ↓
    active assignment
      ↓
    actor is active assigned driver
      ↓
    trip.status == in_progress
      ↓
    authoritative current intermediate stop
      ↓
    requested action valid for current state/time
      ↓
    row locks / transaction
      ↓
    state + events + outbox mutation
      ↓
    commit

Stale or replaced drivers cannot manipulate the stop.

---

## 19. Concurrency Model

Consequential actions serialize through database row locks.

The implementation locks the relevant:

- trip;
- assignment where needed;
- current `TripStop`;
- `TripStopWaitState`.

Mutually exclusive operations use first-valid-commit-wins semantics.

### 19.1 Continue vs End Trip

If `Continue Trip` commits first:

- the stop is departed;
- a simultaneous termination request sees closed state and fails.

If `End Trip` commits first:

- the trip becomes terminal;
- a simultaneous continue request fails.

Both cannot become authoritative.

### 19.2 Duplicate extensions

Two requests cannot stack two five-minute extensions from one decision boundary.

Behavior:

- same idempotency key → replay the same successful result;
- different key at the same already-consumed boundary → conflict;
- a new extension becomes available only at the next valid decision boundary.

---

## 20. Database Invariants

The database should enforce important invariants in addition to application validation.

At minimum:

- one `TripStopWaitState` per `TripStop`;
- one `TripStopLocationVerificationState` per `TripStop`;
- `accrued_billable_seconds >= 0`;
- `extension_count >= 0`;
- `wait_rate_per_minute >= 0`;
- an active paid interval cannot have `authorized_until` before its start;
- closed waiting state cannot remain an active open paid interval;
- notification `dedupe_key` uniqueness for idempotent scheduling.

Foreign keys should preserve trip/stop/assignment ownership and appropriate cascade behavior.

---

## 21. Error Semantics

Expected API classes:

### 404

Use when the requested trip/current intermediate stop does not exist for the operation.

### 403

Use when the authenticated user is not permitted to perform the action, including a driver who is not the active assigned driver.

### 409

Use for authoritative-state conflicts, including:

- trip not in progress;
- stop already departed;
- stop already closed;
- extension requested before a valid decision boundary;
- decision boundary already consumed;
- trip already terminated;
- stale assignment;
- reused idempotency key with conflicting input.

### 422

Use for invalid location observations, including:

- mocked location;
- stale sample;
- unacceptable accuracy;
- implausible movement;
- otherwise invalid location evidence.

Rejected actions do not create authoritative `TripEvent` entries.

Operational/security logging may separately record rejected attempts.

---

## 22. Privacy

Batch 9 follows the privacy principle established in Batch 8.

Durable stop audit events may contain:

- stop ID;
- stop sequence;
- assignment ID;
- verification method;
- distance-to-stop outcome;
- server timestamps;
- billable seconds;
- gross waiting charge;
- extension count;
- termination reason.

They must not contain the driver's raw transient latitude/longitude samples.

Notification payloads must also avoid raw driver GPS coordinates.

---

## 23. Audit Events

Expected durable events include, as appropriate:

- `intermediate_stop_arrived`;
- `paid_waiting_started` or an equivalent effective waiting-start audit fact;
- `intermediate_stop_exit_right_available`;
- `intermediate_stop_wait_extended`;
- `intermediate_stop_departed`;
- `intermediate_stop_wait_ended`;
- `trip_terminated_at_intermediate_stop`.

Where an event is created after its effective boundary rather than exactly at that wall-clock instant, event data should preserve the authoritative effective timestamp.

The final termination event records:

- stop ID;
- stop sequence;
- assignment ID;
- arrived-at time;
- terminated-at time;
- free-wait seconds;
- billable-wait seconds;
- gross wait charge;
- extension count;
- termination reason.

---

## 24. Marketplace Integrity Compatibility

Batch 9 does not implement Marketplace Integrity scoring or punishment.

It emits structured factual events that a later anti-circumvention subsystem can consume.

For example, a later system may correlate:

- repeated intermediate-stop terminations;
- rider reports of off-app continuation;
- cancellation patterns;
- direct-payment solicitation reports.

Batch 9 itself does not infer fraud from a stop termination and does not automatically sanction a driver.

---

## 25. Testing Strategy

Batch 9 uses test-driven development and deterministic server timestamps.

Tests must not depend on real sleeps.

### 25.1 Stop execution

Prove that:

- only an `in_progress` trip can operate an intermediate stop;
- only the active assigned driver can mutate stop state;
- only the current intermediate stop can be operated;
- stops execute strictly by sequence;
- departed stops cannot reopen;
- pickup does not enter intermediate waiting flow;
- destination does not enter intermediate waiting flow.

### 25.2 Location verification

Prove that:

- two valid samples verify arrival;
- one sample does not;
- poor accuracy is rejected;
- stale samples are rejected;
- excessive future skew is rejected;
- mocked samples are rejected;
- implausible movement is rejected;
- out-of-order samples are rejected;
- exact duplicate samples replay safely;
- a reused sample ID with different data conflicts;
- old assignment evidence cannot verify the current driver;
- Stop 1 evidence cannot verify Stop 2.

### 25.3 Waiting mathematics

Prove:

    arrive 12:00:00
    depart 12:02:59
      → billable 0
      → ₦0

    arrive 12:00:00
    depart 12:05:00
      → 120 billable seconds
      → ₦150

    arrive 12:00:00
    no extension
    depart 12:20:00
      → billable capped at 420 seconds
      → ₦525

Freeze-gap test:

    initial paid window
      12:03 → 12:10

    driver extends
      12:11:30

    new window
      12:11:30 → 12:16:30

    12:10 → 12:11:30
      must remain non-billable

Fractional billing:

    90 billable seconds
      → ₦112.50

### 25.4 Extensions

Prove:

- an extension grants exactly 300 seconds;
- no automatic rollover occurs;
- duplicate retry does not grant another extension;
- a different key cannot stack a second extension from the same decision boundary;
- a later valid decision boundary permits another extension.

### 25.5 Rider warnings

Prove the initial schedule:

    arrival        immediate notice
    +2 min         1-minute free warning
    +3 min         paid waiting notice
    +8 min         2-minute exit warning
    +9 min         1-minute exit warning
    +10 min        exit-right notice

Also prove:

- early departure cancels future warnings;
- trip termination cancels future warnings;
- extension creates the correct new notices;
- delivery failure does not mutate billing or trip state;
- final stop closure creates the final waiting-charge notification intent.

### 25.6 Termination

Prove:

- termination is rejected at 9:59;
- termination is available at 10:00;
- rider approval is not required once the exit right exists;
- billing remains capped to authorized windows;
- termination during an extension bills only through the termination time;
- later stops never become current;
- trip becomes `terminated`;
- structured reason is `intermediate_stop_wait_timeout`.

### 25.7 Concurrency and idempotency

Prove:

- Continue vs End Trip produces exactly one authoritative outcome;
- concurrent extension attempts grant one extension only;
- old/rematched driver actions are rejected;
- successful retries replay without duplicate state or events.

### 25.8 Privacy

Prove that raw driver latitude/longitude does not appear in:

- intermediate-stop arrival `TripEvent`;
- waiting `TripEvent`;
- termination `TripEvent`;
- notification-outbox payloads.

### 25.9 Regression

After focused Batch 9 tests, run the complete backend suite before commit.

The final integration gate also includes migration status, diff checks, API/OpenAPI registration checks, and repository status review.

---

## 26. Out of Scope

Batch 9 deliberately excludes:

- post-match stop addition/removal and two-party consent;
- post-match route/fare recalculation;
- final partial-trip base-fare settlement;
- driver commission and payout accounting;
- full production push-provider integration;
- Marketplace Integrity risk scoring/enforcement;
- destination waiting charges;
- destination-arrival verification;
- stored-value wallet behavior.

These belong to later batches.

---

## 27. Batch 10 Boundary

Batch 10 will handle post-match itinerary changes:

    rider requests add/remove stop
      ↓
    backend recalculates route and fare
      ↓
    driver sees and accepts/rejects change
      ↓
    rider confirms revised fare
      ↓
    itinerary mutation becomes authoritative

Batch 9 provides the stop-execution foundation Batch 10 will rely on.

---

## 28. Acceptance Summary

Batch 9 is acceptable when RideNG can demonstrate that:

- planned intermediate stops execute in authoritative sequence;
- waiting cannot begin from a client-only arrival claim;
- physical arrival requires fresh, plausible, multi-sample evidence;
- the first 180 seconds are free;
- paid waiting is ₦75/minute by second;
- paid time never exceeds an authorized window;
- the driver gains an exit right at 10 minutes;
- extensions are explicit, renewable, and exactly 5 minutes;
- no automatic extension or retroactive gap billing occurs;
- rider warnings follow the approved cadence;
- notification scheduling is transactional but delivery failure is non-authoritative;
- consequential actions are idempotent and concurrency-safe;
- stop termination is auditable and does not invent partial-trip settlement;
- raw transient driver GPS does not leak into durable audit/notification payloads;
- existing RideNG behavior remains green under the full backend regression suite.
