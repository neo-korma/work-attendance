import argparse
from .config import load_all, load_employees_from_csv
from .scheduler import build_and_solve
from .postprocess import save_schedule_excel

def parse_employees_arg(arg: str):
    if not arg:
        return []
    return [name.strip() for name in arg.split(",") if name.strip()]

def main():
    parser = argparse.ArgumentParser(description="교대근무 스케줄 생성기")
    parser.add_argument("--horizon", type=int, default=28, help="계획 일수 (기본 28)")
    parser.add_argument("--export", choices=["excel", "none"], default="excel", help="결과 저장 방식")
    parser.add_argument("--employees", type=str, default="", help="쉼표로 구분된 직원명 목록")
    parser.add_argument("--employees-file", type=str, default="", help="직원 CSV 경로")
    parser.add_argument("--workers-per-day", type=int, default=None, help="하루 총 근무자 수(정확히 ==)")
    parser.add_argument("--min-workers-per-day", type=int, default=None, help="하루 총 근무자 수 최소")
    parser.add_argument("--max-workers-per-day", type=int, default=None, help="하루 총 근무자 수 최대")
    args = parser.parse_args()

    rules, default_employees_obj, demand, vacations = load_all()
    employees = [e.name for e in default_employees_obj]

    if args.employees_file:
        alt = load_employees_from_csv(args.employees_file)
        employees = [e.name for e in alt]

    selected = parse_employees_arg(args.employees)
    if selected:
        base = set(employees)
        employees = [n for n in selected if n in base] or employees

    # 간단 경고
    if len(employees) < 2:
        print("[주의] 직원 수가 매우 적습니다. 해를 찾지 못할 수 있어요.")

    schedule, status = build_and_solve(
        employees=employees,
        horizon=args.horizon,
        hours=rules.hours,
        constraints=rules.constraints,
        weights=rules.weights,
        demand=demand,
        vacations=vacations,
        workers_per_day=args.workers_per_day,
        min_workers_per_day=args.min_workers_per_day,
        max_workers_per_day=args.max_workers_per_day,
        forbid_free_vac=True,
    )

    print(f"해 상태: {status}")
    if schedule and args.export == "excel":
        path = save_schedule_excel(schedule)
        print(f"엑셀 저장 완료: {path}")

if __name__ == "__main__":
    main()