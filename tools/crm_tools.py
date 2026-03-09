"""
CRM tools for Pantheon V1 — HubSpot integration.

Used by the email bridge and orchestrator to create/update contacts and deals
when new leads are identified. Import and use CrmTools or the module-level helpers.
"""

import logging
from typing import Optional

from openclaw.agents.ira.src.crm.hubspot_client import HubSpotClient

logger = logging.getLogger("ira.crm_tools")

# HubSpot association type: Contact to Deal
CONTACT_TO_DEAL_ASSOCIATION_TYPE = 3
# Deal to Note
DEAL_TO_NOTE_ASSOCIATION_TYPE = 214


class CrmTools:
    """Tools for HubSpot CRM: contact check/create, deal creation, logging emails as notes."""

    def __init__(self, api_key: str = ""):
        self.client = HubSpotClient(api_key=api_key)

    def check_and_create_contact(
        self,
        email: str,
        firstname: str = "",
        lastname: str = "",
        company: str = "",
    ) -> Optional[str]:
        """
        Check if a contact exists in HubSpot by email. If not, create one.

        Returns:
            HubSpot contact ID (string), or None if HubSpot is unavailable.
        """
        try:
            search_result = self.client.search_contact_by_email(email)
            total = search_result.get("total", 0)
            if total and search_result.get("results"):
                contact_id = search_result["results"][0]["id"]
                logger.info("Contact %s already exists with ID: %s", email, contact_id)
                return contact_id

            properties = {
                "email": email,
                "firstname": firstname or "",
                "lastname": lastname or "",
                "company": company or "",
            }
            new_contact = self.client.create_contact(properties)
            contact_id = new_contact.get("id")
            logger.info("Created new contact for %s with ID: %s", email, contact_id)
            try:
                from openclaw.agents.ira.src.core.activity_logger import log_event
                log_event("LEAD_CREATED", f"email={email} contact_id={contact_id}")
            except Exception:
                pass
            return contact_id
        except Exception as e:
            logger.warning("HubSpot check_and_create_contact failed: %s", e)
            return None

    def create_deal_for_contact(
        self,
        contact_id: str,
        deal_name: str,
        amount: str = "0",
        pipeline: str = "default",
        stage: str = "appointmentscheduled",
    ) -> Optional[str]:
        """
        Create a new deal and associate it with a contact.

        Returns:
            HubSpot deal ID (string), or None on failure.
        """
        try:
            properties = {
                "dealname": deal_name,
                "amount": amount,
                "pipeline": pipeline,
                "dealstage": stage,
            }
            associations = [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": CONTACT_TO_DEAL_ASSOCIATION_TYPE,
                        }
                    ],
                }
            ]
            new_deal = self.client.create_deal(properties, associations)
            deal_id = new_deal.get("id")
            logger.info("Created new deal '%s' with ID: %s", deal_name, deal_id)
            try:
                from openclaw.agents.ira.src.core.activity_logger import log_event
                log_event("DEAL_CREATED", f"deal_id={deal_id} name={deal_name}")
            except Exception:
                pass
            return deal_id
        except Exception as e:
            logger.warning("HubSpot create_deal_for_contact failed: %s", e)
            return None

    def log_email_to_deal(self, deal_id: str, email_body: str, timestamp: str = "") -> bool:
        """
        Log an email as a note on a deal timeline.

        timestamp: ISO format (e.g. 2023-03-01T00:00:00Z). If empty, uses current time.
        """
        import datetime
        ts = timestamp or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            properties = {
                "hs_timestamp": ts,
                "hs_note_body": email_body[:65536],  # HubSpot body limit
            }
            associations = [
                {
                    "to": {"id": deal_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": DEAL_TO_NOTE_ASSOCIATION_TYPE,
                        }
                    ],
                }
            ]
            self.client.create_note(properties, associations)
            logger.info("Logged email to deal ID: %s", deal_id)
            return True
        except Exception as e:
            logger.warning("HubSpot log_email_to_deal failed: %s", e)
            return False


def get_crm_tools(api_key: str = "") -> CrmTools:
    """Return a CrmTools instance (singleton optional)."""
    return CrmTools(api_key=api_key)
