import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json

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
    
    # PIL 이미지 변환 및 Draw 객체 생성
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(img)
    
    # 텍스트 블록 및 좌표 추출 
    # (실제 환경에서는 XML 텍스트와 매칭된 특정 좌표만 그려야 하지만, 현재는 시각화 확인을 위해 PDF의 모든 텍스트 블록을 표시합니다)
    blocks = page.get_text("dict")["blocks"]
    
    for block in blocks:
        if "lines" in block:
            # 원본 PDF 좌표에 zoom 비율 반영
            b = block["bbox"]
            scaled_bbox = [b[0]*zoom, b[1]*zoom, b[2]*zoom, b[3]*zoom]
            
            # 붉은색 바운딩 박스 그리기
            draw.rectangle(scaled_bbox, outline="red", width=2)
    
    # 3. 화면 분할 출력 (좌측: 렌더링된 PDF 이미지, 우측: 매칭 데이터 패널)
    st.markdown("---")
    col_img, col_data = st.columns([5, 5]) # 화면을 5:5 비율로 분할
    
    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        # 컨테이너 너비에 맞춰 이미지 출력
        st.image(img, use_container_width=True)
        
    with col_data:
        st.subheader("📊 JATS 1.3 매칭 데이터 상세 검수")
        st.caption("XML 태그와 PDF 바운딩 박스 간의 매핑 상태를 확인하고 수정할 수 있습니다.")
        
        # JATS 1.3 규격에 맞춘 가상의 상세 매칭 데이터 (실제 매칭 로직 연동 시 이 부분을 교체)
        sample_data = [
            {"category": "Front", "tag": "journal-title", "text": "Journal of Korean Library...", "page": 0, "bbox": "[70, 80, 250, 100]", "status": "✅ 99%"},
            {"category": "Front", "tag": "article-title", "text": "공공도서관 장서개발에 영향을 미치는...", "page": 0, "bbox": "[100, 150, 500, 180]", "status": "✅ 98%"},
            {"category": "Front", "tag": "contrib", "text": "박윤서, 남영준", "page": 0, "bbox": "[350, 200, 480, 220]", "status": "✅ 95%"},
            {"category": "Front", "tag": "abstract", "text": "본 연구는 공공도서관의...", "page": 0, "bbox": "[70, 250, 500, 350]", "status": "⚠️ 줄바꿈 오류"},
            {"category": "Front", "tag": "kwd-group", "text": "공공도서관, 장서개발, 사서", "page": 0, "bbox": "[70, 360, 500, 380]", "status": "✅ 100%"},
            {"category": "Body", "tag": "sec", "text": "1. 서론", "page": 0, "bbox": "[70, 400, 200, 420]", "status": "✅ 100%"},
            {"category": "Body", "tag": "p", "text": "지식정보사회의 도래와 함께...", "page": 0, "bbox": "[70, 430, 500, 550]", "status": "✅ 96%"},
            {"category": "Back", "tag": "ref-list", "text": "박윤서 (2020). 장서평가론...", "page": 1, "bbox": "None", "status": "❌ 좌표 누락"}
        ]

        # 탭을 활용하여 JATS 구조(Front/Body/Back)별로 데이터 분리
        tab_all, tab_front, tab_body, tab_back = st.tabs(["전체", "Front (메타)", "Body (본문)", "Back (참고문헌 등)"])

        with tab_all:
            # 상태 요약 메트릭
            metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
            metrics_col1.metric("총 추출 태그", f"{len(sample_data)}개")
            metrics_col2.metric("매칭 성공", "6개")
            metrics_col3.metric("검토 필요", "2개", delta="-2", delta_color="inverse")
            
            # 전체 데이터 에디터 (UI 상에서 직접 텍스트나 박스 좌표 수정 가능)
            edited_df = st.data_editor(
                sample_data,
                column_config={
                    "category": st.column_config.SelectboxColumn("영역", options=["Front", "Body", "Back"], required=True),
                    "tag": st.column_config.TextColumn("JATS 태그", help="XML 태그명"),
                    "text": st.column_config.TextColumn("추출 텍스트", width="large"),
                    "page": st.column_config.NumberColumn("페이지", min_value=0),
                    "bbox": st.column_config.TextColumn("바운딩 박스 (x0, y0, x1, y1)"),
                    "status": st.column_config.SelectboxColumn("상태", options=["✅ 99%", "✅ 98%", "✅ 96%", "✅ 95%", "✅ 100%", "⚠️ 줄바꿈 오류", "❌ 좌표 누락"])
                },
                use_container_width=True,
                num_rows="dynamic"
            )

        with tab_front:
            front_data = [d for d in sample_data if d["category"] == "Front"]
            st.dataframe(front_data, use_container_width=True)
            st.info("💡 `article-meta`, `journal-meta`, `abstract` 등의 메타데이터 영역입니다.")

        with tab_body:
            body_data = [d for d in sample_data if d["category"] == "Body"]
            st.dataframe(body_data, use_container_width=True)
            st.info("💡 `sec`, `p`, `fig`, `table-wrap` 등 논문 본문 및 시각자료 영역입니다.")

        with tab_back:
            back_data = [d for d in sample_data if d["category"] == "Back"]
            st.dataframe(back_data, use_container_width=True)
            st.info("💡 `ref-list`, `app` 등 참고문헌 및 부록 영역입니다.")

        st.markdown("---")
        
        # JSON 다운로드 버튼 (검수 완료된 edited_df를 변환)
        json_data = json.dumps(edited_df, ensure_ascii=False, indent=2)
        st.download_button(
            label="💾 학습용 JSON 데이터세트 다운로드",
            data=json_data,
            file_name="labeled_jats_data.json",
            mime="application/json",
            type="primary"
        )
