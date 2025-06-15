import os
import json
import pandas as pd
import google.generativeai as genai
import streamlit as st
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# ※ torch.classes 관련 오류 회피용 처리 (주의: 추후 해당 모듈 사용 시 문제될 수 있음)
import sys
sys.modules["torch.classes"] = None

# ─────────────────────────────────────────────────────────────
# 1. 환경 설정: API 키 및 모델 초기화
# ─────────────────────────────────────────────────────────────
load_dotenv()
genai.configure(api_key=os.environ["API_KEY"])

# KoELECTRA 기반 텍스트 분류기 로딩
tokenizer = AutoTokenizer.from_pretrained("./koelectra-intent")
model = AutoModelForSequenceClassification.from_pretrained("./koelectra-intent")

def classify(text):
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    logits = outputs.logits
    predicted_class_id = logits.argmax().item()
    return predicted_class_id  # LABEL_0 → 0, LABEL_1 → 1 (정수형으로 반환됨)

# ─────────────────────────────────────────────────────────────
# 2. Streamlit 기본 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="개인정보 필터 데모", page_icon="🔐")
st.title("🔐 개인정보 필터 데모")

# ─────────────────────────────────────────────────────────────
# 3. 데이터 로딩 (최초 한 번만 실행, 캐시 사용)
# ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    with open("data.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    json_text = json.dumps(data, ensure_ascii=False, indent=2)
    return json_text

json_text = load_data()
# print(json_text)

# ─────────────────────────────────────────────────────────────
# 3-2. 사이드바: 학과 정보 요약 및 학생 개별 정보 보기
# ─────────────────────────────────────────────────────────────
@st.cache_data
def extract_departments(json_text):
    """학과 요약 테이블 생성"""
    data = json.loads(json_text)
    departments = [{
        "학과명": d["학과명"],
        "소속대학": d["소속대학"],
        "건물호실": d["건물호실"],
        "전화번호": d["전화번호"],
        "웹사이트": d["웹사이트"],
        "평균학점": d["평균학점"],
        "학생 수": len(d["학생목록"]),
        "학생회장": d["학생회장"]
    } for d in data]
    return pd.DataFrame(departments)

@st.cache_data
def get_department_names(json_text):
    data = json.loads(json_text)
    return [dept["학과명"] for dept in data]

@st.cache_data
def get_students_by_department(json_text, dept_name):
    data = json.loads(json_text)
    for dept in data:
        if dept["학과명"] == dept_name:
            return pd.DataFrame(dept["학생목록"])
    return pd.DataFrame()

# ─────────────────────────────────────────────────────────────
# 사이드바 구성
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏫 학과 정보 보기")

    # 학과 요약 테이블 보기
    with st.expander("📘 전체 학과 요약"):
        st.markdown("※ 이 시스템이 기억하고 있는 전체 학과 정보입니다.")
        df_summary = extract_departments(json_text)
        st.dataframe(df_summary)

    # 개별 학과 학생 정보 보기
    with st.expander("👥 학과별 학생 상세 정보"):
        st.markdown("※ 테스트용 가상 개인정보입니다.")

        department_list = get_department_names(json_text)
        selected_dept = st.selectbox("학과를 선택하세요", department_list)

        students_df = get_students_by_department(json_text, selected_dept)
        if not students_df.empty:
            st.dataframe(students_df.style.highlight_max("GPA", axis=0).highlight_min("GPA", axis=0))
        else:
            st.info("선택한 학과에 학생 정보가 없습니다.")


# ─────────────────────────────────────────────────────────────
# 4. 세션 상태 초기화
# ─────────────────────────────────────────────────────────────
if "chat" not in st.session_state:
    # 시스템 프롬프트 정의
    prompt_alternative_recommender = "너는 사용자의 질문이 개인정보를 침해하지 않도록, 집단적인 통계에 관련된 우회 질문을 추천하는 역할을 해. 답은 반드시 한국어로 해줘."
    prompt = "모든 대답은 반드시 한국어로 해줘."
    prompt_output_filter = """입력받은 텍스트에서 개인정보가 포함되어 있다면 개인정보 보호로 인해 알려줄 수 없다고 말해.
개인정보가 포함되어 있지 않다면 입력받은 값을 그대로 출력해줘. 평가 과정은 출력하지 말고, 결과만 출력해."""

    # Gemini 세션 초기화
    model = genai.GenerativeModel("gemini-1.5-flash")
    st.session_state.chat_alternative = model.start_chat(history=[{"role": "user", "parts": [prompt_alternative_recommender]}])
    st.session_state.chat = model.start_chat(history=[
        {"role": "user", "parts": [prompt]},
        {"role": "user", "parts": [f"다음은 서울대학교에 관련된 정보입니다:\n\n{json_text}"]}
    ])
    st.session_state.chat_output_filter = model.start_chat(history=[{"role": "user", "parts": [prompt_output_filter]}])
    st.session_state.chat_history = []

# 세션에서 채팅 객체 불러오기
chat_alternative = st.session_state.chat_alternative
chat = st.session_state.chat
chat_output_filter = st.session_state.chat_output_filter

# ─────────────────────────────────────────────────────────────
# 5. 기존 대화 출력
# ─────────────────────────────────────────────────────────────
for role, message in st.session_state.chat_history:
    with st.chat_message("user" if role == "user" else "ai"):
        st.markdown(message)

# ─────────────────────────────────────────────────────────────
# 6. 사용자 입력 및 필터링 로직
# ─────────────────────────────────────────────────────────────

user_input = st.chat_input("질문을 입력하세요...")

# ─────────────────────────────────────────────────────────────
# 6-1. 예시 질문 제공 (개인정보 질문 vs 일반 정보 탐색 질문)
# ─────────────────────────────────────────────────────────────

example_questions_sensitive = [
    "김하윤 학생의 학번 알려줘",
    "장윤서의 주소가 뭐야?",
    "심리학과 학생 중에서 GPA 제일 높은 사람은 누구야?",
    "사회학과 학생회장의 전화번호 알려줘"
]

example_questions_general = [
    "국사학과 학생회장은 누구야?",
    "심리학과 평균 학점 알려줘",
    "사회복지학과는 어느 건물에 있어?",
    "컴퓨터공학부 학생 수는 몇 명이야?",
    "언어학과의 웹사이트 주소 알려줘"
]

st.markdown("💬 **예시 질문으로 테스트해보세요!**")

# 비침해 질문
st.markdown("✅ **개인정보 비침해 질문 (LABEL_0):**")
cols_0 = st.columns(len(example_questions_general))
for i, q in enumerate(example_questions_general):
    if cols_0[i].button(q, key=f"label0_{i}"):
        user_input = q # 예시 질문을 선택하면 입력창에 자동 입력되도록 처리

# 개인정보 침해 질문
st.markdown("🚫 **개인정보 침해 질문 (LABEL_1):**")
cols_1 = st.columns(len(example_questions_sensitive))
for i, q in enumerate(example_questions_sensitive):
    if cols_1[i].button(q, key=f"label1_{i}"):
        user_input = q # 예시 질문을 선택하면 입력창에 자동 입력되도록 처리

if user_input:
    # 입력된 사용자 메시지 출력 및 저장
    st.chat_message("user").markdown(user_input)
    st.session_state.chat_history.append(("user", user_input))
    
    # 입력 필터링 (KoELECTRA 분류기 사용)
    with st.spinner("Input Filter가 동작 중입니다..."):
        label_id = classify(user_input)
        label = f"LABEL_{label_id}"
        print("☑️", label)

    # 필터링 결과에 따른 분기 처리
    if label == 'LABEL_1':  # 개인정보 포함 질문 → 우회 질문 생성
        with st.spinner("Gemini가 응답 중입니다..."):
            try:
                response = chat_alternative.send_message(user_input)
                print("✖️ Alternative Response", response)
                ai_reply = response.text
            except Exception as e:
                ai_reply = f"⚠️ 오류가 발생했습니다: {e}"
                
    else:  # 개인정보 비포함 질문 → Gemini → Output Filter
        with st.spinner("Gemini가 응답 중입니다..."):
            try:
                response = chat.send_message(user_input)
                print("🔥 First Response", response.text)

                response_final = chat_output_filter.send_message(response.text)
                print("🤖 Final Response", response_final.text)

                ai_reply = response_final.text
            except Exception as e:
                ai_reply = f"⚠️ 오류가 발생했습니다: {e}"

    # ─────────────────────────────────────────────────────────────
    # 7. 필터링 과정 요약 (클릭해서 보기)
    # ─────────────────────────────────────────────────────────────
    with st.expander("🔎 필터링 과정 자세히 보기"):
        st.markdown(f"""
        **1단계: 입력 필터링**  
        - KoELECTRA 분류기로 입력 문장을 분석하여 '개인정보 질문' 여부를 판별합니다.  
        - 예측 결과: `☑️ {label}`
        """)

        st.markdown("""
        **2단계: 대답 생성**  
        - 개인정보 질문일 경우 → Gemini에게 우회 질문을 요청  
        - 개인정보가 아닐 경우 → Gemini에게 직접 응답 생성 요청
        - 🔥 초기 응답:
        """)
        st.code(f"{response.text if 'response' in locals() else '-'}", language="text")

        st.markdown("""
        **3단계: 출력 필터링**  
        - Gemini의 응답에서 개인정보가 포함되어 있지는 않은지 Output Filter로 다시 점검합니다.
        - 🤖 최종 응답:
        """)
        st.code(f"{response_final.text if 'response_final' in locals() else '-'}", language="text")

    # ─────────────────────────────────────────────────────────────
    # 8. 최종 응답 출력 및 대화 기록 저장
    # ─────────────────────────────────────────────────────────────
    st.chat_message("ai").markdown(ai_reply)
    st.session_state.chat_history.append(("ai", ai_reply))
