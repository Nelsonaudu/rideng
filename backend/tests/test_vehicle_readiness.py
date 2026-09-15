from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import unittest

from app.services.vehicle_readiness import calculate_vehicle_readiness


class VehicleReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(
            2026,
            9,
            16,
            12,
            0,
            tzinfo=UTC,
        )

    def vehicle(
        self,
        *,
        is_active: bool = True,
        verification_status: str = "pending",
    ):
        return SimpleNamespace(
            id=uuid4(),
            is_active=is_active,
            verification_status=verification_status,
        )

    def inspection(
        self,
        *,
        status: str,
        expires_at=None,
    ):
        return SimpleNamespace(
            status=status,
            expires_at=expires_at,
        )

    def test_new_vehicle_requires_inspection_but_can_present(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(),
            latest_inspection=None,
            now=self.now,
        )

        self.assertTrue(snapshot.inspection_required)
        self.assertTrue(snapshot.inspection_eligible)
        self.assertFalse(snapshot.inspection_valid)
        self.assertFalse(snapshot.vehicle_compliance_approved)
        self.assertFalse(snapshot.ride_eligible)
        self.assertIn(
            "valid_inspection_required",
            snapshot.blockers,
        )

    def test_approved_vehicle_with_valid_inspection_is_ride_eligible(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(
                verification_status="approved",
            ),
            latest_inspection=self.inspection(
                status="passed",
                expires_at=self.now + timedelta(days=30),
            ),
            now=self.now,
        )

        self.assertFalse(snapshot.inspection_required)
        self.assertTrue(snapshot.inspection_eligible)
        self.assertTrue(snapshot.inspection_valid)
        self.assertTrue(snapshot.vehicle_compliance_approved)
        self.assertTrue(snapshot.ride_eligible)
        self.assertEqual(snapshot.blockers, [])

    def test_expired_inspection_requires_new_inspection(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(
                verification_status="approved",
            ),
            latest_inspection=self.inspection(
                status="passed",
                expires_at=self.now - timedelta(days=1),
            ),
            now=self.now,
        )

        self.assertTrue(snapshot.inspection_required)
        self.assertFalse(snapshot.inspection_valid)
        self.assertFalse(snapshot.ride_eligible)

    def test_failed_inspection_is_not_valid(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(
                verification_status="approved",
            ),
            latest_inspection=self.inspection(
                status="failed",
            ),
            now=self.now,
        )

        self.assertTrue(snapshot.inspection_required)
        self.assertFalse(snapshot.inspection_valid)
        self.assertFalse(snapshot.ride_eligible)

    def test_suspended_vehicle_cannot_present_or_ride(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(
                verification_status="suspended",
            ),
            latest_inspection=self.inspection(
                status="passed",
                expires_at=self.now + timedelta(days=30),
            ),
            now=self.now,
        )

        self.assertFalse(snapshot.inspection_eligible)
        self.assertFalse(snapshot.vehicle_compliance_approved)
        self.assertFalse(snapshot.ride_eligible)
        self.assertIn(
            "vehicle_suspended",
            snapshot.blockers,
        )

    def test_inactive_vehicle_cannot_ride(self):
        snapshot = calculate_vehicle_readiness(
            vehicle=self.vehicle(
                is_active=False,
                verification_status="approved",
            ),
            latest_inspection=self.inspection(
                status="passed",
                expires_at=self.now + timedelta(days=30),
            ),
            now=self.now,
        )

        self.assertFalse(snapshot.inspection_eligible)
        self.assertFalse(snapshot.ride_eligible)
        self.assertIn(
            "vehicle_inactive",
            snapshot.blockers,
        )


if __name__ == "__main__":
    unittest.main()