"""API routers: auth + portfolio/preferences (Phase 3); watchlist, summaries,
alerts & notifications (Phase 4)."""
from .alerts import router as alerts_router
from .auth import router as auth_router
from .digest import router as digest_router
from .portfolio import create_portfolio_router
from .recommendations import create_recommendations_router
from .summaries import create_summaries_router
from .watchlist import router as watchlist_router

__all__ = [
    "alerts_router",
    "auth_router",
    "create_portfolio_router",
    "create_recommendations_router",
    "create_summaries_router",
    "digest_router",
    "watchlist_router",
]
