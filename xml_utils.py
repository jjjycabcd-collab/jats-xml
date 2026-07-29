import xml.etree.ElementTree as ET
import difflib
import re
import ast
import pandas as pd
import streamlit as st

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
        
        if clean_xml in clean_pdf:
            return 1.0, str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]]), pdf_item["page"], pdf_item["text"]
        
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
        max_page = _extracted_pdf_texts[-1]["page"] if _extracted_pdf_texts else 0
        front_target_texts = [item for item in _extracted_pdf_texts if item["page"] in (0, max_page)]

        for contrib in front_node.findall('.//contrib'):
            for name_node in contrib.findall('.//name'):
                surname = extract_xml_text(name_node.find('surname'))
                given = extract_xml_text(name_node.find('given-names'))
                pure_surname = re.sub(r'[^\w가-힣a-zA-Z]', '', surname)
                pure_given = re.sub(r'[^\w가-힣a-zA-Z]', '', given)
                format1 = pure_given + pure_surname
                format2 = pure_surname + pure_given
                
                best_match_ratio, best_bbox, best_page, best_pdf_text = 0.0, "None", -1, ""
                for pdf_item in front_target_texts:
                    pure_pdf = re.sub(r'[^\w가-힣a-zA-Z]', '', pdf_item["text"])
                    if format1 and format1 in pure_pdf:
                        best_match_ratio = 1.0
                        best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
                        best_page = pdf_item["page"]; best_pdf_text = pdf_item["text"]; break
                    if format2 and format2 in pure_pdf:
                        best_match_ratio = 1.0
                        best_bbox = str([[pdf_item["page"]] + [round(c, 2) for c in pdf_item["bbox"]]])
                        best_page = pdf_item["page"]; best_pdf_text = pdf_item["text"]; break
                
                if best_match_ratio < front_th:
                    r1, b1, p1, t1 = find_accumulated_match(format1, front_target_texts, front_th)
                    r2, b2, p2, t2 = find_accumulated_match(format2, front_target_texts, front_th)
                    if max(r1, r2) > best_match_ratio:
                        if r1 >= r2: best_match_ratio, best_bbox, best_page, best_pdf_text = r1, b1, p1, t1
                        else: best_match_ratio, best_bbox, best_page, best_pdf_text = r2, b2, p2, t2
                
                xml_display_text = f"{given} {surname}".strip()
                if best_match_ratio >= front_th: mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "matched_pdf_text": best_pdf_text, "page": best_page, "bbox": best_bbox, "similarity": f"{best_match_ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "name", "xml_text": xml_display_text, "matched_pdf_text": "", "page": best_page if best_page != -1 else 0, "bbox": "None", "similarity": f"{best_match_ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(name_node))

            for email_node in contrib.findall('.//email'):
                xml_text = extract_xml_text(email_node)
                ratio, bbox_str, b_page, pdf_text = find_front_entity(xml_text, front_target_texts)
                if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "email", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(email_node))

            for orcid_node in contrib.findall('.//contrib-id'):
                if orcid_node.attrib.get('contrib-id-type') == 'orcid' or 'orcid' in extract_xml_text(orcid_node).lower():
                    xml_text = extract_xml_text(orcid_node)
                    orcid_num = xml_text.split('/')[-1] if '/' in xml_text else xml_text
                    ratio, bbox_str, b_page, pdf_text = find_front_entity(orcid_num, front_target_texts)
                    if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                    else: mapped_data.append({"category": "Front", "tag": "orcid", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(orcid_node))

            for role_node in contrib.findall('.//role'):
                xml_text = extract_xml_text(role_node)
                ratio, bbox_str, b_page, pdf_text = find_front_entity(xml_text, front_target_texts)
                if ratio >= front_th: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "matched_pdf_text": pdf_text, "page": b_page, "bbox": bbox_str, "similarity": f"{ratio * 100:.1f}%", "status": "✅ 매칭 완료"})
                else: mapped_data.append({"category": "Front", "tag": "role", "xml_text": xml_text, "matched_pdf_text": "", "page": b_page if b_page != -1 else 0, "bbox": "None", "similarity": f"{ratio * 100:.1f}%", "status": "❌ 매핑 실패"}); unmapped_xml_front.append(get_raw_xml(role_node))

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
