import streamlit as st
from PIL import Image
from datetime import datetime, timedelta
import json
import io
import google.generativeai as genai

# -------------------------------------------------
# 기본 세팅
# -------------------------------------------------
st.set_page_config(
    page_title="DayPharm 통합 서비스 💊",
    page_icon="💊",
    layout="wide"
)

# -------------------------------------------------
# 세션 초기화
# -------------------------------------------------
if "role" not in st.session_state:
    st.session_state.role = "👩‍🦳 환자 모드"

# 환자→약사 공유 저장소
if "shared_patients" not in st.session_state:
    st.session_state.shared_patients = []

if "patient_medications" not in st.session_state:
    st.session_state.patient_medications = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# API 키 입력
if "api_key" not in st.session_state:
    st.session_state.api_key = "GEMINI_API_KEY"

# -------------------------------------------------
# 사이드바
# -------------------------------------------------
st.sidebar.title("⚙️ 데이팜 모드 설정")
role = st.sidebar.radio(
    "사용자 역할 선택",
    ["👩‍⚕️ 약사 모드", "👩‍🦳 환자 모드"],
    index=0 if st.session_state.role == "👩‍⚕️ 약사 모드" else 1,
)
st.session_state.role = role
st.sidebar.divider()

# 여기서 실제로 Gemini 설정을 해줘야 밑에서 모델을 만들 수 있음 ✅
if st.session_state.api_key:
    genai.configure(api_key=st.session_state.api_key)

# -------------------------------------------------
# 공통 함수
# -------------------------------------------------
def make_gemini():
    """가능하면 2.5-pro 먼저, 안 되면 flash로"""
    if not st.session_state.api_key:
        return None
    try:
        return genai.GenerativeModel("gemini-2.5-pro")
    except Exception:
        return genai.GenerativeModel("gemini-1.5-flash")


def analyze_prescription_image(image):
    """
    환자 모드: 약봉투 → 이름/나이/약 추출
    """
    model = make_gemini()
    if model is None:
        return None, "API 키가 없습니다."

    prompt = """
    이 이미지는 한국 약봉투이거나 약 정보가 적힌 사진입니다.
    가능하면 환자 이름과 나이도 같이 뽑아주세요.
    아래 JSON 형식으로만 응답하세요.

    {
        "name": "환자 이름 (없으면 \"\")",
        "age": "나이 (숫자만, 없으면 \"\")",
        "medications": [
            {
                "name": "약 이름",
                "dosage": "용량 (예: 500mg)",
                "frequency": "복용 횟수 (예: 1일 3회)",
                "timing": "복용 시간 (예: 아침 식후, 점심 식후, 저녁 식후, 취침 전 중 택1)",
                "duration": "복용 기간 (예: 7일)"
            }
        ]
    }

    글씨가 안 보이면 가능한 것만 추론해서 채우고, 없는 건 빈 문자열로 두세요.
    """
    res = model.generate_content([prompt, image])
    text = res.text
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        data = json.loads(text)
        return data, None
    except Exception as e:
        return None, f"JSON 파싱 오류: {e}"


def generate_pharmacist_report(patient_data, context_data=None):
    """
    약사 모드: 환자 데이터 → 설명 리포트
    """
    model = make_gemini()
    if model is None:
        return "⚠️ Gemini API 키를 입력하면 여기서 실제 리포트를 생성할 수 있습니다."

    meds = patient_data.get("medications", [])
    meds_str = ", ".join(meds) if isinstance(meds, list) else str(meds)

    extra = ""
    if context_data:
        extra = "[참고 데이터]\n" + context_data

    prompt = f"""
        당신은 한국 약국에서 일하는 약사입니다.
        아래 환자 정보를 읽고,
        1) 환자에게 설명해줄 문장,
        2) 약사 메모,
        3) 주의해야 할 점
        을 한국어로 작성하세요.
        너무 길지 않게, A4 1장 안에서 끝나도록 합니다.

        [환자 정보]
        이름: {patient_data.get("name","")}
        나이: {patient_data.get("age","")}
        성별: {patient_data.get("gender","")}
        진단/질환: {patient_data.get("conditions","")}
        복용약: {meds_str}

        [약사 메모]
        {patient_data.get("memo","")}

        {extra}
        """
    res = model.generate_content(prompt)
    return res.text


def generate_schedule_from_meds(meds):
    """
    환자 모드: 약 목록 → 7일 스케줄
    """
    schedule = {}
    for med in meds:
        timing = (med.get("timing") or "").lower()
        frequency = med.get("frequency", "1일 1회")

        times = []
        if "아침" in timing:
            times.append("08:00")
        if "점심" in timing:
            times.append("12:00")
        if "저녁" in timing:
            times.append("18:00")
        if "취침" in timing or "자기 전" in timing:
            times.append("22:00")

        if not times:
            if "3회" in frequency:
                times = ["08:00", "12:00", "18:00"]
            elif "2회" in frequency:
                times = ["08:00", "18:00"]
            else:
                times = ["08:00"]

        for day in range(7):
            date = datetime.now() + timedelta(days=day)
            date_str = date.strftime("%Y-%m-%d")
            if date_str not in schedule:
                schedule[date_str] = []
            for t in times:
                schedule[date_str].append({
                    "medication": med.get("name", "이름 없음"),
                    "time": t,
                    "dosage": med.get("dosage", ""),
                    "taken": False
                })
    return schedule


# =========================================================
# 👩‍⚕️ 1. 약사 모드
# =========================================================
if st.session_state.role == "👩‍⚕️ 약사 모드":
    st.title("💊 DayPharm – 약사용")

    patients = st.session_state.shared_patients

    if not patients:
        st.info("아직 환자가 아무것도 안 보냈어요. 환자 모드에서 약봉투를 분석하면 자동으로 입력됩니다.)")

        # 환자가 없을 때도 아래 입력창이 돌아가게 기본값 세팅 ✅
        selected_patient = None
        default_name = ""
        default_age = ""
        meds_text_prefilled = ""
    else:
        # 자동으로 가장 최근 걸로 선택되게
        options = [
            f"{p.get('name') or '이름없음'} / {p.get('age') or '?'}세 / 약 {len(p.get('medications', []))}개"
            for p in patients
        ]
        selected_idx = st.selectbox(
            "환자 선택",
            list(range(len(patients))),
            index=len(patients) - 1,  # 가장 최근
            format_func=lambda i: options[i],
        )

        selected_patient = patients[selected_idx]
        default_name = selected_patient.get("name", "")
        default_age = selected_patient.get("age", "")
        # meds가 dict일 수도 있고 string일 수도 있어서 통일
        meds_text_prefilled = ", ".join(
            [m if isinstance(m, str) else m.get("name", "") for m in selected_patient.get("medications", [])]
        )

        # st.subheader(f"🧾 환자 정보")
        #st.write(f"- 이름: {default_name or '이름없음'}")
        #st.write(f"- 나이: {default_age or '미상'}")
        #st.write("**약 목록**")
        #for m in selected_patient.get("medications", []):
        #    if isinstance(m, str):
        #        st.write(f"• {m}")
        #    else:
        #        st.write(f"• {m.get('name','')} / {m.get('dosage','')} / {m.get('timing','')}")

    # 약사 입력폼 (위에서 값이 없어도 돌아가게 됨)
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("환자 이름", value=default_name)
        age = st.text_input("나이", value=default_age)
        gender = st.selectbox("성별", ["", "여성", "남성", "기타"], index=1)
        conditions = st.text_area("질환 / 진단 / 증상", value=selected_patient.get("conditions","") if selected_patient else "")
    with col2:
        meds_text = st.text_area("현재 복용 중인 약 (쉼표로 구분)", value=meds_text_prefilled)
        memo = st.text_area("약사 메모", value=selected_patient.get("memo","") if selected_patient else "")

    if st.button("📑 AI 리포트 생성"):
        meds_list = []
        for m in meds_text.split(","):
            m = m.strip()
            if m:
                meds_list.append(m)

        patient_data = {
            "name": name,
            "age": age,
            "gender": gender,
            "conditions": conditions,
            "medications": meds_list,
            "memo": memo,
        }

        with st.spinner("AI가 리포트를 작성 중입니다..."):
            report_text = generate_pharmacist_report(patient_data)

        st.subheader("📝 생성된 리포트")
        st.write(report_text)

        # 기존 환자면 덮어쓰기, 아니면 추가
        if selected_patient:
            selected_patient.update(patient_data)
            selected_patient["report"] = report_text
        else:
            st.session_state.shared_patients.append({
                **patient_data,
                "report": report_text,
            })

        st.success("✅ 환자 모드에서도 이 리포트를 볼 수 있어요!")

    # 약사가 지금까지 만든 환자 리스트
    if st.session_state.shared_patients:
        st.markdown("### 📦 오늘 등록된 환자들")
        for p in st.session_state.shared_patients[::-1]:
            meds_label = p["medications"] if isinstance(p["medications"], list) else [p["medications"]]
            st.write(f"- {p.get('name','')} / {', '.join([m if isinstance(m,str) else m.get('name','') for m in meds_label])}")

    st.caption("⚠️ 이 앱은 보조 도구입니다. 환자에게 제공할 때에는 반드시 마지막으로 의사나 약사의 확인이 필요합니다.")


# =========================================================
# 👩‍🦳 2. 환자 모드
# =========================================================
else:
    st.title("👩‍🦳 Daypharm - 환자용")

    # 약사가 만들어놓은 리포트 있으면 보여주기
    if st.session_state.shared_patients:
        st.subheader("📦 약국에서 등록한 내 정보")
        options = [p["name"] or "(이름없음)" for p in st.session_state.shared_patients]
        selected_name = st.selectbox("내 이름 선택", options)
        selected_patient = next(p for p in st.session_state.shared_patients if (p["name"] or "(이름없음)") == selected_name)

        with st.expander("약사가 작성한 리포트 보기", expanded=False):
            st.write(selected_patient.get("report","(리포트 없음)"))

        # 약사가 넣은 약을 그대로 환자 약 목록에도 동기화
        st.session_state.patient_medications = [
            {
                "name": m if isinstance(m, str) else m.get("name",""),
                "dosage": "",
                "frequency": "1일 1회",
                "timing": "아침",
                "duration": ""
            } for m in selected_patient.get("medications", [])
        ]

    tab1, tab2, tab3, tab4 = st.tabs(["📸 약 등록", "📅 복용 스케줄", "⚠️ 주의사항", "💬 챗봇 상담"])

    # ----------------- 📸 약 등록 -----------------
    with tab1:
        st.subheader("📸 약봉투 등록하기")
        uploaded_file = st.file_uploader("약봉투 사진 업로드", type=["png", "jpg", "jpeg"])
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            st.image(image, caption="업로드된 약봉투", use_container_width=True)

            if st.button("🔍 AI로 약 정보 추출"):
                if not st.session_state.api_key:
                    st.warning("Gemini API Key를 먼저 입력해주세요.")
                else:
                    with st.spinner("AI가 약봉투를 분석하고 있습니다..."):
                        data, err = analyze_prescription_image(image)
                    if err:
                        st.error(err)
                    else:
                        # 1) 약은 내 로컬에도 등록
                        meds = data.get("medications", [])
                        st.session_state.patient_medications.extend(meds)

                        # 2) 분석이 되면 바로 약국쪽으로도 넣기
                        auto_record = {
                            "id": datetime.now().isoformat(),
                            "name": data.get("name", ""),
                            "age": data.get("age", ""),
                            "gender": "",
                            "conditions": "",
                            "medications": meds,
                            "report": None,
                        }
                        st.session_state.shared_patients.append(auto_record)

                        st.success("✅ 약이 등록됐고 약국으로 자동 전송됐어요!")

                        # 3) 원하면 수정해서 다시 보내기
                        #with st.form("update_patient_data"):
                        #    name_input = st.text_input("이름", value=data.get("name",""))
                        #    age_input = st.text_input("나이", value=data.get("age",""))
                        #    ok = st.form_submit_button("수정 내용 약국에 다시 보내기")
                        #    if ok:
                        #        st.session_state.shared_patients[-1]["name"] = name_input
                        #        st.session_state.shared_patients[-1]["age"] = age_input
                        #        st.success("📮 수정해서 다시 보냈어요!")

                        name_input = st.text_input("이름", value=data.get("name",""))
                        age_input = st.text_input("나이", value=data.get("age",""))
                        
                        for m in meds:
                            st.write(f"- {m.get('name')} / {m.get('dosage','')} / {m.get('timing','')}")

        if st.session_state.patient_medications:
            st.markdown("### 📋 현재 등록된 약")
            for m in st.session_state.patient_medications:
                st.write(f"- {m.get('name')} / {m.get('dosage','')} / {m.get('timing','')}")

    # ----------------- 📅 복용 스케줄 -----------------
    with tab2:
        st.subheader("📅 내 복약 스케줄")
        if not st.session_state.patient_medications:
            st.info("먼저 약을 등록해주세요.")
        else:
            schedule = generate_schedule_from_meds(st.session_state.patient_medications)
            for date_str in sorted(schedule.keys())[:7]:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = ['월', '화', '수', '목', '금', '토', '일'][date_obj.weekday()]
                st.markdown(f"#### {date_obj.strftime('%m월 %d일')} ({day_name})")
                cols = st.columns(4)
                for idx, item in enumerate(sorted(schedule[date_str], key=lambda x: x['time'])):
                    with cols[idx % 4]:
                        st.write(f"**{item['time']}**")
                        st.write(item['medication'])
                        if item['dosage']:
                            st.caption(item['dosage'])
                        st.checkbox("복용완료", key=f"{date_str}_{item['time']}_{idx}")

    # ----------------- ⚠️ 주의사항 -----------------
    with tab3:
        st.subheader("⚠️ 복용 주의사항 / 상호작용")
        if not st.session_state.patient_medications:
            st.info("등록된 약이 없습니다.")
        else:
            names = [m["name"] for m in st.session_state.patient_medications]
            st.write("현재 복용 중:", ", ".join(names))
            if st.session_state.api_key and st.button("🔍 AI로 상호작용 확인"):
                model = make_gemini()
                q = f"다음 약들을 함께 복용할 때 주의사항과 피해야 할 음식/음료를 한국어로 정리해줘: {', '.join(names)}"
                with st.spinner("AI가 상호작용을 분석 중입니다..."):
                    res = model.generate_content(q)
                st.write(res.text)
            else:
                st.info("위 약들은 위장장애, 간독성, 어지러움 같은 부작용이 있을 수 있으니 증상이 지속되면 약사에게 문의하세요.")

    # ----------------- 💬 챗봇 상담 -----------------
    with tab4:
        st.subheader("💬 약 관련 질문하기")
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        user_q = st.chat_input("질문을 입력하세요...")
        if user_q:
            st.session_state.chat_history.append({"role": "user", "content": user_q})
            with st.chat_message("user"):
                st.write(user_q)

            if not st.session_state.api_key:
                answer = "Gemini API 키를 넣으면 여기서 약사 스타일로 답변해줄 수 있어요 🙂"
            else:
                model = make_gemini()
                meds_ctx = ", ".join([m["name"] for m in st.session_state.patient_medications])
                prompt = f"""
                당신은 한국 약국의 약사입니다.
                환자가 지금 먹는 약: {meds_ctx}
                환자 질문: {user_q}
                안전하게 설명하고, 위험하거나 모호하면 '가까운 약국/의료진에게 문의'라고 써주세요.
                """
                with st.spinner("답변 생성 중..."):
                    res = model.generate_content(prompt)
                answer = res.text

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
            with st.chat_message("assistant"):
                st.write(answer)

    st.caption("⚠️ 이 앱은 약 복용 보조 도구입니다. 의학적 조언이 필요한 경우 반드시 의사나 약사와 상담하세요.")
