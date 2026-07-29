import streamlit as st
from PIL import Image, ImageDraw
import pandas as pd
import ast
import json
import fitz

# 분리된 모듈 임포트
from pdf_utils import load_pdf_doc, process_pdf, create_annotated_pdf
from xml_utils import run_mapping_pipeline

# Streamlit 부분 재실행(Fragment) 데코레이터 호환성 처리
try:
    from streamlit import fragment
except ImportError:
    try:
        from streamlit import experimental_fragment as fragment
    except ImportError:
        def fragment(func): return func

st.set_page_config(layout="wide", page_title="JATS XML-PDF 라벨링 검수 툴")
st.title("JATS XML - PDF 태깅 시각화 및 검수 도구")
st.markdown("XML 데이터를 기준으로 단(Column)과 페이지(Page)를 넘나드는 문단을 정교하게 분리하여 매핑합니다.")

st.sidebar.header("매칭 임계값 설정 (Threshold)")
FRONT_THRESHOLD = st.sidebar.slider("Front (저자 항목별) 매칭 기준", 0.0, 1.0, 0.70, 0.05)
BODY_TITLE_THRESHOLD = st.sidebar.slider("Body (본문 제목) 매칭 기준", 0.0, 1.0, 0.95, 0.05) 
BODY_P_THRESHOLD = st.sidebar.slider("Body (본문 문단) 매칭 기준", 0.0, 1.0, 0.70, 0.05) 
BODY_FIG_TABLE_THRESHOLD = st.sidebar.slider("Body (표/그림 제목) 매칭 기준", 0.0, 1.0, 0.80, 0.05) 
BACK_THRESHOLD = st.sidebar.slider("Back (참고문헌) 매칭 기준", 0.0, 1.0, 0.65, 0.05) 

# =========================================================================
# DTD 기준 12개 탭 클래스 매핑 설정
# (현재 코드에서 추출되는 tag명 기준으로 매핑, 필요 시 실제 데이터에 맞춰 수정)
# =========================================================================
dtd_mapping = {
    # 02. 저자 그룹
    "name": 1, "email": 1, "orcid": 1, "role": 1,
    # 03. 소속 그룹
    "aff": 2, 
    # 04. 초록 그룹 (향후 확장 시)
    "abstract": 3,
    # 08. 표 및 그림 그룹
    "table-wrap": 7, "fig": 7, 
    # 09. 본문 그룹
    "sec/title": 8, "p": 8,
    # 11. 참고문헌 그룹
    "annotation": 10
}

tab_names = [
    "01. 제목", "02. 저자", "03. 소속", "04. 초록", 
    "05. 키워드", "06. 저널", "07. 식별자", "08. 표/그림", 
    "09. 본문", "10. 사사/출판", "11. 참고문헌", "12. 기타"
]

# 상태(State) 초기화
if "prev_sel" not in st.session_state: st.session_state.prev_sel = {i: [] for i in range(12)}
if "active_sel_data" not in st.session_state: st.session_state.active_sel_data = None
if "pdf_view_page" not in st.session_state: st.session_state.pdf_view_page = 0

col_up1, col_up2 = st.columns(2)
with col_up1:
    uploaded_pdf = st.file_uploader("PDF 원문 파일을 업로드하세요", type=["pdf"])
with col_up2:
    uploaded_xml = st.file_uploader("JATS XML 파일을 업로드하세요", type=["xml"])

if uploaded_pdf and uploaded_xml:
    try:
        pdf_bytes = uploaded_pdf.read()
        xml_bytes = uploaded_xml.read()
    except Exception as e:
        st.error(f"❌ 파일 읽기 오류: {e}")
        st.stop()

    doc = load_pdf_doc(pdf_bytes)
    extracted_pdf_texts, page_widths = process_pdf(pdf_bytes)
    
    df, unmapped_xml_front, unmapped_xml_body, unmapped_xml_back = run_mapping_pipeline(
        xml_bytes, extracted_pdf_texts, page_widths, 
        FRONT_THRESHOLD, BODY_TITLE_THRESHOLD, BODY_P_THRESHOLD, BODY_FIG_TABLE_THRESHOLD, BACK_THRESHOLD
    )

    st.markdown("---")
    col_img, col_data = st.columns([5, 5])
    
    with col_data:
        with st.container(height=850):
            
            # [헤더 영역] 제목 및 PDF 다운로드 버튼
            header_col1, header_col2 = st.columns([7, 3], vertical_alignment="bottom")
            with header_col1:
                st.subheader("📌 매핑된 정보 목록")
                st.markdown("<p style='color:gray; font-size:14px;'>아래 탭을 선택하고 목록을 클릭하면 좌측 PDF에 표시됩니다.</p>", unsafe_allow_html=True)
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
            
            st.write("") # 간격
            
            # DTD 12개 탭 생성
            tabs = st.tabs(tab_names)
            
            if not df.empty and 'tag' in df.columns:
                # DTD 매핑 딕셔너리에 없으면 11(12.기타)번 탭으로 분류
                df['tab_index'] = df['tag'].map(dtd_mapping).fillna(11).astype(int)
            
            changed = False
            for i, tab in enumerate(tabs):
                with tab:
                    if not df.empty:
                        tab_df = df[df['tab_index'] == i].reset_index(drop=True)
                        if not tab_df.empty:
                            event = st.dataframe(
                                tab_df.drop(columns=['tab_index']), # 보여줄 때 tab_index는 숨김 처리
                                use_container_width=True, 
                                height=300, 
                                on_select="rerun", 
                                selection_mode="single-row", 
                                key=f"tab_df_{i}"
                            )
                            
                            curr_sel = event.selection.rows if event else []
                            if curr_sel != st.session_state.prev_sel[i]:
                                st.session_state.prev_sel[i] = curr_sel
                                if curr_sel:
                                    st.session_state.active_sel_data = tab_df.iloc[curr_sel[0]].to_dict()
                                    changed = True
                                else:
                                    st.session_state.active_sel_data = None
                        else:
                            st.info("해당 그룹으로 매핑된 데이터가 없습니다.")
                    else:
                        st.info("데이터가 없습니다.")

            # 선택이 변경되었을 때 뷰어 페이지 동기화
            if changed and st.session_state.active_sel_data:
                if st.session_state.active_sel_data.get('bbox') != "None":
                    st.session_state.pdf_view_page = int(st.session_state.active_sel_data['page'])

            selected_row_data = st.session_state.active_sel_data
                
            st.markdown("<br>##### 📌 선택된 추출 정보 전체 데이터", unsafe_allow_html=True)
            with st.container(height=200):
                if selected_row_data: 
                    # 딕셔너리에서 화면에 출력할 때만 tab_index 키 제거
                    display_data = {k: v for k, v in selected_row_data.items() if k != 'tab_index'}
                    st.json(display_data)
                else: 
                    st.info("👆 위 테이블에서 행을 클릭하면 전체 매핑 정보가 이곳에 출력됩니다.")
                    
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
        # AI 학습용 JSON 데이터 다운로드 영역 (하단)
        # =========================================================================
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("### 💾 AI 학습용 데이터 Export")
        st.markdown("**매핑에 성공(✅ 매칭 완료)한 데이터**만 추출합니다.")
        
        if not df.empty:
            success_df = df[df["status"] == "✅ 매칭 완료"].copy()
            export_list = []
            for _, row in success_df.iterrows():
                row_dict = row.to_dict()
                row_dict.pop('tab_index', None) # 내보내기 시 tab_index 제거
                
                if row_dict.get('bbox') and row_dict['bbox'] != "None":
                    try:
                        row_dict['bbox'] = ast.literal_eval(row_dict['bbox'])
                    except (ValueError, SyntaxError):
                        pass
                export_list.append(row_dict)
                
            export_json = json.dumps(export_list, ensure_ascii=False, indent=4)
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

    # [좌측 패널] PDF 시각화 뷰어
    @fragment
    def render_pdf_viewer(doc, selected_row):
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        with nav_col1:
            if st.button("◀ 이전 페이지", use_container_width=True):
                if st.session_state.pdf_view_page > 0: st.session_state.pdf_view_page -= 1
        with nav_col3:
            if st.button("다음 페이지 ▶", use_container_width=True):
                if st.session_state.pdf_view_page < len(doc) - 1: st.session_state.pdf_view_page += 1
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
                    bbox_data = ast.literal_eval(selected_row['bbox']) if isinstance(selected_row['bbox'], str) else selected_row['bbox']
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
