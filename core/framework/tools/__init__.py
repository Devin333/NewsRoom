from __future__ import annotations

# TODO(boundary-migration): compatibility bridge; import framework.tool or
# infrastructure.tools directly in new code.

from framework.tool import *  # noqa: F401,F403
from infrastructure.tools import (  # noqa: F401
    DuckDuckGoHtmlSearchProvider,
    EmailSender,
    LocalJsonToolStore,
    RssFeedPublisher,
    SmtpEmailSender,
    WebSearchFetcher,
    WebSearchProvider,
    WebSearchResult,
    WebhookSender,
    build_builtin_dangerous_registry,
    build_builtin_dangerous_tool_registry,
    build_builtin_safe_registry,
    build_builtin_safe_tool_registry,
    build_builtin_tool_registry,
    build_tool_catalog,
    register_local_json_tools,
    register_notification_tools,
    register_qdrant_tools,
    register_web_search_tools,
)
