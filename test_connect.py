import streamlit as st
from google.cloud import firestore
import pandas as pd
import os

# 1. Firestoreクライアントの初期化
# "service_account.json" をご自身の秘密鍵ファイル名に書き換えてください
# 同じフォルダに置いてあることを前提としています
KEY_PATH = "service_account.json" 

if not os.path.exists(KEY_PATH):
    st.error(f"エラー: 秘密鍵ファイル '{KEY_PATH}' が見つかりません。")
else:
    db = firestore.Client.from_service_account_json(KEY_PATH)

    st.title("🔥 Firestore 接続テスト")

    # 2. データの取得 (daily_summaries コレクションから日付の新しい順に10件)
    st.write("Firestoreから最新データを取得中...")
    
    try:
        docs = db.collection("daily_summaries").order_by("lastUpdate", direction="DESCENDING").limit(10).stream()

        # 3. 取得したデータをリストに格納
        data_list = []
        for doc in docs:
            d = doc.to_dict()
            # ドキュメントID（日付_デバイスID）も一応確認用に含める
            d["doc_id"] = doc.id 
            data_list.append(d)

        if data_list:
            # PandasのDataFrameに変換して表示
            df = pd.DataFrame(data_list)
            
            st.success("取得成功！")
            
            # 列の並びを人間が見やすいように調整（存在する場合のみ）
            cols = ["date", "dailyConsumption", "correctedDailyConsumption", "lastWeight", "lastCorrectedWeight"]
            existing_cols = [c for c in cols if c in df.columns]
            
            st.write("### 集計データプレビュー")
            st.dataframe(df[existing_cols] if existing_cols else df)
            
            st.write("### 全データ（デバッグ用JSON）")
            st.json(data_list)
        else:
            st.warning("データは見つかりましたが、中身が空かコレクション名が正しくない可能性があります。")
            
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")