"""Unit tests for shed-side data table install behavior."""

import os
from unittest import mock

import pytest

from galaxy.tool_shed.tools.data_table_manager import (
    DataTableColumnMismatch,
    DataTableFileConflict,
    ShedToolDataTableManager,
)
from galaxy.tool_util.data import ToolDataTableManager
from galaxy.util import (
    Element,
    SubElement,
)


class _FakeTableRegistry(ToolDataTableManager):
    def __init__(self):
        self.data_tables: dict = {}
        self.to_xml_calls: list = []

    def to_xml_file(self, shed_tool_data_table_config, new_elems=None, remove_elems=None):
        self.to_xml_calls.append((shed_tool_data_table_config, new_elems))
        with open(shed_tool_data_table_config, "wb") as fh:
            fh.write(b"<tables/>")


SAMPLE_TABLE_CONF = """\
<tables>
    <table name="all_fasta" comment_char="#">
        <columns>value, dbkey, name, path</columns>
        <file path="tool-data/all_fasta.loc" />
    </table>
</tables>
"""

LOC_SAMPLE_CONTENT = "# all_fasta.loc sample\n"


def _write(path: str, contents: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(contents)


def _make_stdtm(tmp_path):
    repo_dir = str(tmp_path / "repo")
    tool_data_path = str(tmp_path / "tool-data")
    shed_tool_data_path = str(tmp_path / "shed_tool_data")
    relative_target_dir = "owner/name/abc"

    os.makedirs(tool_data_path)
    os.makedirs(os.path.join(shed_tool_data_path, relative_target_dir))
    _write(os.path.join(repo_dir, "tool_data_table_conf.xml.sample"), SAMPLE_TABLE_CONF)
    _write(os.path.join(repo_dir, "tool-data", "all_fasta.loc.sample"), LOC_SAMPLE_CONTENT)

    app = mock.MagicMock(name="app")
    app.config.tool_data_path = tool_data_path
    app.config.shed_tool_data_path = shed_tool_data_path
    registry = _FakeTableRegistry()
    app.tool_data_tables = registry
    captured = {"to_xml_calls": registry.to_xml_calls}

    stdtm = ShedToolDataTableManager(app)

    repo = mock.MagicMock(name="tool_shed_repository")
    repo.name = "data_manager_fetch_genome_dbkeys_all_fasta"
    repo.owner = "iuc"
    repo.installed_changeset_revision = "abc"
    repo.tool_shed = "tool-shed"
    repo.get_tool_relative_path.return_value = (repo_dir, relative_target_dir)

    sample_files = [
        "tool_data_table_conf.xml.sample",
        os.path.join("tool-data", "all_fasta.loc.sample"),
    ]
    return stdtm, repo, sample_files, captured, tool_data_path, shed_tool_data_path, relative_target_dir


def _registered_table(columns, filenames=None):
    existing = mock.MagicMock(spec=["columns", "filenames"])
    existing.columns = columns
    existing.filenames = filenames or {}
    return existing


def test_loc_file_lands_at_shared_root_not_per_revision(tmp_path):
    stdtm, repo, samples, captured, tool_data_path, shed_tool_data_path, _ = _make_stdtm(tmp_path)
    _, kept_elems = stdtm.install_tool_data_tables(repo, samples)

    shared_loc = os.path.join(tool_data_path, "all_fasta.loc")
    assert os.path.exists(shared_loc)
    per_rev_loc = os.path.join(shed_tool_data_path, "owner/name/abc", "all_fasta.loc")
    assert not os.path.exists(per_rev_loc)

    assert len(kept_elems) == 1
    file_elems = list(kept_elems[0].findall("file"))
    assert len(file_elems) == 1
    assert file_elems[0].get("path") == shared_loc


def test_existing_loc_file_is_not_overwritten(tmp_path):
    stdtm, repo, samples, _, tool_data_path, _, _ = _make_stdtm(tmp_path)
    shared_loc = os.path.join(tool_data_path, "all_fasta.loc")
    _write(shared_loc, "preexisting DM-populated content\n")

    stdtm.install_tool_data_tables(repo, samples)

    with open(shared_loc) as fh:
        assert fh.read() == "preexisting DM-populated content\n"


def test_column_mismatch_raises(tmp_path):
    stdtm, repo, samples, captured, _, _, _ = _make_stdtm(tmp_path)
    stdtm.app.tool_data_tables.data_tables = {
        "all_fasta": _registered_table({"value": 0, "name": 1, "path": 2}),
    }

    with pytest.raises(DataTableColumnMismatch) as exc_info:
        stdtm.install_tool_data_tables(repo, samples)
    assert exc_info.value.table_name == "all_fasta"
    assert not captured["to_xml_calls"]


def test_column_match_dedupes_without_writing(tmp_path):
    stdtm, repo, samples, captured, _, _, _ = _make_stdtm(tmp_path)
    matching_columns = {"value": 0, "dbkey": 1, "name": 2, "path": 3}
    stdtm.app.tool_data_tables.data_tables = {
        "all_fasta": _registered_table(matching_columns),
    }

    _, kept_elems = stdtm.install_tool_data_tables(repo, samples)

    assert kept_elems == []
    assert not captured["to_xml_calls"]


def test_column_match_with_column_elements_dedupes(tmp_path):
    stdtm, repo, _, captured, _, _, _ = _make_stdtm(tmp_path)
    column_form_conf = """\
<tables>
    <table name="all_fasta" comment_char="#">
        <column name="value" index="0" />
        <column name="dbkey" index="1" />
        <column name="name" index="2" />
        <column name="path" index="3" />
        <file path="tool-data/all_fasta.loc" />
    </table>
</tables>
"""
    repo_dir, _ = repo.get_tool_relative_path.return_value
    _write(os.path.join(repo_dir, "tool_data_table_conf.xml.sample"), column_form_conf)
    stdtm.app.tool_data_tables.data_tables = {
        "all_fasta": _registered_table({"value": 0, "dbkey": 1, "name": 2, "path": 3}),
    }

    _, kept_elems = stdtm.install_tool_data_tables(
        repo,
        ["tool_data_table_conf.xml.sample", os.path.join("tool-data", "all_fasta.loc.sample")],
    )
    assert kept_elems == []


def test_file_path_conflict_raises(tmp_path):
    stdtm, repo, samples, captured, tool_data_path, _, _ = _make_stdtm(tmp_path)
    shared_loc = os.path.join(tool_data_path, "all_fasta.loc")
    stdtm.app.tool_data_tables.data_tables = {
        "other_table": _registered_table(
            {"value": 0, "name": 1},
            filenames={shared_loc: {"found": True}},
        ),
    }

    with pytest.raises(DataTableFileConflict) as exc_info:
        stdtm.install_tool_data_tables(repo, samples)
    assert exc_info.value.candidate_name == "all_fasta"
    assert exc_info.value.existing_name == "other_table"
    assert not captured["to_xml_calls"]


def test_parse_table_columns_aliases_name_to_value():
    from galaxy.tool_shed.tools.data_table_manager import _parse_table_columns

    elem = Element("table")
    cols = SubElement(elem, "columns")
    cols.text = "value, path"
    parsed = _parse_table_columns(elem)
    assert parsed == {"value": 0, "path": 1, "name": 0}
