# flake8: noqa: WPS412, WPS410 -- package only re-exports its routers
from handlers.inline import router as inline_router
from handlers.media import router as media_router
from handlers.start import router as start_router

__all__ = ["inline_router", "media_router", "start_router"]
