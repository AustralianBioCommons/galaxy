import pytest

from galaxy.tool_util.data import (
    DataTableColumnMismatch,
    DataTableFileConflict,
)

LOC_ALPHA_CONTENTS_V2 = """
data1	data1name	${__HERE__}/data1/entry.txt
data2	data2name	${__HERE__}/data2/entry.txt
data3	data3name	${__HERE__}/data3/entry.txt
"""

CONFLICTING_TABLE_CONF_XML = """<tables>
  <table name="other_table" comment_char="#">
    <columns>value, name, path</columns>
    <file path="{loc_path}" />
  </table>
</tables>
"""

COLUMN_DIVERGENT_TABLE_CONF_XML = """<tables>
  <table name="testalpha" comment_char="#">
    <columns>value, name, path, extra</columns>
    <file path="{loc_path}" />
  </table>
</tables>
"""


def test_data_tables_as_dictionary(tdt_manager):
    assert "testalpha" in tdt_manager.data_tables
    assert "testdelta" not in tdt_manager.data_tables


def test_to_dict(tdt_manager):
    as_dict = tdt_manager.to_dict()
    assert "testalpha" in as_dict
    assert "testdelta" not in as_dict
    testalpha_as_dict = as_dict["testalpha"]
    assert "columns" in testalpha_as_dict


def test_index(tdt_manager):
    index = tdt_manager.index()
    assert len(index.root) >= 1
    entry = index.find_entry("testalpha")
    assert entry
    entry = index.find_entry("testomega")
    assert not entry


def test_reload(tdt_manager, tmp_path):
    assert len(tdt_manager["testalpha"].data) == 2
    loc1 = tmp_path / "testalpha.loc"
    loc1.write_text(LOC_ALPHA_CONTENTS_V2)
    tdt_manager.reload_tables()
    assert len(tdt_manager["testalpha"].data) == 3


def test_reload_by_path(tdt_manager, tmp_path):
    assert len(tdt_manager["testalpha"].data) == 2
    loc1 = tmp_path / "testalpha.loc"
    loc1.write_text(LOC_ALPHA_CONTENTS_V2)
    tdt_manager.reload_tables(path=str(loc1))
    assert len(tdt_manager["testalpha"].data) == 3


def test_reload_by_name(tdt_manager, tmp_path):
    assert len(tdt_manager["testalpha"].data) == 2
    loc1 = tmp_path / "testalpha.loc"
    loc1.write_text(LOC_ALPHA_CONTENTS_V2)
    tdt_manager.reload_tables("testalpha")
    assert len(tdt_manager["testalpha"].data) == 3


def test_merging_tables(merged_tdt_manager):
    assert len(merged_tdt_manager["testbeta"].data) == 2


def test_to_json(merged_tdt_manager, tmp_path):
    json_path = tmp_path / "as_json.json"
    assert not json_path.exists()
    merged_tdt_manager.to_json(json_path)
    assert json_path.exists()


def test_assert_data_table_consistency_accepts_new_table(tdt_manager, tmp_path):
    tdt_manager.assert_data_table_consistency(
        "brand_new_table",
        {"value": 0, "name": 1, "path": 2},
        [str(tmp_path / "brand_new_table.loc")],
    )


def test_assert_data_table_consistency_accepts_matching_redefinition(tdt_manager, tmp_path):
    existing = tdt_manager["testalpha"]
    tdt_manager.assert_data_table_consistency(
        "testalpha",
        existing.columns,
        list(existing.filenames),
    )


def test_assert_data_table_consistency_raises_column_mismatch(tdt_manager, tmp_path):
    with pytest.raises(DataTableColumnMismatch) as exc_info:
        tdt_manager.assert_data_table_consistency(
            "testalpha",
            {"value": 0, "name": 1, "path": 2, "extra": 3},
            [str(tmp_path / "testalpha.loc")],
        )
    assert exc_info.value.table_name == "testalpha"


def test_assert_data_table_consistency_raises_file_conflict(tdt_manager, tmp_path):
    shared_loc = str(tmp_path / "testalpha.loc")
    with pytest.raises(DataTableFileConflict) as exc_info:
        tdt_manager.assert_data_table_consistency(
            "other_table",
            {"value": 0, "name": 1, "path": 2},
            [shared_loc],
        )
    assert exc_info.value.candidate_name == "other_table"
    assert exc_info.value.existing_name == "testalpha"


def test_load_from_config_file_raises_on_file_path_conflict(tdt_manager, tmp_path):
    conflicting_conf = tmp_path / "conflict.xml"
    conflicting_conf.write_text(CONFLICTING_TABLE_CONF_XML.format(loc_path=str(tmp_path / "testalpha.loc")))
    with pytest.raises(DataTableFileConflict):
        tdt_manager.load_from_config_file(str(conflicting_conf), str(tmp_path), from_shed_config=True)


def test_load_from_config_file_raises_on_column_mismatch_same_name(tdt_manager, tmp_path):
    column_conflict_conf = tmp_path / "column_conflict.xml"
    column_conflict_conf.write_text(COLUMN_DIVERGENT_TABLE_CONF_XML.format(loc_path=str(tmp_path / "testalpha.loc")))
    with pytest.raises(DataTableColumnMismatch):
        tdt_manager.load_from_config_file(str(column_conflict_conf), str(tmp_path), from_shed_config=True)
