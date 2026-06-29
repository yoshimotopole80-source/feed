import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from google.cloud import firestore
import os
import json

# --- Streamlit 設定 ---
st.set_page_config(layout="wide", page_title="飼料消費量ダッシュボード")

__version__ = "0.9.0"
st.sidebar.markdown(f"**バージョン：{__version__}**")

# --- Firestore クライアント初期化関数 ---
def get_firestore_client():
    key_path = "service_account.json"
    if os.path.exists(key_path):
        return firestore.Client.from_service_account_json(key_path)
    else:
        json_text = os.getenv("FIREBASE_SERVICE_ACCOUNT")
        if json_text:
            return firestore.Client.from_service_account_info(json.loads(json_text))
    return firestore.Client()

# --- マスタデータ読み込み関数 ---
@st.cache_data(ttl="1h") # マスタは頻繁に変わらないので1時間キャッシュ
def load_device_master():
    try:
        db = get_firestore_client()
        docs = db.collection("device_master").stream()
        master_list = []
        for doc in docs:
            d = doc.to_dict()
            d["deviceId"] = doc.id  # ドキュメントIDをdeviceIdとして保持
            master_list.append(d)
        return pd.DataFrame(master_list)
    except Exception as e:
        st.error(f"マスタ読み込みエラー: {e}")
        return pd.DataFrame()

# --- 消費量データ読み込み関数 ---
@st.cache_data(ttl="10m")
def load_consumption_data():
    try:
        db = get_firestore_client()
        docs = db.collection("daily_summaries").order_by("date", direction="DESCENDING").stream()
        data_list = []
        for doc in docs:
            d = doc.to_dict()
            if "date" in d:
                d["日付"] = pd.to_datetime(d["date"])
            data_list.append(d)
        return pd.DataFrame(data_list)
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame()

# 1. データの読み込み
df_master = load_device_master()
df_raw = load_consumption_data()

if df_raw.empty or df_master.empty:
    st.warning("Firestoreのデータまたはデバイスマスタが読み込めません。")
    st.stop()

# 2. マスタデータと消費量データを紐付け（ここが重要！）
# daily_summariesのdeviceIdと、masterのdeviceIdを結合
df_merged = pd.merge(df_raw, df_master, on="deviceId", how="left")

# 紐付けが失敗した場合（マスタ未登録）の処理
df_merged["building_name"] = df_merged["building_name"].fillna(df_merged["deviceId"])
df_merged["farm_name"] = df_merged["farm_name"].fillna("未登録農場")

# --- サイドバー ---
st.sidebar.header("表示設定")
use_corrected = st.sidebar.toggle("確定値(Corrected)を表示する", key="use_corrected")
value_col = "correctedDailyConsumption" if use_corrected else "dailyConsumption"

# 農場選択フィルター（建物が多くなるので、まず農場で絞れるように追加）
farms = sorted(df_merged["farm_name"].unique().tolist())
selected_farm = st.sidebar.selectbox("農場を選択", farms)

# 建物選択フィルター（選択された農場の建物だけを表示）
buildings_in_farm = sorted(df_merged[df_merged["farm_name"] == selected_farm]["building_name"].unique().tolist())
selected_buildings = st.sidebar.multiselect("建物（棟）を選択", options=buildings_in_farm, default=buildings_in_farm)

# --- データフィルタリング ---
df_filtered = df_merged[
    (df_merged["farm_name"] == selected_farm) & 
    (df_merged["building_name"].isin(selected_buildings))
].copy()

# 3. 建物単位で集計（ここが「建物を基準にする」ポイント！）
# 同じ日の同じ建物の消費量を合計する
df_building_daily = df_filtered.groupby(['日付', 'farm_name', 'building_name'])[value_col].sum().reset_index()
df_building_daily = df_building_daily.rename(columns={value_col: "消費量"})

# --- グラフ描画 ---
st.subheader(f"{selected_farm} の建物別消費量")

# グラフ1: 建物別推移
fig_line = px.line(
    df_building_daily,
    x='日付',
    y='消費量',
    color='building_name',
    markers=True,
    title="建物ごとの日次消費量合計",
    labels={"building_name": "建物名"}
)
st.plotly_chart(fig_line, use_container_width=True)

# グラフ2: 建物別合計
st.subheader("建物別合計（期間内）")
total_by_building = df_building_daily.groupby('building_name')['消費量'].sum().reset_index()
fig_bar = px.bar(total_by_building, x='building_name', y='消費量', color='building_name')
st.plotly_chart(fig_bar, use_container_width=True)

# 生データ表示（マスタの内容も含めて表示）
st.subheader("詳細データプレビュー")
st.dataframe(df_filtered[["日付", "farm_name", "building_name", "silo_name", value_col]], use_container_width=True)