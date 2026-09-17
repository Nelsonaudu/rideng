import unittest

from app.main import app


class PickupLocationApiContractTests(
    unittest.TestCase
):
    def test_driver_pickup_location_endpoint_is_registered(
        self,
    ):
        path = (
            "/api/v1/trips/"
            "{trip_id}/pickup-location"
        )

        paths = app.openapi()["paths"]

        self.assertIn(
            path,
            paths,
        )

        self.assertIn(
            "post",
            paths[path],
        )


if __name__ == "__main__":
    unittest.main()