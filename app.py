import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json
import pandas as pd
import ast
import difflib

# ---------------------------------------------------------
# 설정 및 헬퍼 함수
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="JATS XML-PDF 라벨링 검수 툴")
st.title("JATS XML - PDF 저자 정보 매칭 및 검수 도구")
st.markdown("XML 데이터를 기준으로 PDF 텍스트와 유사도를 비교하여 바운딩 박스를 추출합니다.")

def get_similarity(text1, text2):
    """두 문자열 간의 유사도를 0.0 ~ 1.0 사이로 반환 (공백 무시)"""
    if not text1 or not text2:
        return 0.0
    t1 = text1.replace(" ", "").replace("\n", "").strip()
    t2 = text2.replace(" ", "").replace("\n", "").strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()

def extract_xml_text(element):
    """XML 엘리먼트 내의 모든 텍스트를 재귀적으로 추출"""
    return "".join(element.itertext()).strip()

def get_raw_xml(element):
    """XML 엘리먼트를 원시 문자열로 변환"""
    if element is None:
        return ""
    # 유니코드 디코딩 시 발생할 수 있는 에러 방지
    return ET.tostring(element, encoding='utf-8', method='xml').decode('utf-8')

# ---------------------------------------------------------
# 메인 로직
# ---------------------------------------------------------
col_up1, col_up2 = st.columns(2)
with col_up1:
    uploaded_pdf = st.file_uploader("PDF 원문 파일을 업로드하세요", type=["pdf"])
with col_up2:
    uploaded_xml = st.file_uploader("JATS XML 파일을 업로드하세요", type=["xml"])

if uploaded_pdf and uploaded_xml:
    try:
        tree = ET.parse(uploaded_xml)
        root = tree.getroot()
        st.success("✅ 파일이 성공적으로 로드되었습니다. Front(저자 정보) 매칭을 시작합니다.")
    except Exception as e:
        st.error(f"❌ XML 파싱 오류: {e}")
        st.stop()

    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    st.sidebar.header("네비게이션")
    page_num = st.sidebar.number_input(f"페이지 번호 (0 ~ {len(doc)-1})", min_value=0, max_value=len(doc)-1, value=0)
    page = doc[page_num]
    
    # 1. PDF 텍스트 블록 및 좌표 추출
    pdf_blocks = page.get_text("dict")["blocks"]
    extracted_pdf_texts = []
    for b in pdf_blocks:
        if "lines" in b:
            block_text = "".join([span["text"] for line in b["lines"] for span in line["spans"]])
            extracted_pdf_texts.append({"text": block_text, "bbox": b["bbox"]})

    # 2. XML Front 영역 저자(contrib) 정보 파싱 및 매칭
    mapped_data = []
    unmapped_xml_front = []
    
    front_node = root.find('.//front')
    if front_node is not None:
        # 저자 정보(contrib) 추출
        for contrib in front_node.findall('.//contrib'):
            xml_text = extract_xml_text(contrib)
            if not xml_text:
                continue
                
            # PDF 블록들과 유사도 비교
            best_match_ratio = 0
            best_bbox = None
            
            for pdf_item in extracted_pdf_texts:
                ratio = get_similarity(xml_text, pdf_item["text"])
                if ratio > best_match_ratio:
                    best_match_ratio = ratio
                    best_bbox = pdf_item["bbox"]
            
            # 임계치(예: 70%) 이상일 경우 매핑 성공으로 간주
            SIMILARITY_THRESHOLD = 0.7
            if best_match_ratio >= SIMILARITY_THRESHOLD:
                mapped_data.append({
                    "category": "Front",
                    "tag": "contrib (저자)",
                    "xml_text": xml_text,
                    "page": page_num,
                    "bbox": str([round(c, 2) for c in best_bbox]),
                    "similarity": f"{best_match_ratio * 100:.1f}%",
                    "status": "✅ 매칭 완료"
                })
            else:
                mapped_data.append({
                    "category": "Front",
                    "tag": "contrib (저자)",
                    "xml_text": xml_text,
                    "page": page_num,
                    "bbox": "None",
                    "similarity": f"{best_match_ratio * 100:.1f}%",
                    "status": "❌ 매핑 실패"
                })
                # 매핑 실패한 XML 노드는 미처리 목록에 추가
                unmapped_xml_front.append(get_raw_xml(contrib))

    df = pd.DataFrame(mapped_data)
    selected_row_data = None

    # 3. 화면 분할 (좌: PDF, 우: 데이터 표)
    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    with col_data:
        st.subheader("📊 Front 영역 매칭 데이터 (저자 정보 중심)")
        st.caption("XML의 저자 텍스트를 기준으로 PDF 텍스트와 유사도를 비교하여 좌표를 찾습니다.")
        
        # 상단: 데이터 테이블 렌더링 및 선택 이벤트 캡처
        if not df.empty:
            event = st.dataframe(
                df,
                use_container_width=True,
                height=200,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if len(event.selection.rows) > 0:
                selected_idx = event.selection.rows[0]
                selected_row_data = df.iloc[selected_idx].to_dict()
        else:
            st.warning("현재 페이지에서 매핑된 Front(저자) 정보가 없습니다.")
            
        # 하단: 선택된 행의 전체 JSON 상세 출력
        st.markdown("<br>##### 📌 선택된 추출 정보 전체 데이터", unsafe_allow_html=True)
        json_container = st.container(height=200)
        with json_container:
            if selected_row_data:
                st.json(selected_row_data)
            else:
                st.info("👆 위 테이블에서 행을 클릭하면 전체 매핑 정보가 이곳에 출력됩니다.")
                
        # 미매핑 / 미처리 XML 데이터 출력 (Front 실패건, Body, Back 전체)
        st.markdown("<br>##### ⚠️ 매핑 실패 및 미처리 XML 데이터", unsafe_allow_html=True)
        
        tab_f, tab_b, tab_bk = st.tabs(["Front (매핑 실패)", "Body (미처리)", "Back (미처리)"])
        with tab_f:
            if unmapped_xml_front:
                for raw_xml in unmapped_xml_front:
                    st.code(raw_xml, language="xml")
            else:
                st.success("Front 영역의 저자 정보가 모두 매핑되었습니다.")
                
        with tab_b:
            body_node = root.find('.//body')
            if body_node is not None:
                st.code(get_raw_xml(body_node), language="xml")
            else:
                st.info("Body 영역이 없습니다.")
                
        with tab_bk:
            back_node = root.find('.//back')
            if back_node is not None:
                st.code(get_raw_xml(back_node), language="xml")
            else:
                st.info("Back 영역이 없습니다.")

    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        
        zoom = 2.0  
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)
        
        # 선택된 데이터가 있고, 좌표가 존재할 경우 파란색 박스로 시각화
        if selected_row_data and selected_row_data['bbox'] != "None" and selected_row_data['page'] == page_num:
            try:
                bbox = ast.literal_eval(selected_row_data['bbox'])
                scaled_bbox = [b * zoom for b in bbox]
                draw.rectangle(scaled_bbox, outline="blue", width=5)
            except Exception as e:
                pass
                
        st.image(img, use_container_width=True)
