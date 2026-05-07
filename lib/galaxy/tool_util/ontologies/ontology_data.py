from collections import defaultdict
from typing import (
    cast,
    Dict,
    List,
    NamedTuple,
    Optional,
    Tuple,
)

import yaml

from galaxy.tool_util.biotools import BiotoolsMetadataSource
from galaxy.tool_util.parser import ToolSource
from galaxy.tool_util_models.tool_source import XrefDict
from galaxy.util.resources import resource_string


def _multi_dict_mapping(content: str) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for x in content.splitlines():
        if x.startswith("#"):
            continue
        key, value = cast(Tuple[str, str], tuple(x.split("\t")))
        mapping.setdefault(key, []).append(value)
    return mapping


def _read_ontology_data_text(filename: str) -> str:
    return resource_string(__name__, filename)


BIOTOOLS_MAPPING_FILENAME = "biotools_mappings.tsv"
EDAM_OPERATION_MAPPING_FILENAME = "edam_operation_mappings.tsv"
EDAM_TOPIC_MAPPING_FILENAME = "edam_topic_mappings.tsv"
TOOL_TAG_MAPPING_FILENAME = "tool_tag_mappings.yml"

BIOTOOLS_MAPPING_CONTENT = _read_ontology_data_text(BIOTOOLS_MAPPING_FILENAME)
BIOTOOLS_MAPPING: Dict[str, List[str]] = defaultdict(list)
for line in BIOTOOLS_MAPPING_CONTENT.splitlines():
    if not line.startswith("#"):
        tool_id, xref = line.split("\t")
        BIOTOOLS_MAPPING[tool_id].append(xref)
EDAM_OPERATION_MAPPING_CONTENT = _read_ontology_data_text(EDAM_OPERATION_MAPPING_FILENAME)
EDAM_OPERATION_MAPPING: Dict[str, List[str]] = _multi_dict_mapping(EDAM_OPERATION_MAPPING_CONTENT)

EDAM_TOPIC_MAPPING_CONTENT = _read_ontology_data_text(EDAM_TOPIC_MAPPING_FILENAME)
EDAM_TOPIC_MAPPING: Dict[str, List[str]] = _multi_dict_mapping(EDAM_TOPIC_MAPPING_CONTENT)


def _load_tool_tag_mapping(content: str) -> Dict[str, List[str]]:
    raw = cast(
        Dict[str, List[str]],
        (yaml.safe_load(content) or {}).get("tool_tags", {}),
    )
    # Galaxy lowercases tool ids when constructing `Tool.all_ids` (see
    # `Tool._setup_id`), so the curated mapping must use lowercase keys to
    # be looked up successfully. Normalize at load time so admin-supplied
    # YAML files don't have to worry about case.
    return {tool_id.lower(): tags for tool_id, tags in raw.items()}


TOOL_TAG_MAPPING_CONTENT = _read_ontology_data_text(TOOL_TAG_MAPPING_FILENAME)
TOOL_TAG_MAPPING: Dict[str, List[str]] = _load_tool_tag_mapping(TOOL_TAG_MAPPING_CONTENT)


def configure_tool_tag_mapping(file_path: Optional[str]) -> None:
    """Replace the in-memory curated tool → tag mapping.

    Galaxy calls this once at startup with the value of the
    ``tool_tag_mappings_file`` config option. If ``file_path`` is empty or
    ``None``, the bundled minimal mapping (see ``tool_tag_mappings.yml``) is
    retained. Missing or unreadable files are logged and the in-memory
    mapping is left untouched so a typo in ``galaxy.yml`` doesn't take down
    tool loading.
    """
    if not file_path:
        return
    try:
        with open(file_path, encoding="utf-8") as fh:
            new_mapping = _load_tool_tag_mapping(fh.read())
    except OSError:
        # Surface the failure but keep the bundled fallback active.
        import logging

        logging.getLogger(__name__).warning(
            "Could not read tool_tag_mappings_file %s; falling back to bundled mapping.",
            file_path,
        )
        return
    global TOOL_TAG_MAPPING
    TOOL_TAG_MAPPING = new_mapping


class OntologyData(NamedTuple):
    xrefs: List[XrefDict]
    edam_operations: Optional[List[str]]
    edam_topics: Optional[List[str]]
    tool_tags: List[str]


def biotools_reference(xrefs):
    for xref in xrefs:
        if xref["type"] == "bio.tools":
            return xref["value"]
    return None


def legacy_biotools_external_reference(all_ids: List[str]) -> List[str]:
    for tool_id in all_ids:
        if tool_id in BIOTOOLS_MAPPING:
            return BIOTOOLS_MAPPING[tool_id]
    return []


def curated_tool_tags(all_ids: List[str]) -> List[str]:
    seen = set()
    tags: List[str] = []
    for tool_id in all_ids:
        for tag in TOOL_TAG_MAPPING.get(tool_id, []):
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def expand_ontology_data(
    tool_source: ToolSource, all_ids: List[str], biotools_metadata_source: Optional[BiotoolsMetadataSource]
) -> OntologyData:
    xrefs = tool_source.parse_xrefs()
    has_biotools_reference = any(x["type"] == "bio.tools" for x in xrefs)
    if not has_biotools_reference:
        for legacy_biotools_ref in legacy_biotools_external_reference(all_ids):
            if legacy_biotools_ref is not None:
                xrefs.append({"value": legacy_biotools_ref, "type": "bio.tools"})

    edam_operations = tool_source.parse_edam_operations()
    edam_topics = tool_source.parse_edam_topics()

    for tool_id in all_ids:
        if tool_id in EDAM_OPERATION_MAPPING:
            edam_operations = EDAM_OPERATION_MAPPING[tool_id]
            break

    for tool_id in all_ids:
        if tool_id in EDAM_TOPIC_MAPPING:
            edam_topics = EDAM_TOPIC_MAPPING[tool_id]
            break

    has_missing_data = len(edam_operations) == 0 or len(edam_topics) == 0
    if has_missing_data:
        biotools_reference_str = biotools_reference(xrefs)
        if biotools_reference_str and biotools_metadata_source:
            biotools_entry = biotools_metadata_source.get_biotools_metadata(biotools_reference_str)
            if biotools_entry:
                edam_info = biotools_entry.edam_info
                if len(edam_operations) == 0:
                    edam_operations = edam_info.edam_operations
                if len(edam_topics) == 0:
                    edam_topics = edam_info.edam_topics

    return OntologyData(
        xrefs,
        edam_operations,
        edam_topics,
        curated_tool_tags(all_ids),
    )
