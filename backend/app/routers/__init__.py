"""Phase 3 API routers: auth + portfolio/preferences CRUD."""
from .auth import router as auth_router
from .portfolio import create_portfolio_router

__all__ = ["auth_router", "create_portfolio_router"]
