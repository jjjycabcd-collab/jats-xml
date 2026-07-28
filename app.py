import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json
import pandas as pd
import ast

# 페이지 기본 설정 (와이드 레이아웃)
st.set_page_config(layout="wide", page_title="JATS XML-PDF 라벨링 검수 툴")
st.title("JATS XML - PDF 태깅 시각화 및 검수 도구")
st.markdown("PDF 원문과 JATS XML 데이터를 매칭하여 바운딩 박스를 시각적으로 확인합니다.")

# 1. 파일 업로드 창 2개 나란히 배치
col_up1, col_up2 = st.columns(2)
with col_up1:
    uploaded_pdf = st.file_uploader("PDF 원문 파일을 업로드하세요", type=["pdf"])
with col_up2:
    uploaded_xml = st.file_uploader("JATS XML 파일을 업로드하세요", type=["xml"])

# 2. 두 파일이 모두 업로드되었을 때만 핵심 로직 실행
if uploaded_pdf and uploaded_xml:
    
    # XML 파싱 테스트
    try:
        tree = ET.parse(uploaded_xml)
        root = tree.getroot()
        st.success("✅ XML 및 PDF 파일이 성공적으로 로드되었습니다.")
    except Exception as e:
        st.error(f"❌ XML 파일을 읽는 중 오류가 발생했습니다: {e}")
        st.stop() 

    # PyMuPDF로 PDF 스트림 읽기
    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    # 사이드바: 페이지 네비게이션
    st.sidebar.header("네비게이션")
    page_num = st.sidebar.number_input(
        f"페이지 번호 (0 ~ {len(doc)-1})", 
        min_value=0, 
        max_value=len(doc)-1, 
        value=0
    )
    page = doc[page_num]
    
    st.markdown("---")
    # 3. 화면 분할 출력
    col_img, col_data = st.columns([5, 5]) 
    
    # 가상의 샘플 매칭 데이터 (실제 데이터로 교체 필요)
    # 반영: 저자소개(bio) 제외, 참고문헌(ref-list) 우선 추출 규칙 적용
    sample_data = [
        {"category": "Front", "tag": "journal-title", "text": "Journal of Korean Library and Information Science Society", "page": 0, "bbox": "[70, 80, 450, 100]", "status": "✅ 99%"},
        {"category": "Front", "tag": "article-title", "text": "공공도서관 장서개발에 영향을 미치는 요인 분석에 관한 연구", "page": 0, "bbox": "[100, 150, 500, 180]", "status": "✅ 98%"},
        {"category": "Front", "tag": "contrib", "text": "박윤서, 남영준", "page": 0, "bbox": "[350, 200, 480, 220]", "status": "✅ 95%"},
        {"category": "Front", "tag": "abstract", "text": "본 연구의 목적은 공공도서관 장서개발에 영향을 미치는 요인을 분석하기 위함이다...", "page": 0, "bbox": "[70, 250, 500, 350]", "status": "⚠️ 줄바꿈 오류"},
        {"category": "Front", "tag": "kwd-group", "text": "공공도서관, 장서개발, 사서, 도서, 참고정보원, 영향요인", "page": 0, "bbox": "[70, 360, 500, 380]", "status": "✅ 100%"},
        {"category": "Body", "tag": "sec", "text": "1. 서론", "page": 0, "bbox": "[70, 400, 200, 420]", "status": "✅ 100%"},
        {"category": "Body", "tag": "p", "text": "지식정보사회의 도래와 함께 도서관의 역할이 크게 변화하고 있다...", "page": 0, "bbox": "[70, 430, 500, 550]", "status": "✅ 96%"},
        {"category": "Back", "tag": "ref-list", "text": "박윤서 (2020). 장서평가론. 한국도서관협회.", "page": 0, "bbox": "[70, 600, 500, 650]", "status": "✅ 100%"} 
    ]
    
    df = pd.DataFrame(sample_data)
    selected_row_data = None

    # 우측 패널: 데이터 탭 분리 및 선택 로직
    with col_data:
        st.subheader("📊 JATS 1.3 매칭 데이터 상세 검수")
        
        # JATS 구조에 따른 탭 생성
        tab_front, tab_body, tab_back = st.tabs(["Front (메타)", "Body (본문)", "Back (참고문헌 등)"])
        
        # Front 탭
        with tab_front:
            df_front = df[df["category"] == "Front"].reset_index(drop=True)
            event_front = st.dataframe(df_front, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row")
            if len(event_front.selection.rows) > 0:
                selected_row_data = df_front.iloc[event_front.selection.rows[0]].to_dict()
                
        # Body 탭
        with tab_body:
            df_body = df[df["category"] == "Body"].reset_index(drop=True)
            event_body = st.dataframe(df_body, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row")
            if len(event_body.selection.rows) > 0:
                selected_row_data = df_body.iloc[event_body.selection.rows[0]].to_dict()
                
        # Back 탭
        with tab_back:
            df_back = df[df["category"] == "Back"].reset_index(drop=True)
            event_back = st.dataframe(df_back, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row")
            if len(event_back.selection.rows) > 0:
                selected_row_data = df_back.iloc[event_back.selection.rows[0]].to_dict()

        st.markdown("---")
        st.markdown("##### 📌 선택된 추출 정보 전체 데이터")
        
        # 부분 스크롤이 적용되는 고정 높이 컨테이너 생성
        json_container = st.container(height=200)
        with json_container:
            if selected_row_data:
                st.json(selected_row_data) # 생략 없이 전체 내용 출력
            else:
                st.info("위 탭의 데이터 테이블에서 행을 클릭하면 해당 데이터의 상세 정보가 이곳에 표시됩니다.")
                
        st.markdown("---")
        # JSON 다운로드 버튼
        json_data_str = json.dumps(sample_data, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 학습용 JSON 데이터세트 다운로드",
            data=json_data_str,
            file_name="labeled_jats_data.json",
            mime="application/json",
            type="primary"
        )

    # 좌측 패널: PDF 시각화 및 클릭 시 바운딩 박스 강조
    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        
        # 해상도를 높여 PDF 렌더링
        zoom = 2.0  
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)
        
        # 1. 탭/선택 여부와 무관하게 모든 바운딩 박스를 붉은색으로 그리기
        for idx, row in df.iterrows():
            bbox_str = row['bbox']
            if bbox_str != "None" and row['page'] == page_num:
                try:
                    bbox = ast.literal_eval(bbox_str)
                    scaled_bbox = [b * zoom for b in bbox]
                    draw.rectangle(scaled_bbox, outline="red", width=2)
                except:
                    pass
                
        # 2. 행이 클릭(선택)된 경우 파란색 두꺼운 박스로 덮어 그리기
        if selected_row_data and selected_row_data['bbox'] != "None" and selected_row_data['page'] == page_num:
            try:
                bbox = ast.literal_eval(selected_row_data['bbox'])
                scaled_bbox = [b * zoom for b in bbox]
                draw.rectangle(scaled_bbox, outline="blue", width=5)
            except:
                pass
            
        st.image(img, use_container_width=True)
        st.caption("※ 알림: 좌표가 원문과 맞지 않는다면, 코드 내 `sample_data`의 임의 좌표가 화면에 표시되었기 때문입니다. 실제 추출 좌표가 연동되면 정상적으로 그려집니다.")
