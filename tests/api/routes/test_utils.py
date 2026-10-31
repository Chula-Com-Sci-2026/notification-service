from fastapi.testclient import TestClient


def test_up_needs_no_token(client: TestClient) -> None:
    response = client.get("/up")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
