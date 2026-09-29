from datetime import datetime
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="專屬權證篩選系統", page_icon="📈", layout="wide"
)

# 1. 預設標準參數
DEFAULT_CONFIG = {
    "stock_code": "2330",
    "min_days": 150,
    "moneyness_range": (-10.0, 0.0),
    "price_range": (0.8, 2.0),
    "max_spread": 1.5,
    "max_chagang": 0.3,
    "max_iv_change": 1.0,
}


def init_state():
    for key, val in DEFAULT_CONFIG.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_state()


def reset_defaults():
    for key, val in DEFAULT_CONFIG.items():
        st.session_state[key] = val
    st.toast("✅ 已還原為標準專屬策略條件！", icon="🔄")


# 2. CMoney 資料抓取 (TTL = 10分鐘快取)
@st.cache_data(ttl=600, show_spinner=False)
def fetch_cmoney_warrants(stock_code: str):
    url = f"https://www.cmoney.tw/finance/warrantsbystock.aspx?stock={stock_code}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers)
    tables = pd.read_html(resp.text)
    df = tables[0]

    def parse_moneyness(val):
        s = str(val).strip()
        if "外" in s:
            return -float(s.replace("外", "").replace("%", "").strip())
        elif "內" in s:
            return float(s.replace("內", "").replace("%", "").strip())
        return 0.0

    if "價內外（％）" in df.columns:
        df["價內外_數值"] = df["價內外（％）"].apply(parse_moneyness)

    num_cols = [
        "賣價",
        "買價",
        "即時委賣 IV",
        "昨日委賣 IV",
        "價差比",
        "差槓比",
        "剩餘天數",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace("%", "")
                .str.replace("--", "")
                .str.replace(",", ""),
                errors="coerce",
            )

    if "即時委賣 IV" in df.columns and "昨日委賣 IV" in df.columns:
        df["IV相對變動率"] = (
            (df["即時委賣 IV"] - df["昨日委賣 IV"]).abs()
            / df["昨日委賣 IV"]
        ) * 100

    fetch_time = datetime.now().strftime("%H:%M:%S")
    return df, fetch_time


# 3. 側邊欄控制面板
st.sidebar.header("⚙️ 策略參數微調")
st.sidebar.button(
    "🔄 一鍵還原專屬預設",
    on_click=reset_defaults,
    type="primary",
    use_container_width=True,
)

stock_code = st.sidebar.text_input("標的股票代碼", key="stock_code")
min_days = st.sidebar.number_input(
    "剩餘天數 ≥", min_value=30, max_value=500, key="min_days"
)
moneyness_range = st.sidebar.slider(
    "價內外 % 範圍", -30.0, 10.0, key="moneyness_range", step=0.5
)
price_range = st.sidebar.slider(
    "權證賣價範圍 (元)", 0.1, 10.0, key="price_range", step=0.1
)
max_spread = st.sidebar.slider(
    "價差比 ≤ (%)", 0.1, 5.0, key="max_spread", step=0.1
)
max_chagang = st.sidebar.slider(
    "差槓比 ≤", 0.05, 1.00, key="max_chagang", step=0.05
)
max_iv_change = st.sidebar.slider(
    "IV 相對變動率 ≤ (%)", 0.1, 5.0, key="max_iv_change", step=0.1
)

# 4. 主畫面與資料顯示
st.title("📈 權證專屬篩選器")

col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(f"當前標的：{stock_code}")
with col2:
    if st.button("🔄 重新抓取最新資料", use_container_width=True):
        st.cache_data.clear()
        st.toast("✅ 已刷洗快取，取得盤中最新數據！", icon="🔄")

try:
    with st.spinner("資料讀取中..."):
        df, update_time = fetch_cmoney_warrants(stock_code)

    st.caption(
        f"⏱️ 資料最後更新時間：**{update_time}**（10"
        " 分鐘內讀取記憶體快取，不重複發送請求）"
    )

    # 篩選條件
    cond_days = df["剩餘天數"] >= min_days
    cond_money = (df["價內外_數值"] >= moneyness_range[0]) & (
        df["價內外_數值"] <= moneyness_range[1]
    )
    cond_price = (df["賣價"] >= price_range[0]) & (
        df["賣價"] <= price_range[1]
    )
    cond_spread = df["價差比"] <= max_spread
    cond_chagang = df["差槓比"] <= max_chagang
    cond_iv = df["IV相對變動率"] < max_iv_change

    filtered_df = df[
        cond_days
        & cond_money
        & cond_price
        & cond_spread
        & cond_chagang
        & cond_iv
    ].copy()

    # 排序：依賣價從小到大
    filtered_df = filtered_df.sort_values(by="賣價", ascending=True)

    st.markdown(f"### 篩選結果 (共 {len(filtered_df)} 檔符合條件)")

    display_cols = [
        "權證名稱",
        "賣價",
        "買價",
        "價內外（％）",
        "剩餘天數",
        "價差比",
        "差槓比",
        "即時委賣 IV",
        "昨日委賣 IV",
        "IV相對變動率",
    ]
    existing_cols = [c for c in display_cols if c in filtered_df.columns]

    st.dataframe(filtered_df[existing_cols], use_container_width=True)

except Exception as e:
    st.error(
        "擷取或處理資料時發生錯誤，請確認股票代碼是否正確。"
        f"詳細訊息: {e}"
    )
