"""Unit tests for Web Application Knowledge Templates and Registry."""

import pytest

from friday.integrations.webapp_templates.registry import (
    WebAppTemplate,
    WebAppTemplateRegistry,
    webapp_templates,
)
from friday.tools.builtin.webapp_knowledge_tool import LookupWebAppTemplateTool


def test_webapp_template_model_matching() -> None:
    tmpl = WebAppTemplate(
        app_name="GitHub",
        domains=["github.com"],
        keywords=["pr", "pull request", "repo"],
        description="GitHub repository operations",
        url="https://github.com",
        rules=["Rule 1: navigate URL first"],
    )
    assert tmpl.matches_url("https://github.com/owner/repo") is True
    assert tmpl.matches_url("https://google.com") is False
    assert tmpl.matches_query("merge this pull request") is True
    assert tmpl.matches_query("unrelated query") is False


def test_registry_seed_templates_presence() -> None:
    registry = WebAppTemplateRegistry()
    templates = registry.list_templates()
    assert len(templates) >= 5

    wa = registry.get_template("whatsapp")
    assert wa is not None
    assert "web.whatsapp.com" in wa.domains

    gm = registry.find_by_url("https://mail.google.com/mail/u/0/#inbox")
    assert gm is not None
    assert gm.app_name == "Gmail"

    gh = registry.find_by_query("how to check github issues")
    assert gh is not None
    assert gh.app_name == "GitHub"


@pytest.mark.asyncio
async def test_lookup_webapp_template_tool() -> None:
    tool = LookupWebAppTemplateTool()

    # 1. Valid lookup by name
    res = await tool.execute(app_name_or_url="whatsapp")
    assert res.is_error is False
    assert res.metadata["app_name"] == "WhatsApp"
    assert len(res.metadata["rules"]) > 0

    # 2. Valid lookup by URL
    res2 = await tool.execute(app_name_or_url="https://github.com/torvalds/linux")
    assert res2.is_error is False
    assert res2.metadata["app_name"] == "GitHub"

    # 3. Missing query
    res_err = await tool.execute(app_name_or_url="")
    assert res_err.is_error is True
    assert "required" in res_err.content

    # 4. Unknown query
    res_unknown = await tool.execute(app_name_or_url="xyzNonExistentApp123")
    assert res_unknown.is_error is True
    assert "No template found" in res_unknown.content
