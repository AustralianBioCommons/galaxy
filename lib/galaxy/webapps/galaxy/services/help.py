import logging

from galaxy.config import GalaxyAppConfiguration
from galaxy.exceptions import (
    GatewayTimeoutException,
    InternalServerError,
    ServerNotConfiguredForRequest,
    UpstreamProxyError,
)
from galaxy.schema.help import HelpForumSearchResponse
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.util import requests
from galaxy.webapps.galaxy.services.base import ServiceBase

log = logging.getLogger(__name__)


class HelpService(ServiceBase):
    """Common interface/service logic for interactions with Galaxy Help API.

    Provides the logic of the actions invoked by API controllers and uses type definitions
    and pydantic models to declare its parameters and return types.
    """

    def __init__(
        self,
        security: IdEncodingHelper,
        config: GalaxyAppConfiguration,
    ):
        super().__init__(security)
        self.config = config

    def search_forum(self, query: str) -> HelpForumSearchResponse:
        """Search the Galaxy Help forum using the Discourse API."""
        if not self.config.enable_help_forum_tool_panel_integration:
            raise ServerNotConfiguredForRequest(
                "Integration with the Galaxy Help Forum is not enabled in the configuration."
            )
        if not self.config.help_forum_api_url:
            raise ServerNotConfiguredForRequest("Help forum API URL is not configured.")
        forum_search_url = f"{self.config.help_forum_api_url}/search.json"
        try:
            response = requests.get(
                url=forum_search_url,
                params={
                    "q": query,
                },
            )
        except requests.exceptions.ConnectionError as e:
            log.error("Could not connect to the Galaxy Help Forum at %s: %s", forum_search_url, e)
            raise UpstreamProxyError(
                "Could not connect to the Galaxy Help Forum. The service may be temporarily unavailable."
            )
        except requests.exceptions.Timeout as e:
            log.error("Request to the Galaxy Help Forum at %s timed out: %s", forum_search_url, e)
            raise GatewayTimeoutException("The request to the Galaxy Help Forum timed out. Please try again later.")
        except requests.exceptions.RequestException as e:
            log.error("Unexpected error requesting the Galaxy Help Forum at %s: %s", forum_search_url, e)
            raise InternalServerError(f"An error occurred while requesting the Galaxy Help Forum: {e}")

        if not response.ok:
            if 400 <= response.status_code < 500:
                log.error(
                    "The Galaxy Help Forum returned a client error (HTTP %d) from %s. "
                    "This likely indicates a misconfigured URL or API key.",
                    response.status_code,
                    forum_search_url,
                )
                raise InternalServerError(
                    f"The Galaxy Help Forum returned an error (HTTP {response.status_code}). "
                    "This may indicate a misconfigured URL or API key that requires admin intervention."
                )
            else:
                log.error(
                    "The Galaxy Help Forum returned a server error (HTTP %d) from %s",
                    response.status_code,
                    forum_search_url,
                )
                raise UpstreamProxyError(
                    f"The Galaxy Help Forum returned an error (HTTP {response.status_code}). "
                    "The service may be temporarily unavailable. Please try again later."
                )

        try:
            return HelpForumSearchResponse(**response.json())
        except ValueError as e:
            raise InternalServerError(f"Received an unexpected response format from the Galaxy Help Forum: {e}")
