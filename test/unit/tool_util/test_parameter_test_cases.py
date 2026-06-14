import os
import re
from typing import (
    Any,
    List,
    Optional,
    Tuple,
)

from galaxy.tool_util.model_factory import parse_tool
from galaxy.tool_util.parameters import (
    DataCollectionRequest,
    DataRequestHda,
    encode_test,
    input_models_for_tool_source,
)
from galaxy.tool_util.parameters.case import (
    test_case_state as case_state,
    TestCaseStateAndWarnings,
    TestCaseStateValidationResult,
    validate_test_cases_for_tool_source,
)
from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.parser.interface import (
    ToolSource,
    ToolSourceTest,
)
from galaxy.tool_util.unittest_utils import (
    functional_test_tool_directory,
    functional_test_tool_source,
)
from galaxy.tool_util.verify.parse import parse_tool_test_descriptions
from galaxy.tool_util_models.tool_source import (
    JsonTestCollectionDefDict,
    JsonTestDatasetDefDict,
)
from galaxy.util.permutations import is_in_state
from .util import dict_verify_each

# legacy tools allows specifying parameter and repeat parameters without
# qualification. This was problematic and could result in ambigious specifications.
TOOLS_THAT_USE_UNQUALIFIED_PARAMETER_ACCESS = [
    "boolean_conditional.xml",
    "simple_constructs.xml",
    "disambiguate_cond.xml",
    "multi_repeats.xml",
    "implicit_default_conds.xml",
]

TOOLS_THAT_USE_SELECT_BY_VALUE = [
    "multi_select.xml",
]

# Figure out the problem and resolve.
TOOLS_THAT_ARE_OUTSTANDING_ISSUES = [
    "gx_conditional_boolean_optional.xml",
    "gx_conditional_boolean_discriminate_on_string_value.xml",
]

TEST_TOOL_THAT_DO_NOT_VALIDATE = (
    TOOLS_THAT_USE_UNQUALIFIED_PARAMETER_ACCESS
    + TOOLS_THAT_USE_SELECT_BY_VALUE
    + TOOLS_THAT_ARE_OUTSTANDING_ISSUES
    + [
        # will never handle upload_dataset
        "upload.xml",
    ]
)

MOCK_ID = "thisisafakeid"


def test_parameter_test_cases_validate():
    validation_result = validate_test_cases_for("column_param")
    assert len(validation_result[0].warnings) == 0
    assert len(validation_result[1].warnings) == 0
    assert len(validation_result[2].warnings) == 1

    validation_result = validate_test_cases_for("column_param", use_latest_profile=True)
    assert validation_result[2].validation_error


def test_legacy_features_fail_validation_with_24_2(tmp_path):
    for filename in TOOLS_THAT_USE_UNQUALIFIED_PARAMETER_ACCESS:
        _assert_tool_test_parsing_only_fails_with_newer_profile(tmp_path, filename, index=None)

    # column parameters need to be indexes
    _assert_tool_test_parsing_only_fails_with_newer_profile(tmp_path, "column_param.xml", index=2)

    # selection by value only
    _assert_tool_test_parsing_only_fails_with_newer_profile(tmp_path, "multi_select.xml", index=1)


def _assert_tool_test_parsing_only_fails_with_newer_profile(tmp_path, filename: str, index: Optional[int] = 0):
    test_tool_directory = functional_test_tool_directory()
    original_path = os.path.join(test_tool_directory, filename)
    new_path = tmp_path / filename
    with open(original_path) as rf:
        tool_contents = rf.read()
        tool_contents = re.sub(r'profile="[\d\.]*"', r"", tool_contents)
        new_profile_contents = tool_contents.replace("<tool ", '<tool profile="24.2" ', 1)
    with open(new_path, "w") as wf:
        wf.write(new_profile_contents)
    test_cases = list(parse_tool_test_descriptions(get_tool_source(original_path)))
    if index is not None:
        assert test_cases[index].to_dict()["error"] is False
    else:
        # just make sure there is at least one failure...
        assert not any(c.to_dict()["error"] is True for c in test_cases)

    test_cases = list(parse_tool_test_descriptions(get_tool_source(new_path)))
    if index is not None:
        assert (
            test_cases[index].to_dict()["error"] is True
        ), f"expected {filename} to have validation failure preventing loading of tools"
    else:
        assert any(c.to_dict()["error"] is True for c in test_cases)


def test_validate_framework_test_tools():
    test_tool_directory = functional_test_tool_directory()
    parameter_tool_directory = os.path.join(test_tool_directory, "parameters")
    for test_directory in [test_tool_directory, parameter_tool_directory]:
        for tool_name in os.listdir(test_directory):
            if tool_name in TEST_TOOL_THAT_DO_NOT_VALIDATE:
                continue
            if tool_name.endswith("_conf.xml") or tool_name == "macros.xml":
                # tool conf (toolbox) files or sample datatypes
                continue
            tool_path = os.path.join(test_directory, tool_name)
            if not (tool_path.endswith(".xml") or tool_path.endswith(".yml")) or os.path.isdir(tool_path):
                continue

            try:
                _validate_path(tool_path)
            except Exception as e:
                raise Exception(f"Failed to validate {tool_path}: {str(e)}")


def test_test_case_state_conversion():
    tool_source = tool_source_for("collection_nested_test")
    test_cases: List[ToolSourceTest] = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations: List[Tuple[List[Any], Optional[Any]]]
    expectations = [
        (["f1", "collection_type"], "list:paired"),
        (["f1", "class"], "Collection"),
        (["f1", "elements", 0, "class"], "Collection"),
        (["f1", "elements", 0, "collection_type"], "paired"),
        (["f1", "elements", 0, "elements", 0, "class"], "File"),
        (["f1", "elements", 0, "elements", 0, "path"], "simple_line.txt"),
        (["f1", "elements", 0, "elements", 0, "identifier"], "forward"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    tool_source = tool_source_for("dbkey_filter_input")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations = [
        (["inputs", "class"], "File"),
        (["inputs", "dbkey"], "hg19"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    tool_source = tool_source_for("discover_metadata_files")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations = [
        (["input_bam", "class"], "File"),
        (["input_bam", "filetype"], "bam"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    tool_source = tool_source_for("remote_test_data_location")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations = [
        (["input", "class"], "File"),
        (
            ["input", "location"],
            "https://raw.githubusercontent.com/galaxyproject/planemo/7be1bf5b3971a43eaa73f483125bfb8cabf1c440/tests/data/hello.txt",
        ),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    tool_source = tool_source_for("composite")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations = [
        (["input", "class"], "File"),
        (["input", "filetype"], "velvet"),
        (["input", "composite_data", 0], "velveth_test1/Sequences"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    tool_source = tool_source_for("parameters/gx_group_tag")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[0])
    expectations = [
        (["ref_parameter", "class"], "Collection"),
        (["ref_parameter", "collection_type"], "paired"),
        (["ref_parameter", "elements", 0, "identifier"], "forward"),
        (["ref_parameter", "elements", 0, "tags", 0], "group:type:single"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    index = 2
    tool_source = tool_source_for("filter_param_value_ref_attribute")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[index])
    expectations = [
        (["data_mult", 0, "path"], "1.bed"),
        (["data_mult", 0, "dbkey"], "hg19"),
        (["data_mult", 1, "path"], "2.bed"),
        (["data_mult", 0, "dbkey"], "hg19"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    index = 1
    tool_source = tool_source_for("expression_pick_larger_file")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[index])
    expectations = [
        (["input1", "path"], "simple_line_alternative.txt"),
        (["input2"], None),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    index = 2
    state = case_state_for(tool_source, test_cases[index])
    expectations = [
        (["input1"], None),
        (["input2", "path"], "simple_line.txt"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    index = 0
    tool_source = tool_source_for("composite_shapefile")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[index])
    expectations = [
        (["input", "filetype"], "shp"),
        (["input", "composite_data", 0], "shapefile/shapefile.shp"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)

    index = 0
    tool_source = tool_source_for("simple_constructs_y")
    test_cases = tool_source.parse_tests_to_dict()["tests"]
    state = case_state_for(tool_source, test_cases[index])
    expectations = [
        (["booltest"], True),
        (["simp_file", "path"], "simple_line.txt"),
        (["more_files", 0, "nestinput", "path"], "simple_line_alternative.txt"),
    ]
    dict_verify_each(state.tool_state.input_state, expectations)


def test_is_in_state_supports_nested_keys():
    state = {
        "section": {
            "parameter": "value",
        },
    }

    assert is_in_state(state, "section|parameter", nested=True)
    assert not is_in_state(state, "section|missing", nested=True)




def test_test_case_request_conversion_preserves_non_default_select_and_booleans():
    tool_source = raw_xml_tool_source(
        """
<tool id="async_request_regression" name="async_request_regression" version="1.0.0">
    <command>echo</command>
    <inputs>
        <param name="output_type" type="select">
            <option value="meta" selected="true">MetaBAT2</option>
            <option value="semi">SemiBin2</option>
        </param>
        <param name="full_contig_name" type="boolean" truevalue="--full-contig-name" falsevalue="" />
        <section name="advanced_settings" expanded="false">
            <param name="method" type="select">
                <option value="hybrid" selected="true">Hybrid</option>
                <option value="wgs">WGS</option>
            </param>
            <param name="remove_identical_sequences" type="boolean" truevalue="-d" falsevalue="" />
        </section>
    </inputs>
    <outputs />
    <tests>
        <test>
            <param name="output_type" value="semi" />
            <param name="full_contig_name" value="true" />
            <section name="advanced_settings">
                <param name="method" value="wgs" />
                <param name="remove_identical_sequences" value="true" />
            </section>
        </test>
    </tests>
</tool>
        """
    )
    parameters = input_models_for_tool_source(tool_source)
    parsed_tool = parse_tool(tool_source)
    test_case = tool_source.parse_tests_to_dict()["tests"][0]
    test_case_state = case_state(test_case, parsed_tool.inputs, tool_source.parse_profile()).tool_state

    request_state = encode_test(test_case_state, parameters, mock_adapt_datasets, mock_adapt_collections)

    expectations = [
        (["output_type"], "semi"),
        (["full_contig_name"], True),
        (["advanced_settings", "method"], "wgs"),
        (["advanced_settings", "remove_identical_sequences"], True),
    ]
    dict_verify_each(request_state.input_state, expectations)


def test_nested_conditional_duplicate_short_names_are_distinct_when_qualified():
    tool_source = raw_xml_tool_source(
        """
<tool id="duplicate_use_regression" name="duplicate_use_regression" version="1.0.0">
    <command>echo</command>
    <inputs>
        <conditional name="operation">
            <param name="use" type="select">
                <option value="droplets" selected="true">Droplets</option>
                <option value="other">Other</option>
            </param>
            <when value="droplets">
                <conditional name="method">
                    <param name="use" type="select">
                        <option value="default" selected="true">Default</option>
                        <option value="expected">Expected</option>
                    </param>
                    <when value="default" />
                    <when value="expected">
                        <param name="expected" type="integer" value="1000" />
                    </when>
                </conditional>
            </when>
            <when value="other" />
        </conditional>
    </inputs>
    <outputs />
    <tests>
        <test>
            <conditional name="operation">
                <param name="use" value="droplets" />
                <conditional name="method">
                    <param name="use" value="expected" />
                    <param name="expected" value="2000" />
                </conditional>
            </conditional>
        </test>
    </tests>
</tool>
        """
    )
    parsed_tool = parse_tool(tool_source)
    test_case = tool_source.parse_tests_to_dict()["tests"][0]

    tool_state = case_state(test_case, parsed_tool.inputs, tool_source.parse_profile()).tool_state

    expectations = [
        (["operation", "use"], "droplets"),
        (["operation", "method", "use"], "expected"),
        (["operation", "method", "expected"], 2000),
    ]
    dict_verify_each(tool_state.input_state, expectations)


def test_convert_to_requests():
    tools = [
        "parameters/gx_drill_down_recurse_multiple",
        "parameters/gx_conditional_select",
        "expression_pick_larger_file",
        "identifier_in_conditional",
        "column_param_list",
        "composite_shapefile",
    ]
    for tool_path in tools:
        tool_source = tool_source_for(tool_path)
        parameters = input_models_for_tool_source(tool_source)
        parsed_tool = parse_tool(tool_source)
        profile = tool_source.parse_profile()
        test_cases: List[ToolSourceTest] = tool_source.parse_tests_to_dict()["tests"]

        def mock_adapt_datasets(input: JsonTestDatasetDefDict) -> DataRequestHda:
            return DataRequestHda(src="hda", id=MOCK_ID)

        def mock_adapt_collections(input: JsonTestCollectionDefDict) -> DataCollectionRequest:
            return DataCollectionRequest(src="hdca", id=MOCK_ID)

        for test_case in test_cases:
            if test_case.get("expect_failure"):
                continue
            test_case_state_and_warnings = case_state(test_case, parsed_tool.inputs, profile)
            test_case_state = test_case_state_and_warnings.tool_state

            encode_test(test_case_state, parameters, mock_adapt_datasets, mock_adapt_collections)


def _validate_path(tool_path: str):
    tool_source = get_tool_source(tool_path)

    tool_source_class = type(tool_source).__name__
    raw_tool_source = tool_source.to_string()
    tool_source = get_tool_source(tool_source_class=tool_source_class, raw_tool_source=raw_tool_source)

    tool_id = tool_source.parse_id()
    model_name = f"{tool_id} (test case model)"
    parsed_tool = parse_tool(tool_source)
    profile = tool_source.parse_profile()
    test_cases: List[ToolSourceTest] = tool_source.parse_tests_to_dict()["tests"]
    for test_case in test_cases:
        if test_case.get("expect_failure"):
            continue
        test_case_state_and_warnings = case_state(test_case, parsed_tool.inputs, profile, name=model_name)
        tool_state = test_case_state_and_warnings.tool_state
        assert tool_state.state_representation == "test_case_xml"


def validate_test_cases_for(tool_name: str, **kwd) -> List[TestCaseStateValidationResult]:
    return validate_test_cases_for_tool_source(tool_source_for(tool_name), **kwd)


def case_state_for(tool_source: ToolSource, test_case: ToolSourceTest) -> TestCaseStateAndWarnings:
    parsed_tool = parse_tool(tool_source)
    profile = tool_source.parse_profile()
    return case_state(test_case, parsed_tool.inputs, profile)


def raw_xml_tool_source(raw_tool_source: str) -> ToolSource:
    return get_tool_source(tool_source_class="XmlToolSource", raw_tool_source=raw_tool_source)


def mock_adapt_datasets(input: JsonTestDatasetDefDict) -> DataRequestHda:
    return DataRequestHda(src="hda", id=MOCK_ID)


def mock_adapt_collections(input: JsonTestCollectionDefDict) -> DataCollectionRequest:
    return DataCollectionRequest(src="hdca", id=MOCK_ID)


tool_source_for = functional_test_tool_source
