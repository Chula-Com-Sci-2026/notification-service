from fastapi.testclient import TestClient


def test_openapi_matches_contract_identity(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "Notification Service"
    assert document["info"]["version"] == "1.0.0"
    assert document["paths"]["/up"]["get"]["operationId"] == "health_up_get"
