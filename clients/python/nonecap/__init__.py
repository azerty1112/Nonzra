"""عميل NoneCap Clone لبايثون (متزامن وغير متزامن)."""

from .client import NoneCap, SolveResult as PySolveResult, AutoSolveResult as PyAutoSolveResult
from .async_client import NoneCapAsync

__all__ = ["NoneCap", "NoneCapAsync", "PySolveResult", "PyAutoSolveResult"]
__version__ = "0.2.0"
