from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class Employee:
    name: str
    team: Optional[str] = None
    role: Optional[str] = None

@dataclass
class Rules:
    hours: Dict[str, int]
    constraints: Dict[str, object]
    weights: Dict[str, int]
    calendar: Dict[str, str]