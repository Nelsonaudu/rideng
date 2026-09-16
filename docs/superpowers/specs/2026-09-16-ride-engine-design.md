# RideNG Abuja MVP Ride Engine Design

**Status:** Approved Design
**Date:** 2026-09-16
**Initial Market:** Abuja, Nigeria

## 1. Purpose

This document defines the RideNG Abuja MVP architecture for:

- rider ride requests;
- Quick Ride;
- negotiated rides;
- fare calculation;
- progressive driver matching;
- driver offers and counteroffers;
- atomic driver assignment;
- trip lifecycle;
- cancellation and no-show handling;
- trip-start PIN verification;
- planned and added stops;
- waiting charges;
- payments and driver settlement;
- live location and dispatch;
- rider/driver communication;
- ratings and reputation;
- active-trip safety.

The initial MVP supports on-demand rides only.

Scheduled rides, hourly bookings, pooling, corporate accounts, recurring rides, and fleet dispatch are deferred.

---

## 2. Core Product Modes

RideNG provides two rider booking modes.

### Quick Ride

Quick Ride prioritizes speed and simplicity.

Characteristics:

- RideNG calculates the fare.
- Fare includes a priority premium.
- Quick Ride is intentionally priced above the recommended negotiation band.
- Drivers receive the request through progressive small-batch dispatch.
- Driver response window is 10 seconds.
- First valid driver acceptance that commits successfully wins.
- Search expands immediately when a batch produces no valid acceptance.
- Part of the priority premium may fund higher driver compensation for more difficult pickups.

Quick Ride does not guarantee a pickup time.

It provides priority matching.

### Make an Offer

Negotiation prioritizes price flexibility and rider choice.

Characteristics:

- RideNG calculates:
  - hard minimum fare;
  - recommended fare;
  - maximum permitted counteroffer.
- Rider proposes a fare within server-defined limits.
- Drivers may:
  - accept;
  - counteroffer once;
  - decline;
  - allow the offer to expire.
- Driver response window is 25 seconds.
- Rider selection window is 30 seconds.
- Rider chooses the final valid driver/offer.
- Negotiation is limited to one rider offer plus at most one counteroffer per driver.

There is no endless bargaining loop.

---

## 3. Pricing Architecture

RideNG uses a server-controlled pricing engine.

Conceptually:

    base fare
    + passenger trip distance
    + estimated trip time
    + pickup allowance
    + demand adjustment
    + product-specific adjustments
    = fare

The pricing engine may calculate:

    minimum_allowed_fare
    recommended_fare
    quick_ride_fare
    maximum_counteroffer

Quick Ride normally sits above the recommended negotiation band.

A negotiation counteroffer may exceed the Quick Ride fare in exceptional circumstances, but never exceed the server-defined maximum.

The rider and driver cannot bypass fare boundaries supplied by the backend.

---

## 4. Priority Pricing

Quick Ride represents a time-priority product.

The priority premium may support:

- higher driver earnings;
- stronger dispatch priority;
- faster batch expansion;
- compensation for progressively longer pickups.

The premium must not merely become an undisclosed platform surcharge.

Driver economics should benefit meaningfully from the product.

Priority pricing must remain configurable by market and should not be permanently hard-coded as one percentage.

---

## 5. Progressive Driver Search

RideNG uses progressive matching.

The system begins with the strongest nearby eligible candidates and expands search if necessary.

Pickup ETA is the main expansion/ranking concept rather than straight-line distance alone.

Example search progression:

    Stage 1: very short pickup ETA
    Stage 2: moderate pickup ETA
    Stage 3: longer pickup ETA
    Stage 4: extended pickup search

Exact thresholds are policy configuration.

Eligible candidates must satisfy all required conditions, including:

- user/driver account active;
- driver online;
- fresh live-location heartbeat;
- driver compliance valid;
- vehicle ride eligible;
- vehicle inspection valid;
- no existing conflicting assignment;
- not blocked from matching with the rider;
- within current dispatch geography.

---

## 6. Progressive Search and Fare Effects

Normal search expansion must not repeatedly change the rider's displayed Quick Ride fare.

During ordinary progressive expansion:

- rider fare remains locked;
- RideNG may allocate more of the existing priority/pickup buffer to driver compensation.

When search enters an extended long-pickup range and existing economics are no longer reasonable:

- RideNG may calculate a revised Quick Ride fare;
- the rider must explicitly approve the revised price;
- no silent price increase is allowed.

For negotiated rides:

- rider offer never increases automatically;
- farther drivers may express additional pickup cost using their single allowed counteroffer.

---

## 7. Dispatch Batches

RideNG uses ranked small-batch broadcast rather than broadcasting every request to the entire marketplace.

Initial behavior:

- start with approximately 3 highly ranked eligible drivers;
- expand to subsequent groups when necessary.

Exact batch sizes must remain configurable.

### Quick Ride

    batch offered
        ↓
    10-second acceptance window
        ↓
    first valid atomic acceptance wins
        ↓
    no acceptance
        ↓
    next batch

### Negotiation

    batch offered
        ↓
    25-second response period
        ↓
    accept / counter / decline
        ↓
    rider receives valid responses
        ↓
    30-second selection period

If no useful responses exist, search expands.

Expired responses can no longer win the ride.

---

## 8. Atomic Assignment

Redis may coordinate dispatch quickly, but PostgreSQL is the final authority for assignments.

When multiple drivers attempt to accept simultaneously:

    multiple acceptance requests
        ↓
    PostgreSQL transaction / locking
        ↓
    exactly one valid active assignment
        ↓
    winner receives matched state
    others receive ride unavailable/conflict

RideNG must enforce:

- one authoritative active assignment per ride request;
- driver still available;
- ride still assignable;
- vehicle still ride eligible;
- offer still valid where applicable.

Assignment history must never be overwritten during rematching.

---

## 9. Idempotency

Consequential operations must support idempotent execution.

Examples include:

- accept ride;
- select negotiated offer;
- cancel ride;
- mark arrival;
- verify trip PIN;
- start trip;
- complete trip;
- capture payment.

Network retries or duplicate taps must not create:

- duplicate assignments;
- duplicate trips;
- duplicate payment capture;
- duplicate cancellations;
- duplicate state transitions.

---

## 10. Marketplace and Trip Data Separation

RideNG separates marketplace negotiation from physical transportation.

Core models:

    RideRequest
    RideOffer
    DriverAssignment
    Trip
    TripStop
    TripEvent
    TripStartVerification

Finance and real-time location remain separate subsystems.

### RideRequest

Represents what the rider requested.

May contain:

- rider;
- ride mode;
- pickup;
- destination;
- planned stops;
- pricing snapshot;
- rider offer;
- payment method;
- request status;
- timestamps.

### RideOffer

Represents one driver opportunity.

May contain:

- ride request;
- driver;
- vehicle;
- rider offer;
- driver counteroffer;
- expiration;
- response status.

Offer statuses may include:

- open;
- accepted;
- countered;
- declined;
- expired;
- selected;
- closed.

### DriverAssignment

Represents authoritative driver assignment history.

If Driver A cancels and Driver B is later assigned, both assignment records remain in history.

---

## 11. Trip State Machine

The physical trip lifecycle is:

    REQUESTED
        ↓
    SEARCHING
        ↓
    MATCHED
        ↓
    DRIVER_ARRIVING
        ↓
    DRIVER_ARRIVED
        ↓
    IN_PROGRESS
        ↓
    COMPLETED

Relevant terminal or exceptional outcomes include:

- rider cancelled;
- rider no-show;
- no driver found;
- driver cancellation followed by rematching;
- safety/emergency termination where applicable.

A driver cancellation should normally return the request to matching rather than immediately terminating the rider's entire request.

---

## 12. Server-Controlled Transitions

Clients request state transitions.

They do not directly set authoritative ride state.

For example:

    driver requests "Start Trip"
        ↓
    backend validates:
      actor
      assignment
      current state
      eligibility
      PIN verification
      pickup conditions
        ↓
    backend records event
        ↓
    backend transitions state

Invalid transitions must be rejected.

---

## 13. Cancellation Architecture

### Before assignment

Rider cancellation is free.

No cancellation compensation applies.

### After assignment

The rider receives a 2-minute free-cancellation grace period.

After the grace period, a rider cancellation fee may apply only if the driver has genuinely begun progressing toward pickup.

A rider must not be charged when the assigned driver:

- remains unreasonably stationary;
- is moving materially away from pickup;
- has not made reasonable pickup progress;
- is excessively late due to driver-controlled behavior.

### Driver cancellation

Driver cancellation after assignment:

- never charges the rider;
- closes that assignment;
- normally triggers automatic rematching;
- records a structured reason.

A decline before assignment is not a cancellation.

Repeated unjustified post-assignment cancellations may feed reliability enforcement.

---

## 14. Cancellation Compensation

Cancellation compensation may eventually use:

    maximum(
        configured base cancellation compensation,
        eligible pickup commitment compensation
    )

subject to a market-defined cap.

The MVP may begin with simpler configurable policy while preserving the architecture for future pickup-time/distance compensation.

Drivers must never chase riders directly for platform cancellation fees.

---

## 15. Arrival and Rider No-Show

A driver cannot authoritatively mark arrival from an arbitrary location.

RideNG validates:

- active assignment;
- proximity to pickup;
- location confidence.

When arrival is validated:

    DRIVER_ARRIVED
        ↓
    5-minute free waiting period
        ↓
    rider boards
      OR
    rider no-show becomes available

A valid rider no-show may generate driver compensation.

Fake or remote arrival claims must not qualify.

---

## 16. Mandatory Trip PIN

Every Abuja MVP passenger trip requires a 4-digit trip-start PIN.

The PIN is generated only after authoritative driver assignment.

The PIN must be:

- random;
- single-trip;
- short-lived;
- securely stored as a verifier/hash rather than raw plaintext where practical;
- invalidated by cancellation;
- invalidated after successful use;
- invalidated when assignment changes.

When rematching occurs, a new assignment receives a new PIN.

### Verification

The transition:

    DRIVER_ARRIVED → IN_PROGRESS

requires backend verification of:

- correct trip;
- correct active assignment;
- correct PIN;
- pickup-location requirements;
- current trip state.

Three incorrect attempts trigger a temporary verification lock/recovery path.

Drivers have no unrestricted "Start Anyway" override.

---

## 17. Fare Locking

RideNG primarily uses locked upfront pricing.

### Quick Ride

The matched Quick Ride fare becomes the trip's base agreed fare.

### Negotiated Ride

The rider-selected negotiated amount becomes the trip's base agreed fare.

Normal traffic or ordinary route variation does not silently increase the fare.

Material rider-requested changes may trigger backend recalculation.

Examples:

- added stop;
- changed destination;
- materially extended requested itinerary;
- extended stop waiting;
- toll/parking or other disclosed exceptional charges.

Whenever practical, significant changes require rider confirmation before becoming binding.

---

## 18. Planned Stops

RideNG Abuja MVP supports up to 4 planned intermediate stops.

Therefore an itinerary may be:

    Pickup
      ↓
    Stop 1
      ↓
    Stop 2
      ↓
    Stop 3
      ↓
    Stop 4
      ↓
    Final destination

Stops entered before the ride request are part of:

- routing;
- fare calculation;
- duration estimate;
- driver earnings;
- driver pre-acceptance disclosure.

They are not surprise modifications.

---

## 19. Stops Added After Matching

A new stop requested after matching requires:

    rider requests stop
        ↓
    backend recalculates route and fare
        ↓
    driver sees change
        ↓
    driver agrees
        ↓
    rider confirms revised fare
        ↓
    stop becomes authoritative

Neither party should be forced into a materially changed itinerary without consent.

Removing a stop should also trigger appropriate backend recalculation.

---

## 20. Intermediate Stop Waiting

Each intermediate stop receives:

- first 3 minutes free;
- paid waiting after minute 3.

At 10 minutes:

- the driver gains the right to stop waiting;
- 10 minutes is not an automatic trip cutoff.

The driver may voluntarily continue waiting.

Continued waiting occurs in renewable 5-minute extensions.

Paid waiting continues during extensions.

The rider is notified that additional paid waiting is accumulating.

---

## 21. Payment Architecture

Abuja MVP supports:

- cash;
- in-app electronic payment through an approved payment service provider.

A stored-value RideNG wallet is deferred.

RideNG must not store raw card data.

Payment providers should supply secure payment tokens/authorizations.

The payment method is chosen before the request and becomes locked after authoritative matching.

The driver sees the payment type before accepting.

---

## 22. Cash Ride Accounting

For cash trips:

    trip completes
        ↓
    rider pays driver cash
        ↓
    driver physically retains cash
        ↓
    RideNG records gross fare
        ↓
    platform commission recorded against driver balance

Cancellation/no-show platform charges owed by a cash rider should become an outstanding RideNG balance rather than requiring roadside collection by the driver.

---

## 23. Financial Ledger

RideNG requires an internal financial ledger from the beginning.

Ledger accounting is separate from offering users a stored-value wallet.

The ledger should support:

- gross fare;
- driver earnings;
- platform commission;
- waiting adjustments;
- cancellation compensation;
- refunds;
- bonuses;
- electronic payment capture;
- cash collected by driver;
- driver payout;
- rider outstanding balance.

Standard driver payout may initially be weekly.

Future early payout may be added later.

---

## 24. Live Location Architecture

RideNG uses:

    PostgreSQL/PostGIS
    +
    Redis

### Redis

Redis contains ephemeral marketplace state such as:

- current driver location;
- last heartbeat;
- online state;
- dispatch availability;
- active assignment;
- vehicle used for dispatch.

Redis answers:

> Where is an available driver now?

### PostgreSQL/PostGIS

PostgreSQL is the durable source of truth for:

- important trip locations;
- assignment location;
- arrival location;
- pickup;
- destination;
- stops;
- active-trip location history;
- audit/safety reconstruction.

It answers:

> What happened during this ride?

---

## 25. Driver Location Heartbeats

Online moving drivers should initially send live-location updates approximately every 5–10 seconds.

Frequency should become adaptive based on:

- movement;
- active assignment;
- active trip;
- device/network conditions.

Stationary drivers may update less frequently.

A stale heartbeat removes the driver from active dispatch eligibility.

Idle-driver heartbeat history should not be retained indefinitely by default.

Active-trip location history should be durably retained according to RideNG privacy and retention policy.

---

## 26. Driver Information Before Acceptance

RideNG uses progressive disclosure.

Before acceptance, a driver may see:

- approximate pickup area;
- pickup ETA/distance;
- destination area;
- estimated trip distance;
- estimated duration;
- number of planned stops;
- payment method;
- Quick Ride driver earnings;
- or negotiation offer/counter range;
- rider aggregate reputation where policy permits.

The driver should not receive before assignment:

- exact home/pickup address;
- rider phone number;
- rider email;
- unnecessary identifying information.

---

## 27. Post-Assignment Disclosure

After atomic assignment, the driver may receive:

- rider first name;
- exact pickup pin;
- navigation;
- ride-scoped communication.

The rider receives identity information needed for safe vehicle verification, including:

- driver first name;
- driver photo;
- driver rating;
- vehicle make/model/color;
- licence plate;
- arrival ETA.

---

## 28. Communication

Matched riders and drivers receive:

- in-app messaging;
- quick-message shortcuts;
- privacy-preserving relayed/masked voice calling.

Real personal phone numbers should not normally be exposed.

Communication is ride-scoped.

After completion:

- ordinary ride chat closes;
- a controlled contact/support window may remain available for approximately 24 hours for legitimate trip-related needs such as lost items;
- after that, communication proceeds through support relay.

The implementation should use a provider-neutral communications service so telecom vendors can be changed without rewriting the trip engine.

---

## 29. Ratings and Reputation

Ratings apply to completed trips only.

RideNG supports mutual:

    1–5 star rating

Individual ratings are anonymous.

Lower ratings should request structured reason categories.

Ratings are separate from formal safety reports.

New users should appear as:

    New

until enough ratings exist to produce a meaningful aggregate.

RideNG should use a rolling/recent reputation model rather than treating every historical rating equally forever.

---

## 30. Future Match Blocking

After a serious poor experience, users may explicitly choose to prevent future pairing.

A future-match block prevents the dispatch engine from pairing that rider and driver again unless appropriately reversed through support.

The system should not expose the existence of the block unnecessarily to the blocked party.

---

## 31. Reputation Enforcement

One negative review must not automatically cause severe punishment.

Progressive enforcement may include:

    sustained quality decline
        ↓
    feedback/warning
        ↓
    repeated quality problems
        ↓
    review/restriction

Serious safety allegations follow the safety process rather than ordinary star-rating enforcement.

---

## 32. Active-Trip Safety

RideNG MVP safety includes:

- Share Trip;
- persistent Safety/Emergency access;
- structured safety reporting;
- objective trip anomaly detection;
- evidence/location preservation.

Safety access should remain easy to reach during an active trip.

---

## 33. Share Trip

Rider and driver may share a temporary live-trip link with trusted contacts.

The link:

- contains only trip-relevant information;
- does not grant account access;
- expires automatically according to policy.

---

## 34. Emergency and Safety Reporting

Emergency handling is separate from ordinary customer support.

Serious safety categories may include:

- threat or violence;
- sexual misconduct;
- harassment;
- accident;
- identity mismatch;
- wrong vehicle;
- dangerous driving;
- theft/property incident;
- serious vehicle safety concern;
- other immediate safety threats.

Consequential safety decisions require appropriate human oversight.

Future AI systems may assist with fact collection and triage but must not autonomously decide permanent bans, serious incident conclusions, or law-enforcement/regulatory actions.

---

## 35. Trip Anomaly Detection

RideNG may detect objective anomalies such as:

- major route deviation;
- unexpectedly prolonged stop;
- trip continuing unusually long;
- GPS/contact loss during active trip;
- movement continuing after trip completion;
- repeated inability to complete pickup.

A single anomaly does not automatically prove danger.

The system may initiate a discreet check:

    "Is everything okay?"

with options such as:

    I'm okay
    I need help

Serious or repeated signals may escalate.

Safety activation should remain discreet where disclosure to the other party could increase risk.

---

## 36. Trip Events and Auditability

Important marketplace and trip actions should create durable events.

Examples:

- ride requested;
- offer sent;
- offer accepted;
- offer countered;
- offer declined;
- driver assigned;
- assignment cancelled;
- driver started pickup;
- driver arrived;
- PIN verified;
- trip started;
- stop arrived;
- paid waiting started;
- stop departed;
- destination changed;
- rider cancelled;
- driver cancelled;
- rider no-show;
- trip completed;
- safety workflow triggered.

Events should include appropriate:

- actor;
- timestamp;
- request/trip identifiers;
- relevant structured metadata.

Audit history should be append-oriented.

---

## 37. Architecture Boundaries

RideNG separates responsibilities into:

### Marketplace

- RideRequest
- RideOffer
- DriverAssignment
- matching/dispatch

### Transportation

- Trip
- TripStop
- TripEvent

### Security

- TripStartVerification
- assignment/state authorization
- idempotency

### Finance

- pricing
- payment
- ledger
- driver settlement

### Real-Time Marketplace

- Redis location/availability
- dispatch coordination

### Durable Location

- PostgreSQL/PostGIS

### Communications

- messaging
- push
- masked/relayed voice

### Safety

- sharing
- anomaly detection
- incident workflow
- evidence preservation

---

## 38. Abuja MVP Scope

The first RideNG ride engine includes:

- on-demand Quick Ride;
- on-demand Negotiated Ride;
- progressive ETA-based dispatch;
- priority pricing;
- fare negotiation guardrails;
- one driver counteroffer maximum;
- atomic assignment;
- rematching;
- mandatory trip PIN;
- up to 4 intermediate stops;
- stop waiting policy;
- locked upfront pricing;
- cancellation/no-show handling;
- cash and electronic payment;
- internal financial ledger;
- live driver location;
- ratings;
- future-match blocking;
- ride-scoped communications;
- active-trip safety.

---

## 39. Deferred Ride Products

The following are outside the first Abuja MVP ride-engine implementation:

- scheduled/reserved rides;
- recurring rides;
- hourly/errand booking product;
- ride pooling;
- corporate accounts;
- multi-driver fleet dispatch;
- full stored-value rider wallet;
- autonomous AI safety adjudication;
- dynamic ML dispatch optimization.

The architecture should permit these later without redesigning the core marketplace and trip data model.

---

## 40. Implementation Principles

The RideNG ride engine must follow:

- backend-authoritative pricing;
- backend-authoritative state transitions;
- backend-authoritative eligibility;
- atomic assignment;
- idempotent consequential operations;
- least privilege;
- no unrestricted client database control;
- no unrestricted AI control;
- auditable consequential actions;
- privacy by progressive disclosure;
- configurable market policy;
- safe failure modes.

When implementation choices conflict, correctness, safety, auditability, and marketplace integrity take priority over frontend convenience.

---

## 41. Approved Architecture Summary

RideNG Abuja MVP adopts:

    QUICK RIDE
    priority fare
    + 10-second progressive batch matching
    + first valid acceptance wins

    NEGOTIATED RIDE
    guarded rider offer
    + one counteroffer per driver
    + 25-second driver response
    + 30-second rider selection

    BOTH MODES
    progressive ETA search
    + atomic assignment
    + rematching
    + locked upfront fare
    + mandatory trip PIN
    + maximum 4 planned stops
    + controlled paid waiting
    + cancellation/no-show protections
    + cash/electronic payment
    + internal ledger
    + Redis live marketplace state
    + PostgreSQL/PostGIS durable truth
    + privacy-preserving communication
    + ratings and match blocking
    + active-trip safety
    + append-oriented trip events

This specification is the implementation baseline unless a later documented architecture decision explicitly supersedes it.