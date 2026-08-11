import httpx
import pytest
import respx

from pipeline_py.ingest.jpx_csv import JpxCsvAdapter


def test_fetch_rows_raises_clear_error_when_url_not_configured():
    adapter = JpxCsvAdapter(dataset_urls={})
    with pytest.raises(KeyError, match="JPX_CSV_URL_SHORT_SALE_BALANCE"):
        adapter.fetch_rows("short_sale_balance")


@respx.mock
def test_fetch_rows_parses_shift_jis_csv():
    csv_bytes = "コード,日付\n72030,20260807\n".encode("shift-jis")
    respx.get("https://example.jpx.co.jp/short_sale.csv").mock(
        return_value=httpx.Response(200, content=csv_bytes)
    )
    adapter = JpxCsvAdapter(dataset_urls={"short_sale_balance": "https://example.jpx.co.jp/short_sale.csv"})
    rows = adapter.fetch_rows("short_sale_balance")
    adapter.close()

    assert rows == [{"コード": "72030", "日付": "20260807"}]
