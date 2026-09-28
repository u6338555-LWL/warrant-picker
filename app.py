from datetime import datetime
from io import StringIO
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
import urllib3

# 關閉不安全連線 (SSL) 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="專屬權證篩選系統", page_icon="📈", layout="wide")

# 1. 預設標準量化策略參數
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

# 2. 欄位清洗與標準化處理
def parse_moneyness(val):
    s = str(val).strip()
    if "外" in s:
        try:
            return -float(s.replace("外", "").replace("%", "").replace(",", "").strip())
        except:
            return 0.0
    elif "內" in s:
        try:
            return float(s.replace("內", "").replace("%", "").replace(",", "").strip())
        except:
            return 0.0
    try:
        return float(s.replace("%", "").replace(",", "").strip())
    except:
        return 0.0

def normalize_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # 欄位對照（對齊不同資料源的標頭）
    col_map = {
        "權證代號": "代號",
        "權證代碼": "代號",
        "權證": "權證名稱",
        "名稱": "權證名稱",
        "最新價": "賣價",
        "市價": "賣價",
        "委賣價": "賣價",
        "委買價": "買價",
        "剩餘天": "剩餘天數",
        "剩餘交易日": "剩餘天數",
        "價內外": "價內外（％）",
        "價內/外": "價內外（％）",
        "隱含波動率": "即時委賣 IV",
        "委賣IV": "即時委賣 IV",
        "歷史IV": "昨日委賣 IV",
    }
    df.rename(columns=col_map, inplace=True)

    # 處理價內外數值
    for col in ["價內外（％）", "價內外"]:
        if col in df.columns:
            df["價內外_數值"] = df[col].apply(parse_moneyness)
            break
    if "價內外_數值" not in df.columns and "價內外" in df.columns:
        df["價內外_數值"] = df["價內外"].apply(parse_moneyness)

    # 清理並轉型數值欄位
    num_cols = ["賣價", "買價", "即時委賣 IV", "昨日委賣 IV", "價差比", "差槓比", "剩餘天數"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace("%", "").str.replace("--", "").str.replace(",", "").str.strip(),
                errors="coerce",
            )

    # 若資料源無『價差比』，自動根據買賣價計算
    if ("價差比" not in df.columns or df["價差比"].isna().all()) and ("賣價" in df.columns and "買價" in df.columns):
        df["價差比"] = ((df["賣價"] - df["買價"]).abs() / df["賣價"]) * 100

    # 計算 IV 相對變動率（顯示名稱統一為：相對變動率）
    if "即時委賣 IV" in df.columns and "昨日委賣 IV" in df.columns:
        df["相對變動率"] = ((df["即時委賣 IV"] - df["昨日委賣 IV"]).abs() / df["昨日委賣 IV"]) * 100
    else:
        df["相對變動率"] = 0.0

    return df

# 3. 備用資料源抓取 (HiStock)
def fetch_from_histock(stock_code: str):
    url = f"https://histock.tw/stock/warrant.aspx?no={stock_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://histock.tw/",
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.encoding = "utf-8"
    if resp.status_code == 200:
        tables = pd.read_html(StringIO(resp.text))
        for t in tables:
            if any(c in str(t.columns) for c in ["代號", "權證", "名稱", "最新價", "履約價"]):
                return t
    return None

# 4. 主資料擷取模組 (CMoney + HiStock 備用自動容錯)
@st.cache_data(ttl=300, show_spinner=False)
def fetch_warrants(stock_code: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.cmoney.tw/finance/",
    }

    source_used = "CMoney"
    df = None
    status_code = 200
    raw_preview = ""

    # 嘗試主要來源：CMoney
    try:
        url = f"https://www.cmoney.tw/finance/warrantsbystock.aspx?stock={stock_code}"
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.encoding = "utf-8"
        status_code = resp.status_code
        raw_preview = resp.text[:1500]

        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if tables:
            parsed = pd.read_html(StringIO(str(tables[0])))
            if parsed and not parsed[0].empty:
                df = parsed[0]
        else:
            try:
                parsed = pd.read_html(StringIO(resp.text))
                if parsed and not parsed[0].empty:
                    df = parsed[0]
            except:
                pass
    except Exception as e:
        raw_preview = f"CMoney 請求發生例外: {e}"

    # 若主要來源失敗，自動切換至備用來源：HiStock
    if df is None or df.empty:
        try:
            df_histock = fetch_from_histock(stock_code)
            if df_histock is not None and not df_histock.empty:
                df = df_histock
                source_used = "HiStock (自動備用源)"
        except Exception as e:
            raw_preview += f"\nHiStock 備用源請求例外: {e}"

    fetch_time = datetime.now().strftime("%H:%M:%S")
    return df, status_code, raw_preview, fetch_time, source_used

# 5. 主頁面與控制面版
st.title("📈 權證專屬量化篩選器")

stock_code = st.sidebar.text_input("標的股票代碼", key="stock_code")
min_days = st.sidebar.number_input("剩餘天數 ≥ (天)", min_value=30, max_value=500, key="min_days")
moneyness_range = st.sidebar.slider("價內外 % 範圍", -30.0, 10.0, key="moneyness_range", step=0.5)
price_range = st.sidebar.slider("權證賣價範圍 (元)", 0.1, 10.0, key="price_range", step=0.1)
max_spread = st.sidebar.slider("價差比 ≤ (%)", 0.1, 5.0, key="max_spread", step=0.1)
max_chagang = st.sidebar.slider("差槓比 ≤", 0.05, 1.00, key="max_chagang", step=0.05)
max_iv_change = st.sidebar.slider("相對變動率 ≤ (%)", 0.1, 5.0, key="max_iv_change", step=0.1)

if st.sidebar.button("🔄 一鍵還原專屬預設", on_click=reset_defaults, type="primary", use_container_width=True):
    pass

try:
    with st.spinner(f"正在擷取 {stock_code} 的權證數據中..."):
        df, status_code, raw_preview, update_time, source_used = fetch_warrants(stock_code)

    if df is None or df.empty:
        st.error(f"❌ 數據擷取失敗 (HTTP 狀態碼: {status_code})：主要與備用數據源均未找到權證表格。")
        with st.expander("🔍 點此查看伺服器回應除錯資訊"):
            st.code(raw_preview, language="html")
    else:
        # 清洗與正規化資料
        df = normalize_and_clean_data(df)
        
        st.success(f"✅ 成功擷取數據！資料來源：**{source_used}**｜最後更新時間：{update_time}")

        # 執行量化篩選
        cond_days = df["剩餘天數"] >= min_days if "剩餘天數" in df.columns else True
        cond_money = (
            (df["價內外_數值"] >= moneyness_range[0]) & (df["價內外_數值"] <= moneyness_range[1])
            if "價內外_數值" in df.columns else True
        )
        cond_price = (
            (df["賣價"] >= price_range[0]) & (df["賣價"] <= price_range[1])
            if "賣價" in df.columns else True
        )
        cond_spread = df["價差比"] <= max_spread if "價差比" in df.columns else True
        cond_chagang = df["差槓比"] <= max_chagang if "差槓比" in df.columns else True
        cond_iv = df["相對變動率"] <= max_iv_change if "相對變動率" in df.columns else True

        filtered_df = df[cond_days & cond_money & cond_price & cond_spread & cond_chagang & cond_iv].copy()
        
        if "賣價" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="賣價", ascending=True)

        st.markdown(f"### 🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)")

        # 指定欄位與順序：代號 權證名稱 買價 賣價 相對變動率 價差比 差槓比
        display_cols = [
            "代號", "權證名稱", "買價", "賣價", "相對變動率", "價差比", "差槓比"
        ]
        existing_cols = [c for c in display_cols if c in filtered_df.columns]

        st.dataframe(
            filtered_df[existing_cols] if existing_cols else filtered_df,
            use_container_width=True,
            hide_index=True,
        )

except Exception as e:
    st.error(f"❌ 處理資料時發生例外錯誤：{e}")
