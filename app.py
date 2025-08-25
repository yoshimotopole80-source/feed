import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import gspread
from google.oauth2 import service_account
import json
import hashlib
# --- Streamlit アプリケーションのメインコード ---
# Streamlitのページ設定
st.set_page_config(layout="wide", page_title="飼料消費量ダッシュボード")

st.title("飼料消費量ダッシュボード")

st.write("Googleスプレッドシートから飼料消費量データを表示します。")

# バージョン情報を定義
__version__ = "0.5.0"

# サイドバーにバージョンを表示
st.sidebar.markdown(f"**バージョン：{__version__}**")


# --- コールバック関数 ---
def on_select_all_toggle():
    """
    "すべて選択/解除" チェックボックスがトグルされたときのコールバック。
    すべてのデバイスの選択状態を更新します。
    """
    # 現在利用可能なデバイスオプションを取得 (セッションステートから)
    all_actual_device_options = sorted(st.session_state.filtered_device_options)
    if st.session_state.toggle_all_checkbox:
        # "すべて選択"がチェックされたら、すべてのデバイスを選択状態にする
        st.session_state.selected_devices = set(all_actual_device_options)
    else:
        # "すべて選択"が解除されたら、すべてのデバイスの選択を解除する
        st.session_state.selected_devices = set()

def on_individual_device_checkbox_change(device_id):
    """
    個別のデバイスチェックボックスが変更されたときのコールバック。
    セッションステートの選択されたデバイスリストを更新し、
    "すべて選択/解除" チェックボックスの状態を同期します。
    """
    if st.session_state[f"device_checkbox_{device_id}"]:
        st.session_state.selected_devices.add(device_id)
    else:
        st.session_state.selected_devices.discard(device_id)

    # "すべて選択/解除" チェックボックスの状態を同期
    all_actual_device_options = sorted(st.session_state.filtered_device_options)
    if len(st.session_state.selected_devices) == len(all_actual_device_options) and len(all_actual_device_options) > 0:
        st.session_state.toggle_all_checkbox = True
    else:
        st.session_state.toggle_all_checkbox = False



# Googleスプレッドシートへの接続
# secrets.tomlファイルから認証情報を読み込みます
@st.cache_data(ttl="10m") # データを10分間キャッシュ
def load_data_from_gsheets():
    try:
        # secrets.tomlから認証情報を取得
        gsheets_secrets = st.secrets["gsheets"]

        # サービスアカウント認証情報の辞書を作成
        credentials_info = {
            "type": gsheets_secrets["type"],
            "project_id": gsheets_secrets["project_id"],
            "private_key_id": gsheets_secrets["private_key_id"],
            "private_key": gsheets_secrets["private_key"].replace("\\n", "\n"), # 改行コードを修正
            "client_email": gsheets_secrets["client_email"],
            "client_id": gsheets_secrets["client_id"],
            "auth_uri": gsheets_secrets["auth_uri"],
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": gsheets_secrets["client_x509_cert_url"]
        }

        # サービスアカウント認証情報を使ってGoogle APIにアクセス
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=scope)
        client = gspread.authorize(creds)

        # スプレッドシートのURLまたは名前を指定
        if "spreadsheet_url" in st.secrets["gsheets"]:
            spreadsheet_url = st.secrets["gsheets"]["spreadsheet_url"]
            spreadsheet = client.open_by_url(spreadsheet_url)
        elif "spreadsheet_name" in st.secrets["gsheets"]:
            spreadsheet_name = st.secrets["gsheets"]["spreadsheet_name"]
            spreadsheet = client.open(spreadsheet_name)
        else:
            st.error("secrets.tomlに 'spreadsheet_url' または 'spreadsheet_name' が指定されていません。")
            st.stop()

        # 最初のワークシートからすべてのデータを取得
        worksheet = spreadsheet.sheet1
        data = worksheet.get_all_values()

        # 最初の行をヘッダーとしてDataFrameを作成
        df = pd.DataFrame(data[1:], columns=data[0])
        st.success("Googleスプレッドシートからデータを正常に読み込みました。")
        return df

    except Exception as e:
        st.error(f"Googleスプレッドシートへの接続中にエラーが発生しました: {e}")
        st.info("secrets.tomlファイルにGoogle Sheetsの認証情報とスプレッドシートのURL/名前が正しく設定されているか確認してください。")
        st.stop()
        return pd.DataFrame() # エラー時は空のDataFrameを返す

df = load_data_from_gsheets()

# 日付列をdatetime型に変換（エラーを無視して無効な日付はNaTに）
if df.empty:
    st.warning("スプレッドシートにデータがありません。")
    st.stop()

date_column_name = df.columns[0]
try:
    df[date_column_name] = pd.to_datetime(df[date_column_name], errors='coerce')
    df = df.dropna(subset=[date_column_name]) # 日付がNaTの行を削除
    df = df.rename(columns={date_column_name: '日付'}) # 列名を「日付」に変更
except Exception as e:
    st.error(f"日付列の変換中にエラーが発生しました: {e}")
    st.info("スプレッドシートの最初の列が日付形式であることを確認してください。")
    st.stop()

# デバイスIDの列を取得（日付列を除くすべての列）
device_columns = [col for col in df.columns if col != '日付']
if not device_columns:
    st.warning("日付列以外のデバイスIDの列が見つかりません。")
    st.stop()

# ここが重要な変更点: デバイスIDの列を明示的に文字列型に変換
# これにより、長い数字のIDが浮動小数点数として丸められるのを防ぎます
for col in device_columns:
    df[col] = df[col].astype(str)

# データを「長い形式」に変換（Plotlyでのプロットに適した形式）
df_melted = df.melt(id_vars=['日付'], value_vars=device_columns, var_name='デバイスID', value_name='消費量')

# デバッグ用: デバイスID列のデータ型を確認 (必要に応じてコメントアウトを解除してください)
# st.write(f"df_melted['デバイスID'] dtype: {df_melted['デバイスID'].dtype}")

# 消費量列を数値型に変換（エラーを無視して無効な値はNaNに）
df_melted['消費量'] = pd.to_numeric(df_melted['消費量'], errors='coerce')
df_melted = df_melted.dropna(subset=['消費量']) # 消費量がNaNの行を削除

# サイドバーのフィルター
st.sidebar.header("フィルターオプション")

# 日付範囲入力の値をセッションステートで管理
min_date_overall = df_melted['日付'].min().date()
max_date_overall = df_melted['日付'].max().date()

# セッションステートに開始日と終了日が設定されていない場合、初期値を設定
if 'start_date' not in st.session_state:
    st.session_state.start_date = min_date_overall
if 'end_date' not in st.session_state:
    st.session_state.end_date = max_date_overall

# 開始日のカレンダー入力
start_date_input = st.sidebar.date_input(
    "開始日を選択",
    value=st.session_state.start_date,
    min_value=min_date_overall,
    max_value=max_date_overall,
    key='start_date_picker'
)

# 終了日のカレンダー入力
end_date_input = st.sidebar.date_input(
    "終了日を選択",
    value=st.session_state.end_date,
    min_value=min_date_overall,
    max_value=max_date_overall,
    key='end_date_picker'
)

# 選択された日付が不正な場合（開始日 > 終了日）のハンドリング
if start_date_input > end_date_input:
    st.sidebar.error("開始日は終了日より前に設定してください。")
    filtered_df = pd.DataFrame() # 不正な選択の場合、filtered_dfを空にする
else:
    # 選択された日付をセッションステートに保存
    st.session_state.start_date = start_date_input
    st.session_state.end_date = end_date_input

    # 選択された日付範囲でデータをフィルタリング
    filtered_df = df_melted[
        (df_melted['日付'].dt.date >= st.session_state.start_date) &
        (df_melted['日付'].dt.date <= st.session_state.end_date)
    ]

# デバイスID選択ボックス (チェックボックス)
all_actual_device_options = sorted(filtered_df['デバイスID'].unique().tolist())

# コールバック関数内で使用するために、利用可能なデバイスオプションをセッションステートに保存
st.session_state.filtered_device_options = all_actual_device_options

# セッションステートにデバイス選択が設定されていない場合、初期値を設定
if 'selected_devices' not in st.session_state:
    st.session_state.selected_devices = set() # 初期は空のセット

# オプションリストが変更された場合に、セッションステートの選択をクリーンアップ
st.session_state.selected_devices = {
    device for device in st.session_state.selected_devices
    if device in all_actual_device_options
}

# "すべて選択/解除" チェックボックスの初期状態を決定
initial_toggle_all_value = (len(st.session_state.selected_devices) == len(all_actual_device_options) and len(all_actual_device_options) > 0)

# セッションステートに 'toggle_all_checkbox' がない場合、または値が異なる場合に設定
if 'toggle_all_checkbox' not in st.session_state or st.session_state.toggle_all_checkbox != initial_toggle_all_value:
    st.session_state.toggle_all_checkbox = initial_toggle_all_value

# "すべて選択/解除" チェックボックスの表示
st.sidebar.checkbox(
    "すべて選択/解除",
    value=st.session_state.toggle_all_checkbox,
    key="toggle_all_checkbox",
    on_change=on_select_all_toggle
)

st.sidebar.write("---") # 区切り線

# 個別のデバイスIDチェックボックス
for device_id in all_actual_device_options:
    st.sidebar.checkbox(
        device_id,
        value=device_id in st.session_state.selected_devices,
        key=f"device_checkbox_{device_id}",
        on_change=on_individual_device_checkbox_change,
        args=(device_id,)
    )

# 最終的な選択されたデバイスリスト
selected_devices_final = list(st.session_state.selected_devices)

# フィルターロジックの調整:
# selected_devices_finalが空の場合（何も選択されていない場合）は、グラフを表示しない
if not selected_devices_final:
    df_to_plot = pd.DataFrame() # 空のDataFrameを設定し、グラフ表示をスキップさせる
else:
    df_to_plot = filtered_df[filtered_df['デバイスID'].isin(selected_devices_final)]

if df_to_plot.empty:
    # 選択されたデバイスがない場合、またはフィルター条件に一致するデータがない場合
    if not selected_devices_final: # デバイスが選択されていない場合
        st.info("サイドバーからデバイスを選択してください。")
    else: # デバイスが選択されているが、その条件でデータがない場合
        st.warning("選択されたフィルター条件に一致するデータがありません。")
else:
    # グラフの表示

    st.subheader("デバイスIDごとの日次消費量")
    fig_line = px.line(
        df_to_plot,
        x='日付',
        y='消費量',
        color='デバイスID',
        title='デバイスIDごとの日次消費量推移',
        labels={'消費量': '消費量', '日付': '日付'},
        hover_data={'日付': '|%Y年%m月%d日', '消費量': True, 'デバイスID': True}
    )
    fig_line.update_traces(mode='lines+markers')
    fig_line.update_layout(hovermode="x unified")
    st.plotly_chart(fig_line, use_container_width=True)

    st.subheader("デバイスID別合計消費量")
    total_consumption_by_device = df_to_plot.groupby('デバイスID')['消費量'].sum().reset_index()
    fig_bar = px.bar(
        total_consumption_by_device,
        x='デバイスID',
        y='消費量',
        title='デバイスID別合計消費量',
        labels={'消費量': '合計消費量', 'デバイスID': 'デバイスID'},
        color='消費量',
        color_continuous_scale=px.colors.sequential.Viridis,
        # ここでX軸をカテゴリとして明示的に指定します
        category_orders={"デバイスID": sorted(total_consumption_by_device['デバイスID'].unique().tolist())}
    )
    # PlotlyのX軸タイプをカテゴリに設定
    fig_bar.update_xaxes(type='category')
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("日次合計消費量")
    daily_total_consumption = df_to_plot.groupby('日付')['消費量'].sum().reset_index()
    fig_daily_total = px.area(
        daily_total_consumption,
        x='日付',
        y='消費量',
        title='日次合計消費量',
        labels={'消費量': '合計消費量', '日付': '日付'},
        hover_data={'日付': '|%Y年%m月%d日', '消費量': True}
    )
    fig_daily_total.update_layout(hovermode="x unified")
    st.plotly_chart(fig_daily_total, use_container_width=True)

    st.subheader("生データプレビュー")
    st.dataframe(df_to_plot)
