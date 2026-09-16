import unittest
from uuid import uuid4

from app.services.idempotency import (
    IdempotencyKeyError,
    build_request_hash,
    normalize_idempotency_key,
)


class IdempotencyTests(unittest.TestCase):
    def test_hash_is_stable_for_same_payload(self):
        first = build_request_hash(
            {
                "offer_id": "abc",
                "ride_request_id": "xyz",
            }
        )

        second = build_request_hash(
            {
                "ride_request_id": "xyz",
                "offer_id": "abc",
            }
        )

        self.assertEqual(
            first,
            second,
        )

    def test_different_payload_has_different_hash(self):
        first = build_request_hash(
            {
                "offer_id": "abc",
            }
        )

        second = build_request_hash(
            {
                "offer_id": "def",
            }
        )

        self.assertNotEqual(
            first,
            second,
        )

    def test_valid_key_is_preserved(self):
        key = str(
            uuid4()
        )

        self.assertEqual(
            normalize_idempotency_key(
                key
            ),
            key,
        )

    def test_blank_key_is_rejected(self):
        with self.assertRaises(
            IdempotencyKeyError
        ):
            normalize_idempotency_key(
                "   "
            )

    def test_overlong_key_is_rejected(self):
        with self.assertRaises(
            IdempotencyKeyError
        ):
            normalize_idempotency_key(
                "x" * 256
            )


if __name__ == "__main__":
    unittest.main()