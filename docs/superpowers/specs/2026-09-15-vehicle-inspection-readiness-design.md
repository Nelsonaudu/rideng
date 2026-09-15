# RideNG Vehicle Inspection Readiness Design

**Status:** Approved  
**Date:** 2026-09-15  
**Initial Market:** Abuja, Nigeria

## 1. Purpose

This document defines RideNG's vehicle-inspection architecture for the Abuja MVP.

The design follows the practical Nigerian ride-hailing model we researched:

- drivers control when they physically present their vehicle for inspection;
- routine inspections do not require an administrator to schedule an appointment;
- vehicle documents and physical inspection may progress in parallel;
- government roadworthiness documentation and RideNG's own physical inspection are separate compliance requirements;
- final vehicle eligibility is determined by the backend only after all required compliance conditions are satisfied.

The system must remain configurable for future Nigerian markets.

---

## 2. Core Design Principle

An inspection requirement is not the same thing as an inspection record.

RideNG therefore separates:

1. **Inspection readiness / requirement**
2. **Actual physical inspection activity**
3. **Final vehicle ride eligibility**

A `VehicleInspection` database record should represent a real inspection event, not simply an onboarding task that may never occur.

---

## 3. Driver Experience

The normal onboarding flow is:

```text
Vehicle registered
        ↓
Vehicle details/documents submitted
        ↓
RideNG evaluates inspection readiness
        ↓
Driver sees: "Vehicle inspection required"
        ↓
Driver chooses when to visit an approved inspection centre
        ↓
Authorized inspection/compliance staff starts inspection
        ↓
Physical inspection performed
        ↓
passed / failed / reinspection_required
        ↓
RideNG recalculates vehicle compliance
        ↓
Vehicle becomes ride-eligible only when all activation
requirements are satisfied
```

Appointment booking is not required for the Abuja MVP.

A future optional appointment feature may be introduced as a convenience without changing the compliance model.

---

## 4. Inspection Requirement

RideNG should derive whether a vehicle currently requires inspection.

Conceptually:

```text
inspection_required
```

is true when the vehicle does not currently possess a valid RideNG physical inspection.

Examples include:

- newly registered vehicle;
- no prior inspection;
- most recent inspection failed;
- reinspection was required;
- previous passed inspection expired;
- a compliance or safety event invalidated the previous inspection;
- platform policy requires another inspection.

This value must be calculated by backend business logic.

It must not be a manually editable boolean controlled by drivers, administrators, mobile clients, or AI systems.

---

## 5. Inspection Eligibility

RideNG should separately derive whether a vehicle may currently present for inspection.

Conceptually:

```text
inspection_eligible
```

may require:

- vehicle exists;
- vehicle record is active;
- required basic vehicle information is present;
- vehicle is not suspended;
- vehicle is not permanently rejected;
- no compliance or safety block prevents inspection.

Full vehicle-document approval is not required merely to visit the inspection centre.

Vehicle-document verification and physical inspection may therefore progress in parallel.

---

## 6. Government Compliance vs RideNG Inspection

Government/regulatory compliance and RideNG physical inspection are separate requirements.

Government requirements may include:

- vehicle licence;
- insurance;
- roadworthiness certificate;
- hackney/commercial permits where applicable;
- other applicable Nigerian or FCT requirements.

RideNG operational compliance separately includes:

- RideNG physical vehicle inspection.

A government roadworthiness certificate does not automatically replace RideNG's physical inspection.

Passing RideNG's inspection also does not replace legally required government documentation.

---

## 7. Inspection Record Creation

Routine RideNG operations should not require a broad administrator to manually create every inspection.

An actual `VehicleInspection` record should normally be created when the vehicle is physically presented for inspection.

```text
Driver arrives at approved inspection centre
        ↓
Authorized compliance/inspection user locates vehicle
        ↓
Backend verifies inspection eligibility
        ↓
VehicleInspection record created
        ↓
status = pending_inspection
```

The existing admin-only inspection-creation functionality is transitional development functionality.

Administrators may retain controlled override capability for exceptional operational or support cases.

---

## 8. Compliance Role

RideNG should introduce a least-privilege role:

```text
compliance_agent
```

During the startup phase, this role may:

- review driver documents;
- review vehicle documents;
- create/start an inspection when a vehicle is physically presented;
- record physical inspection outcomes.

This role must not automatically receive unrelated system-administration permissions.

As RideNG grows, it may later split into more granular roles such as:

```text
document_reviewer
vehicle_inspector
```

Drivers must never be able to approve their own documents or certify their own vehicle inspection.

---

## 9. Inspection Compliance States

RideNG uses the following compliance states:

```text
pending_inspection
passed
failed
reinspection_required
cancelled
```

Normal transitions include:

```text
pending_inspection ─────► passed
        │
        ├───────────────► failed
        │
        ├───────────────► reinspection_required
        │
        └───────────────► cancelled
```

Operational queue states such as:

```text
checked_in
in_progress
```

are intentionally excluded from the compliance state machine.

If RideNG later needs queue-management telemetry, it should use timestamps, events, or a separate inspection-session/visit model.

---

## 10. Physical Inspection Data

Physical findings belong to the actual inspection-result workflow.

Examples include:

```text
odometer_km
checklist_data
evidence_data
failure_reason
notes
expires_at
```

These fields should not be fabricated when merely determining inspection readiness.

`inspected_at` must be generated by the backend when an actual inspection result is recorded.

The authenticated reviewer/inspector identity must also be assigned by the backend.

---

## 11. API Validation

Compliance APIs must reject unsupported request fields.

Unknown fields should return:

```text
422 Unprocessable Entity
```

rather than being silently discarded.

For example, sending `odometer_km` to an endpoint that does not accept physical inspection findings must fail validation rather than return success while ignoring the field.

This is important for:

- auditability;
- frontend/mobile integration;
- debugging;
- compliance integrity.

---

## 12. Inspection Validity

Inspection validity must be controlled by platform or market policy.

RideNG must not permanently hard-code one universal inspection-validity period.

A passed inspection is considered valid only when:

- the latest applicable inspection result is `passed`;
- it has not expired;
- no later inspection invalidates it;
- no compliance or safety event requires reinspection.

This allows Abuja, Lagos, Port Harcourt, and future markets to use different policies without redesigning the database model.

---

## 13. Vehicle Status vs Ride Eligibility

`Vehicle.is_active` means the vehicle record is enabled.

It does not mean the vehicle is currently permitted to carry RideNG passengers.

Ride eligibility must be derived separately by backend logic.

Conceptually:

```text
ride_eligible =
    vehicle_active
    AND mandatory_vehicle_documents_valid
    AND required_inspection_valid
    AND no_compliance_block
    AND no_safety_block
```

No frontend, driver, inspector, administrator, or AI agent should be able to directly override this calculation.

---

## 14. Final Vehicle Approval

A vehicle may become fully approved for RideNG operation only when all market-required activation conditions are satisfied.

For example:

```text
Vehicle active
+
Required documents approved
+
Required expiring documents still valid
+
RideNG physical inspection passed and valid
+
No safety/compliance suspension
=
Vehicle ride eligible
```

Passing an inspection alone does not equal complete vehicle approval.

---

## 15. Driver Online Eligibility

Driver online eligibility must be calculated separately from vehicle eligibility.

Conceptually, a driver may go online only when:

- driver account is active;
- required identity/licensing compliance is approved and valid;
- driver is not suspended or safety-blocked;
- at least one linked vehicle is ride eligible;
- all other applicable RideNG market requirements pass.

This prevents driver, vehicle, document, and inspection status from being incorrectly collapsed into one field.

---

## 16. Duplicate Inspection Protection

RideNG must prevent multiple open physical-inspection records for the same vehicle when an existing inspection is already pending.

A duplicate attempt should normally return:

```text
409 Conflict
```

unless an authorized exceptional workflow explicitly supersedes the previous inspection.

---

## 17. Failure and Reinspection

A failed inspection must include a meaningful failure reason.

A `reinspection_required` result should preserve enough information for:

- driver communication;
- compliance review;
- future inspector context;
- audit investigation.

RideNG must never silently convert a failed inspection into a passing state.

---

## 18. Audit Requirements

Consequential compliance actions should preserve sufficient audit data.

At minimum:

```text
actor_id
actor_role
target_vehicle_id
inspection_id
previous_status
new_status
timestamp
reason where applicable
```

Document-verification actions should follow the same principle.

Audit records should eventually be append-oriented and difficult to tamper with.

---

## 19. Safety Principles

The inspection subsystem follows these RideNG-wide principles:

- least privilege;
- fail-safe defaults;
- deterministic backend authorization;
- no self-approval;
- server-controlled timestamps;
- preservation of historical inspection records;
- complete action attribution;
- separation of `is_active` from ride eligibility;
- no unrestricted frontend control over compliance;
- no unrestricted AI control over compliance;
- human control for consequential safety/compliance decisions.

Whenever possible, the system should ask:

```text
How can this feature fail?
How can it be abused?
What is the blast radius?
How do we detect the failure?
How do we recover safely?
```

---

## 20. Required Automated Tests

Implementation should cover at least:

1. New eligible vehicle requires inspection.
2. Suspended vehicle is not inspection eligible.
3. Rejected vehicle is not inspection eligible.
4. Vehicle with no valid inspection returns `inspection_required = true`.
5. Vehicle with a valid passed inspection does not currently require inspection.
6. Expired inspection requires another inspection.
7. Failed inspection requires another inspection.
8. `reinspection_required` requires another inspection.
9. Driver cannot create/certify inspection results.
10. Authorized compliance agent can start an inspection.
11. Authorized compliance agent can record an inspection outcome.
12. Duplicate pending inspection is rejected.
13. Unknown create/update fields return `422`.
14. Failed inspection requires a reason.
15. Reinspection-required result requires a reason.
16. Inspector identity is assigned by the server.
17. `inspected_at` is generated by the server.
18. `Vehicle.is_active = true` alone does not make a vehicle ride eligible.
19. Passing inspection alone does not make a vehicle ride eligible.
20. Vehicle becomes ride eligible only when every required activation condition passes.
21. Admin override paths remain permission controlled.
22. Compliance actions remain auditable.

---

## 21. Migration Strategy

Existing vehicle-inspection history must be preserved.

The current development/test inspection associated with Daniel's test vehicle may remain development data, but production logic must not rely on that specific record.

Any schema-changing Alembic migration must be reviewed before execution.

Where practical, migrations should include a safe downgrade path.

---

## 22. Deferred Features

The following are intentionally outside the Abuja MVP inspection architecture:

- mandatory appointment scheduling;
- inspection-centre queue management;
- `checked_in` compliance state;
- `in_progress` compliance state;
- automated computer-vision inspection;
- dedicated inspector mobile application;
- fleet-management inspection workflows;
- AI autonomous inspection certification;
- RideNG Agentic Ops integration.

These may be introduced later without compromising the core compliance model.

---

## 23. Approved Architecture Summary

RideNG adopts:

```text
Driver-controlled walk-in inspection
+
Backend-derived inspection readiness
+
Actual inspection record created upon physical presentation
+
Least-privilege compliance staff
+
Simple compliance state machine
+
Parallel document and inspection onboarding
+
Strict final activation requirements
+
Separate government and RideNG inspection requirements
+
Separate vehicle activity and ride eligibility
+
Strict validation
+
Complete auditability
```

This design is the baseline for implementation unless a later documented architecture decision explicitly supersedes it.