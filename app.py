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
st.title("JATS XML - PDF 저자 및 참고문헌 매칭 검수 도구")
st.markdown("XML 데이터를 기준으로 PDF 전체 텍스트를 탐색하여 바운딩 박스를 추출합니다.")

# 사이드바 매칭 임계값 설정
st.sidebar.header("매칭 임계값 설정 (Threshold)")
FRONT_THRESHOLD = st.sidebar.slider("Front (저자 항목별) 매칭 기준", 0.0, 1.0, 0.70, 0.05)
BACK_THRESHOLD = st.sidebar.slider("Back (참고문헌) 매칭 기준", 0.0, 1.0, 0.65, 0.05) 

def get_similarity(text1, text2):
    """두 문자열 간의 유사도를 0.0 ~ 1.0 사이로 반환 (공백/줄바꿈 무시)"""
    if not text1 or not text2:
        return 0.0
    t1 = text1.replace(" ", "").replace("\n", "").strip()
    t2 = text2.replace(" ", "").replace("\n", "").strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()

def extract_xml_text(element):
    """XML 엘리먼트 내의 모든 텍스트를 재귀적으로 추출"""
    if element is None:
        return ""
    return "".join(element.itertext()).strip()

def get_raw_xml(element):
    """XML 엘리먼트를 원시 문자열로 변환"""
    if element is None:
        return ""
    return ET.tostring(element, encoding='utf-8', method='xml').decode('utf-8')

def find_best_match(xml_text, pdf_texts):
    """전체 문서 텍스트 중 최고 유사도, 바운딩 박스, 페이지 번호 반환"""
    best_match_ratio, best_bbox, best_page = 0, None, -1
    for pdf_item in pdf_texts:
        ratio = get_similarity(xml_text, pdf_item["text"])
        if ratio > best_match_ratio:
            best_match_ratio = ratio
            best_bbox = pdf_item["bbox"]
            best_page = pdf_item["page"]
    return best_match_ratio, best_bbox, best_page

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
    
    # 세션 상태를 활용한 페이지 네비게이션 제어
    if "pdf_page" not in st.session_state:
        st.session_state.pdf_page = 0
        
    st.sidebar.header("네비게이션")
    st.sidebar.number_input(
        f"페이지 번호 (0 ~ {len(doc)-1})", 
        min_value=0, 
        max_value=len(doc)-1, 
        key="pdf_page" # 세션 상태 변수와 위젯 연동
    )
    page_num = st.session_state.pdf_page
    page = doc[page_num]
    
    # 1. PDF 전체 문서 텍스트 블록 및 좌표 추출 (페이지 정보 포함)
    extracted_pdf_texts = []
    for p_num in range(len(doc)):
        p_blocks = doc[p_num].get_text("dict")["blocks"]
        for b in p_blocks:
            if "lines" in b:
                block_text = "".join([span["text"] for line in b["lines"] for span in line["spans"]])
                block_text = block_text.replace("- ", "").replace("-\n", "")
                extracted_pdf_texts.append({
                    "page": p_num, 
                    "text": block_text, 
                    "bbox": b["bbox"]
                })

    mapped_data = []
    unmapped_xml_front = []
    unmapped_xml_back = []
    
    # ==========================================
    # [Front - 저자 정보 상세 항목 매칭]
    # ==========================================
    front_node = root.find('.//front')
    if front_node is not None:
        for contrib in front_node.findall('.//contrib'):
            
            # 1. 이름 (name) 매칭 로직
            for name_node in contrib.findall('.//name'):
                surname = extract_xml_text(name_node.find('surname'))
                given = extract_xml_text(name_node.find('given-names'))
                
                format1 = given + surname
                format2 = surname + given
                
                best_match_ratio, best_bbox, best_page = 0, None, -1
                for pdf_item in extracted_pdf_texts:
                    ratio1 = get_similarity(format1, pdf_item["text"])
                    ratio2 = get_similarity(format2, pdf_item["text"])
                    max_ratio = max(ratio1, ratio2)
                    
                    if max_ratio > best_match_ratio:
                        best_match_ratio = max_ratio
                        best_bbox = pdf_item["bbox"]
                        best_page = pdf_item["page"]
                
                xml_display_text = f"{given} {surname}".strip()
                if best_match_ratio >= FRONT_THRESHOLD:
                    mapped_data.append({
                        "category": "Front", "tag": "name", "xml_text": xml_display_text,
                        "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]),
                        "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"
                    })
                else:
                    mapped_data.append({
                        "category": "Front", "tag": "name", "xml_text": xml_display_text,
                        "page": best_page if best_page != -1 else 0, "bbox": "None",
                        "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"
                    })
                    unmapped_xml_front.append(get_raw_xml(name_node))

            # 2. 이메일, 3. ORCID, 4. 역할 매칭
            for email_node in contrib.findall('.//email'):
                xml_text = extract_xml_text(email_node)
                if not xml_text: continue
                ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD:
                    mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else:
                    mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                    unmapped_xml_front.append(get_raw_xml(email_node))

            for orcid_node in contrib.findall('.//contrib-id'):
                if orcid_node.attrib.get('contrib-id-type') == 'orcid' or 'orcid' in extract_xml_text(orcid_node).lower():
                    xml_text = extract_xml_text(orcid_node)
                    ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                    if ratio >= FRONT_THRESHOLD:
                        mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else:
                        mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                        unmapped_xml_front.append(get_raw_xml(orcid_node))

            for role_node in contrib.findall('.//role'):
                xml_text = extract_xml_text(role_node)
                if not xml_text: continue
                ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD:
                    mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else:
                    mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                    unmapped_xml_front.append(get_raw_xml(role_node))

    # ==========================================
    # [Back - 참고문헌 영역 찾기 및 다중 블록 병합 매칭]
    # ==========================================
    ref_start_idx = 0
    for i, item in enumerate(extracted_pdf_texts):
        clean_text = item["text"].replace(" ", "").strip()
        if clean_text in ["참고문헌", "REFERENCES", "References"]:
            ref_start_idx = i
            break
            
    pdf_texts_for_back = extracted_pdf_texts[ref_start_idx:]

    back_node = root.find('.//back')
    if back_node is not None:
        for ref in back_node.findall('.//ref'):
            annotation = ref.find('.//annotation')
            if annotation is None: continue
                
            xml_text = extract_xml_text(annotation)
            if not xml_text: continue
            
            clean_xml = xml_text.replace(" ", "").replace("\n", "").strip()
            if len(clean_xml) < 3: continue
            
            xml_prefix = clean_xml[:3]
            best_match_ratio, best_bbox, best_page = 0, None, -1
            
            for i in range(len(pdf_texts_for_back)):
                clean_pdf_block = pdf_texts_for_back[i]["text"].replace(" ", "").replace("\n", "").strip()
                
                if clean_pdf_block.startswith(xml_prefix):
                    accumulated_text = ""
                    min_x0, min_y0, max_x1, max_y1 = float('inf'), float('inf'), float('-inf'), float('-inf')
                    match_page = pdf_texts_for_back[i]["page"]
                    
                    for j in range(i, len(pdf_texts_for_back)):
                        if pdf_texts_for_back[j]["page"] != match_page:
                            break
                            
                        accumulated_text += pdf_texts_for_back[j]["text"]
                        bx0, by0, bx1, by1 = pdf_texts_for_back[j]["bbox"]
                        min_x0 = min(min_x0, bx0)
                        min_y0 = min(min_y0, by0)
                        max_x1 = max(max_x1, bx1)
                        max_y1 = max(max_y1, by1)
                        
                        ratio = get_similarity(xml_text, accumulated_text)
                        if ratio > best_match_ratio:
                            best_match_ratio = ratio
                            best_bbox = [min_x0, min_y0, max_x1, max_y1]
                            best_page = match_page
                        
                        if len(accumulated_text.replace(" ", "")) > len(clean_xml) * 1.5:
                            break
            
            if best_match_ratio >= BACK_THRESHOLD:
                mapped_data.append({
                    "category": "Back", "tag": "annotation", "xml_text": xml_text,
                    "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]),
                    "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"
                })
            else:
                mapped_data.append({
                    "category": "Back", "tag": "annotation", "xml_text": xml_text,
                    "page": best_page if best_page != -1 else 0, "bbox": "None",
                    "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"
                })
                unmapped_xml_back.append(get_raw_xml(ref))

    df = pd.DataFrame(mapped_data)
    selected_row_data = None

    # 3. 화면 분할 출력
    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    # 우측 패널
    with col_data:
        with st.container(height=850):
            st.subheader("📊 영역별 매칭 데이터 (Front & Back)")
            tab_front, tab_body, tab_back = st.tabs(["Front (저자 정보)", "Body (미구현)", "Back (참고문헌)"])
            
            # [기능 추가] 선택 시 페이지 자동 이동 로직 적용
            with tab_front:
                if not df.empty and "Front" in df["category"].values:
                    df_front = df[df["category"] == "Front"].reset_index(drop=True)
                    event_front = st.dataframe(df_front, use_container_width=True, height=200, on_select="rerun", selection_mode="single-row", key="df_f")
                    if len(event_front.selection.rows) > 0:
                        selected_row_data = df_front.iloc[event_front.selection.rows[0]].to_dict()
                        # 매핑 성공이고, 현재 페이지와 선택된 데이터의 페이지가 다르면 페이지 이동
                        if selected_row_data['bbox'] != "None" and selected_row_data['page'] != st.session_state.pdf_page:
                            st.session_state.pdf_page = int(selected_row_data['page'])
                            st.rerun()
                        
            with tab_body:
                st.info("Body 영역 매칭 로직은 아직 적용되지 않았습니다.")
                
            with tab_back:
                if not df.empty and "Back" in df["category"].values:
                    df_back = df[df["category"] == "Back"].reset_index(drop=True)
                    event_back = st.dataframe(df_back, use_container_width=True, height=200, on_select="rerun", selection_mode="single-row", key="df_b")
                    if len(event_back.selection.rows) > 0 and selected_row_data is None:
                        selected_row_data = df_back.iloc[event_back.selection.rows[0]].to_dict()
                        # 매핑 성공이고, 현재 페이지와 선택된 데이터의 페이지가 다르면 페이지 이동
                        if selected_row_data['bbox'] != "None" and selected_row_data['page'] != st.session_state.pdf_page:
                            st.session_state.pdf_page = int(selected_row_data['page'])
                            st.rerun()
                
            st.markdown("<br>##### 📌 선택된 추출 정보 전체 데이터", unsafe_allow_html=True)
            with st.container(height=200):
                if selected_row_data: st.json(selected_row_data)
                else: st.info("👆 위 테이블에서 행을 클릭하면 전체 매핑 정보가 이곳에 출력됩니다.")
                    
            st.markdown("<br>##### ⚠️ 매핑 실패 및 미처리 XML 데이터", unsafe_allow_html=True)
            tab_f_fail, tab_b_fail, tab_bk_fail = st.tabs(["Front (항목 실패)", "Body (원문)", "Back (실패)"])
            
            with tab_f_fail:
                if unmapped_xml_front:
                    for raw in unmapped_xml_front: st.code(raw, language="xml")
            with tab_b_fail:
                body_node = root.find('.//body')
                if body_node is not None: st.code(get_raw_xml(body_node)[:2000] + "\n...", language="xml")
            with tab_bk_fail:
                if unmapped_xml_back:
                    for raw in unmapped_xml_back: st.code(raw, language="xml")

    # 좌측 패널
    with col_img:
        with st.container(height=850):
            st.subheader(f"📄 PDF 시각화 (Page {page_num})")
            
            zoom = 2.0  
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)
            
            # 선택된 행의 'page' 값이 현재 좌측에 렌더링된 'page_num'과 일치할 때만 바운딩 박스를 그림
            if selected_row_data and selected_row_data.get('bbox') != "None" and selected_row_data.get('page') == page_num:
                try:
                    bbox = ast.literal_eval(selected_row_data['bbox'])
                    scaled_bbox = [b * zoom for b in bbox]
                    draw.rectangle(scaled_bbox, outline="blue", width=4)
                except Exception:
                    st.warning("⚠️ 좌표 데이터 형식이 올바르지 않습니다.")
            elif selected_row_data and selected_row_data.get('bbox') == "None":
                st.warning("⚠️ 선택된 항목은 매핑에 실패하여 좌표(bbox) 정보가 존재하지 않습니다.")
                    
            st.image(img, use_container_width=True)
