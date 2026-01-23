import csv
import os
import yaml
from typing import Dict, List, Optional
from .data_models import Employee, Rules

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "configs")

def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_employees_from_csv(path: str) -> List[Employee]:
    if not os.path.exists(path):
        # 웹 배포 시 파일 누락으로 인한 크래시 방지
        return []
    emps: List[Employee] = []
    # Excel에서 저장한 CSV 인코딩(BOM)을 고려하여 utf-8-sig 사용
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            emps.append(Employee(name=name, team=r.get("team"), role=r.get("role")))
    return emps

def load_employees(path: str) -> List[Employee]:
    emps = load_employees_from_csv(path)
    return emps

def load_demand(path: str) -> Optional[Dict[int, Dict[str, int]]]:
    if not os.path.exists(path):
        return None
    out: Dict[int, Dict[str, int]] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            day = int(r["day"])
            out[day-1] = {
                "A": int(r.get("A", 0) or 0),
                "B": int(r.get("B", 0) or 0),
                "C": int(r.get("C", 0) or 0),
                "N": int(r.get("N", 0) or 0),
            }
    return out

def load_vacations(path: str) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            day = int(r["day"]) - 1
            out.setdefault(name, []).append(day)
    return out

def load_all():
    rules_dict = load_yaml(os.path.join(CONFIG_DIR, "rules.yaml"))
    rules = Rules(
        hours=rules_dict.get("hours", {}),
        constraints=rules_dict.get("constraints", {}),
        weights=rules_dict.get("weights", {}),
        calendar=rules_dict.get("calendar", {}),
    )
    employees = load_employees(os.path.join(CONFIG_DIR, "employees.csv"))
    demand = load_demand(os.path.join(CONFIG_DIR, "demand.csv"))
    vacations = load_vacations(os.path.join(CONFIG_DIR, "vacations.csv"))
    return rules, employees, demand, vacations