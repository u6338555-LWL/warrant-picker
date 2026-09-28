from datetime import datetime, date
from io import StringIO
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="專屬權證量化篩選系統", page_icon="📈", layout="wide")

# 1. 統一管理預設參數與範圍
DEFAULT_CONFIG = {
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

# 3. 資料正規化與欄位清洗（對應 CMoney 格式與 Excel 複製邏輯）
def normalize_and_clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    col_map = {
        "權證代號": "權證代碼", "代碼": "權證代碼", "代號": "權證代碼",
        "權證": "名稱", "權證簡稱": "名稱", "標的": "名稱",
        "最新": "成交價", "最新價": "成交價", "市價": "成交價", "成交": "成交價",
        "委賣價": "賣價", "委賣": "賣價", "賣出": "賣價",
        "委買價": "買價", "委買": "買價", "買進": "買價",
        "剩餘天": "剩餘天數", "剩餘交易日": "剩餘天數", "到期天數": "剩餘天數", "剩餘日": "剩餘天數",
        "價內外": "價內外（％）", "價內/外": "價內外（％）", "價內外%": "價內外（％）", "價內外（％）": "價內外（％）",
        "即時委賣IV": "即時委賣 IV", "委賣IV": "即時委賣 IV", "委賣隱波": "即時委賣 IV", "隱含波動率": "即時委賣 IV",
        "昨日委賣IV": "昨日委賣 IV", "歷史IV": "昨日委賣 IV", "昨日隱波": "昨日委賣 IV",
        "行使比例": "行使比例", "執行比例": "行使比例",
        "履約價": "履約價", "履約價格": "履約價",
        "即時槓桿": "即時槓桿", "有效槓桿": "即時槓桿", "實質槓桿": "即時槓桿", "槓桿比率": "即時槓桿",
    }
    df.rename(columns=col_map, inplace=True)

    if "權證代碼" not in df.columns:
        df["權證代碼"] = ""
    if "名稱" not in df.columns:
        df["名稱"] = ""

    # 確保數值欄位乾淨
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

    # 價內外處理：保留原始字串，建立數值欄位供滑桿過濾
    raw_col = "價內外（％）" if "價內外（％）" in df.columns else None
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

    # 計算價差比 = (賣價 - 買價) / 賣價
    valid_mask = (df["賣價"] > 0) & (df["買價"] > 0)
    df["價差比"] = 0.0
    df.loc[valid_mask, "價差比"] = (
        (df.loc[valid_mask, "賣價"] - df.loc[valid_mask, "買價"]).abs()
        / df.loc[valid_mask, "賣價"]
    )
    df["價差比"] = df["價差比"].fillna(0.0)

    # 計算差槓比 = 價差比 / 即時槓桿
    valid_lev = df["即時槓桿"].notna() & (df["即時槓桿"] > 0)
    df["差槓比"] = 0.0
    df.loc[valid_lev, "差槓比"] = df.loc[valid_lev, "價差比"] / df.loc[valid_lev, "即時槓桿"]
    df["差槓比"] = df["差槓比"].fillna(0.0)

    for col in num_cols:
        df[col] = df[col].fillna(0.0)

    return df

# 4. 主頁面與控制面板
st.title("📈 權證量化篩選器 (CMoney 資料來源模式)")

st.sidebar.header("⚙️ 篩選條件設定")
min_days = st.sidebar.number_input("剩餘天數 ≥ (天)", min_value=10, max_value=500, key="min_days")

moneyness_range = st.sidebar.slider(
    "價內外 % 範圍", 
    min_value=-30.0, 
    max_value=30.0, 
    key="moneyness_range", 
    step=0.5
)

price_range = st.sidebar.slider("權證買價範圍 (元)", 0.0, 20.0, key="price_range", step=0.1)
max_spread = st.sidebar.slider("價差比 (小數) ≤", 0.0, 0.1, key="max_spread", step=0.001, format="%.3f")
max_iv_change = st.sidebar.slider("相對變動率 ≤ (%)", 0.0, 50.0, key="max_iv_change", step=0.5)

if st.sidebar.button("🔄 一鍵還原專屬預設", on_click=reset_defaults, type="primary", use_container_width=True):
    pass

# 資料輸入方式選擇
st.markdown("### 📥 資料輸入來源")
input_method = st.radio("選擇資料輸入方式：", ["上傳 Excel 檔案", "直接貼上 CMoney 表格文字"], horizontal=True)

df = None

if input_method == "上傳 Excel 檔案":
    uploaded_file = st.file_uploader("請上傳從 CMoney 複製並整理好的 Excel 檔案 (.xlsx)", type=["xlsx", "xls"])
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            st.success("✅ 成功讀取上傳的 Excel 檔案！")
        except Exception as e:
            st.error(f"讀取 Excel 失敗: {e}")
else:
    st.info("💡 請前往 [CMoney 權證頁面](https://www.cmoney.tw/finance/warrantsbystock.aspx?stock=2330)，將表格反白複製，然後直接貼到下方的文字框中：")
    raw_text = st.text_area("在此貼上複製的表格內容（支援 Tab 分隔的表格格式）：", height=150)
    if raw_text:
        try:
            df = pd.read_csv(StringIO(raw_text), sep="\t")
            st.success("✅ 成功解析貼上的表格文字！")
        except Exception as e:
            st.error(f"解析文字失敗，請確保是從網頁直接複製的表格: {e}")

# 5. 資料處理與篩選呈現
if df is not None and not df.empty:
    df = normalize_and_clean_data(df)
    
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
        st.warning("⚠️ 在目前篩選條件下無符合權證，以下顯示符合買價範圍之原始資料：")
        filtered_df = df[cond_price].copy()

    # 依差槓比由小到大 (升冪) 排序
    if "差槓比" in filtered_df.columns:
        filtered_df = filtered_df.sort_values(by="差槓比", ascending=True)

    st.markdown(f"### 🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)")

    display_cols = [
        "權證代碼", "名稱", "買價", "賣價", "成交價",
        "即時委賣 IV", "昨日委賣 IV", "價內外（％）", "剩餘天數",
        "行使比例", "履約價", "即時槓桿", "價差比", "差槓比"
    ]

    valid_display_cols = [c for c in display_cols if c in filtered_df.columns]

    st.dataframe(
        filtered_df[valid_display_cols],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.warning("👉 請先於上方「上傳 Excel 檔案」或「直接貼上 CMoney 表格文字」以載入權證數據。")
