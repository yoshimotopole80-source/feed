import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import gspread
from google.oauth2 import service_account
import json
import hashlib
import os

# --- Streamlit アプリケーションのメインコード ---
# Streamlitのページ設定
st.set_page_config(layout="wide", page_title="飼料消費量ダッシュボード")

st.title("飼料消費量ダッシュボード")

st.write("Googleスプレッドシートから飼料消費量データを表示します。")

# バージョン情報を定義
__version__ = "0.7.1"

# サイドバーにバージョンを表示
st.sidebar.markdown(f"**バージョン：{__version__}**")

# --- コールバック関数 ---
def on_select_all_toggle():
    """
    "すべて選択/解除" チェックボックスがトグルされたときのコールバック。
    すべてのデバイスの選択状態を更新します。
    """
    all_actual_device_options = sorted(st.session_state.filtered_device_options)
    if st.session_state.toggle_all_checkbox:
        st.session_state.selected_devices = set(all_actual_device_options)
    else:
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

    all_actual_device_options = sorted(st.session_state.filtered_device_options)
    if len(st.session_state.selected_devices) == len(all_actual_device_options) and len(all_actual_device_options) > 0:
        st.session_state.toggle_all_checkbox = True
    else:
        st.session_state.toggle_all_checkbox = False

# Googleスプレッドシートへの接続
@st.cache_data(ttl="10m")
def load_data_from_gsheets():
    """
    Googleスプレッドシートからデータを読み込みます。
    ローカルでは secrets.toml、Cloud Run では環境変数を使用します。
    """
    try:
        # secrets.tomlを試行。ローカル開発時はこちらが使われる
        gsheets_secrets = st.secrets.gsheets
    except AttributeError:
        # secrets.tomlが見つからない場合、環境変数を試行
        # Cloud Runにデプロイされた場合はこちらが使われる
        gsheets_secrets = os.environ
    except Exception as e:
        st.error(f"認証情報の読み込み中に予期せぬエラーが発生しました: {e}")
        st.stop()
        return pd.DataFrame()

    try:
        # 認証情報とスプレッドシートの情報を取得
        private_key = gsheets_secrets["GSHEETS_PRIVATE_KEY"].replace(r'\n', '\n')
        spreadsheet_url = gsheets_secrets.get("GSHEETS_SPREADSHEET_URL")
        spreadsheet_name = gsheets_secrets.get("GSHEETS_SPREADSHEET_NAME")

        credentials_info = {
            "type": gsheets_secrets["GSHEETS_TYPE"],
            "project_id": gsheets_secrets["GSHEETS_PROJECT_ID"],
            "private_key_id": gsheets_secrets["GSHEETS_PRIVATE_KEY_ID"],
            "private_key": private_key,
            "client_email": gsheets_secrets["GSHEETS_CLIENT_EMAIL"],
            "client_id": gsheets_secrets["GSHEETS_CLIENT_ID"],
            "auth_uri": gsheets_secrets["GSHEETS_AUTH_URI"],
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": gsheets_secrets["GSHEETS_CLIENT_X509_CERT_URL"]
        }

        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=scope)
        client = gspread.authorize(creds)

        if spreadsheet_url:
            spreadsheet = client.open_by_url(spreadsheet_url)
        elif spreadsheet_name:
            spreadsheet = client.open(spreadsheet_name)
        else:
            raise KeyError("GSHEETS_SPREADSHEET_URL or GSHEETS_SPREADSHEET_NAME not specified.")
        
        worksheet = spreadsheet.sheet1
        data = worksheet.get_all_values()
        
        df = pd.DataFrame(data[1:], columns=data[0])
        st.success("Googleスプレッドシートからデータを正常に読み込みました。")
        return df

    except KeyError as e:
        st.error(f"必要な認証情報が見つかりません。'{e.args[0]}' が不足しています。")
        st.info("secrets.toml または Cloud Runの環境変数が正しく設定されているか確認してください。")
        st.stop()
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Googleスプレッドシートへの接続中にエラーが発生しました: {e}")
        st.stop()
        return pd.DataFrame()

df = load_data_from_gsheets()

if df.empty:
    st.warning("スプレッドシートにデータがありません。")
    st.stop()

date_column_name = df.columns[0]
try:
    df[date_column_name] = pd.to_datetime(df[date_column_name], errors='coerce')
    df = df.dropna(subset=[date_column_name])
    df = df.rename(columns={date_column_name: '日付'})
except Exception as e:
    st.error(f"日付列の変換中にエラーが発生しました: {e}")
    st.info("スプレッドシートの最初の列が日付形式であることを確認してください。")
    st.stop()

device_columns = [col for col in df.columns if col != '日付']
if not device_columns:
    st.warning("日付列以外のデバイスIDの列が見つかりません。")
    st.stop()

for col in device_columns:
    df[col] = df[col].astype(str)

df_melted = df.melt(id_vars=['日付'], value_vars=device_columns, var_name='デバイスID', value_name='消費量')

df_melted['消費量'] = pd.to_numeric(df_melted['消費量'], errors='coerce')
df_melted = df_melted.dropna(subset=['消費量'])

st.sidebar.header("フィルターオプション")

min_date_overall = df_melted['日付'].min().date()
max_date_overall = df_melted['日付'].max().date()

if 'start_date' not in st.session_state:
    st.session_state.start_date = min_date_overall
if 'end_date' not in st.session_state:
    st.session_state.end_date = max_date_overall

start_date_input = st.sidebar.date_input(
    "開始日を選択",
    value=st.session_state.start_date,
    min_value=min_date_overall,
    max_value=max_date_overall,
    key='start_date_picker'
)

end_date_input = st.sidebar.date_input(
    "終了日を選択",
    value=st.session_state.end_date,
    min_value=min_date_overall,
    max_value=max_date_overall,
    key='end_date_picker'
)

if start_date_input > end_date_input:
    st.sidebar.error("開始日は終了日より前に設定してください。")
    filtered_df = pd.DataFrame()
else:
    st.session_state.start_date = start_date_input
    st.session_state.end_date = end_date_input
    filtered_df = df_melted[
        (df_melted['日付'].dt.date >= st.session_state.start_date) &
        (df_melted['日付'].dt.date <= st.session_state.end_date)
    ]

all_actual_device_options = sorted(filtered_df['デバイスID'].unique().tolist())

st.session_state.filtered_device_options = all_actual_device_options

if 'selected_devices' not in st.session_state:
    st.session_state.selected_devices = set()

st.session_state.selected_devices = {
    device for device in st.session_state.selected_devices
    if device in all_actual_device_options
}

initial_toggle_all_value = (len(st.session_state.selected_devices) == len(all_actual_device_options) and len(all_actual_device_options) > 0)

if 'toggle_all_checkbox' not in st.session_state or st.session_state.toggle_all_checkbox != initial_toggle_all_value:
    st.session_state.toggle_all_checkbox = initial_toggle_all_value

st.sidebar.checkbox(
    "すべて選択/解除",
    value=st.session_state.toggle_all_checkbox,
    key="toggle_all_checkbox",
    on_change=on_select_all_toggle
)

st.sidebar.write("---")

for device_id in all_actual_device_options:
    st.sidebar.checkbox(
        device_id,
        value=device_id in st.session_state.selected_devices,
        key=f"device_checkbox_{device_id}",
        on_change=on_individual_device_checkbox_change,
        args=(device_id,)
    )

selected_devices_final = list(st.session_state.selected_devices)

if not selected_devices_final:
    df_to_plot = pd.DataFrame()
else:
    df_to_plot = filtered_df[filtered_df['デバイスID'].isin(selected_devices_final)]

if df_to_plot.empty:
    if not selected_devices_final:
        st.info("サイドバーからデバイスを選択してください。")
    else:
        st.warning("選択されたフィルター条件に一致するデータがありません。")
else:
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
        category_orders={"デバイスID": sorted(total_consumption_by_device['デバイスID'].unique().tolist())}
    )
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
