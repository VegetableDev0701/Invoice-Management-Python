from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import datetime
import pytest
from main import app

client = TestClient(app)


@pytest.mark.parametrize(
    "company_id, doc_id, filenames",
    [
        ("demo", "AcBG", ["file1", "file2", "file3"]),
    ],
)
def test_generate_signed_url(company_id, doc_id, filenames, mock_auth):
    # Mock Blob
    mock_blob = Mock()
    mock_blob.generate_signed_url.return_value = "mock_signed_url"

    with patch("routers.invoices.bucket.get_blob", return_value=mock_blob), patch(
        "utils.auth.check_user_data"
    ):
        headers = {"auth0": "Bearer mock_token"}
        response = client.get(
            f"/{company_id}/invoice/generate-signed-url",
            params={"doc_id": doc_id, "filenames": filenames},
            headers=headers,
        )

    expected = {
        "signed_urls": ["mock_signed_url"] * len(filenames),
        "expiration": str(
            int((datetime.datetime.utcnow() + datetime.timedelta(hours=1)).timestamp()),
        ),
    }

    assert response.status_code == 200
    assert response.json() == expected
