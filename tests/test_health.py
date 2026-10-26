from tests.conftest import make_client


def test_health_returns_ok():
    client = make_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
