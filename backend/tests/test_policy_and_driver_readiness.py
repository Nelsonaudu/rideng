from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import unittest

from app.services.driver_readiness import (
    calculate_driver_readiness,
)
from app.services.market_policy import (
    ABUJA_DRIVER_DOCUMENT_REQUIREMENTS,
    ABUJA_VEHICLE_DOCUMENT_REQUIREMENTS,
    evaluate_document_requirements,
)
from app.services.vehicle_readiness import (
    calculate_vehicle_readiness,
)


class CompliancePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(
            2026,
            9,
            16,
            12,
            0,
            tzinfo=UTC,
        )

    def document(
        self,
        document_type: str,
        *,
        status: str = "approved",
        expires_at: date | None = None,
    ):
        return SimpleNamespace(
            document_type=document_type,
            verification_status=status,
            expires_at=expires_at,
        )

    def test_passport_can_satisfy_government_identity(self):
        result = evaluate_document_requirements(
            documents=[
                self.document(
                    "drivers_license",
                    expires_at=(
                        self.now.date()
                        + timedelta(days=365)
                    ),
                ),
                self.document(
                    "passport",
                    expires_at=(
                        self.now.date()
                        + timedelta(days=365)
                    ),
                ),
            ],
            requirements=(
                ABUJA_DRIVER_DOCUMENT_REQUIREMENTS
            ),
            today=self.now.date(),
        )

        self.assertTrue(result.valid)
        self.assertEqual(
            result.missing_or_invalid_requirements,
            [],
        )

    def test_expired_insurance_fails_vehicle_policy(self):
        result = evaluate_document_requirements(
            documents=[
                self.document(
                    "vehicle_licence_certificate",
                ),
                self.document(
                    "insurance",
                    expires_at=(
                        self.now.date()
                        - timedelta(days=1)
                    ),
                ),
                self.document(
                    "roadworthiness_certificate",
                ),
            ],
            requirements=(
                ABUJA_VEHICLE_DOCUMENT_REQUIREMENTS
            ),
            today=self.now.date(),
        )

        self.assertFalse(result.valid)

        self.assertIn(
            "insurance",
            result.missing_or_invalid_requirements,
        )

    def test_vehicle_requires_documents_to_be_ride_eligible(self):
        vehicle = SimpleNamespace(
            id=uuid4(),
            is_active=True,
            verification_status="approved",
        )

        inspection = SimpleNamespace(
            status="passed",
            expires_at=(
                self.now + timedelta(days=30)
            ),
        )

        snapshot = calculate_vehicle_readiness(
            vehicle=vehicle,
            latest_inspection=inspection,
            vehicle_documents=[],
            now=self.now,
        )

        self.assertFalse(snapshot.ride_eligible)

        self.assertIn(
            "vehicle_documents_missing_or_invalid",
            snapshot.blockers,
        )

    def test_driver_with_all_requirements_can_go_online(self):
        driver_id = uuid4()
        vehicle_id = uuid4()

        profile = SimpleNamespace(
            user_id=driver_id,
            verification_status="approved",
        )

        documents = [
            self.document(
                "drivers_license",
            ),
            self.document(
                "national_id",
            ),
        ]

        vehicle_readiness = [
            SimpleNamespace(
                vehicle_id=vehicle_id,
                ride_eligible=True,
            )
        ]

        snapshot = calculate_driver_readiness(
            driver_profile=profile,
            user_active=True,
            driver_documents=documents,
            vehicle_readiness=vehicle_readiness,
            now=self.now,
        )

        self.assertTrue(snapshot.online_eligible)

        self.assertEqual(
            snapshot.eligible_vehicle_ids,
            [vehicle_id],
        )

    def test_driver_without_eligible_vehicle_cannot_go_online(self):
        profile = SimpleNamespace(
            user_id=uuid4(),
            verification_status="approved",
        )

        documents = [
            self.document(
                "drivers_license",
            ),
            self.document(
                "government_id",
            ),
        ]

        snapshot = calculate_driver_readiness(
            driver_profile=profile,
            user_active=True,
            driver_documents=documents,
            vehicle_readiness=[],
            now=self.now,
        )

        self.assertFalse(snapshot.online_eligible)

        self.assertIn(
            "no_ride_eligible_vehicle",
            snapshot.blockers,
        )

    def test_inactive_user_cannot_go_online(self):
        profile = SimpleNamespace(
            user_id=uuid4(),
            verification_status="approved",
        )

        documents = [
            self.document(
                "drivers_license",
            ),
            self.document(
                "government_id",
            ),
        ]

        vehicle_readiness = [
            SimpleNamespace(
                vehicle_id=uuid4(),
                ride_eligible=True,
            )
        ]

        snapshot = calculate_driver_readiness(
            driver_profile=profile,
            user_active=False,
            driver_documents=documents,
            vehicle_readiness=vehicle_readiness,
            now=self.now,
        )

        self.assertFalse(snapshot.online_eligible)

        self.assertIn(
            "user_inactive",
            snapshot.blockers,
        )


if __name__ == "__main__":
    unittest.main()