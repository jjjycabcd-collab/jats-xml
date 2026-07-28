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
        st.stop() # 에러 발생 시 아래 코드 실행 중단

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
    
    # PDF 페이지를 렌더링 (해상도를 높이기 위해 zoom 적용)
    zoom = 2.0  
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    
    # 3. 화면 분할 출력 및 데이터 처리
    st.markdown("---")
    col_img, col_data = st.columns([5, 5]) # 화면을 5:5 비율로 분할
    
    # JATS 1.3 규격에 맞춘 상세 매칭 데이터 (생략 없이 전체 데이터 출력)
    sample_data = [
        {"category": "Front", "tag": "journal-title", "text": "Journal of Korean Library and Information Science Society", "page": 0, "bbox": "[70, 80, 250, 100]", "status": "✅ 99%"},
        {"category": "Front", "tag": "article-title", "text": "공공도서관 장서개발에 영향을 미치는 요인 분석에 관한 연구", "page": 0, "bbox": "[100, 150, 500, 180]", "status": "✅ 98%"},
        {"category": "Front", "tag": "contrib", "text": "박윤서, 남영준", "page": 0, "bbox": "[350, 200, 480, 220]", "status": "✅ 95%"},
        {"category": "Front", "tag": "abstract", "text": "본 연구의 목적은 공공도서관 장서개발에 영향을 미치는 요인을 분석하기 위함이다. 이를 위해 공공도서관 사서를 대상으로 인식조사를 시행하여...", "page": 0, "bbox": "[70, 250, 500, 350]", "status": "⚠️ 줄바꿈 오류"},
        {"category": "Front", "tag": "kwd-group", "text": "공공도서관, 장서개발, 사서, 도서, 참고정보원, 영향요인", "page": 0, "bbox": "[70, 360, 500, 380]", "status": "✅ 100%"},
        {"category": "Body", "tag": "sec", "text": "1. 서론", "page": 0, "bbox": "[70, 400, 200, 420]", "status": "✅ 100%"},
        {"category": "Body", "tag": "p", "text": "지식정보사회의 도래와 함께 도서관의 역할이 크게 변화하고 있다...", "page": 0, "bbox": "[70, 430, 500, 550]", "status": "✅ 96%"},
        {"category": "Back", "tag": "ref-list", "text": "박윤서 (2020). 장서평가론. 한국도서관협회.", "page": 1, "bbox": "None", "status": "❌ 좌표 누락"}
    ]
    
    df = pd.DataFrame(sample_data)
    selected_row_data = None

    # 우측 패널 (데이터 테이블 및 상세 정보) 먼저 렌더링하여 선택 이벤트를 캡처
    with col_data:
        st.subheader("📊 JATS 1.3 매칭 데이터 상세 검수")
        st.info("💡 `article-meta`, `journal-meta`, `abstract` 등의 메타데이터 영역입니다.")
        
        # 선택 가능한 데이터프레임 렌더링 (height를 지정하여 부분 스크롤 활성화)
        event = st.dataframe(
            df,
            use_container_width=True,
            height=300, 
            on_select="rerun", # 행을 클릭하면 화면을 다시 그림
            selection_mode="single-row"
        )
        
        # 클릭된 행의 인덱스를 통해 상세 데이터 추출
        if len(event.selection.rows) > 0:
            selected_idx = event.selection.rows[0]
            selected_row_data = df.iloc[selected_idx].to_dict()

        # 학습용 JSON 다운로드 버튼 이전에 선택된 상세 정보 출력
        st.markdown("<br>", unsafe_allow_html=True)
        if selected_row_data:
            st.markdown("##### 📌 선택된 추출 정보 전체 데이터")
            st.json(selected_row_data)
        else:
            st.markdown("##### 📌 선택된 추출 정보 전체 데이터")
            st.caption("위 테이블에서 행을 클릭하면 해당 데이터의 상세 JSON이 표시됩니다.")
            
        st.markdown("---")
        
        # JSON 다운로드 버튼
        json_data = json.dumps(sample_data, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 학습용 JSON 데이터세트 다운로드",
            data=json_data,
            file_name="labeled_jats_data.json",
            mime="application/json",
            type="primary"
        )

    # 좌측 패널 (PDF 렌더링 및 바운딩 박스)
    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        
        # PIL 이미지 변환 및 Draw 객체 생성
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)
        
        # 1. 모든 데이터의 바운딩 박스를 붉은색으로 그리기
        for idx, row in df.iterrows():
            bbox_str = row['bbox']
            if bbox_str != "None" and row['page'] == page_num:
                bbox = ast.literal_eval(bbox_str)
                scaled_bbox = [b * zoom for b in bbox]
                draw.rectangle(scaled_bbox, outline="red", width=2)
                
        # 2. 선택된 행이 있다면 파란색 굵은 테두리로 강조 표시하여 덮어 그리기
        if selected_row_data and selected_row_data['bbox'] != "None" and selected_row_data['page'] == page_num:
            bbox = ast.literal_eval(selected_row_data['bbox'])
            scaled_bbox = [b * zoom for b in bbox]
            draw.rectangle(scaled_bbox, outline="blue", width=5) # 두께를 5로 주어 확연히 눈에 띄게 처리
            
        # 완성된 이미지를 출력
        st.image(img, use_container_width=True)
