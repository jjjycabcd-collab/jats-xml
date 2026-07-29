import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import xml.etree.ElementTree as ET
import pandas as pd
import ast
import difflib
import re
import json

# Streamlit 부분 재실행(Fragment) 데코레이터 호환성 처리
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

def merge_multi_page_bboxes(blocks):
    if not blocks: return []
    merged = []
    
    curr_box = list(blocks[0]["bbox"])
    curr_page = blocks[0]["page"]
    curr_width = blocks[0]["page_width"]
    curr_col = 0 if curr_box[0] < (curr_width / 2) else 1
    
    for b in blocks[1:]:
        p = b["page"]
        box = b["bbox"]
        w = b["page_width"]
        col = 0 if box[0] < (w / 2) else 1
        
        y_gap = box[1] - curr_box[3]
        
        if p == curr_page and col == curr_col and y_gap < 150:
            curr_box[0] = min(curr_box[0], box[0])
            curr_box[1] = min(curr_box[1], box[1])
            curr_box[2] = max(curr_box[2], box[2])
            curr_box[3] = max(curr_box[3], box[3])
        else:
            merged.append([curr_page] + [round(c, 2) for c in curr_box])
            curr_box = list(box)
            curr_page = p
            curr_col = col
            
    merged.append([curr_page] + [round(c, 2) for c in curr_box])
    return merged

def find_front_entity(xml_text, pdf_texts):
    if not xml_text: return 0.0, "None", -1, ""
    clean_xml = xml_text.replace(" ", "").lower()
    
    best_match_ratio, best_bbox, best_page, best_pdf_text = 0.0, "None", -1, ""
    
    for pdf_item in pdf_texts:
        clean_pdf = pdf_item["text"].replace(" ", "").lower()
        
        # 1. 완벽하게 포함되는 경우 (in) -> 블록 전체 반환
        if clean_xml in clean_pdf:
            return 1.0, str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]]), pdf_item["page"], pdf_item["text"]
        
        # 2. 부분 일치 실패 시 기존 유사도 알고리즘 적용
        ratio = get_similarity(clean_xml, clean_pdf)
        if ratio > best_match_ratio:
            best_match_ratio = ratio
            best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
            best_page = pdf_item["page"]
            best_pdf_text = pdf_item["text"]
            
    return best_match_ratio, best_bbox, best_page, best_pdf_text

def find_accumulated_match(xml_text, pdf_texts, threshold):
    if not xml_text: return 0.0, "None", -1, ""
    clean_xml = xml_text.replace(" ", "").replace("\n", "").strip()
    pure_xml_text = re.sub(r'[^\w가-힣a-zA-Z]', '', clean_xml)
    if not pure_xml_text: return 0.0, "None", -1, ""
        
    first_char = pure_xml_text[0]
    
    best_match_ratio, best_blocks, best_start_page, best_accumulated_text = 0.0, [], -1, ""
    
    for i in range(len(pdf_texts)):
        pure_pdf_block = re.sub(r'[^\w가-힣a-zA-Z]', '', pdf_texts[i]["text"])
        if not pure_pdf_block: continue
        
        # 글자가 하나씩 쪼개진 경우도 탐색을 시작하도록 조건 완화
        if first_char in pure_pdf_block or pure_pdf_block in pure_xml_text or pure_xml_text in pure_pdf_block:
            accumulated_text = ""
            raw_accumulated_text = ""
            current_lines = []
            match_page = pdf_texts[i]["page"]
            
            for j in range(i, len(pdf_texts)):
                if pdf_texts[j]["page"] - match_page > 1: break 
                
                line_clean = pdf_texts[j]["text"].replace(" ", "").replace("\n", "").strip()
                if not line_clean: continue
                
                accumulated_text += line_clean
                raw_accumulated_text += pdf_texts[j]["text"] + " "
                
                current_lines.append({
                    "length": len(line_clean),
                    "bbox": pdf_texts[j]["bbox"],
                    "page": pdf_texts[j]["page"],
                    "page_width": pdf_texts[j]["page_width"]
                })
                
                ratio = get_similarity(clean_xml, accumulated_text)
                
                if ratio > best_match_ratio:
                    best_match_ratio = ratio
                    best_start_page = match_page
                    best_accumulated_text = raw_accumulated_text.strip()
                    
                    sm = difflib.SequenceMatcher(None, clean_xml, accumulated_text)
                    matched_indices = set()
                    for match in sm.get_matching_blocks():
                        # 이름같이 짧은 경우 1글자 매칭도 허용
                        if match.size >= 2 or len(clean_xml) <= 4: 
                            for idx in range(match.b, match.b + match.size):
                                matched_indices.add(idx)
                                
                    valid_bboxes = []
                    current_char_idx = 0
                    for line_info in current_lines:
                        line_len = line_info["length"]
                        matched_in_line = sum(1 for k in range(current_char_idx, current_char_idx + line_len) if k in matched_indices)
                        
                        if matched_in_line >= max(1, int(line_len * 0.2)) or (line_len < 5 and matched_in_line > 0):
                            valid_bboxes.append({
                                "page": line_info["page"], 
                                "bbox": line_info["bbox"],
                                "page_width": line_info["page_width"]
                            })
                            
                        current_char_idx += line_len
                        
                    best_blocks = list(valid_bboxes)
                    
                if len(accumulated_text) >= len(clean_xml) + 150: 
                    break
                    
    if best_match_ratio >= threshold:
        merged = merge_multi_page_bboxes(best_blocks)
        return best_match_ratio, str(merged), best_start_page, best_accumulated_text
    else:
        return best_match_ratio, "None", best_start_page if best_start_page != -1 else 0, best_accumulated_text

@st.cache_resource
def load_pdf_doc(pdf_bytes):
    return fitz.open(stream=pdf_bytes, filetype="pdf")

@st.cache_data
def process_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_texts = []
    page_widths = {}
    
    for p_num in range(len(doc)):
        page = doc[p_num]
        w = page.rect.width
        page_widths[p_num] = w
        p_blocks = page.get_text("dict")["blocks"]
        
        def get_block_sort_key(block):
            if "bbox" in block:
                x0, y0, x1, y1 = block["bbox"]
                col = 0 if x0 < (w / 2) else 1 
                return (col, y0)
            return (0, 0)
            
        p_blocks_sorted = sorted(p_blocks, key=get_block_sort_key)
        
        for b in p_blocks_sorted:
            if "lines" in b:
                for line in b["lines"]:
                    line_text = "".join([span["text"] for span in line["spans"]])
                    line_text_stripped = line_text.strip()
                    if line_text_stripped.endswith("-"): line_text = line_text_stripped[:-1]
                    extracted_texts.append({
                        "page": p_num, 
                        "text": line_text, 
                        "bbox": line["bbox"],
                        "page_width": w
                    })
    return extracted_texts, page_widths

# =========================================================================
# [신규 추가] 시각화(Bounding Box)가 적용된 PDF 생성 함수
# =========================================================================
@st.cache_data(show_spinner=False)
def create_annotated_pdf(pdf_bytes, mapped_data_df):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    for _, row in mapped_data_df.iterrows():
        # bbox 데이터가 존재하는 매핑 완료 행만 처리
        if row.get("status") == "✅ 매칭 완료" and "bbox" in row and pd.notna(row["bbox"]) and row["bbox"] != "None":
            try:
                # 문자열이면 리스트로 변환, 이미 리스트면 그대로 사용
                bbox_val = row["bbox"]
                bboxes = ast.literal_eval(bbox_val) if isinstance(bbox_val, str) else bbox_val
                
                for b in bboxes:
                    page_num = int(b[0])
                    rect = fitz.Rect(b[1], b[2], b[3], b[4])
                    page = doc[page_num]
                    # PDF 페이지 위에 빨간색 외곽선 그리기
                    page.draw_rect(rect, color=(1, 0, 0), width=1.5)
            except Exception:
                pass
                
    return doc.tobytes()

# =========================================================================
# 매핑 로직 전체 캐싱 
# =========================================================================
@st.cache_data(show_spinner="XML과 PDF 텍스트를 분석하여 매핑 중입니다... (최초 1회만 실행)")
def run_mapping_pipeline(xml_bytes, _extracted_pdf_texts, _page_widths, 
                         front_th, body_title_th, body_p_th, body_fig_th, back_th):
    
    tree = ET.ElementTree(ET.fromstring(xml_bytes))
    root = tree.getroot()
    parent_map = {c: p for p in root.iter() for c in p}

    def should_exclude_body_node(node):
        text = extract_xml_text(node).replace(" ", "").replace("\n", "").lower()
        if not text: return False
        prefix_exclusions = ["keyword", "keywords", "핵심어", "주제어", "핵심주제어"]
        if any(text.startswith(p) for p in prefix_exclusions): return True
        exact_abstract_titles = ["요약", "국문요약", "영문요약", "초록", "국문초록", "영문초록", "abstract"]
        if node.tag == 'title' and text.strip("1234567890.ivx()[]<>- ") in exact_abstract_titles: return True
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

    abs_page = -1
    abs_y0 = -1
    abs_idx = 0
    
    for i, item in enumerate(_extracted_pdf_texts):
        if item["page"] > 2: break
        c_text = item["text"].replace(" ", "").strip().lower()
        
        is_fm = False
        for kw in ["초록", "요약", "주제어", "핵심어", "abstract", "keyword"]:
            if (c_text.startswith(kw + ":") or c_text.startswith(kw + "]") or 
                c_text.startswith(kw + ">") or c_text.startswith("[" + kw) or 
                c_text.startswith("<" + kw) or c_text.startswith("【" + kw) or c_text.startswith(kw + "】")):
                is_fm = True
                break
            elif c_text.startswith(kw) and len(c_text) < 20:
                is_fm = True
                break
                
        if is_fm:
            abs_page = item["page"]
            abs_y0 = item["bbox"][1] 
            abs_idx = i              
            
    pdf_texts_for_body = []
    for i, item in enumerate(_extracted_pdf_texts):
        if i < abs_idx:
            continue
            
        if abs_page != -1 and item["page"] == abs_page:
            if item["bbox"][1] < abs_y0 - 20:
                continue 
                
        pdf_texts_for_body.append(item)

    mapped_data = []
    unmapped_xml_front, unmapped_xml_body, unmapped_xml_back = [], [], []
    
    # [Front 매핑]
    front_node = root.find('.//front')
    if front_node is not None:
        
        # 첫 페이지와 마지막 페이지만 Front 탐색 대상으로 제한
        max_page = _extracted_pdf_texts[-1]["page"] if _extracted_pdf_texts else 0
        front_target_texts = [item for item in _extracted_pdf_texts if item["page"] in (0, max_page)]

        for contrib in front_node.findall('.//contrib'):
            
            # 1. 저자명 (Name)
            for name_node in contrib.findall('.//name'):
                surname = extract_xml_text(name_node.find('surname'))
                given = extract_xml_text(name_node.find('given-names'))
                
                # 공백 없는 순수 텍스트 추출
                pure_surname = re.sub(r'[^\w가-힣a-zA-Z]', '', surname)
                pure_given = re.sub(r'[^\w가-힣a-zA-Z]', '', given)
                
                # 이름+성, 성+이름 조합 생성
                format1 = pure_given + pure_surname
                format2 = pure_surname + pure_given
                
                best_match_ratio, best_bbox, best_page, best_pdf_text = 0.0, "None", -1, ""
                
                # 1차 탐색: 같은 블록 안에 완전히 포함되어 있는지 확인
                for pdf_item in front_target_texts:
                    pure_pdf = re.sub(r'[^\w가-힣a-zA-Z]', '', pdf_item["text"])
                    if format1 and format1 in pure_pdf:
                        best_match_ratio = 1.0
                        best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
                        best_page = pdf_item["page"]
                        best_pdf_text = pdf_item["text"]
                        break
                    if format2 and format2 in pure_pdf:
                        best_match_ratio = 1.0
                        best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
                        best_page = pdf_item["page"]
                        best_pdf_text = pdf_item["text"]
                        break
                
                # 2차 탐색: 쪼개진 글자(누적 블록)를 대상으로 이름+성, 성+이름 순서로 찾기
                if best_match_ratio < front_th:
                    r1, b1, p1, t1 = find_accumulated_match(format1, front_target_texts, front_th)
                    r2, b2, p2, t2 = find_accumulated_match(format2, front_target_texts, front_th)
                    
                    if max(r1, r2) > best_match_ratio:
                        if r1 >= r2:
                            best_match_ratio, best_bbox, best_page, best_pdf_text = r1, b1, p1, t1
                        else:
                            best_match_ratio, best_bbox, best_page, best_pdf_text = r2, b2, p2, t2
                
                xml_display_text = f"{given} {surname}".strip()
                if best_match_ratio >= front_th: 
                    mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "matched_pdf_text": best_pdf_text, "page": best_page, "bbox": best_bbox, "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: 
                    mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "matched_pdf_text": "", "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"})
                    unmapped_xml_front.append(get_raw_xml(name_node))

            # 2. 이메일 (Email)
            for email_node in contrib.findall('.//email'):
                xml_text = extract_xml_text(email_node)
                ratio, bbox_str, b_page, pdf_text = find_front_entity(xml_text, front_target_texts)
                if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(email_node))

            # 3. ORCID (Contrib-id)
            for orcid_node in contrib.findall('.//contrib-id'):
                if orcid_node.attrib.get('contrib-id-type') == 'orcid' or 'orcid' in extract_xml_text(orcid_node).lower():
                    xml_text = extract_xml_text(orcid_node)
                    orcid_num = xml_text.split('/')[-1] if '/' in xml_text else xml_text
                    
                    ratio, bbox_str, b_page, pdf_text = find_front_entity(orcid_num, front_target_texts)
                    if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(orcid_node))

            # 4. 역할 (Role)
            for role_node in contrib.findall('.//role'):
                xml_text = extract_xml_text(role_node)
                ratio, bbox_str, b_page, pdf_text = find_front_entity(xml_text, front_target_texts)
                if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(role_node))

        # 5. 소속 (Affiliation)
        for aff_node in front_node.findall('.//aff'):
            label_node = aff_node.find('label')
            label_text = extract_xml_text(label_node) if label_node is not None else ""
            full_text = extract_xml_text(aff_node)
            
            clean_aff_text = full_text.replace(label_text, "", 1).strip() if label_text else full_text
            
            if clean_aff_text:
                ratio, bbox_str, b_page, pdf_text = find_front_entity(clean_aff_text, front_target_texts)
                
                if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "aff", "xml_text": full_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "aff", "xml_text": full_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(aff_node))

    # [Body 매핑]
    body_node = root.find('.//body')
    if body_node is not None:
        for sec_node in body_node.findall('.//sec'):
            title_node = sec_node.find('title')
            if title_node is not None:
                if should_exclude_body_node(title_node): continue
                xml_text = extract_xml_text(title_node)
                if xml_text:
                    ratio, bbox_str, b_page, pdf_text = find_accumulated_match(xml_text, pdf_texts_for_body, body_title_th)
                    if ratio >= body_title_th: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Body", "tag": "sec/title", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(title_node))
        
        for fig_table_node in body_node.findall('.//table-wrap') + body_node.findall('.//fig'):
            if should_exclude_body_node(fig_table_node): continue
            tag_name = fig_table_node.tag
            label_node = fig_table_node.find('label')
            title_node = fig_table_node.find('.//caption/title')
            if title_node is None: title_node = fig_table_node.find('.//caption/p')
                
            xml_text = f"{extract_xml_text(label_node)} {extract_xml_text(title_node)}".strip()
            ratio, bbox_str, b_page, pdf_text = find_accumulated_match(xml_text, pdf_texts_for_body, body_fig_th)
            if ratio >= body_fig_th: mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Body", "tag": tag_name, "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(fig_table_node))

        for p_node in body_node.findall('.//p'):
            if should_exclude_body_node(p_node): continue
            xml_text = extract_xml_text(p_node)
            ratio, bbox_str, b_page, pdf_text = find_accumulated_match(xml_text, pdf_texts_for_body, body_p_th)
            if ratio >= body_p_th: mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Body", "tag": "p", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_body.append(get_raw_xml(p_node))

    # [Back 매핑]
    ref_start_idx = 0
    for i, item in enumerate(_extracted_pdf_texts):
        c_text = item["text"].replace(" ", "").strip().lower()
        if "참고문헌" in c_text or "references" in c_text:
            ref_start_idx = i; break
            
    pdf_texts_for_back = _extracted_pdf_texts[ref_start_idx:]
    back_node = root.find('.//back')
    if back_node is not None:
        for ref in back_node.findall('.//ref'):
            annotation = ref.find('.//annotation')
            if annotation is None: continue
            xml_text = extract_xml_text(annotation)
            ratio, bbox_str, b_page, pdf_text = find_accumulated_match(xml_text, pdf_texts_for_back, back_th)
            
            if ratio >= back_th: mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
            elif xml_text: mapped_data.append({"category": "Back", "tag": "annotation", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_back.append(get_raw_xml(ref))

    # [정렬 및 DataFrame 반환]
    df = pd.DataFrame(mapped_data)
    if not df.empty:
        def get_sort_keys(row):
            page, bbox_str = row['page'], row['bbox']
            if bbox_str == "None": return page, 9999, 9999
            try:
                bbox_data = ast.literal_eval(bbox_str)
                p, x0, y0, x1, y1 = bbox_data[0]
                pw = _page_widths.get(p, 595.0) 
                col = 0 if x0 < (pw / 2) else 1
                return p, col, y0
            except (ValueError, SyntaxError, IndexError): 
                return page, 9999, 9999

        df['sort_page'] = df.apply(get_sort_keys, axis=1).apply(lambda x: x[0])
        df['sort_col']  = df.apply(get_sort_keys, axis=1).apply(lambda x: x[1])
        df['sort_y0']   = df.apply(get_sort_keys, axis=1).apply(lambda x: x[2])
        df = df.sort_values(by=['sort_page', 'sort_col', 'sort_y0']).drop(columns=['sort_page', 'sort_col', 'sort_y0']).reset_index(drop=True)

    return df, unmapped_xml_front, unmapped_xml_body, unmapped_xml_back


# ---------------------------------------------------------
# 메인 로직
# ---------------------------------------------------------
col_up1, col_up2 = st.columns(2)
with col_up1:
    uploaded_pdf = st.file_uploader("PDF 원문 파일을 업로드하세요", type=["pdf"])
with col_up2:
    uploaded_xml = st.file_uploader("JATS XML 파일을 업로드하세요", type=["xml"])

if "prev_sel_f" not in st.session_state: st.session_state.prev_sel_f = []
if "prev_sel_body" not in st.session_state: st.session_state.prev_sel_body = []
if "prev_sel_b" not in st.session_state: st.session_state.prev_sel_b = []
if "active_sel_data" not in st.session_state: st.session_state.active_sel_data = None

if uploaded_pdf and uploaded_xml:
    try:
        pdf_bytes = uploaded_pdf.read()
        xml_bytes = uploaded_xml.read()
    except Exception as e:
        st.error(f"❌ 파일 읽기 오류: {e}")
        st.stop()

    doc = load_pdf_doc(pdf_bytes)
    extracted_pdf_texts, page_widths = process_pdf(pdf_bytes)
    
    if "pdf_view_page" not in st.session_state: 
        st.session_state.pdf_view_page = 0

    df, unmapped_xml_front, unmapped_xml_body, unmapped_xml_back = run_mapping_pipeline(
        xml_bytes, extracted_pdf_texts, page_widths, 
        FRONT_THRESHOLD, BODY_TITLE_THRESHOLD, BODY_P_THRESHOLD, BODY_FIG_TABLE_THRESHOLD, BACK_THRESHOLD
    )

    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    with col_data:
        with st.container(height=850):
            
            # =========================================================================
            # [추가된 영역] 매핑 정보 목록 제목 및 PDF 다운로드 버튼 배치
            # =========================================================================
            header_col1, header_col2 = st.columns([7, 3], vertical_alignment="bottom")
            with header_col1:
                st.subheader("📌 매핑된 정보 목록")
                st.markdown("<p style='color:gray; font-size:14px;'>아래 목록을 클릭하면 좌측 PDF에 해당 영역이 표시됩니다.</p>", unsafe_allow_html=True)
            with header_col2:
                if not df.empty:
                    annotated_pdf_bytes = create_annotated_pdf(pdf_bytes, df)
                    st.download_button(
                        label="📥 PDF 다운로드",
                        data=annotated_pdf_bytes,
                        file_name="annotated_document.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary"
                    )
            
            st.write("") # 간격 띄우기
            
            tab_front, tab_body, tab_back = st.tabs(["Front (저자 정보)", "Body (본문)", "Back (참고문헌)"])
            
            event_front, event_body, event_back = None, None, None
            df_front, df_body, df_back = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
            
            with tab_front:
                if not df.empty and "Front" in df["category"].values:
                    df_front = df[df["category"] == "Front"].reset_index(drop=True)
                    event_front = st.dataframe(df_front, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_f")
            
            with tab_body:
                if not df.empty and "Body" in df["category"].values:
                    df_body = df[df["category"] == "Body"].reset_index(drop=True)
                    event_body = st.dataframe(df_body, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_body_tab")
                else: st.info("매핑된 Body 데이터가 없습니다.")
            
            with tab_back:
                if not df.empty and "Back" in df["category"].values:
                    df_back = df[df["category"] == "Back"].reset_index(drop=True)
                    event_back = st.dataframe(df_back, use_container_width=True, height=250, on_select="rerun", selection_mode="single-row", key="df_b")

            curr_sel_f = event_front.selection.rows if event_front else []
            curr_sel_body = event_body.selection.rows if event_body else []
            curr_sel_b = event_back.selection.rows if event_back else []

            changed = False
            
            if curr_sel_f != st.session_state.prev_sel_f:
                st.session_state.prev_sel_f = curr_sel_f
                if curr_sel_f:
                    st.session_state.active_sel_data = df_front.iloc[curr_sel_f[0]].to_dict()
                    changed = True
                else: st.session_state.active_sel_data = None
            
            elif curr_sel_body != st.session_state.prev_sel_body:
                st.session_state.prev_sel_body = curr_sel_body
                if curr_sel_body:
                    st.session_state.active_sel_data = df_body.iloc[curr_sel_body[0]].to_dict()
                    changed = True
                else: st.session_state.active_sel_data = None
            
            elif curr_sel_b != st.session_state.prev_sel_b:
                st.session_state.prev_sel_b = curr_sel_b
                if curr_sel_b:
                    st.session_state.active_sel_data = df_back.iloc[curr_sel_b[0]].to_dict()
                    changed = True
                else: st.session_state.active_sel_data = None

            if changed and st.session_state.active_sel_data:
                if st.session_state.active_sel_data.get('bbox') != "None":
                    st.session_state.pdf_view_page = int(st.session_state.active_sel_data['page'])

            selected_row_data = st.session_state.active_sel_data
                
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

        # =========================================================================
        # AI 학습용 데이터 다운로드 영역 (하단)
        # =========================================================================
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("### 💾 AI 학습용 데이터 Export")
        st.markdown("Front, Body, Back 영역 중 **매핑에 성공(✅ 매칭 완료)한 데이터**만 추출합니다.")
        
        if not df.empty:
            # 1. '✅ 매칭 완료' 된 항목만 필터링
            success_df = df[df["status"] == "✅ 매칭 완료"].copy()
            
            export_list = []
            for _, row in success_df.iterrows():
                row_dict = row.to_dict()
                
                # 2. AI 학습용으로 처리하기 쉽도록 Bounding Box 문자열을 실제 리스트 객체로 변환
                if row_dict.get('bbox') and row_dict['bbox'] != "None":
                    try:
                        row_dict['bbox'] = ast.literal_eval(row_dict['bbox'])
                    except (ValueError, SyntaxError):
                        pass
                        
                export_list.append(row_dict)
                
            # JSON 형태로 변환
            export_json = json.dumps(export_list, ensure_ascii=False, indent=4)
            
            # 다운로드 버튼 생성
            st.download_button(
                label="📥 AI 학습용 데이터 다운로드 (.json)",
                data=export_json,
                file_name="ai_training_dataset.json",
                mime="application/json",
                use_container_width=True,
                type="primary"
            )
        else:
            st.info("추출할 매핑 데이터가 없습니다.")

    # [좌측 패널] PDF 시각화 
    @fragment
    def render_pdf_viewer(doc, selected_row):
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        with nav_col1:
            if st.button("◀ 이전 페이지", use_container_width=True):
                if st.session_state.pdf_view_page > 0: 
                    st.session_state.pdf_view_page -= 1
        with nav_col3:
            if st.button("다음 페이지 ▶", use_container_width=True):
                if st.session_state.pdf_view_page < len(doc) - 1: 
                    st.session_state.pdf_view_page += 1
        with nav_col2:
            st.markdown(f"<h4 style='text-align: center; margin-top: 0px;'>📄 Page {st.session_state.pdf_view_page + 1} / {len(doc)}</h4>", unsafe_allow_html=True)
            
        st.divider()
        
        with st.container(height=750):
            view_page = st.session_state.pdf_view_page
            zoom = 2.0  
            
            page = doc[view_page]
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            if selected_row and selected_row.get('bbox') != "None":
                try:
                    bbox_data = ast.literal_eval(selected_row['bbox'])
                    draw = ImageDraw.Draw(img)
                    for b in bbox_data:
                        if b[0] == view_page:
                            scaled_bbox = [c * zoom for c in b[1:]]
                            draw.rectangle(scaled_bbox, outline="red", width=4)
                except (ValueError, SyntaxError, IndexError):
                    pass
                    
            st.image(img, use_container_width=True)

    with col_img:
        render_pdf_viewer(doc, selected_row_data)
