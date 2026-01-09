import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from google.cloud import firestore
import os
import json

# --- Streamlit アプリケーションのメイン設定 ---
st.set_page_config(layout="wide", page_title="飼料消費量ダッシュボード (Firestore版)")

st.title("飼料消費量ダッシュボード")
st.write("Firestoreから飼料消費量データをリアルタイム表示します。")

__version__ = "0.8.3"
st.sidebar.markdown(f"**バージョン：{__version__}**")

# --- セッション状態の初期化  ---
if 'selected_devices' not in st.session_state:
    st.session_state['selected_devices'] = []  # 初期値：全未選択

if 'use_corrected' not in st.session_state:
    st.session_state['use_corrected'] = True  # 初期値：確定値ON


# --- データ読み込み関数 ---
@st.cache_data(ttl="10m")
def load_data_from_firestore():
    """
    Firestoreの daily_summaries コレクションからデータを読み込みます。
    """
    try:
        # 1. 認証設定
        key_path = "service_account.json"
        
        if os.path.exists(key_path):
            # ローカル環境：ファイルから読み込む
            db = firestore.Client.from_service_account_json(key_path)
        else:
            # Cloud Run環境：環境変数から読み込む
            # 管理画面で設定する名前を "FIREBASE_SERVICE_ACCOUNT" と想定
            json_text = os.getenv("FIREBASE_SERVICE_ACCOUNT")
            if json_text:
                key_dict = json.loads(json_text)
                db = firestore.Client.from_service_account_info(key_dict)
            else:
                # どちらもない場合はデフォルト（権限エラーになる可能性あり）
                db = firestore.Client()

        # 2. データの取得
        docs = db.collection("daily_summaries").order_by("date", direction="DESCENDING").stream()
        
        data_list = []
        for doc in docs:
            d = doc.to_dict()
            # 日付文字列をdatetimeオブジェクトに変換
            if "date" in d:
                d["日付"] = pd.to_datetime(d["date"])
            data_list.append(d)
            
        if not data_list:
            return pd.DataFrame()
            
        return pd.DataFrame(data_list)

    except Exception as e:
        st.error(f"Firestoreへの接続中にエラーが発生しました: {e}")
        return pd.DataFrame()

# データの読み込み
df_raw = load_data_from_firestore()

if df_raw.empty:
    st.warning("表示できるデータがありません。")
    st.stop()

# --- サイドバー：フィルターオプション ---
st.sidebar.header("表示設定")

# 1. 確定値/暫定値の切り替えスイッチ(keyで管理)
use_corrected = st.sidebar.toggle("確定値(Corrected)を表示する", key="use_corrected", 
    help="ONにするとNanolikeから再送された確定値を使用します。"
)

# 表示に使う列を決定
value_col = "correctedDailyConsumption" if use_corrected else "dailyConsumption"
st.sidebar.info(f"現在表示中: {'確定値' if use_corrected else '暫定値'}")

# 2. 日付フィルター
min_date = df_raw["日付"].min().date()
max_date = df_raw["日付"].max().date()

start_date = st.sidebar.date_input("開始日", value=min_date, min_value=min_date, max_value=max_date)
end_date = st.sidebar.date_input("終了日", value=max_date, min_value=min_date, max_value=max_date)

# --- データフィルタリング ---
mask = (df_raw["日付"].dt.date >= start_date) & (df_raw["日付"].dt.date <= end_date)
df_filtered = df_raw.loc[mask].copy()

# 3. デバイスフィルター (keyのみで管理)
all_devices = sorted(df_filtered["deviceId"].unique().tolist())

selected_devices = st.sidebar.multiselect(
    "デバイス選択", 
    options=all_devices, 
    key="selected_devices"
)

# --- メインコンテンツの描画 ---
if not selected_devices:
    st.info("サイドバーからデバイスを選択してください。")
    st.stop()

# 最終的なプロット用データ
df_to_plot = df_filtered[df_filtered["deviceId"].isin(selected_devices)].copy()

# 列名を日本語に整える
df_to_plot = df_to_plot.rename(columns={
    "deviceId": "デバイスID",
    value_col: "消費量"
})

# グラフ1: デバイス別推移
st.subheader("デバイスIDごとの日次消費量")
fig_line = px.line(
    df_to_plot,
    x='日付',
    y='消費量',
    color='デバイスID',
    markers=True,
    title=f"{'確定' if use_corrected else '暫定'}消費量の推移",
    hover_data={'日付': '|%Y年%m月%d日', '消費量': ':.3f'}
)
fig_line.update_layout(hovermode="x unified")
st.plotly_chart(fig_line, use_container_width=True)

# グラフ2: デバイス別合計
col1, col2 = st.columns(2)

with col1:
    st.subheader("デバイス別合計")
    total_by_device = df_to_plot.groupby('デバイスID')['消費量'].sum().reset_index()
    fig_bar = px.bar(total_by_device, x='デバイスID', y='消費量', color='デバイスID')
    st.plotly_chart(fig_bar, use_container_width=True)

with col2:
    st.subheader("日次合計")
    daily_total = df_to_plot.groupby('日付')['消費量'].sum().reset_index()
    fig_area = px.area(daily_total, x='日付', y='消費量', title="全デバイスの合計消費量")
    st.plotly_chart(fig_area, use_container_width=True)

# 生データ表示
st.subheader("生データプレビュー")
st.dataframe(df_to_plot[["日付", "デバイスID", "消費量", "lastWeight", "lastCorrectedWeight"]], use_container_width=True)