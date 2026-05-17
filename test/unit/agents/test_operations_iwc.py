from types import SimpleNamespace
from typing import (
    Any,
    cast,
)
from unittest.mock import patch

import pytest

from galaxy import exceptions
from galaxy.managers.context import ProvidesUserContext
from galaxy.managers.workflows import WorkflowContentsManager
from galaxy.webapps.galaxy.services.workflows import WorkflowsService


class MutatingWorkflowContentsManager:
    def ensure_raw_description(self, definition):
        return SimpleNamespace(as_dict=definition)

    def build_workflow_from_raw_description(self, trans, raw_workflow_description, create_options, source=None):
        raw_workflow_description.as_dict["steps"]["0"]["subworkflow"] = object()
        return SimpleNamespace(
            stored_workflow=SimpleNamespace(id=1, name="Imported IWC workflow"),
            missing_tools=[("missing/tool", "Missing Tool", "1.0", "0")],
        )


def _make_service() -> WorkflowsService:
    service = WorkflowsService.__new__(WorkflowsService)
    # Duck-typed mock; we only need the two methods import_from_iwc calls.
    service._workflow_contents_manager = cast(WorkflowContentsManager, MutatingWorkflowContentsManager())
    return service


def test_import_from_iwc_does_not_mutate_cached_definition():
    definition: dict[str, Any] = {
        "name": "IWC workflow with subworkflow",
        "annotation": "",
        "tags": [],
        "steps": {
            "0": {
                "id": 0,
                "type": "subworkflow",
                "subworkflow": {
                    "name": "Embedded subworkflow",
                    "annotation": "",
                    "tags": [],
                    "steps": {},
                },
            }
        },
    }
    manifest = [
        {
            "workflows": [
                {
                    "trsID": "#workflow/github.com/iwc-workflows/with-subworkflow/main",
                    "definition": definition,
                }
            ]
        }
    ]
    trans = SimpleNamespace(
        user=SimpleNamespace(id=42),
        security=SimpleNamespace(encode_id=lambda value: f"encoded-{value}"),
    )
    service = _make_service()

    with patch("galaxy.agents.iwc.fetch_manifest", return_value=manifest):
        result = service.import_from_iwc(
            cast(ProvidesUserContext, trans),
            "#workflow/github.com/iwc-workflows/with-subworkflow/main",
        )

    assert result["id"] == "encoded-1"
    assert result["missing_tools"] == ["missing/tool"]
    assert isinstance(definition["steps"]["0"]["subworkflow"], dict)


def test_import_from_iwc_requires_authenticated_user():
    trans = SimpleNamespace(user=None)
    service = _make_service()

    with pytest.raises(exceptions.AuthenticationRequired):
        service.import_from_iwc(cast(ProvidesUserContext, trans), "#workflow/anything/main")


def test_import_from_iwc_raises_object_not_found_for_unknown_trs_id():
    manifest = [
        {
            "workflows": [
                {
                    "trsID": "#workflow/github.com/iwc-workflows/known/main",
                    "definition": {"name": "Known", "steps": {}},
                }
            ]
        }
    ]
    trans = SimpleNamespace(
        user=SimpleNamespace(id=1),
        security=SimpleNamespace(encode_id=lambda value: f"encoded-{value}"),
    )
    service = _make_service()

    with patch("galaxy.agents.iwc.fetch_manifest", return_value=manifest):
        with pytest.raises(exceptions.ObjectNotFound, match="not found"):
            service.import_from_iwc(
                cast(ProvidesUserContext, trans),
                "#workflow/github.com/iwc-workflows/missing/main",
            )
