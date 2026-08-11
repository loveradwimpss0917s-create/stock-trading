import httpx
import respx

from pipeline_py.ingest.edinet import BASE_URL, EdinetClient


@respx.mock
def test_fetch_documents_list_sends_subscription_key_and_date():
    route = respx.get(f"{BASE_URL}/documents.json").mock(
        return_value=httpx.Response(200, json={"results": [{"docID": "S100ABCD"}]})
    )
    client = EdinetClient(subscription_key="test-sub-key")
    result = client.fetch_documents_list("2026-08-07")
    client.close()

    assert result == [{"docID": "S100ABCD"}]
    sent_params = dict(route.calls[0].request.url.params)
    assert sent_params["Subscription-Key"] == "test-sub-key"
    assert sent_params["date"] == "2026-08-07"
    assert sent_params["type"] == "2"


@respx.mock
def test_fetch_document_returns_raw_bytes():
    respx.get(f"{BASE_URL}/documents/S100ABCD").mock(
        return_value=httpx.Response(200, content=b"zip-bytes")
    )
    client = EdinetClient(subscription_key="test-sub-key")
    content = client.fetch_document("S100ABCD")
    client.close()

    assert content == b"zip-bytes"
