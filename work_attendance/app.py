import io
import math
import pandas as pd
import streamlit as st
from datetime import date

# Local imports
from src.config import load_all, load_employees_from_csv
from src.scheduler import build_and_solve
from src.postprocess import build_formatted_workbook_bytes

# Page Config
st.set_page_config(page_title="교대근무 스케줄러", page_icon="🗓️", layout="wide")

# --- 보안 접속 설정 ---
def check_password():
    """로그인 상태를 확인하고 비밀번호 입력창을 표시합니다."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    # 센터 정렬을 위한 컨테이너
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.write("## 🔒 보안 접속")
        st.info("이 앱은 개인정보 보호를 위해 비밀번호가 필요합니다.")
        input_password = st.text_input("비밀번호를 입력해 주세요.", type="password")
        if st.button("로그인"):
            # 기본 비밀번호 설정 (원하시는 대로 수정 가능)
            if input_password == "6394": 
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("⚠️ 비밀번호가 틀렸습니다.")
    return False

if not check_password():
    st.stop()

st.title("🗓️ 교대근무 스케줄러 (Excel 다운로드)")

# 1. Load Base Data
rules, default_employees_obj, default_demand, default_vacations = load_all()

# Deployment Check: If default_employees_obj is empty, it means employees.csv was not found or is empty
if not default_employees_obj:
    st.error("⚠️ 직원 데이터(`configs/employees.csv`)를 불러올 수 없습니다.")
    st.info("GitHub 저장소의 `configs` 폴더 안에 `employees.csv` 파일이 정상적으로 올라가 있는지 확인해주세요.")
    st.stop()

# Sidebar
with st.sidebar:
    st.header("⚙️ 기본 설정")
    horizon = st.number_input("계획 일수 (D1~Dn)", min_value=7, max_value=62, value=28, step=1)
    st.caption("💡 모델은 주말/공휴일을 구분하지 않고 D1~Dn을 동일하게 취급합니다.")

    # Month Settings
    st.header("🗓️ 월 설정")
    month_start = st.date_input("월 시작일", value=date.today().replace(day=1))
    base_month_hours = st.number_input(
        "기준 월 소정근로시간(연장근로 계산)",
        min_value=0, max_value=400, value=209, step=1,
        help="예: 209(통상 월 소정시간), 또는 부서 산정치(예: 168)"
    )

    st.header("👥 직원 선택")
    source = st.radio("직원 목록 소스", ["기본(employees.csv)", "파일 업로드"], horizontal=True)
    
    # Determine employees list here to calculate defaults for next inputs
    current_employees_obj = default_employees_obj
    if source == "파일 업로드":
        uploaded_emps = st.file_uploader("직원 CSV 업로드 (name,team,role)", type=["csv"])
        if uploaded_emps is not None:
            emp_df = pd.read_csv(uploaded_emps)
            current_employees_obj = [type(default_employees_obj[0])(name=str(r["name"]), team=r.get("team"), role=r.get("role"))
                                     for _, r in emp_df.iterrows() if str(r.get("name", "")).strip()]
    
    employees_all = [e.name for e in current_employees_obj]
    
    manual_select = st.text_input("직원 일부만 사용(쉼표 구분, 예: 홍길동,김철수)", value="", placeholder="비우면 전체 사용")
    
    # Filter employees
    employees = employees_all
    selected = [n.strip() for n in manual_select.split(",") if n.strip()]
    if selected:
        base_set = set(employees_all)
        filtered = [n for n in selected if n in base_set]
        if filtered:
            employees = filtered
        else:
            st.warning("선택한 이름이 명단에 없어 전체 목록을 사용합니다.")

    # Calculate smart defaults for workers per day
    emp_count = len(employees)
    # Roughly: Total Shifts = N * 5 (assuming 5 days/week)
    # Daily needed = (N * 5) / 7
    # E.g. N=16 => 80/7 = 11.4 => Range 10~13
    if emp_count > 0:
        rec_center = emp_count * 5 / 7
        rec_min = max(0, math.floor(rec_center - 1.5))
        rec_max = math.ceil(rec_center + 1.5)
    else:
        rec_min, rec_max = 0, 0

    st.header(" 하루 총 근무자 수(OFF/VAC 제외)")
    # Defaults logic...
    st.info(f"선택된 직원 {emp_count}명 기준 권장 범위: {rec_min}~{rec_max}명")
    
    use_range = st.toggle("최소/최대 범위 사용 (권장)", value=True)
    if use_range:
        min_workers = st.number_input("최소 인원(일)", min_value=0, max_value=999, value=int(rec_min), step=1)
        max_workers = st.number_input("최대 인원(일)", min_value=0, max_value=999, value=int(rec_max), step=1)
        exact_workers = None
    else:
        exact_workers = st.number_input("정확히 이 인원으로 (일)", min_value=0, max_value=999, value=int(rec_center) if emp_count>0 else 0, step=1)
        min_workers = None
        max_workers = None

    # (NEW) 지난 달 말일 N 근무자 선택
    st.header("🌙 전월 근무 이력")
    prev_n_emps = st.multiselect(
        "지난 달 마지막 날(어제) N 근무자 (D1 휴무 적용)",
        options=employees,
        default=[],
        help="여기 선택된 직원은 1일차에 반드시 '주휴' 또는 '휴가'가 배정됩니다."
    )

    # (NEW) N 근무 후 최소 휴무 설정 (전체/개별)
    st.header("🛏️ N 근무 후 휴식 설정")
    global_min_off = st.radio(
        "기본 휴무 일수 (전체 적용)",
        [1, 2],
        index=0,
        horizontal=True,
        format_func=lambda x: f"{x}일 휴식"
    )
    
    overrides = {}
    with st.expander("직원별 예외 설정 (2일 휴식 지정)"):
        over_2 = st.multiselect("N 후 2일 휴식 적용 대상", employees, default=[])

    # Build overrides map
    for e in over_2:
        overrides[e] = 2

    # (NEW) 동반 근무 금지 탭/설정
    st.header("🚫 근무 제한 설정")
    incompatible_group = st.multiselect(
        "N 근무 동반 금지 그룹 (선택된 인원은 같은 날 N 불가)",
        employees,
        help="여기 선택된 인원들끼리는 같은 날 동시에 N(야간) 근무에 들어가지 않습니다. (최대 1명만 배치)"
    )

    # (NEW) 고급 설정 (제약 완화)
    with st.expander("⚙️ 고급 제약 조건 설정 (제약 완화)"):
        st.caption("스케줄 생성이 실패할 경우, 아래 제약을 해제하거나 범위를 넓혀보세요.")
        
        # constraints 업데이트용 변수들
        c_3a = st.checkbox("3연속 A 근무 금지", value=rules.constraints.get("forbid_three_A_in_row", True))
        c_ba = st.checkbox("B 다음날 A 근무 금지", value=rules.constraints.get("forbid_B_then_A", True))
        c_off_after_day = st.checkbox("주간(A,B,C) 후 휴무 금지 (OFF는 N 뒤에만)", value=rules.constraints.get("forbid_off_after_day_shift", True))
        
        st.markdown("---")
        st.write("#### 🌙 직원별 야간(N) 근무 횟수")
        def_min_n = int(rules.constraints.get("min_night_shifts_per_employee", 0))
        def_max_n = int(rules.constraints.get("max_night_shifts_per_employee", 99))
        
        c_min_n = st.number_input("최소 야간 근무", min_value=0, max_value=31, value=def_min_n)
        c_max_n = st.number_input("최대 야간 근무", min_value=0, max_value=31, value=def_max_n)

    # 룰 업데이트
    rules.constraints["forbid_three_A_in_row"] = c_3a
    rules.constraints["forbid_B_then_A"] = c_ba
    rules.constraints["forbid_off_after_day_shift"] = c_off_after_day
    rules.constraints["min_night_shifts_per_employee"] = c_min_n
    rules.constraints["max_night_shifts_per_employee"] = c_max_n

    run_btn = st.button("🚀 스케줄 생성")

# ----- Main Content -----
st.write(f"### 선택된 직원 ({len(employees)}명)")
if employees:
    st.write(", ".join(employees))

    
    # Demand Parsing (Removed)
    demand = None
    
    # Vacation Parsing (Removed upload, default only)
    vacations = default_vacations
    
    # Execution

# Execution
if run_btn:
    if len(employees) < 3:
        st.warning("직원 수가 너무 적습니다. 정상적인 스케줄 생성이 어려울 수 있습니다.")

    with st.spinner("스케줄을 생성 중입니다..."):
        # Update global rule based on UI selection
        rules.constraints["min_off_after_N"] = global_min_off
        
        schedule, status = build_and_solve(
            employees=employees,
            horizon=int(horizon),
            hours=rules.hours,
            constraints=rules.constraints,
            weights=rules.weights,
            demand=demand,
            vacations=vacations,
            workers_per_day=int(exact_workers) if exact_workers not in (None, 0) else None,
            min_workers_per_day=int(min_workers) if use_range and min_workers not in (None, 0) else None,
            max_workers_per_day=int(max_workers) if use_range and max_workers not in (None, 0) else None,
            forbid_free_vac=True,
            prev_n_employees=prev_n_emps,
            min_off_overrides=overrides, # Pass overrides
            incompatible_employees=incompatible_group,
        )
        
        # Save to session state
        st.session_state["schedule_result"] = schedule
        st.session_state["status_result"] = status

# Check if result exists in session state
if "schedule_result" in st.session_state and "status_result" in st.session_state:
    schedule = st.session_state["schedule_result"]
    status = st.session_state["status_result"]

    if schedule and status in ("OPTIMAL", "FEASIBLE"):
        if run_btn:
             st.success(f"해 상태: {status}")
        else:
             st.info(f"이전 생성 결과 (상태: {status})")
        
        # Display DataFrame
        rows = []
        for e, days in schedule.items():
            row = {"name": e}
            for i, s in enumerate(days):
                row[f"D{i+1}"] = s
            rows.append(row)
        df = pd.DataFrame(rows)
        st.dataframe(df)

        # 1) Raw Excel
        raw_buf = io.BytesIO()
        with pd.ExcelWriter(raw_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="schedule")
        raw_buf.seek(0)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="⬇️ 원시 엑셀 다운로드",
                data=raw_buf,
                file_name="schedule_raw.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        # 2) Report Excel
        pretty_bytes = build_formatted_workbook_bytes(
            schedule=schedule,
            hours_map=rules.hours,
            month_title=f"{month_start.year}년 {month_start.month}월 근무명령서",
            start_date=month_start,
            base_month_hours=int(base_month_hours),
        )
        with col2:
            st.download_button(
                label="⬇️ 보고서형 엑셀 다운로드",
                data=pretty_bytes,
                file_name=f"근무명령서_{month_start.year}-{month_start.month:02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.error(f"스케줄 생성 실패 (Status: {status})")
        st.error("힌트: 하루 근무 인원 최소/최대 범위를 넓히거나, 제약조건을 완화해보세요.")