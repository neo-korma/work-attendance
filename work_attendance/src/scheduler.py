from ortools.sat.python import cp_model
from typing import Dict, List, Tuple, Optional

def build_and_solve(
    employees: List[str],
    horizon: int,
    hours: Dict[str, int],
    constraints: Dict[str, object],
    weights: Dict[str, int],
    demand: Optional[Dict[int, Dict[str, int]]] = None,
    vacations: Optional[Dict[str, List[int]]] = None,
    # 옵션: 하루 총 근무자 수 범위(OFF/VAC 제외)
    workers_per_day: Optional[int] = None,   # 정확히 == 값(미사용 시 None)
    min_workers_per_day: Optional[int] = None,  # 최소값(미사용 시 None)
    max_workers_per_day: Optional[int] = None,  # 최대값(미사용 시 None)
    # 옵션: 휴가(VAC)는 요청된 날에만 허용(기본 True)
    # 옵션: 휴가(VAC)는 요청된 날에만 허용(기본 True)
    forbid_free_vac: bool = True,
    # (NEW) 전월 말일 N 근무자
    prev_n_employees: Optional[List[str]] = None,
    # (NEW) N 근무 후 휴무일수 개별 설정 (이름 -> 일수)
    min_off_overrides: Optional[Dict[str, int]] = None,
    # (NEW) 동반 근무 금지 그룹 (이 그룹 내 인원은 같은 시프트 근무 불가)
    incompatible_employees: Optional[List[str]] = None,
) -> Tuple[Dict[str, List[str]], str]:
    """
    반환: (schedule, status_str)
    """
    shifts = ["A", "A2", "B", "C", "N", "OFF", "VAC"]
    model = cp_model.CpModel()

    # 방탄: 설정에 누락된 키가 있어도 0으로 처리
    hours_local = {s: int(hours.get(s, 0)) for s in shifts}

    # 변수 x[e, d, s] ∈ {0,1}
    x = {}
    for e in employees:
        for d in range(horizon):
            for s in shifts:
                x[(e, d, s)] = model.NewBoolVar(f"x_{e}_{d}_{s}")

    # 하루 1개 시프트
    for e in employees:
        for d in range(horizon):
            model.Add(sum(x[(e, d, s)] for s in shifts) == 1)

    # 휴가 고정/제약
    vacations = vacations or {}
    for e in employees:
        vac_days = set(vacations.get(e, []))
        for d in range(horizon):
            if d in vac_days:
                model.Add(x[(e, d, "VAC")] == 1)          # 요청일은 VAC
            elif forbid_free_vac:
                model.Add(x[(e, d, "VAC")] == 0)          # 그 외 VAC 금지

    # 주 52시간: 슬라이딩 7일
    if constraints.get("weekly_hours_window", 7) and constraints.get("max_weekly_hours", 52):
        W = int(constraints.get("weekly_hours_window", 7))
        MAXH = int(constraints.get("max_weekly_hours", 52))
        for e in employees:
            for start in range(horizon - W + 1):
                wnd = range(start, start + W)
                model.Add(
                    sum(hours_local[s] * x[(e, d, s)]
                        for d in wnd for s in shifts) <= MAXH
                )

    # B 다음날 A 금지
    if constraints.get("forbid_B_then_A", True):
        for e in employees:
            for d in range(horizon - 1):
                model.Add(x[(e, d, "B")] + x[(e, d + 1, "A")] <= 1)

    # N 다음날 최소 1일 휴무(OFF 또는 VAC)
    # Generic Logic: N(t) -> OFF(t+1)...OFF(t+k)
    default_min_off = int(constraints.get("min_off_after_N", 1))
    min_off_overrides = min_off_overrides or {}
    
    for e in employees:
        # Determine employee specific limit
        limit = min_off_overrides.get(e, default_min_off)
        if limit < 1:
            limit = 1 # Safety check
            
        for d in range(horizon - limit):
            # If N at d, then d+1...d+limit must be OFF/VAC
            for k in range(1, limit + 1):
                model.Add(x[(e, d, "N")] <= x[(e, d + k, "OFF")] + x[(e, d + k, "VAC")])
                
        # Handle boundary near end of horizon?
        # range(horizon - limit) stops early.
        # e.g. horizon=28, limit=2. range(26) -> 0..25.
        # d=25: N(25) -> check 26, 27. OK.
        # d=26: N(26) -> check 27. (28 out of bounds).
        # We need to check up to whatever fits.
        for d in range(horizon - limit, horizon):
            # Check remaining days
             for k in range(1, limit + 1):
                if d + k < horizon:
                    model.Add(x[(e, d, "N")] <= x[(e, d + k, "OFF")] + x[(e, d + k, "VAC")])

    # N-휴무 직후 A 금지 (수정: d+2의 A만 금지, d+3(N->OFF->OFF->A)은 허용)
    if constraints.get("forbid_A_after_N_rest", True):
        for e in employees:
            for d in range(horizon - 2):
                model.Add(x[(e, d, "N")] + x[(e, d + 2, "A")] <= 1)

    # A 3연속 금지
    if constraints.get("forbid_three_A_in_row", True):
        for e in employees:
            for t in range(horizon - 2):
                model.Add(x[(e, t, "A")] + x[(e, t + 1, "A")] + x[(e, t + 2, "A")] <= 2)

    # (NEW) N -> OFF -> N 금지
    # 즉, N(t) == 1 이고 N(t+2) == 1 이면, 중간 t+1은 OFF/VAC이면 안 됨(근무여야 함).
    # 반대로 말하면: N(t) + OFF(t+1) + N(t+2) <= 2  (VAC 포함 시 OFF+VAC)
    if constraints.get("forbid_N_OFF_N", False):
        for e in employees:
            for d in range(horizon - 2):
                # N - (OFF|VAC) - N 금지
                # x[N,d] + (x[OFF,d+1] + x[VAC,d+1]) + x[N,d+2] <= 2
                model.Add(x[(e, d, "N")] + x[(e, d + 1, "OFF")] + x[(e, d + 1, "VAC")] + x[(e, d + 2, "N")] <= 2)
    
    # (NEW) 주간 근무(A/A2/B/C) 후 OFF 금지 -> 즉 OFF는 N 뒤에만 올 수 있음 (Forward Rotation Force)
    if constraints.get("forbid_off_after_day_shift", False):
        day_shifts = ["A", "A2", "B", "C"]
        for e in employees:
            for d in range(horizon - 1):
                for s in day_shifts:
                    # s(d) -> OFF(d+1) 금지 (VAC는 허용)
                    model.Add(x[(e, d, s)] + x[(e, d + 1, "OFF")] <= 1)

    # (NEW) 직원별 최소/최대 N 근무 횟수 보장
    min_n = int(constraints.get("min_night_shifts_per_employee", 0))
    max_n = int(constraints.get("max_night_shifts_per_employee", 0))
    if min_n > 0:
        for e in employees:
            model.Add(sum(x[(e, d, "N")] for d in range(horizon)) >= min_n)
    if max_n > 0:
        for e in employees:
            model.Add(sum(x[(e, d, "N")] for d in range(horizon)) <= max_n)

    # (NEW) 최소 연속 근무일수 (예: 3일 이상)
    # 짧은 근무 패턴 방지: OFF -> Work(1~2일) -> OFF 금지
    # boundary 처리가 까다로울 수 있으므로, 단순화하여 "Work=1 이면 주변 Work 합계 >= 2" 등으로 접근하거나,
    # 명시적 패턴 금지 사용. 여기서는 "OFF - W - OFF" (1일), "OFF - W - W - OFF" (2일) 금지로 구현.
    # W = (A, A2, B, C, N). OFF = (OFF, VAC)
    min_cons = int(constraints.get("min_consecutive_work_days", 0))
    if min_cons > 1:
        # 편의상 "근무 아님"을 0, "근무"를 1로 하는 보조변수 w_bool 생성 가능,
        # 하지만 변수 늘리기보다 직접 합으로 제약.
        # OFF/VAC 여부: is_off[d] = x[OFF,d] + x[VAC,d]
        # Work 여부: is_work[d] = 1 - is_off[d]
        
        # 1일 근무 금지: OFF(d) - W(d+1) - OFF(d+2)
        # => is_work[d+1]가 1이면 is_off[d] + is_off[d+2] < 2  (즉 적어도 하나는 Work여야 함)
        # => x[O,d] + x[W,d+1] + x[O,d+2] <= 2
        
        # 변수 생성 최소화를 위해 루프 안에서 직접 식 구성
        work_shifts = ["A", "A2", "B", "C", "N"]
        off_shifts = ["OFF", "VAC"]
        
        for e in employees:
            # 보조 변수: day d가 근무인지 여부
            is_work = []
            for d in range(horizon):
                d_work = model.NewBoolVar(f"is_work_{e}_{d}")
                model.Add(sum(x[(e, d, s)] for s in work_shifts) == 1).OnlyEnforceIf(d_work)
                model.Add(sum(x[(e, d, s)] for s in work_shifts) == 0).OnlyEnforceIf(d_work.Not())
                is_work.append(d_work)

            # (NEW) Generic Logic: 1일 ~ (min_cons-1)일 근무 금지
            # OFF - W(k) - OFF 패턴 금지
            if min_cons > 1:
                for k in range(1, min_cons):
                    # k일 근무 금지: W[d]...W[d+k-1] == 1 AND others OFF
                    # => AND(W[d]...W[d+k-1]) -> W[d-1] + W[d+k] >= 1
                    # Range: d from 1 to horizon - k - 1
                    for d in range(1, horizon - k):
                        # k일 근무 금지: W[d]...W[d+k-1] == 1 AND others OFF
                        # => AND(W[d]...W[d+k-1]) -> W[d-1] + W[d+k] >= 1
                        # w_block 변수를 사용하면 "w_block => Pattern"만 되고 "Pattern => w_block"이 안되어
                        # w_block을 False로 두면 제약이 무력화됨.
                        # 따라서 직접 EnforceIf(list)를 사용해야 함.
                        
                        # Conditions: is_work[d] ~ is_work[d+k-1] are ALL True
                        conds = [is_work[t] for t in range(d, d + k)]
                        
                
                        # Requirement: d-1 or d+k is Work
                        model.Add(is_work[d - 1] + is_work[d + k] >= 1).OnlyEnforceIf(conds)

    # (NEW) 전월 말일 N 근무자 -> D1(index 0) OFF/VAC 강제
    if prev_n_employees:
        for e in prev_n_employees:
            if e in employees:
                # D1 is OFF or VAC or mapped equivalent
                # x[e, 0, "OFF"] + x[e, 0, "VAC"] == 1
                model.Add(x[(e, 0, "OFF")] + x[(e, 0, "VAC")] == 1)

    # (NEW) 전월 말일 N 근무자 -> D1(index 0) OFF/VAC 강제
    if prev_n_employees:
        for e in prev_n_employees:
            if e in employees:
                # D1 is OFF or VAC or mapped equivalent
                # x[e, 0, "OFF"] + x[e, 0, "VAC"] == 1
                model.Add(x[(e, 0, "OFF")] + x[(e, 0, "VAC")] == 1)

    # (NEW) 하루 N 근무자 최대 3명 제한
    max_n_day = int(constraints.get("max_night_workers_per_day", 0))
    if max_n_day > 0:
        for d in range(horizon):
            model.Add(sum(x[(e, d, "N")] for e in employees) <= max_n_day)

    # (NEW) 연속 휴무일 최대값 제한
    max_off = int(constraints.get("max_consecutive_off_days", 0))
    if max_off > 0:
        # 연속된 (max_off + 1)일 동안 적어도 하루는 근무해야 함
        # window size = k = max_off + 1
        k = max_off + 1
        work_shifts = ["A", "A2", "B", "C", "N"]
        for e in employees:
            for start in range(horizon - k + 1):
                # sum(is_work[t] for t in start..start+k) >= 1
                # is_work[t] = sum(x[e, t, s] for s in work_shifts)
                # => sum(x[e, t, s] for t in range... for s in work_shifts) >= 1
                model.Add(sum(x[(e, t, s)] for t in range(start, start + k) for s in work_shifts) >= 1)

    # (NEW) 동반 근무 금지 (같은 날 같은 시프트 불가 -> 요청: N 근무만 금지)
    if incompatible_employees and len(incompatible_employees) >= 2:
        group = [e for e in incompatible_employees if e in employees]
        if len(group) >= 2:
            # User specifically asked for N shift conflict prevention
            target_shifts = ["N"] 
            for d in range(horizon):
                for s in target_shifts:
                    # 그룹 내에서 시프트 s(N)는 최대 1명만 가능
                    model.Add(sum(x[(e, d, s)] for e in group) <= 1)

    # (옵션) 시프트별 수요 충족 (Removed by request, keeping arg for compatibility but verify logic)
    if demand:
        # User requested removal, but code supports it. 
        # If passed None, it's skipped.
        for d, need_map in demand.items():
            if 0 <= d < horizon:
                for s in ["A", "B", "C", "N"]:
                    need = int(need_map.get(s, 0))
                    model.Add(sum(x[(e, d, s)] for e in employees) == need)

    # (옵션) 하루 총 근무자 수 제약(OFF/VAC 제외)
    # demand가 있을 땐 충돌 위험이 있어 사용 안 함
    if demand is None:
        if workers_per_day is not None and min_workers_per_day is None and max_workers_per_day is None:
            for d in range(horizon):
                model.Add(
                    sum(x[(e, d, s)] for e in employees for s in ["A", "B", "C", "N"])
                    == int(workers_per_day)
                )
        else:
            if min_workers_per_day is not None:
                for d in range(horizon):
                    model.Add(
                        sum(x[(e, d, s)] for e in employees for s in ["A", "B", "C", "N"])
                        >= int(min_workers_per_day)
                    )
            if max_workers_per_day is not None:
                for d in range(horizon):
                    model.Add(
                        sum(x[(e, d, s)] for e in employees for s in ["A", "B", "C", "N"])
                        <= int(max_workers_per_day)
                    )

    # ---------- 목적함수(균등화 & 페널티) ----------
    penalties = []

    # (1) 종사자별 A/B/C 근무일수 균등화
    w_balance_emp = int(weights.get("balance_shift_counts_per_employee", 10))
    for s in ["A", "B", "C"]:
        for i in range(len(employees)):
            for j in range(i + 1, len(employees)):
                e1, e2 = employees[i], employees[j]
                diff = model.NewIntVar(-1000, 1000, f"diff_{s}_{e1}_{e2}")
                model.Add(diff == sum(x[(e1, d, s)] - x[(e2, d, s)] for d in range(horizon)))
                absdiff = model.NewIntVar(0, 1000, f"absdiff_{s}_{e1}_{e2}")
                model.AddAbsEquality(absdiff, diff)
                penalties.append(w_balance_emp * absdiff)

    # (2) 일자별 총 근무자 수 균등화(OFF/VAC 제외)
    w_balance_day = int(weights.get("balance_total_workers_per_day", 1))
    workcount = []
    for d in range(horizon):
        wc = model.NewIntVar(0, len(employees), f"wc_{d}")
        model.Add(wc == sum(x[(e, d, s)] for e in employees for s in ["A", "B", "C", "N"]))
        workcount.append(wc)

    for d1 in range(horizon):
        for d2 in range(d1 + 1, horizon):
            diffd = model.NewIntVar(-len(employees), len(employees), f"daydiff_{d1}_{d2}")
            model.Add(diffd == workcount[d1] - workcount[d2])
            absdiffd = model.NewIntVar(0, len(employees), f"absdaydiff_{d1}_{d2}")
            model.AddAbsEquality(absdiffd, diffd)
            penalties.append(w_balance_day * absdiffd)

    # (3) N 이후 휴무가 2일 초과하면 벌점
    w_long_rest = int(weights.get("penalty_too_long_rest_after_N", 5))
    for e in employees:
        for d in range(horizon - 3):
            sum_off = (x[(e, d + 1, "OFF")] + x[(e, d + 1, "VAC")] +
                       x[(e, d + 2, "OFF")] + x[(e, d + 2, "VAC")] +
                       x[(e, d + 3, "OFF")] + x[(e, d + 3, "VAC")])
            n_and_three_off = model.NewBoolVar(f"n_and_three_off_{e}_{d}")
            tmp = model.NewIntVar(0, 6, f"sumoff_{e}_{d}")
            model.Add(tmp == sum_off)
            b_off3 = model.NewBoolVar(f"off3_{e}_{d}")
            model.Add(tmp >= 3).OnlyEnforceIf(b_off3)
            model.Add(tmp <= 2).OnlyEnforceIf(b_off3.Not())
            model.AddBoolAnd([x[(e, d, "N")], b_off3]).OnlyEnforceIf(n_and_three_off)
            model.AddBoolOr([x[(e, d, "N")].Not(), b_off3.Not()]).OnlyEnforceIf(n_and_three_off.Not())
            penalties.append(w_long_rest * n_and_three_off)

    # (4) 이상적인 패턴 보상 (Soft Constraint)
    # C -> A -> A2 -> B -> N 순서를 선호.
    # 즉, C(d) -> A(d+1) 이면 보상(페널티 차감) 등.
    # 여기서는 "Minimize(penalties)"이므로, 좋은 패턴에 대해 '음수 페널티'를 추가하거나,
    # 반대로 "나쁜 패턴"에 페널티를 주는 방식이 좋음.
    # OR-Tools CP-SAT은 Minimize만 지원하므로, 음수 추가 가능.
    
    if constraints.get("prefer_ideal_pattern", False):
        w_pattern = int(weights.get("reward_ideal_pattern", 3))
        # ... (pattern logic)

    # (NEW) N 후 불필요한 연속 휴무 억제 (Soft Penalty)
    # 기본 휴무가 1일인데 2일 이상 쉬는 것을 '비선호'하게 만듦.
    # N(d) -> OFF(d+1) -> OFF(d+2) : Penalty
    default_min_off = int(constraints.get("min_off_after_N", 1))
    if default_min_off == 1:
        w_extra_rest = 10 # Penalty weight increased to discourage 2-day rests
        for e in employees:
             for d in range(horizon - 2):
                 # N(d) -> OFF(d+1) -> OFF(d+2) pattern detection
                 long_rest = model.NewBoolVar(f"long_rest_{e}_{d}")
                 model.AddBoolAnd([
                     x[(e, d, "N")], 
                     x[(e, d+1, "OFF")], 
                     x[(e, d+2, "OFF")]
                 ]).OnlyEnforceIf(long_rest)
                 # Penalty
                 penalties.append(w_extra_rest * long_rest)

    # (4) 이상적인 패턴 보상 (Soft Constraint)
    if constraints.get("prefer_ideal_pattern", False):
        w_pattern = int(weights.get("reward_ideal_pattern", 3))
        # 패턴: C->A, A->A2, A2->B, B->N
        # 각각 발생 시 -w만큼 페널티(즉 보상)
        pairs = [("C", "A"), ("A", "A2"), ("A2", "B"), ("B", "N")]
        for e in employees:
            for d in range(horizon - 1):
                for s1, s2 in pairs:
                    # transition = 1 if (s1 at d) and (s2 at d+1)
                    t_var = model.NewBoolVar(f"trans_{e}_{d}_{s1}_{s2}")
                    model.AddBoolAnd([x[(e, d, s1)], x[(e, d + 1, s2)]]).OnlyEnforceIf(t_var)
                    model.AddBoolOr([x[(e, d, s1)].Not(), x[(e, d + 1, s2)].Not()]).OnlyEnforceIf(t_var.Not())
                    
                    # 보상(음수 페널티)
                    penalties.append(-w_pattern * t_var)

    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    schedule: Dict[str, List[str]] = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in employees:
            row = []
            for d in range(horizon):
                assigned = None
                for s in shifts:
                    if solver.Value(x[(e, d, s)]) == 1:
                        assigned = s
                        break
                row.append(assigned or "OFF")
            schedule[e] = row
    return schedule, status_name