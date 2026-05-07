from .interface import (
    ToolBoxRegistry,
    ToolPanelView,
    ToolPanelViewModel,
    ToolPanelViewModelType,
)
from ..panel import (
    panel_item_types,
    ToolPanelElements,
    ToolSection,
)

MY_TOOLS_PANEL_VIEW_ID = "my_panel"
MY_TOOLS_PANEL_SECTION_ID = "favorites"


class MyToolsToolPanelView(ToolPanelView):
    def apply_view(self, base_tool_panel: ToolPanelElements, toolbox_registry: ToolBoxRegistry) -> ToolPanelElements:
        panel = ToolPanelElements()
        panel[MY_TOOLS_PANEL_SECTION_ID] = ToolSection(
            {
                "id": MY_TOOLS_PANEL_SECTION_ID,
                "name": "Favorites",
            }
        )
        return panel

    def to_model(self) -> ToolPanelViewModel:
        return ToolPanelViewModel(
            id=MY_TOOLS_PANEL_VIEW_ID,
            name="My Tools",
            description="Search all tools and view your favorite tools.",
            model_class=self.__class__.__name__,
            view_type=ToolPanelViewModelType.favorites,
            searchable=True,
        )

    def should_filter_element(self, elt, item_type) -> bool:
        # The Favorites section is populated client-side from the user's
        # favorites; the user's tool filters never need to redact it.
        if item_type == panel_item_types.SECTION and getattr(elt, "id", None) == MY_TOOLS_PANEL_SECTION_ID:
            return False
        return True
