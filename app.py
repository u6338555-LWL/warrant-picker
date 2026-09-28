from datetime import datetime
from io import StringIO
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="專屬權證篩選系統", page_icon="📈", layout="wide")

DEFAULT_CONFIG = {
    "stock_code": "2308",
    "min_days": 150,
    "moneyness_range": (-10.0, 0.0),
    "price_range": (0.8, 2.0),
    "max_spread": 1.5,
    "max_chagang": 0.3,
    "max_iv_change": 1.0,
}

def init_state():
    query_params = st.query_params
    if "code" in query_params:
        st.session_state["stock_code"] = query_params["code"]
    for key, val in DEFAULT_CONFIG.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_state()

def reset_defaults():
    for key, val in DEFAULT_CONFIG.items():
        st.session_state[key] = val
    st.toast("✅ 已還原為標準預設條件！", icon="🔄")

# 資料抓取函數（強化反爬蟲偽裝與除錯）
@st.cache_data(ttl=300, show_spinner=False)
def fetch_warrants(stock_code: str):
    url = f"https://www.cmoney.tw/finance/warrantsbystock.aspx?stock={stock_code}"
    
    # 完整的瀏覽器偽裝 Header
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.cmoney.tw/finance/",
        "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    session = requests.Session()
    resp = session.get(url, headers=headers, verify=False, timeout=12)
    resp.encoding = "utf-8"
    
    status_code = resp.status_code
    html_text = resp.text
    
    # 解析表格
    soup = BeautifulSoup(html_text, "html.parser")
    tables = soup.find_all("table")

    df = None
    if tables:
        parsed = pd.read_html(StringIO(str(tables[0])))
        if parsed:
            df = parsed[0]
    else:
        try:
            parsed = pd.read_html(StringIO(html_text))
            if parsed:
                df = parsed[0]
        except:
            pass

    fetch_time = datetime.now().strftime("%H:%M:%S")
    return df, status_code, html_text[:1500], fetch_time

# 主畫面
st.title("📈 權證專屬量化篩選器")

stock_code = st.sidebar.text_input("標的股票代碼", key="stock_code")
min_days = st.sidebar.number_input("剩餘天數 ≥ (天)", min_value=30, max_value=500, key="min_days")
moneyness_range = st.sidebar.slider("價內外 % 範圍", -30.0, 10.0, key="moneyness_range", step=0.5)
price_range = st.sidebar.slider("權證賣價範圍 (元)", 0.1, 10.0, key="price_range", step=0.1)
max_spread = st.sidebar.slider("價差比 ≤ (%)", 0.1, 5.0, key="max_spread", step=0.1)
max_chagang = st.sidebar.slider("差槓比 ≤", 0.05, 1.00, key="max_chagang", step=0.05)
max_iv_change = st.sidebar.slider("IV 相對變動率 ≤ (%)", 0.1, 5.0, key="max_iv_change", step=0.1)

if st.sidebar.button("🔄 一鍵還原專屬預設", on_click=reset_defaults, type="primary", use_container_width=True):
    pass

try:
    with st.spinner(f"正在擷取 {stock_code} 的權證數據中..."):
        df, status_code, raw_preview, update_time = fetch_warrants(stock_code)

    if df is None or df.empty:
        st.error(f"❌ 抓取失敗 (HTTP 狀態碼: {status_code})：目標網站未回傳表格，可能已被雲端防爬蟲攔截。")
        with st.expander("🔍 點此查看伺服器回傳的 HTML 內容（除錯用）"):
            st.code(raw_preview, language="html")
    else:
        st.success(f"✅ 成功擷取數據！最後更新時間：{update_time}")
        
        # 進行數據清洗與篩選...
        def parse_moneyness(val):
            s = str(val).strip()
            if "外" in s:
                return -float(s.replace("外", "").replace("%", "").replace(",", "").strip())
            elif "內" in s:
                return float(s.replace("內", "").replace("%", "").replace(",", "").strip())
            try:
                return float(s.replace("%", "").replace(",", ""))
            except:
                return 0.0

        if "價內外（％）" in df.columns:
            df["價內外_數值"] = df["價內外（％）"].apply(parse_moneyness)

        num_cols = ["賣價", "買價", "即時委賣 IV", "昨日委賣 IV", "價差比", "差槓比", "剩餘天數"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace("%", "").str.replace("--", "").str.replace(",", ""),
                    errors="coerce",
                )

        if "即時委賣 IV" in df.columns and "昨日委賣 IV" in df.columns:
            df["IV相對變動率"] = ((df["即時委賣 IV"] - df["昨日委賣 IV"]).abs() / df["昨日委賣 IV"]) * 100

        cond_days = df["剩餘天數"] >= min_days if "剩餘天數" in df.columns else True
        cond_money = (df["價內外_數值"] >= moneyness_range[0]) & (df["價內外_數值"] <= moneyness_range[1]) if "價內外_數值" in df.columns else True
        cond_price = (df["賣價"] >= price_range[0]) & (df["賣價"] <= price_range[1]) if "賣價" in df.columns else True
        cond_spread = df["價差比"] <= max_spread if "價差比" in df.columns else True
        cond_chagang = df["差槓比"] <= max_chagang if "差槓比" in df.columns else True
        cond_iv = df["IV相對變動率"] <= max_iv_change if "IV相對變動率" in df.columns else True

        filtered_df = df[cond_days & cond_money & cond_price & cond_spread & cond_chagang & cond_iv].copy()
        
        st.markdown(f"### 🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)")
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

except Exception as e:
    st.error(f"❌ 處理資料時發生例外錯誤：{e}")
