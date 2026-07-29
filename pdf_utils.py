import fitz  # PyMuPDF
import ast
import pandas as pd
import streamlit as st

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

@st.cache_data(show_spinner=False)
def create_annotated_pdf(pdf_bytes, mapped_data_df):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    for _, row in mapped_data_df.iterrows():
        if row.get("status") == "✅ 매칭 완료" and "bbox" in row and pd.notna(row["bbox"]) and row["bbox"] != "None":
            try:
                bbox_val = row["bbox"]
                bboxes = ast.literal_eval(bbox_val) if isinstance(bbox_val, str) else bbox_val
                
                for b in bboxes:
                    page_num = int(b[0])
                    rect = fitz.Rect(b[1], b[2], b[3], b[4])
                    page = doc[page_num]
                    page.draw_rect(rect, color=(1, 0, 0), width=1.5)
            except Exception:
                pass
                
    return doc.tobytes()
