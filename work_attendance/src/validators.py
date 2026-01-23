from typing import Dict, List

def check_rules(schedule: Dict[str, List[str]], hours: Dict[str, int]) -> Dict[str, List[str]]:
    """
    간단한 사후검증: 규칙 위반을 문자열로 모아 리턴
    (필요시 더 상세 검증을 추가하세요)
    """
    msgs: Dict[str, List[str]] = {}
    # 예시: 3연속 A 금지 확인
    for e, days in schedule.items():
        for i in range(len(days) - 2):
            if days[i] == days[i+1] == days[i+2] == "A":
                msgs.setdefault(e, []).append(f"D{i+1}~D{i+3} A 3연속")
    return msgs