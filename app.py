import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import json
import pandas as pd
import ast
import difflib
import re
import streamlit.components.v1 as components

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
st.markdown("XML 데이터를 기준으로 단(Column)과 페이지(Page)를 넘나드는 문단을 정교하게 분리하여 매핑합니다.")

st.sidebar.header("매칭 임계값 설정 (Threshold)")
FRONT_THRESHOLD = st.sidebar.slider("Front (저자 항목별) 매칭 기준", 0.0, 1.0, 0.70, 0.05)
BODY_TITLE_THRESHOLD = st.sidebar.slider("Body (본문 제목) 매칭 기준", 0.0, 1.0, 0.95, 0.05) 
BODY_P_THRESHOLD = st.sidebar.slider("Body (본문 문단) 매칭 기준", 0.0, 1.0, 0.70, 0.05) 
BODY_FIG_TABLE_THRESHOLD = st.sidebar.slider("Body (표/그림 제목) 매칭 기준", 0.0, 1.0, 0.80, 0.05) 
BACK_THRESHOLD = st.sidebar.slider("Back (참고문헌) 매칭 기준", 0.0, 1.0, 0.65, 0.05) 

def get_similarity(text1, text2):
    if not text1 or not text2: return 0.0
    t1 = text1.replace(" ", "").replace("\n", "").strip()
    t2 = text2.replace(" ", "").replace("\n", "").strip()
    return difflib.SequenceMatcher(None, t1, t2).ratio()

def extract_xml_text(element):
    if element is None: return ""
    return "".join(element.itertext()).strip()

def get_raw_xml(element):
    if element is None: return ""
    return ET.tostring(element, encoding='utf-8', method='xml').decode('utf-8')

# [신규] 단(Column) 및 페이지(Page) 전환 시 박스를 분리하는 핵심 함수
def merge_multi_page_bboxes(blocks):
    """
    blocks: [{"page": p, "bbox": [x0, y0, x1, y1]}, ...]
    Returns: [[page, x0, y0, x1, y1], [page, x0, y0, x1, y1], ...]
    """
    if not blocks: return []
    merged = []
    
    curr_page = blocks[0]["page"]
    curr_bbox = list(blocks[0]["bbox"])
    
    for b in blocks[1:]:
        p = b["page"]
        box = b["bbox"]
        
        # 단(Column) 판단 기준
        center_curr = (curr_bbox[0] + curr_bbox[2]) / 2
        center_b = (box[0] + box[2]) / 2
        col_curr = 0 if center_curr < 300 else 1
        col_b = 0 if center_b < 300 else 1
        
        # y축 거리 판단 (단락 내 거리가 너무 멀면 분리, 예: 150px)
        y_gap = box[1] - curr_bbox[3]
        
        # 같은 페이지, 같은 단, 너무 멀지 않은 거리일 때만 영역 병합
        if p == curr_page and col_curr == col_b and y_gap < 150:
            curr_bbox[0] = min(curr_bbox[0], box[0])
            curr_bbox[1] = min(curr_bbox[1], box[1])
            curr_bbox[2] = max(curr_bbox[2], box[2])
            curr_bbox[3] = max(curr_bbox[3], box[3])
        else:
            # 단이 넘어가거나 페이지가 넘어가면 기존 박스를 저장하고 새 박스 시작
            merged.append([curr_page] + [round(c, 2) for c in curr_bbox])
            curr_page = p
            curr_bbox = list(box)
            
    merged.append([curr_page] + [round(c, 2) for c in curr_bbox])
    return merged

def find_best_match(xml_text, pdf_texts):
    """(단일 라인용) Front 메타 정보 검색 - 다중 박스 포맷 통일 [[page, x0, y0, x1, y1]]"""
    best_match_ratio, best_bbox, best_page = 0, None, -1
    for pdf_item in pdf_texts:
        ratio = get_similarity(xml_text, pdf_item["text"])
        if ratio > best_match_ratio:
            best_match_ratio = ratio
            best_bbox = [[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]]
            best_page = pdf_item["page"]
    return best_match_ratio, str(best_bbox) if best_bbox else "None", best_page

def find_accumulated_match(xml_text, pdf_texts, threshold):
    """(다중 라인 누적용) Body, Back 본문 단락/참고문헌 정밀 검색"""
    if not xml_text: return 0, "None", -1
    
    clean_xml = xml_text.replace(" ", "").replace("\n", "").strip()
    clean_xml_for_prefix = re.sub(r'^[^\w가-힣]+', '', clean_xml)
    xml_prefix = clean_xml_for_prefix[:3] if len(clean_xml_for_prefix) >= 3 else clean_xml_for_prefix
        
    best_match_ratio, best_blocks, best_start_page = 0, [], -1
    
    for i in range(len(pdf_texts)):
        clean_pdf_block = re.sub(r'^[^\w가-힣]+', '', pdf_texts[i]["text"].replace(" ", "").replace("\n", "").strip())
        
        if not xml_prefix or clean_pdf_block.startswith(xml_prefix):
            accumulated_text = ""
            current_blocks = []
            start_page = pdf_texts[i]["page"]
            
            for j in range(i, len(pdf_texts)):
                accumulated_text += pdf_texts[j]["text"]
                current_blocks.append({"page": pdf_texts[j]["page"], "bbox": pdf_texts[j]["bbox"]})
                
                current_clean_acc = accumulated_text.replace(" ", "").replace("\n", "").strip()
                ratio = get_similarity(clean_xml, current_clean_acc)
                
                if ratio > best_match_ratio:
                    best_match_ratio = ratio
                    best_blocks = list(current_blocks)
                    best_start_page = start_page
                    
                if len(current_clean_acc) >= len(clean_xml) + 5: 
                    break
    
    if best_match_ratio >= threshold:
        # 분리/병합 로직 적용
        merged = merge_multi_page_bboxes(best_blocks)
        return best_match_ratio, str(merged), best_start_page
    else:
        return best_match_ratio, "None", best_start_page if best_start_page != -1 else 0

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
        parent_map = {c: p for p in root.iter() for c in p}
    except Exception as e:
        st.error(f"❌ XML 파싱 오류: {e}")
        st.stop()

    def should_exclude_body_node(node):
        text = extract_xml_text(node).replace(" ", "").replace("\n", "").lower()
        if not text: return False
        
        prefix_exclusions = ["keyword", "keywords", "핵심어", "주제어", "핵심주제어"]
        if any(text.startswith(p) for p in prefix_exclusions): return True
            
        exact_abstract_titles = ["요약", "국문요약", "영문요약", "초록", "국문초록", "영문초록", "abstract"]
        if node.tag == 'title':
            if text.strip("1234567890.ivx()[]<>- ") in exact_abstract_titles: return True
                
        curr = node
        while curr is not None:
            if curr.tag in ['abstract', 'kwd-group', 'kwd']: return True
            if curr.tag == 'sec':
                title_node = curr.find('title')
                if title_node is not None:
                    t_text = extract_xml_text(title_node).replace(" ", "").replace("\n", "").lower()
                    if t_text.strip("1234567890.ivx()[]<>- ") in exact_abstract_titles: return True
            curr = parent_map.get(curr)
        return False

    doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
    
    if "pdf_view_page" not in st.session_state: st.session_state.pdf_view_page = 0
    
    # 1. PDF 텍스트 추출 (Line-level 분해 적용)
    extracted_pdf_texts = []
    for p_num in range(len(doc)):
        p_blocks = doc[p_num].get_text("dict")["blocks"]
        
        def get_block_sort_key(block):
            if "bbox" in block:
                x0, y0, x1, y1 = block["bbox"]
                col = 0 if x0 < 300 else 1
                return (col, y0)
            return (0, 0)
            
        p_blocks_sorted = sorted(p_blocks, key=get_block_sort_key)
        
        for b in p_blocks_sorted:
            if "lines" in b:
                for line in b["lines"]:
                    line_text = "".join([span["text"] for span in line["spans"]])
                    line_text_stripped = line_text.strip()
                    if line_text_stripped.endswith("-"): line_text = line_text_stripped[:-1]
                    extracted_pdf_texts.append({"page": p_num, "text": line_text, "bbox": line["bbox"]})

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
                
                best_match_ratio, best_bbox, best_page = 0, "None", -1
                for pdf_item in extracted_pdf_texts:
                    max_ratio = max(get_similarity(format1, pdf_item["text"]), get_similarity(format2, pdf_item["text"]))
                    if max_ratio > best_match_ratio:
                        best_match_ratio = max_ratio
                        best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
                        best_page = pdf_item["page"]
                
                xml_display_text = f"{given} {surname}".strip()
                if best_match_ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "page": best_page, "bbox": best_bbox, "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(name_node))

            for email_node in contrib.findall('.//email'):
                xml_text = extract_xml_text(email_node)
                if not xml_text: continue
                ratio, bbox_str, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(email_node))

            for orcid_node in contrib.findall('.//contrib-id'):
                if orcid_node.attrib.get('contrib-id-type') == 'orcid' or 'orcid' in extract_xml_text(orcid_node).lower():
                    xml_text = extract_xml_text(orcid_node)
                    ratio, bbox_str, b_page = find_best_match(xml_text, extracted_pdf_texts)
                    if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(orcid_node))

            for role_node in contrib.findall('.//role'):
                xml_text = extract_xml_text(role_node)
                if not xml_text: continue
                ratio, bbox_str, b_page = find_best_match(xml_text, extracted_pdf_texts)
                if ratio >= FRONT_THRESHOLD: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(role_node))

    # ==========================================
    # [Body - 본문 제목, 표, 그림, 단락 매칭]
    # ==========================================
    body_node = root.find('.//body')
    if body_node is not None:
        
        for sec_node in body_node.findall('.//sec'):
            title_node = sec_node.find('title')
            if title_node is not None:
                if should_exclude_body_node(title_node): continue
                xml_text = extract_xml_text(title_node)
                if xml_text:
                    ratio, bbox_str, b_page = find_accumulated_match(xml_text, extracted_pdf_texts, BODY_TITLE_THRESHOLD)
                    if ratio >= BODY_TITLE_THRESHOLD: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(title_node))
        
        for fig_table_node in body_node.findall('.//table-wrap') + body_node.findall('.//fig'):
            if should_exclude_body_node(fig_table_node): continue
            tag_name = fig_table_node.tag
            label_node = fig_table_node.find('label')
            title_node = fig_table_node.find('.//caption/title')
            if title_node is None: title_node = fig_table_node.find('.//caption/p')
                
            xml_text = f"{extract_xml_text(label_node)} {extract_xml_text(title_node)}".strip()
            ratio, bbox_str, b_page = find_accumulated_match(xml_text, extracted_pdf_texts, BODY_FIG_TABLE_THRESHOLD)
            
            if ratio >= BODY_FIG_TABLE_THRESHOLD: mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(fig_table_node))

        for p_node in body_node.findall('.//p'):
            if should_exclude_body_node(p_node): continue
            xml_text = extract_xml_text(p_node)
            ratio, bbox_str, b_page = find_accumulated_match(xml_text, extracted_pdf_texts, BODY_P_THRESHOLD)
            
            if ratio >= BODY_P_THRESHOLD: mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(p_node))

    # ==========================================
    # [Back - 참고문헌 매칭]
    # ==========================================
    ref_start_idx = 0
    for i, item in enumerate(extracted_pdf_texts):
        if item["text"].replace(" ", "").strip() in ["참고문헌", "REFERENCES", "References"]:
            ref_start_idx = i; break
            
    pdf_texts_for_back = extracted_pdf_texts[ref_start_idx:]
    back_node = root.find('.//back')
    if back_node is not None:
        for ref in back_node.findall('.//ref'):
            annotation = ref.find('.//annotation')
            if annotation is None: continue
            xml_text = extract_xml_text(annotation)
            ratio, bbox_str, b_page = find_accumulated_match(xml_text, pdf_texts_for_back, BACK_THRESHOLD)
            
            if ratio >= BACK_THRESHOLD: mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_back.append(get_raw_xml(ref))

    # ==========================================
    # [데이터 정렬 로직]
    # ==========================================
    df = pd.DataFrame(mapped_data)
    if not df.empty:
        def get_sort_keys(row):
            page, bbox_str = row['page'], row['bbox']
            if bbox_str == "None": return page, 9999, 9999
            try:
                bbox_data = ast.literal_eval(bbox_str)
                # 바운딩 박스가 여러 개(리스트의 리스트)일 경우 첫 번째 박스 기준
                p, x0, y0, x1, y1 = bbox_data[0]
                width = x1 - x0
                col = 0 if width > 250 or x0 < 300 else 1
                return p, col, y0
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
                        if selected_row_data['bbox'] != "None": st.session_state.pdf_view_page = int(selected_row_data['page'])
            with tab_body:
                if not df.empty and "Body" in df["category"].values:
                    df_body = df[df["category"] == "Body"].reset_index(drop=True)
                    event_body = st.dataframe(df_body, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_body_tab")
                    if len(event_body.selection.rows) > 0 and selected_row_data is None:
                        selected_row_data = df_body.iloc[event_body.selection.rows[0]].to_dict()
                        if selected_row_data['bbox'] != "None": st.session_state.pdf_view_page = int(selected_row_data['page'])
                else: st.info("매핑된 Body 데이터가 없습니다.")
            with tab_back:
                if not df.empty and "Back" in df["category"].values:
                    df_back = df[df["category"] == "Back"].reset_index(drop=True)
                    event_back = st.dataframe(df_back, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_b")
                    if len(event_back.selection.rows) > 0 and selected_row_data is None:
                        selected_row_data = df_back.iloc[event_back.selection.rows[0]].to_dict()
                        if selected_row_data['bbox'] != "None": st.session_state.pdf_view_page = int(selected_row_data['page'])
                
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

    # [좌측 패널] PDF 시각화 (다중 박스 렌더링 지원)
    @fragment
    def render_pdf_viewer(doc, selected_row):
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        with nav_col1:
            if st.button("◀ 이전 페이지", use_container_width=True):
                if st.session_state.pdf_view_page > 0: st.session_state.pdf_view_page -= 1; st.rerun()
        with nav_col3:
            if st.button("다음 페이지 ▶", use_container_width=True):
                if st.session_state.pdf_view_page < len(doc) - 1: st.session_state.pdf_view_page += 1; st.rerun()
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
                
                if selected_row and selected_row.get('bbox') != "None":
                    try:
                        bbox_data = ast.literal_eval(selected_row['bbox'])
                        draw = ImageDraw.Draw(img)
                        for b in bbox_data:
                            # b 구조: [page, x0, y0, x1, y1]
                            if b[0] == i:
                                scaled_bbox = [c * zoom for c in b[1:]]
                                draw.rectangle(scaled_bbox, outline="blue", width=3)
                    except Exception:
                        pass
                        
                st.image(img, use_container_width=True)
                
            components.html(
                f"""
                <script>
                    var target = window.parent.document.getElementById('pdf_page_{st.session_state.pdf_view_page}');
                    if (target) {{ target.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
                </script>
                """, height=0, width=0
            )

    with col_img:
        render_pdf_viewer(doc, selected_row_data)
