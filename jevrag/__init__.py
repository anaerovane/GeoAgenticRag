"""GeoAgenticRag — JEV-driven Geographic Tree-RAG.

Public surface: run an investigation with `Orchestrator`, or serve it with
`jevrag serve`. See README.md and docs/jev.md.
"""
from .config import Settings
from .evidence import EvidenceTree
from .jev import Decision, JEV, JEVError
from .orchestrator import Orchestrator, RunError
from .planner import Planner, PlannerError
from .tree import BranchResult, Node, QueryTree, Status, TreeError

__version__ = "0.1.0"

__all__ = [
    "Settings", "EvidenceTree", "Decision", "JEV", "JEVError",
    "Orchestrator", "RunError", "Planner", "PlannerError",
    "BranchResult", "Node", "QueryTree", "Status", "TreeError",
    "__version__",
]
