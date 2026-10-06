import pytest


def get_data(client, url, expected_status_code):
    response = client.get(url)
    if response.status_code != expected_status_code:
        pytest.fail(
            f"GET {url} expected {expected_status_code} got {response.status_code}. Response: {response.text}",
            pytrace=False,
        )
    return response.json()