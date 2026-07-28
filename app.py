import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json
import pandas as pd
import ast
import difflib

# ---------------------------------------------------------
# 세션 상태(Session State) 초기화
# ---------------------------------------------------------
if "current_page" not in st.session_state:
    st.session_state.current_page = 0
if "prev_sel_front" not in st.session_state:
    st.session_state.prev_sel_front = []
if "prev_sel_back" not in st.session_state:
    st.session_state.prev_sel_back = []
if "active_selection" not in st.session_state:
    st.session_state.active_selection = None

# ---------------------------------------------------------
# 설정 및 헬퍼 함수
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="JATS XML-PDF 라벨링 검수 툴")
st.title("JATS XML - PDF 매칭 및 자동 라벨링 검수 도구")
st.markdown("표에서 항목을 선택하면, 전체 데이터가 출력되고 PDF 원문이 해당 위치로 자동 이동하여 파란색 박스로 강조됩니다.")

def get_similarity(text1, text2):
    """두 문자열 간의 유사도를 0.0 ~ 1.0 사이로 반환 (공백/줄바꿈 무시)"""
    if not text1 or not text2:
        return 0.0
    t1 = text1.replace(" ", "").replace("\n", "").strip()
    t2 = text2.replace(" ", "").replace("\n", "").strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()

def extract_xml_text(element):
    return "".join(element.itertext()).strip()

def get_raw_xml(element):
    if element is None:
        return ""
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
    except Exception as e:
        st.error(f"❌ XML 파싱 오류: {e}")
        st.stop()

    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    # 1. PDF 텍스트 블록 전체 추출 (모든 페이지 스캔으로 16페이지 등 후반부 참고문헌 탐색 가능)
    extracted_pdf_texts = []
    for p_num in range(len(doc)):
        p = doc[p_num]
        for b in p.get_text("dict")["blocks"]:
            if "lines" in b:
                block_text = "".join([span["text"] for line in b["lines"] for span in line["spans"]])
                extracted_pdf_texts.append({
                    "text": block_text, 
                    "bbox": b["bbox"], 
                    "page": p_num
                })

    # 2. XML 파싱 및 전체 텍스트 매칭
    mapped_data = []
    
    # [Front - 저자 정보 매칭]
    front_node = root.find('.//front')
    if front_node is not None:
        for contrib in front_node.findall('.//contrib'):
            xml_text = extract_xml_text(contrib)
            if not xml_text: continue
                
            best_match_ratio, best_bbox, best_page = 0, None, 0
            for pdf_item in extracted_pdf_texts:
                ratio = get_similarity(xml_text, pdf_item["text"])
                if ratio > best_match_ratio:
                    best_match_ratio, best_bbox, best_page = ratio, pdf_item["bbox"], pdf_item["page"]
            
            if best_match_ratio >= 0.7:
                mapped_data.append({"category": "Front", "tag": "contrib", "xml_text": xml_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            else:
                mapped_data.append({"category": "Front", "tag": "contrib", "xml_text": xml_text, "page": 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})

    # [Back - 참고문헌 매칭]
    back_node = root.find('.//back')
    if back_node is not None:
        for ref in back_node.findall('.//ref'):
            annotation = ref.find('.//annotation')
            if annotation is None: continue
                
            xml_text = extract_xml_text(annotation)
            if not xml_text: continue
                
            best_match_ratio, best_bbox, best_page = 0, None, 0
            for pdf_item in extracted_pdf_texts:
                ratio = get_similarity(xml_text, pdf_item["text"])
                if ratio > best_match_ratio:
                    best_match_ratio, best_bbox, best_page = ratio, pdf_item["bbox"], pdf_item["page"]
            
            if best_match_ratio >= 0.95:
                mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            else:
                mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})

    df = pd.DataFrame(mapped_data)

    # 3. 화면 분할 출력
    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    with col_data:
        st.subheader("📊 영역별 매칭 데이터 (Front & Back)")
        tab_front, tab_body, tab_back = st.tabs(["Front (저자 정보)", "Body (미구현)", "Back (참고문헌)"])
        
        # 데이터프레임 렌더링 및 선택 이벤트 감지
        with tab_front:
            df_front = df[df["category"] == "Front"].reset_index(drop=True)
            event_front = st.dataframe(df_front, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="table_front")
                
        with tab_body:
            st.info("Body 영역 매칭 로직은 아직 적용되지 않았습니다.")
            
        with tab_back:
            df_back = df[df["category"] == "Back"].reset_index(drop=True)
            event_back = st.dataframe(df_back, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="table_back")

        # 탭 간 충돌을 방지하기 위해 최근에 변경된 선택 사항만 활성화
        curr_sel_front = event_front.selection.rows
        curr_sel_back = event_back.selection.rows

        if curr_sel_front != st.session_state.prev_sel_front:
            st.session_state.active_selection = df_front.iloc[curr_sel_front[0]].to_dict() if curr_sel_front else None
            st.session_state.prev_sel_front = curr_sel_front
        elif curr_sel_back != st.session_state.prev_sel_back:
            st.session_state.active_selection = df_back.iloc[curr_sel_back[0]].to_dict() if curr_sel_back else None
            st.session_state.prev_sel_back = curr_sel_back

        # 행이 선택되었고 좌표가 존재하면, 해당 페이지로 자동 이동 설정
        active_sel = st.session_state.active_selection
        if active_sel and active_sel.get('bbox') != "None":
            st.session_state.current_page = int(active_sel['page'])
            
        # 선택된 데이터 하단 출력 (스크롤 컨테이너 적용)
        st.markdown("<br>##### 📌 선택된 추출 정보 전체 데이터", unsafe_allow_html=True)
        with st.container(height=200):
            if active_sel:
                st.json(active_sel)
                if active_sel.get('bbox') == "None":
                    st.warning("⚠️ 해당 항목은 원문과 매핑되지 않아(좌표 없음) PDF에 박스를 표시할 수 없습니다.")
            else:
                st.info("👆 위 테이블에서 행을 클릭(체크)하면 전체 매핑 정보가 이곳에 출력됩니다.")

    # 4. 사이드바 렌더링 (col_data 로직 수행 후 렌더링해야 자동 페이지 이동이 즉각 반영됨)
    st.sidebar.header("네비게이션")
    page_num = st.sidebar.number_input(
        f"페이지 번호 (0 ~ {len(doc)-1})", 
        min_value=0, 
        max_value=len(doc)-1, 
        key="current_page" # 세션 상태와 직접 연동
    )

    # 5. 좌측 패널: PDF 시각화 및 라벨링
    with col_img:
        st.subheader(f"📄 PDF 시각화 (Page {page_num})")
        
        page = doc[page_num]
        zoom = 2.0  
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)
        
        # 현재 페이지에 해당하는 모든 정상 매핑 건에 붉은 박스 그리기
        for data in mapped_data:
            if data['bbox'] != "None" and data['page'] == page_num:
                try:
                    bbox = ast.literal_eval(data['bbox'])
                    scaled_bbox = [b * zoom for b in bbox]
                    draw.rectangle(scaled_bbox, outline="red", width=2)
                except:
                    pass
                
        # 사용자가 선택한 데이터가 현재 페이지에 있다면 파란색 두꺼운 박스로 강조
        if active_sel and active_sel.get('bbox') != "None" and active_sel.get('page') == page_num:
            try:
                bbox = ast.literal_eval(active_sel['bbox'])
                scaled_bbox = [b * zoom for b in bbox]
                draw.rectangle(scaled_bbox, outline="blue", width=5)
            except:
                pass
                
        st.image(img, use_container_width=True)
