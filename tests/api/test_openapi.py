import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Copied from running-buddy-contracts, so the suite runs without a sibling checkout.
CONTRACT: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "contracts" / "notification.openapi.json").read_text()
)
OPERATIONS = [
    (path, method) for path, ops in CONTRACT["paths"].items() for method in ops
]


@pytest.fixture
def served(client: TestClient) -> dict[str, Any]:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_title_and_version_match(served: dict[str, Any]) -> None:
    assert served["info"]["title"] == CONTRACT["info"]["title"]
    assert served["info"]["version"] == CONTRACT["info"]["version"]


def test_auth_is_a_plain_header_with_no_security_scheme(served: dict[str, Any]) -> None:
    assert "securitySchemes" not in served.get("components", {})


@pytest.mark.parametrize(("path", "method"), OPERATIONS)
def test_contract_operation_is_still_served(
    served: dict[str, Any], path: str, method: str
) -> None:
    expected = CONTRACT["paths"][path][method]
    actual = served["paths"][path][method]
    assert actual["operationId"] == expected["operationId"]
    assert actual["summary"] == expected["summary"]
    assert set(expected["responses"]) <= set(actual["responses"])
    actual_parameters = {p["name"]: p for p in actual.get("parameters", [])}
    for parameter in expected.get("parameters", []):
        served_parameter = actual_parameters[parameter["name"]]
        assert served_parameter["in"] == parameter["in"]
        assert served_parameter["required"] == parameter["required"]
        assert served_parameter["schema"] == parameter["schema"]


def test_additions_to_the_contract_are_optional(served: dict[str, Any]) -> None:
    for path, method in OPERATIONS:
        known = {
            p["name"] for p in CONTRACT["paths"][path][method].get("parameters", [])
        }
        for parameter in served["paths"][path][method].get("parameters", []):
            if parameter["name"] not in known:
                assert parameter["required"] is False
