import pytest

mock_token = "mock_token"
mock_jwks = "mock_jwks"
mock_user_payload = {"user_metadata": {"companyId": "mock_company_id"}}


def mock_get_token_auth_header(authorization):
    return mock_token


def mock_get_jwks():
    return mock_jwks


def mock_verify_token(*args, **kwargs):
    return mock_user_payload


def mock_set_up():
    return {
        "DOMAIN": "mock_domain.com",
        "API_AUDIENCE": "mock_api_audience",
        "ISSUER": "mock_issuer",
        "ALGORITHMS": "mock_algorithms",
    }


# # Mocking storage
# class MockBucket:
#     def get_blob(self, blob_name):
#         return MockBlob()

#     def blob(self, blob_name):
#         return MockBlob()


# class MockBlob:
#     def __init__(self):
#         pass

#     def generate_signed_url(self, *args, **kwargs):
#         return "mock_signed_url"

#     # Add any other methods that are called on a Blob in your application


# class MockClient:
#     def get_bucket(self, bucket_name):
#         return MockBucket()

#     def bucket(self, bucket_name):
#         return MockBucket()


@pytest.fixture
def mock_auth(monkeypatch):
    monkeypatch.setattr("utils.auth.get_token_auth_header", mock_get_token_auth_header)
    monkeypatch.setattr("utils.auth.get_jwks", mock_get_jwks)
    monkeypatch.setattr("utils.auth.verify_token", mock_verify_token)
    monkeypatch.setattr("utils.auth.set_up", mock_set_up)
