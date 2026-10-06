from datetime import datetime, date
from io import StringIO
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
import urllib3

# 關閉不安全連線 (SSL) 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


st.set_page_config(page_title="專屬權證篩選系統", page_icon="📈", layout="wide")

# 1. 統一管理預設參數與範圍
DEFAULT_CONFIG = {
    "stock_code": "2330",
    "min_days": 150,
    "moneyness_range": (-10.0, 0.0),
    "price_range": (0.0, 2.0),
    "max_spread": 5.0,
    "max_iv_change": 10.0,
}

def init_state():
    for key, val in DEFAULT_CONFIG.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_state()

def reset_defaults():
    for key, val in DEFAULT_CONFIG.items():
        st.session_state[key] = val
    st.toast("✅ 已還原為標準預設條件！", icon="🔄")


# 3. 資料正規化與欄位清洗
def normalize_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
  

    # 計算價差比 (%) = |賣價 - 買價| / 賣價 * 100
    valid_mask = (df["賣價"] > 0) & (df["買價"] > 0)
    df["價差比"] = 0.0
    df.loc[valid_mask, "價差比"] = (
        (df.loc[valid_mask, "賣價"] - df.loc[valid_mask, "買價"]).abs()
        / df.loc[valid_mask, "賣價"]
        * 100
    )
    df["價差比"] = df["價差比"].fillna(0.0).round(2)

    # 計算差槓比 = 價差比 / 即時槓桿
    valid_lev = df["即時槓桿"].notna() & (df["即時槓桿"] > 0)
    df["差槓比"] = 0.0
    df.loc[valid_lev, "差槓比"] = df.loc[valid_lev, "價差比"] / df.loc[valid_lev, "即時槓桿"]
    df["差槓比"] = df["差槓比"].fillna(0.0).round(2)

    for col in num_cols:
        df[col] = df[col].fillna(0.0)

    return df

# 4. 資料擷取模組
@st.cache_data(ttl=300, show_spinner=False)
def fetch_warrants(stock_code: str):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://histock.tw/"
    }

    df = None
    source_used = "HiStock 財經數據源"
    status_code = 200
    raw_preview = ""

    try:
        url = f"https://histock.tw/stock/warrant.aspx?no={stock_code}"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        status_code = resp.status_code
        raw_preview = resp.text[:1500]

        if resp.status_code == 200:
            tables = pd.read_html(StringIO(resp.text))
            for t in tables:
                cols_str = str(t.columns)
                if any(k in cols_str for k in ["代號", "權證", "買價", "賣價", "履約價", "到期日"]):
                    df = t
                    break
    except Exception as e:
        raw_preview += f"\n請求例外: {e}"

    fetch_time = datetime.now().strftime("%H:%M:%S")
    return df, status_code, raw_preview, fetch_time, source_used

# 5. 主頁面與控制面板
st.markdown(
"<h4>📈 權證專屬量化篩選器</h4>",
unsafe_allow_html=True
)
stock_code = st.sidebar.text_input(
"標的股票代碼",
key="stock_code"
)

days_range = st.sidebar.slider(
"剩餘天數範圍 (天)",
min_value=30,
max_value=300,
value=(st.session_state.min_days, 300),
step=1,
key="days_range"
)
 
min_days = days_range[0]



moneyness_range = st.sidebar.slider(
    "價內外 % 範圍", 
    min_value=-30.0, 
    max_value=30.0, 
    key="moneyness_range", 
    step=0.5
)

price_range = st.sidebar.slider("權證買價範圍 (元)", 0.0, 20.0, key="price_range", step=0.1)
max_spread = st.sidebar.slider("價差比 ≤ (%)", 0.0, 50.0, key="max_spread", step=0.5)
max_iv_change = st.sidebar.slider("相對變動率 ≤ (%)", 0.0, 50.0, key="max_iv_change", step=0.5)

if st.sidebar.button("🔄 一鍵還原專屬預設", on_click=reset_defaults, type="primary", use_container_width=True):
    pass

try:
    with st.spinner(f"正在擷取 {stock_code} 的權證數據中..."):
        df, status_code, raw_preview, update_time, source_used = fetch_warrants(stock_code)

    if df is None or df.empty:
        st.error(f"❌ 數據擷取失敗 (HTTP 狀態碼: {status_code})：無法解析權證表格。")
        with st.expander("🔍 點此查看伺服器回應除錯資訊"):
            st.code(raw_preview, language="html")
    else:
        df = normalize_and_clean_data(df)

        # 顯示除錯資訊
        st.write("欄位名稱")
        st.write(df.columns.tolist())
        if "到期日" in df.columns:
            st.write("到期日原始資料")
            st.write(df["到期日"].head(20))
        
        st.success(f"✅ 成功擷取數據！資料來源：**{source_used}**｜最後更新時間：{update_time}")

        # 執行即時量化篩選
        cond_days = (
(df["剩餘天數"] >= days_range[0]) &
(df["剩餘天數"] <= days_range[1])
if "剩餘天數" in df.columns
else True
)

        cond_money = (
            (df["價內外_數值"] >= moneyness_range[0]) & (df["價內外_數值"] <= moneyness_range[1])
            if "價內外_數值" in df.columns else True
        )
        cond_price = (
            (df["買價"] >= price_range[0]) & (df["買價"] <= price_range[1])
            if "買價" in df.columns else True
        )
        cond_spread = df["價差比"] <= max_spread if "價差比" in df.columns else True
        
        # 計算相對變動率
        if "即時委賣 IV" in df.columns and "昨日委賣 IV" in df.columns:
            valid_iv = df["即時委賣 IV"].notna() & df["昨日委賣 IV"].notna() & (df["昨日委賣 IV"] > 0)
            df["相對變動率"] = 0.0
            df.loc[valid_iv, "相對變動率"] = (
                (df.loc[valid_iv, "即時委賣 IV"] - df.loc[valid_iv, "昨日委賣 IV"]).abs()
                / df.loc[valid_iv, "昨日委賣 IV"]
                * 100
            )
        else:
            df["相對變動率"] = 0.0
            
        cond_iv = df["相對變動率"] <= max_iv_change
        st.write("總筆數", len(df))

        st.write("天數符合", cond_days.sum())

        st.write("價內外符合", cond_money.sum())

        st.write("價格符合", cond_price.sum())

        st.write("價差符合", cond_spread.sum())

        st.write("IV符合", cond_iv.sum())

        filtered_df = df[
            cond_days &
            cond_money &
            cond_price &
            cond_spread &
            cond_iv
        ].copy()

        if filtered_df.empty:
            st.warning(
                "⚠️ 在目前條件下沒有符合所有篩選條件的權證"
            )

            filtered_df = pd.DataFrame(
                columns=df.columns
            )

        # 依差槓比由小到大 (升冪) 排序
        if "差槓比" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="差槓比", ascending=True)

        st.markdown(
f"<h4>🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)</h4>",
unsafe_allow_html=True
)



except Exception as e:
    st.error(f"❌ 處理資料時發生例外錯誤：{e}")
st.write("欄位名稱")
st.write(df.columns.tolist())

st.write("資料預覽")
st.dataframe(df.head(20))
