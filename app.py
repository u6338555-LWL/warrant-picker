df, status_code, raw_preview, update_time, source_used = fetch_warrants(stock_code)

if df is not None:

    st.write("資料筆數")
    st.write(len(df))

    st.write("欄位名稱")
    st.write(df.columns.tolist())

    st.write("前20筆資料")
    st.dataframe(df.head(20))

else:
    st.error("抓取失敗")
