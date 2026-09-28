from datetime import datetime
from io import StringIO
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st
import urllib3

# 關閉不安全連線 (SSL) 的警告提示
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 頁面基本配置
st.set_page_config(
    page_title="專屬權證篩選系統",
    page_icon="📈",
    layout="wide"
)

# 1. 預設標準量化策略參數
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
    # 支援 URL 網址參數帶入 (例如 ?code=2330)
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
    st.toast("✅ 已還原為標準量化專屬策略條件！", icon="🔄")

# 2. 資料抓取與解析模組
@st.cache_data(ttl=300, show_spinner=False)
def fetch_warrants(stock_code: str):
    url = f"https://www.cmoney.tw/finance/warrantsbystock.aspx?stock={stock_code}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.cmoney.tw/finance/",
    }

    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=12)
        resp.encoding = "utf-8"
        
        if resp.status_code != 200:
            raise ValueError(f"伺服器回應異常，狀態碼：{resp.status_code}")
            
        html_text = resp.text
        
        # 檢查是否被雲端 IP 阻擋或出現驗證頁面
        if "Access Denied" in html_text or "Cloudflare" in html_text:
            raise PermissionError("目標網站目前限制雲端 IP 存取，請稍後重試。")

        # 使用 BeautifulSoup 輔助解析表格
        soup = BeautifulSoup(html_text, "html.parser")
        tables = soup.find_all("table")

        df = None
        if tables:
            # 使用 StringIO 包裹，避免 Pandas 2.0+ 將 HTML 字串誤判為檔案路徑
            parsed_tables = pd.read_html(StringIO(str(tables[0])))
            if parsed_tables:
                df = parsed_tables[0]
        else:
            parsed_tables = pd.read_html(StringIO(html_text))
            if parsed_tables:
                df = parsed_tables[0]

        if df is None or df.empty:
            raise ValueError("未讀取到權證數據表格，請確認標的代碼是否正確或該標的是否有發行權證。")

        # 資料清洗與欄位解析
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
        elif "價內外" in df.columns:
            df["價內外_數值"] = df["價內外"].apply(parse_moneyness)

        num_cols = ["賣價", "買價", "即時委賣 IV", "昨日委賣 IV", "價差比", "差槓比", "剩餘天數"]
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

    except Exception as e:
        raise e

# 3. 側邊欄控制面板
st.sidebar.header("⚙️ 篩選策略條件設定")
st.sidebar.button(
    "🔄 一鍵還原專屬預設",
    on_click=reset_defaults,
    type="primary",
    use_container_width=True,
)

stock_code = st.sidebar.text_input("標的股票代碼", key="stock_code")
min_days = st.sidebar.number_input(
    "剩餘天數 ≥ (天)", min_value=30, max_value=500, key="min_days"
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

# 4. 主頁面與數據呈現
st.title("📈 權證專屬量化篩選器")

col1, col2 = st.columns([3, 1])
with col1:
    st.subheader(f"當前查詢標的：{stock_code}")
with col2:
    if st.button("🔄 重新抓取盤中數據", use_container_width=True):
        st.cache_data.clear()
        st.toast("✅ 已清空快取並重新請求數據！", icon="🔄")

try:
    with st.spinner(f"正在擷取 {stock_code} 的權證數據中..."):
        df, update_time = fetch_warrants(stock_code)

    st.caption(f"⏱️ 數據更新時間：**{update_time}**（系統自動快取 5 分鐘，避免頻繁請求）")

    # 執行篩選條件
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
    cond_iv = df["IV相對變動率"] <= max_iv_change if "IV相對變動率" in df.columns else True

    filtered_df = df[
        cond_days & cond_money & cond_price & cond_spread & cond_chagang & cond_iv
    ].copy()

    if "賣價" in filtered_df.columns:
        filtered_df = filtered_df.sort_values(by="賣價", ascending=True)

    st.markdown(f"### 🎯 符合策略之精選權證 (共 {len(filtered_df)} 檔)")

    display_cols = [
        "權證名稱",
        "代號",
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

    st.dataframe(
        filtered_df[existing_cols] if existing_cols else filtered_df,
        use_container_width=True,
        hide_index=True,
    )

except Exception as e:
    st.error(f"❌ 擷取或處理資料時發生錯誤：{e}")
    st.info(
        "💡 **常見問題排查提示：**\n"
        "1. 請確保 GitHub 專案中的 `requirements.txt` 含有 `streamlit`, `pandas`, `requests`, `beautifulsoup4`, `lxml`, `urllib3`, `html5lib`。\n"
        "2. 若目標網站暫時阻擋雲端 IP 請求，可點擊上方『重新抓取盤中數據』重試。"
    )
