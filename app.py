import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.google.com/"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    
    # 檢查是否被轉址到驗證頁面或擋 IP
    if "Access Denied" in response.text or "Cloudflare" in response.text:
        st.error("存取被拒絕：目標網站已阻擋當前 IP，請考慮使用 Proxy 或備用資料源。")
        st.stop()
        
    # 解析表格邏輯...
except Exception as e:
    st.error(f"資料擷取失敗：{e}")
