"""Public health, server time, build version and client-safe configuration.

These endpoints carry no authentication and expose no secrets. They are mounted
outside the IP/geo restriction guard so monitoring and load balancers can reach
``/public/ping`` even while the API is in maintenance mode.
"""

from fastapi import APIRouter

from app.schemas.common import Envelope
from app.schemas.identity import ConfigsOut, VersionOut
from app.services import meta_service

router = APIRouter()


@router.get("/ping", response_model=Envelope[dict[str, str]])
async def ping() -> Envelope[dict[str, str]]:
    return Envelope[dict[str, str]](data={"ping": "pong"})


@router.get("/time", response_model=Envelope[dict[str, str]])
async def server_time() -> Envelope[dict[str, str]]:
    return Envelope[dict[str, str]](data={"time": meta_service.server_time_iso()})


@router.get("/version", response_model=Envelope[VersionOut])
async def version() -> Envelope[VersionOut]:
    return Envelope[VersionOut](data=meta_service.build_version())


@router.get("/configs", response_model=Envelope[ConfigsOut])
async def configs() -> Envelope[ConfigsOut]:
    return Envelope[ConfigsOut](data=meta_service.build_configs())
