"""A small client for Instagram's official API (Instagram API with Instagram
Login): connect, refresh, and publish a STORY (CP23 phase 3).

The endpoints, from Meta's documentation:

  authorize        GET  {authorize_url}?client_id&redirect_uri&response_type=code
                        &scope=instagram_business_basic,instagram_business_content_publish&state
  short token      POST {oauth_url}/oauth/access_token        (form: code -> access_token, user_id)
  long-lived       GET  {graph_url}/access_token?grant_type=ig_exchange_token   (60 days)
  refresh          GET  {graph_url}/refresh_access_token?grant_type=ig_refresh_token
  the account      GET  {graph_url}/{version}/me?fields=user_id,username
  quota            GET  {graph_url}/{version}/{ig_user_id}/content_publishing_limit
  container        POST {graph_url}/{version}/{ig_user_id}/media  (media_type=STORIES, image_url)
  its status       GET  {graph_url}/{version}/{container_id}?fields=status_code
  publish          POST {graph_url}/{version}/{ig_user_id}/media_publish  (creation_id)

NOTHING SECRET LEAVES THIS MODULE IN A MESSAGE. A token travels only in the
request; errors are `GraphError(code)` with Meta's numeric code and a short
reason of OUR wording -- never the URL (it carries the token for GETs), never
Meta's text. Nothing here logs.

The client takes its aiohttp session from the caller: one per task, closed
by the task (CONTRIBUTING: no I/O client cached beyond one Celery task).
The tests point the three base URLs at a fake server; no test calls Meta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp

SCOPES = "instagram_business_basic,instagram_business_content_publish"
TIMEOUT = aiohttp.ClientTimeout(total=20)

#: Meta error codes worth telling apart (others are "graph").
TOKEN_INVALID = {190}
RATE_LIMITED = {4, 17, 32, 613, 9}


class GraphError(Exception):
    """A refusal or failure. `code` is safe to store and show; no secret inside."""

    def __init__(self, code: str, meta_code: int | None = None) -> None:
        super().__init__(code if meta_code is None else f"{code} ({meta_code})")
        self.code = code
        self.meta_code = meta_code


@dataclass(frozen=True)
class Token:
    access_token: str
    expires_in: int  # seconds


@dataclass(frozen=True)
class GraphConfig:
    app_id: str
    app_secret: str
    graph_url: str
    oauth_url: str
    authorize_url: str
    version: str


def authorize_link(config: GraphConfig, *, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": config.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
    )
    return f"{config.authorize_url}?{query}"


class Graph:
    def __init__(self, config: GraphConfig, http: aiohttp.ClientSession) -> None:
        self.config = config
        self.http = http

    def _api(self, path: str) -> str:
        return f"{self.config.graph_url}/{self.config.version}/{path}"

    async def _call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self.http.request(method, url, timeout=TIMEOUT, **kwargs) as response:
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    raise GraphError("bad_response") from None
                status = response.status
        except aiohttp.ClientError:
            # The exception's text includes the URL, and a GET's URL carries
            # the token: dropped, not chained.
            raise GraphError("network") from None
        except TimeoutError:
            raise GraphError("timeout") from None
        if not isinstance(body, dict):
            raise GraphError("bad_response")
        error = body.get("error")
        if status >= 400 or error is not None:
            meta = error.get("code") if isinstance(error, dict) else None
            meta_code = meta if isinstance(meta, int) else None
            if meta_code in TOKEN_INVALID:
                raise GraphError("token_invalid", meta_code)
            if meta_code in RATE_LIMITED:
                raise GraphError("rate_limited", meta_code)
            raise GraphError("graph", meta_code)
        return body

    # --- connecting -----------------------------------------------------------

    async def exchange_code(self, code: str, *, redirect_uri: str) -> tuple[str, str]:
        """The short-lived token and the account's id, from the redirect's code."""
        body = await self._call(
            "POST",
            f"{self.config.oauth_url}/oauth/access_token",
            data={
                "client_id": self.config.app_id,
                "client_secret": self.config.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        token, user = body.get("access_token"), body.get("user_id")
        if not isinstance(token, str) or user is None:
            raise GraphError("bad_response")
        return token, str(user)

    async def long_lived(self, short_token: str) -> Token:
        body = await self._call(
            "GET",
            f"{self.config.graph_url}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self.config.app_secret,
                "access_token": short_token,
            },
        )
        return _token(body)

    async def refresh(self, token: str) -> Token:
        body = await self._call(
            "GET",
            f"{self.config.graph_url}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
        )
        return _token(body)

    async def me(self, token: str) -> tuple[str, str]:
        body = await self._call(
            "GET", self._api("me"), params={"fields": "user_id,username", "access_token": token}
        )
        user, name = body.get("user_id") or body.get("id"), body.get("username")
        if user is None or not isinstance(name, str):
            raise GraphError("bad_response")
        return str(user), name

    # --- publishing -------------------------------------------------------------

    async def quota_left(self, ig_user_id: str, token: str) -> int:
        body = await self._call(
            "GET",
            self._api(f"{ig_user_id}/content_publishing_limit"),
            params={"fields": "quota_usage,config", "access_token": token},
        )
        data = body.get("data")
        first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
        used = first.get("quota_usage", 0)
        total = (first.get("config") or {}).get("quota_total", 0)
        if not isinstance(used, int) or not isinstance(total, int):
            raise GraphError("bad_response")
        return max(0, total - used)

    async def create_story(self, ig_user_id: str, token: str, *, image_url: str) -> str:
        body = await self._call(
            "POST",
            self._api(f"{ig_user_id}/media"),
            data={"media_type": "STORIES", "image_url": image_url, "access_token": token},
        )
        return _id(body)

    async def container_status(self, container_id: str, token: str) -> str:
        body = await self._call(
            "GET",
            self._api(container_id),
            params={"fields": "status_code", "access_token": token},
        )
        status = body.get("status_code")
        if not isinstance(status, str):
            raise GraphError("bad_response")
        return status

    async def publish(self, ig_user_id: str, token: str, *, container_id: str) -> str:
        body = await self._call(
            "POST",
            self._api(f"{ig_user_id}/media_publish"),
            data={"creation_id": container_id, "access_token": token},
        )
        return _id(body)


def _token(body: dict[str, Any]) -> Token:
    token, expires = body.get("access_token"), body.get("expires_in")
    if not isinstance(token, str) or not isinstance(expires, int):
        raise GraphError("bad_response")
    return Token(token, expires)


def _id(body: dict[str, Any]) -> str:
    value = body.get("id")
    if not isinstance(value, str | int) or not str(value).isdigit():
        raise GraphError("bad_response")
    return str(value)
