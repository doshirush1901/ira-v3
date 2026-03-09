"""
HubSpot CRM API client for Pantheon V1.

Handles contacts, deals, and notes. Requires HUBSPOT_API_KEY (private app token)
in the environment.
"""

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger("ira.hubspot")

HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")
BASE_URL = "https://api.hubapi.com/crm/v3"


class HubSpotClient:
    """Client for HubSpot CRM API v3."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or HUBSPOT_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        json: Dict[str, Any] = None,
        params: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        if params is None:
            params = {}
        try:
            r = requests.request(
                method,
                url,
                headers=self.headers,
                json=json,
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            return r.json() if r.content else {}
        except requests.RequestException as e:
            logger.warning("HubSpot API error: %s", e)
            raise

    def search_contact_by_email(self, email: str) -> Dict[str, Any]:
        """Search for a contact by email. Returns HubSpot search response with results."""
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email,
                        }
                    ]
                }
            ]
        }
        return self._request("POST", "/objects/contacts/search", json=payload)

    def create_contact(self, properties: Dict[str, str]) -> Dict[str, Any]:
        """Create a contact. Returns created object with id."""
        payload = {"properties": properties}
        return self._request("POST", "/objects/contacts", json=payload)

    def create_deal(
        self,
        properties: Dict[str, Any],
        associations: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a deal and optionally associate to contacts/companies."""
        payload = {"properties": properties}
        if associations:
            payload["associations"] = associations
        return self._request("POST", "/objects/deals", json=payload)

    def create_note(
        self,
        properties: Dict[str, Any],
        associations: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a note and optionally associate to a deal/contact."""
        payload = {"properties": properties}
        if associations:
            payload["associations"] = associations
        return self._request("POST", "/objects/notes", json=payload)
