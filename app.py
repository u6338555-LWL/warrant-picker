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

# 2. 解析價內外數值（僅用於滑桿過濾邏輯）
def parse_moneyness_for_filter(val):
    s = str(val).strip()
    if not s or s == "nan" or s == "--" or s == "-":
        return 0.0
    
    is_wai = "外" in s or ("-" in s and "內" not in s)
    clean_num = re.sub(r"[^\d.]", "", s)
    try:
        num = float(clean_num)
    except:
        num = 0.0
        
    if is_wai:
        return -abs(num)
    else:
        return abs(num)

# 3. 資料正規化與欄位清洗
def normalize_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    col_map = {
        "權證代號": "代號", "權證代碼": "代號", "代碼": "代號",
        "權證": "權證名稱", "名稱": "權證名稱", "權證簡稱": "權證名稱", "標的": "權證名稱",
        "最新": "成交價", "最新價": "成交價", "市價": "成交價", "成交價": "成交價", "成交": "成交價",
        "委賣價": "賣價", "委賣": "賣價", "賣出": "賣價", "賣價": "賣價",
        "委買價": "買價", "委買": "買價", "買進": "買價", "買價": "買價",
        "剩餘天": "剩餘天數", "剩餘交易日": "剩餘天數", "到期天數": "剩餘天數", "剩餘日": "剩餘天數", "天數": "剩餘天數",
        "價內外": "價內外_raw", "價內/外": "價內外_raw", "價內外%": "價內外_raw", "價內外（％）": "價內外_raw",
        "即時委賣IV": "即時委賣 IV", "委賣IV": "即時委賣 IV", "委賣隱波": "即時委賣 IV", "隱含波動率": "即時委賣 IV",
        "昨日委賣IV": "昨日委賣 IV", "歷史IV": "昨日委賣 IV", "昨日隱波": "昨日委賣 IV",
        "行使比例": "行使比例", "執行比例": "行使比例",
        "履約價": "履約價", "履約價格": "履約價",
        "即時槓桿": "即時槓桿", "有效槓桿": "即時槓桿", "實質槓桿": "即時槓桿", "槓桿比率": "即時槓桿","剩餘天數": "剩餘天數",
"剩餘天": "剩餘天數",
 
"價內外程度": "價內外_raw",
 
"實質槓桿": "即時槓桿",
 
"行使比例": "行使比例"
    }
df.columns = (
    df.columns.astype(str)
    .str.replace(" ", "", regex=False)
    .str.strip()
)
 
df.rename(columns=col_map, inplace=True)
    if "代號" not in df.columns:
        df["代號"] = ""
    if "權證名稱" not in df.columns:
        df["權證名稱"] = ""

    if "剩餘天數" in df.columns:
        df["剩餘天數"] = pd.to_numeric(
            df["剩餘天數"],
            errors="coerce"
        ).fillna(0).astype(int)
    elif "到期日" in df.columns:
        today = date.today()
        def calc_days(d):
            d = str(d).strip()
            for fmt in (
                "%Y/%m/%d",
                "%Y-%m-%d",
                "%Y.%m.%d",
                "%Y%m%d"
            ):
                try:
                    target = datetime.strptime(
                        d,
                        fmt
                    ).date()
                    return max(
                        0,
                        (target - today).days
                    )
                except Exception:
                    pass
            return 0
        df["剩餘天數"] = df["到期日"].apply(calc_days)
    else:
        df["剩餘天數"] = 0

    # 數值清理
    num_cols = ["買價", "賣價", "成交價", "即時委賣 IV", "昨日委賣 IV", "剩餘天數", "行使比例", "履約價", "即時槓桿"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace("%", "")
                .str.replace("--", "")
                .str.replace(",", "")
                .str.replace("倍", "")
                .str.strip(),
                errors="coerce",
            )
        else:
            df[col] = 0.0

    # 價內外：直接保留資料來源的原始字串顯示
    raw_col = "價內外_raw" if "價內外_raw" in df.columns else None
    if not raw_col:
        for c in df.columns:
            if "價內" in str(c) or "價外" in str(c):
                raw_col = c
                break

    if raw_col:
        df["價內外（％）"] = df[raw_col].astype(str).str.strip()
        df["價內外_數值"] = df[raw_col].apply(parse_moneyness_for_filter)
    else:
        df["價內外（％）"] = "0.0%"
        df["價內外_數值"] = 0.0

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
st.title("📈 權證專屬量化篩選器")

stock_code = st.sidebar.text_input("標的股票代碼", key="stock_code")
min_days = st.sidebar.number_input("剩餘天數 ≥ (天)", min_value=10, max_value=500, key="min_days")

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
        cond_days = df["剩餘天數"] >= min_days if "剩餘天數" in df.columns else True
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

        filtered_df = df[cond_days & cond_money & cond_price & cond_spread & cond_iv].copy()
        
        if filtered_df.empty:
            st.warning("⚠️ 在目前條件下無符合權證，以下為買價符合範圍之初步結果：")
            filtered_df = df[cond_price].copy()

        # 依差槓比由小到大 (升冪) 排序
        if "差槓比" in filtered_df.columns:
            filtered_df = filtered_df.sort_values(by="差槓比", ascending=True)

        st.markdown(f"### 🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)")

        display_cols = [
            "代號", "權證名稱", "買價", "賣價", "成交價",
            "即時委賣 IV", "昨日委賣 IV", "價內外（％）", "剩餘天數",
            "行使比例", "履約價", "即時槓桿", "價差比", "差槓比"
        ]

        valid_display_cols = [c for c in display_cols if c in filtered_df.columns]

        st.dataframe(
            filtered_df[valid_display_cols],
            use_container_width=True,
            hide_index=True,
        )

except Exception as e:
    st.error(f"❌ 處理資料時發生例外錯誤：{e}")
