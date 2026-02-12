import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from notion_client import Client
import os
import json
from datetime import datetime
import time

# ==========================================
# ⚙️ 사용자 설정 영역 (이 부분만 수정하세요)
# ==========================================

# 1. 분석할 아파트 단지 리스트 (이름: 원하는 대로, 코드: 네이버 단지번호)
TARGET_COMPLEXES = [
    {"name": "탑선경", "code": "2876"},
    {"name": "이매한신", "code": "2578"},
    # {"name": "원하는아파트명", "code": "단지번호"},  <- 계속 추가 가능
]

# 2. 수집할 거래 종류 (원하지 않는 것은 주석처리 # 하세요)
TARGET_TRADE_TYPES = {
    "A1": "매매",
    "B1": "전세",
    "B2": "월세"
}

# ==========================================

# GitHub Secrets 로드
GOOGLE_JSON = json.loads(os.environ['GOOGLE_CREDENTIALS'])
SHEET_URL = os.environ['SHEET_URL']
NOTION_TOKEN = os.environ['NOTION_TOKEN']
NOTION_PAGE_ID = os.environ['NOTION_PAGE_ID']

def get_naver_listings(complex_name, complex_no, trade_type_code, trade_type_name):
    """특정 단지, 특정 거래 유형의 매물을 가져옵니다."""
    url = "https://m.land.naver.com/complex/getComplexArticleList"
    params = {
        "hscpNo": complex_no,
        "tradTpCd": trade_type_code,
        "order": "date_", # 최신순
        "showR0": "N",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        listing_list = data.get('result', {}).get('list', [])
    except Exception as e:
        print(f"Error fetching {complex_name}: {e}")
        return []

    processed_data = []
    for item in listing_list:
        processed_data.append({
            'complexName': complex_name,       # 단지명 (구분용)
            'tradeType': trade_type_name,      # 매매/전세/월세
            'articleNo': str(item['articleNo']), # 매물 ID (문자열로 통일)
            'articleName': item['articleName'],
            'buildingName': item['buildingName'],
            'floorInfo': item['floorInfo'],
            'dealOrWarrantPrc': item['dealOrWarrantPrc'],
            'areaName': item['areaName'],
            'direction': item['direction'],
            'cdate': datetime.now().strftime('%Y-%m-%d')
        })
    
    return processed_data

def connect_google_sheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    client = gspread.authorize(creds)
    doc = client.open_by_url(SHEET_URL)
    return doc

def analyze_changes(current_df, previous_df):
    report_lines = []
    
    if previous_df.empty:
        return ["초기 데이터가 구축되었습니다. 내일부터 변동 사항이 추적됩니다."]

    # 단지별로 그룹화하여 리포트 작성
    for complex_info in TARGET_COMPLEXES:
        comp_name = complex_info['name']
        
        # 해당 단지의 데이터만 필터링
        cur_comp = current_df[current_df['complexName'] == comp_name]
        prev_comp = previous_df[previous_df['complexName'] == comp_name]
        
        if cur_comp.empty and prev_comp.empty:
            continue

        comp_updates = []

        # 1) 신규 매물
        new_listings = cur_comp[~cur_comp['articleNo'].isin(prev_comp['articleNo'])]
        if not new_listings.empty:
            comp_updates.append(f"🆕 **신규 {len(new_listings)}건**")
            for _, row in new_listings.iterrows():
                comp_updates.append(f"  - [{row['tradeType']}] {row['buildingName']} {row['floorInfo']} ({row['areaName']}) : {row['dealOrWarrantPrc']}")

        # 2) 가격 변동
        merged = pd.merge(cur_comp, prev_comp, on='articleNo', suffixes=('_new', '_old'))
        price_changed = merged[merged['dealOrWarrantPrc_new'] != merged['dealOrWarrantPrc_old']]
        if not price_changed.empty:
            comp_updates.append(f"📉 **가격 변동 {len(price_changed)}건**")
            for _, row in price_changed.iterrows():
                comp_updates.append(f"  - [{row['tradeType_new']}] {row['buildingName_new']} {row['floorInfo_new']}: {row['dealOrWarrantPrc_old']} → **{row['dealOrWarrantPrc_new']}**")

        # 3) 거래 완료 (삭제됨)
        sold_listings = prev_comp[~prev_comp['articleNo'].isin(cur_comp['articleNo'])]
        if not sold_listings.empty:
            comp_updates.append(f"👋 **거래 완료/삭제 {len(sold_listings)}건**")

        # 단지별 리포트 추가
        if comp_updates:
            report_lines.append(f"### 🏢 {comp_name}") # Notion Heading 3 style
            report_lines.extend(comp_updates)
            report_lines.append("") # 공백 줄

    if not report_lines:
        report_lines.append("모든 단지에서 특이사항(신규/변동)이 없습니다.")

    return report_lines

def send_notion_report(report_lines):
    notion = Client(auth=NOTION_TOKEN)
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    children_blocks = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"📅 {today_str} 부동산 리포트"}}]}
        }
    ]
    
    for line in report_lines:
        # 헤딩(단지명) 처리
        if line.startswith("###"):
            children_blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": line.replace("### ", "")}}]}
            })
        else:
            children_blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
            })

    try:
        notion.blocks.children.append(block_id=NOTION_PAGE_ID, children=children_blocks)
        print("Notion Report Sent!")
    except Exception as e:
        print(f"Notion Error: {e}")

def main():
    print("데이터 수집 시작...")
    all_data = []

    # 설정된 모든 단지와 거래 유형 순회
    for complex in TARGET_COMPLEXES:
        for code, name in TARGET_TRADE_TYPES.items():
            print(f"- 수집중: {complex['name']} ({name})")
            data = get_naver_listings(complex['name'], complex['code'], code, name)
            all_data.extend(data)
            time.sleep(1) # 차단 방지용 딜레이
    
    df_today = pd.DataFrame(all_data)
    
    # 구글 시트 연결
    doc = connect_google_sheet()
    try:
        worksheet = doc.worksheet("Latest")
        data_prev = worksheet.get_all_records()
        df_prev = pd.DataFrame(data_prev)
        if not df_prev.empty:
            df_prev['articleNo'] = df_prev['articleNo'].astype(str)
    except gspread.WorksheetNotFound:
        df_prev = pd.DataFrame()
        worksheet = doc.add_worksheet(title="Latest", rows="1000", cols="20")

    if not df_today.empty:
        df_today['articleNo'] = df_today['articleNo'].astype(str)

    # 분석 및 전송
    print("분석 중...")
    report = analyze_changes(df_today, df_prev)
    
    print("리포트 전송 중...")
    send_notion_report(report)
    
    # 데이터 저장
    worksheet.clear()
    if not df_today.empty:
        worksheet.update([df_today.columns.values.tolist()] + df_today.values.tolist())
    
    print("완료!")

if __name__ == "__main__":
    main()