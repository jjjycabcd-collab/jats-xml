import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json
import pandas as pd
import ast
import difflib
import streamlit.components.v1 as components

# Streamlit 버전에 따른 Fragment 데코레이터 안전 로드 (부분 재실행 기능)
try:
    from streamlit import fragment
except ImportError:
    try:
        from streamlit import experimental_fragment as fragment
    except ImportError:
        def fragment(func): return func

# ---------------------------------------------------------
# 설정 및 헬퍼 함수
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="JATS XML-PDF 라벨링 검수 툴")
st.title("JATS XML - PDF 태깅 시각화 및 검수 도구")
st.markdown("XML 데이터를 기준으로 PDF 전체 텍스트를 탐색하여 바운딩 박스를 추출합니다.")

# 사이드바 매칭 임계값 설정
st.sidebar.header("매칭 임계값 설정 (Threshold)")
FRONT_THRESHOLD = st.sidebar.slider("Front (저자 항목별) 매칭 기준", 0.0, 1.0, 0.70, 0.05)
BODY_TITLE_THRESHOLD = st.sidebar.slider("Body (본문 제목) 매칭 기준", 0.0, 1.0, 0.95, 0.05) 
BODY_P_THRESHOLD = st.sidebar.slider("Body (본문 문단) 매칭 기준", 0.0, 1.0, 0.70, 0.05) 
BODY_FIG_TABLE_THRESHOLD = st.sidebar.slider("Body (표/그림 제목) 매칭 기준", 0.0, 1.0, 0.80, 0.05) 
BACK_THRESHOLD = st.sidebar.slider("Back (참고문헌) 매칭 기준", 0.0, 1.0, 0.65, 0.05) 

def get_similarity(text1, text2):
    if not text1 or not text2:
        return 0.0
    t1 = text1.replace(" ", "").replace("\n", "").strip()
    t2 = text2.replace(" ", "").replace("\n", "").strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()

def extract_xml_text(element):
    if element is None: return ""
    return "".join(element.itertext()).strip()

def get_raw_xml(element):
    if element is None: return ""
    return ET.tostring(element, encoding='utf-8', method='xml').decode('utf-8')

def find_best_match(xml_text, pdf_texts):
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
        # 노드의 부모를 추적하기 위한 parent_map 생성
        parent_map = {c: p for p in root.iter() for c in p}
    except Exception as e:
        st.error(f"❌ XML 파싱 오류: {e}")
        st.stop()

    def should_exclude_body_node(node):
        """요약, 초록, 키워드 등 Body 매핑에서 제외할 노드인지 판별"""
        text = extract_xml_text(node).replace(" ", "").replace("\n", "").lower()
        if not text: return False
        
        # 1. 단락이 키워드/주제어로 시작하는 경우
        prefix_exclusions = ["keyword", "keywords", "핵심어", "주제어", "핵심주제어"]
        if any(text.startswith(p) for p in prefix_exclusions):
            return True
            
        exact_abstract_titles = ["요약", "국문요약", "영문요약", "초록", "국문초록", "영문초록", "abstract"]
        
        # 2. 현재 노드가 title일 경우 검사
        if node.tag == 'title':
            clean_title = text.strip("1234567890.ivx()[]<>- ")
            if clean_title in exact_abstract_titles:
                return True
                
        # 3. 부모 노드를 역추적하여 속한 섹션이 요약/초록인지 검사
        curr = node
        while curr is not None:
            if curr.tag in ['abstract', 'kwd-group', 'kwd']:
                return True
            if curr.tag == 'sec':
                title_node = curr.find('title')
                if title_node is not None:
                    t_text = extract_xml_text(title_node).replace(" ", "").replace("\n", "").lower()
                    clean_t_text = t_text.strip("1234567890.ivx()[]<>- ")
                    if clean_t_text in exact_abstract_titles:
                        return True
            curr = parent_map.get(curr)
            
        return False

    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    if "pdf_view_page" not in st.session_state:
        st.session_state.pdf_view_page = 0
    
    # 1. PDF 전체 문서 텍스트 추출
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
    unmapped_xml_front, unmapped_xml_body, unmapped_xml_back = [], [], []
    
    # ==========================================
    # [Front - 저자 정보 상세 매칭]
    # ==========================================
    front_node = root.find('.//front')
    if front_node is not None:
        for contrib in front_node.findall('.//contrib'):
            for name_node in contrib.findall('.//name'):
                surname = extract_xml_text(name_node.find('surname'))
                given = extract_xml_text(name_node.find('given-names'))
                format1, format2 = given + surname, surname + given
                
                best_match_ratio, best_bbox, best_page = 0, None, -1
                for pdf_item in extracted_pdf_texts:
                    max_ratio = max(get_similarity(format1, pdf_item["text"]), get_similarity(format2, pdf_item["text"]))
                    if max_ratio > best_match_ratio:
                        best_match_ratio = max_ratio
                        best_bbox = pdf_item["bbox"]
                        best_page = pdf_item["page"]
                
                xml_display_text = f"{given} {surname}".strip()
                if best_match_ratio >= FRONT_THRESHOLD:
                    mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else:
                    mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                    unmapped_xml_front.append(get_raw_xml(name_node))

            for email_node in contrib.findall('.//email'):
                xml_text = extract_xml_text(email_node)
                if not xml_text: continue
                ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(email_node))

            for orcid_node in contrib.findall('.//contrib-id'):
                if orcid_node.attrib.get('contrib-id-type') == 'orcid' or 'orcid' in extract_xml_text(orcid_node).lower():
                    xml_text = extract_xml_text(orcid_node)
                    ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                    if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(orcid_node))

            for role_node in contrib.findall('.//role'):
                xml_text = extract_xml_text(role_node)
                if not xml_text: continue
                ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(role_node))

    # ==========================================
    # [Body - 본문 매칭 (초록/키워드 제외 로직 적용)]
    # ==========================================
    body_node = root.find('.//body')
    if body_node is not None:
        
        # 1. 제목 (sec/title) 매칭
        for sec_node in body_node.findall('.//sec'):
            title_node = sec_node.find('title')
            if title_node is not None:
                # [추가] 초록/키워드 노드 필터링
                if should_exclude_body_node(title_node):
                    continue
                
                xml_text = extract_xml_text(title_node)
                if xml_text:
                    ratio, bbox, b_page = find_best_match(xml_text, extracted_pdf_texts)
                    if ratio >= BODY_TITLE_THRESHOLD: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "page": b_page, "bbox": str([round(c, 2) for c in bbox]), "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(title_node))
        
        # 2. 표 (table-wrap) / 그림 (fig) 매칭
        for fig_table_node in body_node.findall('.//table-wrap') + body_node.findall('.//fig'):
            if should_exclude_body_node(fig_table_node):
                continue
                
            tag_name = fig_table_node.tag
            label_node = fig_table_node.find('label')
            title_node = fig_table_node.find('.//caption/title')
            if title_node is None:
                title_node = fig_table_node.find('.//caption/p')
                
            label_text = extract_xml_text(label_node)
            title_text = extract_xml_text(title_node)
            
            xml_text = f"{label_text} {title_text}".strip()
            if not xml_text: continue
            
            clean_xml = xml_text.replace(" ", "").replace("\n", "").strip()
            if len(clean_xml) < 2: continue 
            
            xml_prefix = clean_xml[:2]
            best_match_ratio, best_bbox, best_page = 0, None, -1
            
            for i in range(len(extracted_pdf_texts)):
                clean_pdf_block = extracted_pdf_texts[i]["text"].replace(" ", "").replace("\n", "").strip()
                if clean_pdf_block.startswith(xml_prefix):
                    accumulated_text = ""
                    min_x0, min_y0, max_x1, max_y1 = float('inf'), float('inf'), float('-inf'), float('-inf')
                    match_page = extracted_pdf_texts[i]["page"]
                    
                    for j in range(i, len(extracted_pdf_texts)):
                        if extracted_pdf_texts[j]["page"] != match_page: break
                        accumulated_text += extracted_pdf_texts[j]["text"]
                        bx0, by0, bx1, by1 = extracted_pdf_texts[j]["bbox"]
                        min_x0, min_y0 = min(min_x0, bx0), min(min_y0, by0)
                        max_x1, max_y1 = max(max_x1, bx1), max(max_y1, by1)
                        
                        ratio = get_similarity(xml_text, accumulated_text)
                        if ratio > best_match_ratio:
                            best_match_ratio = ratio
                            best_bbox = [min_x0, min_y0, max_x1, max_y1]
                            best_page = match_page
                        if len(accumulated_text.replace(" ", "").replace("\n", "")) > len(clean_xml) * 1.5: break
            
            if best_match_ratio >= BODY_FIG_TABLE_THRESHOLD:
                mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            else:
                mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                unmapped_xml_body.append(get_raw_xml(fig_table_node))

        # 3. 문단 (p) 매칭
        for p_node in body_node.findall('.//p'):
            # [추가] 초록/키워드 노드 필터링
            if should_exclude_body_node(p_node):
                continue
                
            xml_text = extract_xml_text(p_node)
            if not xml_text: continue
            
            clean_xml = xml_text.replace(" ", "").replace("\n", "").strip()
            if len(clean_xml) < 3: continue
            
            xml_prefix = clean_xml[:3]
            best_match_ratio, best_bbox, best_page = 0, None, -1
            
            for i in range(len(extracted_pdf_texts)):
                clean_pdf_block = extracted_pdf_texts[i]["text"].replace(" ", "").replace("\n", "").strip()
                if clean_pdf_block.startswith(xml_prefix):
                    accumulated_text = ""
                    min_x0, min_y0, max_x1, max_y1 = float('inf'), float('inf'), float('-inf'), float('-inf')
                    match_page = extracted_pdf_texts[i]["page"]
                    
                    for j in range(i, len(extracted_pdf_texts)):
                        if extracted_pdf_texts[j]["page"] != match_page: break
                        accumulated_text += extracted_pdf_texts[j]["text"]
                        bx0, by0, bx1, by1 = extracted_pdf_texts[j]["bbox"]
                        min_x0, min_y0 = min(min_x0, bx0), min(min_y0, by0)
                        max_x1, max_y1 = max(max_x1, bx1), max(max_y1, by1)
                        
                        ratio = get_similarity(xml_text, accumulated_text)
                        if ratio > best_match_ratio:
                            best_match_ratio = ratio
                            best_bbox = [min_x0, min_y0, max_x1, max_y1]
                            best_page = match_page
                        if len(accumulated_text.replace(" ", "").replace("\n", "")) > len(clean_xml) * 1.5: break
            
            if best_match_ratio >= BODY_P_THRESHOLD:
                mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            else:
                mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                unmapped_xml_body.append(get_raw_xml(p_node))

    # ==========================================
    # [Back - 참고문헌 다중 블록 매칭]
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
                        if pdf_texts_for_back[j]["page"] != match_page: break
                        accumulated_text += pdf_texts_for_back[j]["text"]
                        bx0, by0, bx1, by1 = pdf_texts_for_back[j]["bbox"]
                        min_x0, min_y0 = min(min_x0, bx0), min(min_y0, by0)
                        max_x1, max_y1 = max(max_x1, bx1), max(max_y1, by1)
                        
                        ratio = get_similarity(xml_text, accumulated_text)
                        if ratio > best_match_ratio:
                            best_match_ratio = ratio
                            best_bbox = [min_x0, min_y0, max_x1, max_y1]
                            best_page = match_page
                        if len(accumulated_text.replace(" ", "")) > len(clean_xml) * 1.5: break
            
            if best_match_ratio >= BACK_THRESHOLD:
                mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": best_page, "bbox": str([round(c, 2) for c in best_bbox]), "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            else:
                mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                unmapped_xml_back.append(get_raw_xml(ref))

    # ==========================================
    # [데이터 정렬 로직 (1단/2단 흐름 반영)]
    # ==========================================
    df = pd.DataFrame(mapped_data)
    if not df.empty:
        def get_sort_keys(row):
            page, bbox_str = row['page'], row['bbox']
            if bbox_str == "None": return page, 9999, 9999
            try:
                x0, y0, x1, y1 = ast.literal_eval(bbox_str)
                width = x1 - x0
                if width > 250 or x0 < 300: col = 0
                else: col = 1
                return page, col, y0
            except: return page, 9999, 9999

        df['sort_page'] = df.apply(lambda x: get_sort_keys(x)[0], axis=1)
        df['sort_col']  = df.apply(lambda x: get_sort_keys(x)[1], axis=1)
        df['sort_y0']   = df.apply(lambda x: get_sort_keys(x)[2], axis=1)
        df = df.sort_values(by=['sort_page', 'sort_col', 'sort_y0']).drop(columns=['sort_page', 'sort_col', 'sort_y0']).reset_index(drop=True)

    selected_row_data = None

    # ---------------------------------------------------------
    # 화면 분할 출력
    # ---------------------------------------------------------
    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    # [우측 패널] 데이터 테이블 영역
    with col_data:
        with st.container(height=850):
            st.subheader("📊 영역별 매칭 데이터 검수")
            tab_front, tab_body, tab_back = st.tabs(["Front (저자 정보)", "Body (본문)", "Back (참고문헌)"])
            
            with tab_front:
                if not df.empty and "Front" in df["category"].values:
                    df_front = df[df["category"] == "Front"].reset_index(drop=True)
                    event_front = st.dataframe(df_front, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_f")
                    if len(event_front.selection.rows) > 0:
                        selected_row_data = df_front.iloc[event_front.selection.rows[0]].to_dict()
                        if selected_row_data['bbox'] != "None":
                            st.session_state.pdf_view_page = int(selected_row_data['page'])
                                
            with tab_body:
                if not df.empty and "Body" in df["category"].values:
                    df_body = df[df["category"] == "Body"].reset_index(drop=True)
                    event_body = st.dataframe(df_body, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_body_tab")
                    if len(event_body.selection.rows) > 0 and selected_row_data is None:
                        selected_row_data = df_body.iloc[event_body.selection.rows[0]].to_dict()
                        if selected_row_data['bbox'] != "None":
                            st.session_state.pdf_view_page = int(selected_row_data['page'])
                else: st.info("매핑된 Body 데이터가 없습니다.")
                
            with tab_back:
                if not df.empty and "Back" in df["category"].values:
                    df_back = df[df["category"] == "Back"].reset_index(drop=True)
                    event_back = st.dataframe(df_back, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_b")
                    if len(event_back.selection.rows) > 0 and selected_row_data is None:
                        selected_row_data = df_back.iloc[event_back.selection.rows[0]].to_dict()
                        if selected_row_data['bbox'] != "None":
                            st.session_state.pdf_view_page = int(selected_row_data['page'])
                
            st.markdown("<br>##### 📌 선택된 추출 정보 전체 데이터", unsafe_allow_html=True)
            with st.container(height=200):
                if selected_row_data: st.json(selected_row_data)
                else: st.info("👆 위 테이블에서 행을 클릭하면 전체 매핑 정보가 이곳에 출력됩니다.")
                    
            st.markdown("<br>##### ⚠️ 매핑 실패 및 미처리 XML 데이터", unsafe_allow_html=True)
            tab_f_fail, tab_b_fail, tab_bk_fail = st.tabs(["Front (항목 실패)", "Body (항목 실패)", "Back (항목 실패)"])
            with tab_f_fail:
                if unmapped_xml_front:
                    for raw in unmapped_xml_front: st.code(raw, language="xml")
            with tab_b_fail:
                if unmapped_xml_body:
                    for raw in unmapped_xml_body: st.code(raw, language="xml")
            with tab_bk_fail:
                if unmapped_xml_back:
                    for raw in unmapped_xml_back: st.code(raw, language="xml")

    # [좌측 패널] PDF 연속 뷰어 (Fragment 사용으로 독립적 렌더링)
    @fragment
    def render_pdf_viewer(doc, selected_row):
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        with nav_col1:
            if st.button("◀ 이전 페이지", use_container_width=True):
                if st.session_state.pdf_view_page > 0:
                    st.session_state.pdf_view_page -= 1
                    st.rerun()
        with nav_col3:
            if st.button("다음 페이지 ▶", use_container_width=True):
                if st.session_state.pdf_view_page < len(doc) - 1:
                    st.session_state.pdf_view_page += 1
                    st.rerun()
        with nav_col2:
            st.markdown(f"<h4 style='text-align: center; margin-top: 0px;'>📄 PDF 시각화 (Page {st.session_state.pdf_view_page})</h4>", unsafe_allow_html=True)
            
        st.divider()
        
        with st.container(height=750):
            zoom = 2.0  
            for i in range(len(doc)):
                st.markdown(f"<div id='pdf_page_{i}'></div>", unsafe_allow_html=True)
                
                page = doc[i]
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                if selected_row and selected_row.get('bbox') != "None" and int(selected_row.get('page')) == i:
                    try:
                        bbox = ast.literal_eval(selected_row['bbox'])
                        scaled_bbox = [b * zoom for b in bbox]
                        draw = ImageDraw.Draw(img)
                        draw.rectangle(scaled_bbox, outline="blue", width=5)
                    except Exception:
                        pass
                        
                st.image(img, use_container_width=True)
                
            components.html(
                f"""
                <script>
                    var target = window.parent.document.getElementById('pdf_page_{st.session_state.pdf_view_page}');
                    if (target) {{
                        target.scrollIntoView({{behavior: 'smooth', block: 'start'}});
                    }}
                </script>
                """,
                height=0,
                width=0
            )

    with col_img:
        render_pdf_viewer(doc, selected_row_data)
