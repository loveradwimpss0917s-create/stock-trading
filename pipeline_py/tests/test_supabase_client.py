import httpx
import respx

from pipeline_py.ingest.supabase_client import SupabaseUpsertClient


@respx.mock
def test_upsert_sends_merge_duplicates_and_on_conflict():
    route = respx.post("https://example.supabase.co/rest/v1/securities").mock(
        return_value=httpx.Response(201, json=[])
    )
    client = SupabaseUpsertClient(url="https://example.supabase.co", service_role_key="svc-key")
    client.upsert("securities", [{"code": "72030"}], on_conflict="code")
    client.close()

    request = route.calls[0].request
    assert request.headers["Prefer"] == "resolution=merge-duplicates,return=minimal"
    assert request.headers["apikey"] == "svc-key"
    assert dict(request.url.params)["on_conflict"] == "code"


@respx.mock
def test_upsert_skips_request_when_rows_are_empty():
    route = respx.post("https://example.supabase.co/rest/v1/securities")
    client = SupabaseUpsertClient(url="https://example.supabase.co", service_role_key="svc-key")
    client.upsert("securities", [], on_conflict="code")
    client.close()

    assert route.call_count == 0
