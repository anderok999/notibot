"""Fuentes de noticias."""

from .base import ArticleData, BaseSource
from .reduno import RedunoSource
from .unitel import UnitelSource

__all__ = ["ArticleData", "BaseSource", "RedunoSource", "UnitelSource"]
