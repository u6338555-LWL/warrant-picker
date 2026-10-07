@st.cache_data(ttl=300)
def fetch_warrants(stock_code):

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cmoney.tw/"
    }

    try:
        url = f"https://www.cmoney.tw/finance/warrantsbystock.aspx?stock={stock_code}"

        resp = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        resp.encoding = "utf-8"

        tables = pd.read_html(
            StringIO(resp.text)
        )

        return tables, resp.status_code

    except Exception as e:

        return str(e), None
