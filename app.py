import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw

st.set_page_config(layout="wide")
st.title("JATS XML - PDF 태깅 시각화 도구")

# 1. 파일 업로드
uploaded_pdf = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
# uploaded_xml = st.file_uploader("JATS XML 파일을 업로드하세요", type=["xml"])

if uploaded_pdf:
    # PyMuPDF로 PDF 읽기
    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    # 페이지 선택
    page_num = st.sidebar.number_input("페이지 번호", min_value=0, max_value=len(doc)-1, value=0)
    page = doc[page_num]
    
    # 2. PDF 페이지를 이미지로 변환 (시각화를 위해 해상도 높임)
    zoom = 2  
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    
    # PIL 이미지로 변환
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(img)
    
    # 3. 텍스트 블록 및 좌표 추출 (임시 매칭 시뮬레이션)
    # 실제로는 이 부분에 XML 텍스트와 매칭하는 알고리즘이 들어갑니다.
    blocks = page.get_text("dict")["blocks"]
    
    for block in blocks:
        if "lines" in block:
            # 블록의 좌표 (x0, y0, x1, y1) - zoom 비율 반영
            b = block["bbox"]
            scaled_bbox = [b[0]*zoom, b[1]*zoom, b[2]*zoom, b[3]*zoom]
            
            # 박스 그리기
            draw.rectangle(scaled_bbox, outline="red", width=2)
    
    # 4. Streamlit 화면에 분할하여 출력
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.image(img, caption=f"Page {page_num}", use_container_width=True)
        
    with col2:
        st.subheader("추출된 데이터 매칭 확인")
        st.write("여기에 st.data_editor()를 활용해 매칭된 텍스트와 XML 레이블(단락, 표, 그림 등)을 띄워 검수합니다.")
