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
def test_select_all_pages_past_postgrest_max_rows():
    # PostgREST truncates a single response at max_rows (1000), so a table
    # larger than that must be paged or rows are silently lost.
    first_page = [{"code": f"{i:05d}"} for i in range(1000)]
    second_page = [{"code": "99999"}]
    respx.get("https://example.supabase.co/rest/v1/ingest_checkpoint").mock(
        side_effect=[
            httpx.Response(200, json=first_page),
            httpx.Response(200, json=second_page),
        ]
    )
    client = SupabaseUpsertClient(url="https://example.supabase.co", service_role_key="svc-key")
    rows = client.select_all("ingest_checkpoint", {"select": "code"})
    client.close()

    assert len(rows) == 1001
    assert rows[-1]["code"] == "99999"


@respx.mock
def test_select_all_stops_after_a_single_short_page():
    route = respx.get("https://example.supabase.co/rest/v1/ingest_checkpoint").mock(
        return_value=httpx.Response(200, json=[{"code": "13010"}])
    )
    client = SupabaseUpsertClient(url="https://example.supabase.co", service_role_key="svc-key")
    rows = client.select_all("ingest_checkpoint", {"select": "code"})
    client.close()

    assert rows == [{"code": "13010"}]
    assert route.call_count == 1


@respx.mock
def test_upsert_skips_request_when_rows_are_empty():
    route = respx.post("https://example.supabase.co/rest/v1/securities")
    client = SupabaseUpsertClient(url="https://example.supabase.co", service_role_key="svc-key")
    client.upsert("securities", [], on_conflict="code")
    client.close()

    assert route.call_count == 0
