from __future__ import annotations

import http.cookiejar
import http.cookiejar
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .event_type import infer_event_type, normalize_event_type


LOG = logging.getLogger(__name__)

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 5
MAX_RETRY_DELAY_SECONDS = 10.0


@dataclass(frozen=True)
class AmoCRMSearchResult:
    found: bool
    entity_type: str | None = None
    entity_id: int | None = None
    created_at: int | None = None
    updated_at: int | None = None
    responsible_user_id: int | None = None
    responsible_user_name: str | None = None
    event_type: str | None = None
    ambiguity_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "responsible_user_id": self.responsible_user_id,
            "responsible_user_name": self.responsible_user_name,
            "event_type": self.event_type,
            "ambiguity_count": self.ambiguity_count,
        }


class AmoCRMClient:
    def __init__(self, domain: str, token: str) -> None:
        self.domain = domain.rstrip("/")
        self._token = token
        self._user_names: dict[int, str] = {}
        self._search_cache: dict[tuple[str, str, str | None], list[dict[str, Any]]] = {}
        self._entity_cache: dict[
            tuple[str, int, tuple[tuple[str, str], ...]],
            dict[str, Any] | None,
        ] = {}
        self._amojo_access_token: str | None = None
        self._amojo_message_cache: dict[str, dict[str, Any] | None] = {}
        self._amojo_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._amojo_access_token: str | None = None
        self._amojo_message_cache: dict[str, dict[str, Any]] = {}

    def search(
        self,
        query: str,
        lead_id: str,
        identifier_type: str,
        target_created_at: int | None = None,
    ) -> AmoCRMSearchResult:
        if not query:
            return AmoCRMSearchResult(found=False)

        direct_leads = self._search_collection("leads", query, with_value=None)
        contacts = self._search_collection("contacts", query, with_value="leads")
        candidates = self._flatten_lead_candidates(direct_leads, contacts)

        seen: set[int] = set()
        unique_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_id = int(candidate["id"])
            if candidate_id not in seen:
                seen.add(candidate_id)
                unique_candidates.append(candidate)

        # A contact alone is not proof that the incoming request was entered as
        # an amoCRM deal. Lead Control therefore treats only a real deal/lead as
        # a CRM match.
        if not unique_candidates:
            return AmoCRMSearchResult(found=False)

        chosen = self._choose_lead_candidate(unique_candidates, target_created_at)

        if len(unique_candidates) > 1:
            LOG.warning(
                "CRM ambiguity lead_id=%s identifier_type=%s candidates=%s chosen_id=%s target_created_at=%s",
                lead_id,
                identifier_type,
                len(unique_candidates),
                chosen["id"],
                target_created_at,
            )

        # Search responses can be shallow. The full chosen deal card is the
        # authoritative source for responsible manager and especially the
        # custom field `Формат`.
        full_lead = self._get_entity("leads", int(chosen["id"])) or {}
        authoritative = full_lead or chosen
        responsible_user_id = authoritative.get("responsible_user_id") or chosen.get("responsible_user_id")
        responsible_user_name = self._get_user_name(responsible_user_id)
        event_type = _extract_event_type_from_entity(authoritative)

        return AmoCRMSearchResult(
            found=True,
            entity_type="lead",
            entity_id=int(chosen["id"]),
            created_at=authoritative.get("created_at") or chosen.get("created_at"),
            updated_at=authoritative.get("updated_at") or chosen.get("updated_at"),
            responsible_user_id=responsible_user_id,
            responsible_user_name=responsible_user_name,
            event_type=event_type,
            ambiguity_count=max(0, len(unique_candidates) - 1),
        )

    def _search_collection(
        self,
        entity_type: str,
        query: str,
        with_value: str | None,
    ) -> list[dict[str, Any]]:
        cache_key = (entity_type, query, with_value)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        params: dict[str, str | int] = {
            "query": query,
            "limit": 50,
        }
        if entity_type == "leads":
            params["order[created_at]"] = "desc"
        else:
            params["order[updated_at]"] = "desc"
        if with_value:
            params["with"] = with_value

        response = self._request_json(f"/api/v4/{entity_type}", params)
        embedded = response.get("_embedded") or {}
        items = list(embedded.get(entity_type) or [])
        self._search_cache[cache_key] = items
        return list(items)

    def _flatten_lead_candidates(
        self,
        leads: list[dict[str, Any]],
        contacts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for lead in leads:
            candidates.append(self._candidate_from_lead(lead))

        for contact in contacts:
            contact_id = int(contact["id"])
            linked_leads = ((contact.get("_embedded") or {}).get("leads")) or []

            # Some amoCRM search responses omit embedded links even with
            # `with=leads`; fetch the exact contact once before concluding that
            # it has no deals.
            if not linked_leads:
                full_contact = self._get_entity("contacts", contact_id, params={"with": "leads"})
                linked_leads = (((full_contact or {}).get("_embedded") or {}).get("leads")) or []

            for linked in linked_leads[:50]:
                linked_id = linked.get("id")
                if not linked_id:
                    continue
                lead = self._get_entity("leads", int(linked_id))
                if lead:
                    candidates.append(self._candidate_from_lead(lead))

        return candidates

    @staticmethod
    def _candidate_from_lead(entity: dict[str, Any]) -> dict[str, Any]:
        return {
            "entity_type": "lead",
            "id": int(entity["id"]),
            "created_at": entity.get("created_at"),
            "updated_at": entity.get("updated_at"),
            "responsible_user_id": entity.get("responsible_user_id"),
            "event_type": _extract_event_type_from_entity(entity),
            "custom_fields_values": entity.get("custom_fields_values") or [],
            "name": entity.get("name"),
        }

    @staticmethod
    def _choose_lead_candidate(
        candidates: list[dict[str, Any]],
        target_created_at: int | None,
    ) -> dict[str, Any]:
        target = int(target_created_at or 0)
        if target > 0:
            def score(item: dict[str, Any]) -> tuple[int, int, int]:
                created = int(item.get("created_at") or 0)
                distance = abs(created - target) if created else 10**15
                return (
                    distance,
                    -int(item.get("updated_at") or 0),
                    -int(item.get("id") or 0),
                )

            return min(candidates, key=score)

        return max(
            candidates,
            key=lambda item: (
                int(item.get("created_at") or 0),
                int(item.get("updated_at") or 0),
                int(item.get("id") or 0),
            ),
        )

    def _get_entity(
        self,
        entity_type: str,
        entity_id: int,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        request_params = params or {}
        cache_key = (
            entity_type,
            int(entity_id),
            tuple(sorted((str(key), str(value)) for key, value in request_params.items())),
        )
        if cache_key in self._entity_cache:
            return self._entity_cache[cache_key]

        try:
            entity = self._request_json(f"/api/v4/{entity_type}/{entity_id}", request_params)
        except RuntimeError as exc:
            LOG.warning(
                "CRM linked entity lookup failed entity_type=%s entity_id=%s error=%s",
                entity_type,
                entity_id,
                exc,
            )
            return None

        self._entity_cache[cache_key] = entity
        return entity

    def _amojo_session_token(self, lead_id: int) -> str:
        """Create one amoCRM web chat session for this refresh.

        amoCRM's public events API exposes internal-message IDs but not their
        text. The lead card itself creates a short-lived amojo session using the
        same authenticated amoCRM account. Reuse that session for all closed
        leads in the current refresh.
        """
        if self._amojo_access_token:
            return self._amojo_access_token

        lead_url = f"{self.domain}/leads/detail/{int(lead_id)}"
        page_request = urllib.request.Request(
            lead_url,
            headers={
                "Accept": "text/html,*/*",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "Mozilla/5.0",
            },
            method="GET",
        )
        try:
            with self._amojo_opener.open(page_request, timeout=30) as response:
                response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            code = getattr(exc, "code", None)
            suffix = f"HTTP {code}" if code else str(getattr(exc, "reason", exc))
            raise RuntimeError(f"amoCRM chat session bootstrap failed: {suffix}") from None

        body = urllib.parse.urlencode(
            {"request[chats][session][action]": "create"}
        ).encode("utf-8")
        session_request = urllib.request.Request(
            f"{self.domain}/ajax/v1/chats/session",
            data=body,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": lead_url,
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        try:
            with self._amojo_opener.open(session_request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"amoCRM chat session request failed: HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"amoCRM chat session request failed: {getattr(exc, 'reason', exc)}"
            ) from None
        except json.JSONDecodeError:
            raise RuntimeError("amoCRM chat session request failed: invalid JSON") from None

        session = ((payload.get("response") or {}).get("chats") or {}).get("session") or {}
        token = str(session.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("amoCRM chat session request returned no access token")

        self._amojo_access_token = token
        return token

    def _get_amojo_message(
        self,
        message_id: str,
        lead_id: int,
    ) -> dict[str, Any] | None:
        """Fetch one internal-message payload by the ID exposed in CRM events."""
        mid = str(message_id or "").strip()
        if not mid:
            return None
        if mid in self._amojo_message_cache:
            return self._amojo_message_cache[mid]

        access_token = self._amojo_session_token(lead_id)
        query = urllib.parse.urlencode([("id[]", mid)])
        request = urllib.request.Request(
            f"https://amojo.amocrm.ru/v2/messages?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
                "X-Auth-Token": access_token,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8") or "[]")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"amoCRM message lookup failed: HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"amoCRM message lookup failed: {getattr(exc, 'reason', exc)}"
            ) from None
        except json.JSONDecodeError:
            raise RuntimeError("amoCRM message lookup failed: invalid JSON") from None

        items = payload if isinstance(payload, list) else []
        found = next(
            (
                item for item in items
                if isinstance(item, dict) and str(item.get("id") or "") == mid
            ),
            None,
        )
        self._amojo_message_cache[mid] = found
        return found

    def _get_user_name(self, user_id: Any) -> str | None:
        if not user_id:
            return None
        uid = int(user_id)
        if uid in self._user_names:
            return self._user_names[uid] or None
        try:
            user = self._request_json(f"/api/v4/users/{uid}", {})
            name = str(user.get("name") or "").strip()
        except RuntimeError as exc:
            LOG.warning("CRM user lookup failed user_id=%s error=%s", uid, exc)
            name = ""
        self._user_names[uid] = name
        return name or None

    def fetch_internal_messages(
        self,
        lead_id: int,
        message_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Read amoCRM internal-chat messages exactly as the lead card does.

        The CRM events API exposes only message IDs for entity_direct_message.
        The web card creates a short-lived amojo session and then loads message
        bodies from /v2/messages using repeated id[] query parameters.
        """
        ids = [str(item or "").strip() for item in message_ids]
        ids = [item for item in ids if item]
        missing = [item for item in dict.fromkeys(ids) if item not in self._amojo_message_cache]
        if not missing:
            return {item: self._amojo_message_cache[item] for item in ids if item in self._amojo_message_cache}

        access_token = self._amojo_access_token or self._create_amojo_session(int(lead_id))
        self._amojo_access_token = access_token

        query = urllib.parse.urlencode([("id[]", item) for item in missing])
        host = "https://amojo.amocrm.com" if ".amocrm.com" in self.domain else "https://amojo.amocrm.ru"
        request = urllib.request.Request(
            f"{host}/v2/messages?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
                "X-Auth-Token": access_token,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8") or "[]")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"amoCRM chat message lookup failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"amoCRM chat message lookup failed: {reason}") from None
        except json.JSONDecodeError:
            raise RuntimeError("amoCRM chat message lookup failed: invalid JSON response") from None

        if not isinstance(payload, list):
            raise RuntimeError("amoCRM chat message lookup failed: invalid payload")

        for item in payload:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "").strip()
            if message_id:
                self._amojo_message_cache[message_id] = item

        return {item: self._amojo_message_cache[item] for item in ids if item in self._amojo_message_cache}

    def _create_amojo_session(self, lead_id: int) -> str:
        """Create the same short-lived chat session used by the amoCRM card."""
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        page_url = f"{self.domain}/leads/detail/{int(lead_id)}"

        page_request = urllib.request.Request(
            page_url,
            headers={
                "Accept": "text/html,*/*",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "Mozilla/5.0",
            },
            method="GET",
        )
        try:
            with opener.open(page_request, timeout=30) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"amoCRM chat session page failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"amoCRM chat session page failed: {reason}") from None

        body = urllib.parse.urlencode(
            {"request[chats][session][action]": "create"}
        ).encode("utf-8")
        session_request = urllib.request.Request(
            f"{self.domain}/ajax/v1/chats/session",
            data=body,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": page_url,
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        try:
            with opener.open(session_request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"amoCRM chat session failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"amoCRM chat session failed: {reason}") from None
        except json.JSONDecodeError:
            raise RuntimeError("amoCRM chat session failed: invalid JSON response") from None

        session = (((payload.get("response") or {}).get("chats") or {}).get("session") or {})
        access_token = str(session.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("amoCRM chat session failed: missing access token")
        return access_token

    def _request_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{self.domain}{path}"
        if query:
            url = f"{url}?{query}"

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
            method="GET",
        )

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status == 204:
                        return {}
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 204:
                    return {}
                if exc.code not in RETRYABLE_HTTP_CODES or attempt >= MAX_REQUEST_ATTEMPTS:
                    raise RuntimeError(f"amoCRM request failed: HTTP {exc.code}") from None
                delay = _retry_delay_seconds(attempt, _retry_after_header(exc))
                LOG.warning(
                    "amoCRM transient HTTP error code=%s path=%s attempt=%s/%s retry_in=%.1fs",
                    exc.code,
                    path,
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= MAX_REQUEST_ATTEMPTS:
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"amoCRM request failed: {reason}") from None
                delay = _retry_delay_seconds(attempt, None)
                LOG.warning(
                    "amoCRM transient network error path=%s attempt=%s/%s retry_in=%.1fs error=%s",
                    path,
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    delay,
                    getattr(exc, "reason", exc),
                )
                time.sleep(delay)
            except json.JSONDecodeError:
                if attempt >= MAX_REQUEST_ATTEMPTS:
                    raise RuntimeError("amoCRM request failed: invalid JSON response") from None
                delay = _retry_delay_seconds(attempt, None)
                LOG.warning(
                    "amoCRM invalid JSON path=%s attempt=%s/%s retry_in=%.1fs",
                    path,
                    attempt,
                    MAX_REQUEST_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError("amoCRM request failed after retries")


def _retry_after_header(exc: urllib.error.HTTPError) -> str | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After")
    except AttributeError:
        return None
    return str(value).strip() if value is not None else None


def _retry_delay_seconds(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(MAX_RETRY_DELAY_SECONDS, float(2 ** max(0, attempt - 1)))


def _extract_event_type_from_entity(entity: dict[str, Any]) -> str | None:
    custom_fields = entity.get("custom_fields_values") or []
    strong_labels = {
        "формат",
        "мероприятие",
        "тип мероприятия",
        "вид мероприятия",
        "формат мероприятия",
        "событие",
        "тип события",
        "вид события",
        "формат события",
    }

    # Exact amoCRM field `Формат` is authoritative. It is intentionally checked
    # before every other label.
    ordered_fields = sorted(
        custom_fields,
        key=lambda field: 0
        if str(field.get("field_name") or "").strip().casefold().replace("ё", "е") == "формат"
        else 1,
    )

    for field in ordered_fields:
        field_name = str(field.get("field_name") or "").strip().casefold().replace("ё", "е")
        if field_name not in strong_labels:
            continue
        for raw_value in _custom_field_values(field):
            inferred = infer_event_type(raw_value)
            if inferred:
                return inferred
            normalized = normalize_event_type(raw_value)
            if normalized:
                return normalized

    # Legacy fallback only when the authoritative event-format fields are
    # absent/empty.
    for field in custom_fields:
        for raw_value in _custom_field_values(field):
            inferred = infer_event_type(raw_value)
            if inferred:
                return inferred

    inferred_from_name = infer_event_type(entity.get("name"))
    return inferred_from_name or None


def _custom_field_values(field: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in field.get("values") or []:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("text")
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result
