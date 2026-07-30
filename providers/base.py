from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional,Any,AsyncIterator
from dataclasses import field



@dataclass
class ToolCall(ABC):
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    

