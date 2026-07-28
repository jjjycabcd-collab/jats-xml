import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET

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
    
    # 텍스트 블록 및 좌표 추출 (현재는 PDF 전체 텍스트 블록을 시각화)
    # *향후 이 부분에 XML 텍스트와의 매칭 알고리즘이 추가되어야 합니다.*
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
    col_img, col_data = st.columns([6, 4])
    
    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        # 컨테이너 너비에 맞춰 이미지 출력
        st.image(img, use_container_width=True)
        
    with col_data:
        st.subheader("📊 매칭 데이터 확인 및 검수")
        st.info("💡 이곳에 XML에서 추출한 구조화된 텍스트/태그 정보와 PDF의 바운딩 박스 좌표 정보를 매칭한 테이블(st.data_editor)이 표시됩니다.")
        
        # 향후 데이터 구조 예시 렌더링
        sample_data = [
            {"label": "article-title", "text": "논문 제목 예시입니다", "bbox": "[70, 80, 500, 110]", "status": "✅ 매칭 성공"},
            {"label": "abstract", "text": "본 연구는...", "bbox": "[70, 120, 500, 200]", "status": "✅ 매칭 성공"},
            {"label": "ref", "text": "참고문헌 텍스트...", "bbox": "None", "status": "⚠️ 매칭 실패(좌표 없음)"}
        ]
        st.dataframe(sample_data, use_container_width=True)
        
        st.button("AI 학습용 JSON 다운로드 (준비 중)", disabled=True)
