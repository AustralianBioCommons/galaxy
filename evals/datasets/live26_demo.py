"""Live26 (GCC2026) demo dataset: rubric-graded content quality for the demo script.

These are the prompts we will actually type on stage at GCC2026 for the Live26
presentation (a histological staining quantification flow ending with an Omero
export). The routing decision for each prompt is scored in
``evals/datasets/routing.py`` under the ``live26_*`` names; this dataset scores
the substance of the response with an LLMJudge per-case rubric, regardless of
which downstream agent the router picks.

Pairs with the planning doc at:
https://docs.google.com/document/d/1-TuXZG-fVRjLDesR3NQFoenBDxJbf7Mt0Sqtokr4DQA

Notes:

- ``live26_import_iwc_workflow`` depends on the in-flight IWC operations on the
  ``agent-ops-iwc-reintroduce`` branch (``search_iwc_workflows``,
  ``import_workflow_from_iwc``). On this branch the case still runs and its
  rubric just measures how degraded the answer is without those tools -- useful
  as a "before" number to diff against once IWC ops merges.
- ``live26_history_sanity_check``, ``live26_summarize_to_page``,
  ``live26_report_takeaway``, and ``live26_social_media_post`` need a real
  Galaxy session because they presuppose specific results in the user's
  history. They carry ``requires_galaxy=True`` and are filtered out by
  default; pass ``--include-galaxy-required`` to include them. Note that
  the harness's MagicMock'd trans means these will still fail until
  real-Galaxy plumbing is added; the flag is forward-looking.
- ``live26_report_takeaway`` and ``live26_social_media_post`` don't have a
  pinned routing target yet (report-template editing isn't a dedicated agent
  and the social-post beat is borderline); they're content-only here.
"""

from typing import (
    Any,
    Optional,
)

from pydantic_ai.models import Model
from pydantic_evals import (
    Case,
    Dataset,
)
from pydantic_evals.evaluators import (
    LLMJudge,
    OutputConfig,
)

_PROTO_CASES: list[dict[str, Any]] = [
    {
        "name": "live26_stain_quantification_intro",
        "query": (
            "The datasets in my history are brightfield RGB images from a "
            "histological staining experiment. I'd like to quantify stain "
            "components from those images. What's a good way to do this?"
        ),
        "rubric": (
            "Response should orient a researcher who has brightfield RGB stain images:\n"
            "1. Identifies stain/color deconvolution as the relevant technique\n"
            "2. Names at least one concrete Galaxy-available approach: QuPath "
            "(interactive tool), Color Deconvolution, or an IWC workflow for "
            "histological staining quantification\n"
            "3. Suggests an ordered workflow: define regions of interest -> "
            "deconvolve / threshold -> quantify per-region area or intensity\n"
            "4. Optionally references the GTN -- the imaging topic has tutorials "
            "for histological staining and electrophoresis-gel quantification\n"
            "5. Does NOT hallucinate non-existent Galaxy tools (e.g. don't make "
            "up a 'StainQuant' tool); generic guidance is preferred over inventions"
        ),
        "requires_galaxy": False,
    },
    {
        "name": "live26_import_iwc_workflow",
        "query": "Import a histological staining workflow from IWC.",
        "rubric": (
            "Response should perform or describe importing an IWC workflow:\n"
            "1. Recognizes IWC as the Intergalactic Workflow Commission "
            "(workflow registry) and treats the request as an actionable import, "
            "not a how-to essay about visiting iwc.galaxyproject.org\n"
            "2. Either (a) confirms the import succeeded with a specific IWC "
            "workflow name/trsID, or (b) lists matching IWC workflows for the "
            "user to pick from -- both are acceptable\n"
            "3. Does NOT hallucinate a fake workflow id or URL\n"
            "4. If no histological-staining workflow is found, says so plainly "
            "rather than inventing one"
        ),
        "requires_galaxy": False,
    },
    {
        "name": "live26_omero_upload_guidance",
        "query": "How can I upload this data to Omero?",
        "rubric": (
            "Response should guide the user through Omero export from Galaxy:\n"
            "1. Mentions that Omero is treated as a file source / remote "
            "repository in Galaxy (not an arbitrary upload destination)\n"
            "2. Tells the user to configure their Omero credentials in their "
            "Galaxy user preferences / file sources before exporting\n"
            "3. Points at the right mechanism: an Omero export tool, or "
            "exporting via the configured Omero file source\n"
            "4. Does NOT invent tool names that don't exist in Galaxy's toolbox\n"
            "5. Acknowledges Omero is for persistent, shareable image storage "
            "(brief, not marketing-y)"
        ),
        "requires_galaxy": False,
    },
    {
        "name": "live26_history_sanity_check",
        "query": "Look at my history -- did I miss anything in this analysis?",
        "rubric": (
            "Response should perform a real sanity check on the user's history:\n"
            "1. References actual datasets present in the history (names, "
            "states), not generic placeholders\n"
            "2. Flags missing-but-expected steps for a histological staining "
            "quantification flow (e.g. ROI definition before quantification, "
            "color deconvolution before downstream analysis)\n"
            "3. Calls out any errored or failed jobs by name\n"
            "4. If everything looks complete, says so plainly rather than "
            "inventing problems"
        ),
        "requires_galaxy": True,
    },
    {
        "name": "live26_summarize_to_page",
        "query": "Summarize this analysis and save it as a Galaxy Page.",
        "rubric": (
            "Response should produce a publishable analysis summary:\n"
            "1. Describes the inputs, the analysis performed, and the key "
            "outputs in plain language\n"
            "2. References real dataset / workflow names from the history -- "
            "not generic stand-ins\n"
            "3. Confirms a Galaxy Page was created (or, if the operation is "
            "unsupported, says so plainly) -- does not pretend to save a Page "
            "that wasn't created\n"
            "4. Output is in a Page-appropriate format (sections, headings, "
            "links to datasets) rather than a one-line summary"
        ),
        "requires_galaxy": True,
    },
    {
        "name": "live26_custom_tool_quantify_brown",
        "query": "Generate a Galaxy tool that counts brown pixels in a TIFF image.",
        "rubric": (
            "Response should produce a working Galaxy tool wrapper in the "
            "GalaxyUserTool YAML schema (this is what the custom_tool agent "
            "emits -- not legacy XML):\n"
            "1. Valid YAML with required fields: class: GalaxyUserTool, id "
            "(lowercase-with-hyphens), version (semver), name, container "
            "(real biocontainer / quay.io image), and a shell_command using "
            "$(inputs.NAME.path) syntax\n"
            "2. inputs list has at least one entry with type: data and a "
            "TIFF-compatible format (e.g. format: tiff or format: [tiff])\n"
            "3. outputs list has at least one text/tabular entry (type: data "
            "with format: txt or tabular) -- not just a log message\n"
            "4. shell_command implements brown-pixel counting plausibly -- "
            "e.g. a Python or ImageMagick one-liner using a sensible brown "
            "threshold in RGB or HSV space\n"
            "5. No invented Galaxy framework features (only the documented "
            "input types data/text/integer/float/boolean/select)"
        ),
        "requires_galaxy": False,
    },
    {
        "name": "live26_report_takeaway",
        "query": (
            "Add a short take-away message to the workflow report summarizing "
            "what the staining quantification results show."
        ),
        "rubric": (
            "Response should produce an interpretive summary:\n"
            "1. Reads like a one-paragraph take-away a domain scientist would "
            "write -- comparative, plain-language\n"
            "2. Does NOT fabricate specific numeric values; either uses "
            "placeholders or references the actual output table\n"
            "3. Is appropriate to drop into a workflow report template (not a "
            "wall of caveats; not a multi-section essay)\n"
            "4. Suggests where the take-away should go in the report (top, "
            "after the results table, etc.) OR returns it in a form that can "
            "be inserted directly"
        ),
        "requires_galaxy": True,
    },
    {
        "name": "live26_social_media_post",
        "query": "Can you summarize my analysis in a couple of sentences I can share?",
        "rubric": (
            "Response should produce a publishable short summary:\n"
            "1. Under ~280 characters or a couple of short sentences -- not a "
            "blog post or a wall of caveats\n"
            "2. Names the analysis topic (histological staining quantification) "
            "concretely, grounded in what's actually in the history\n"
            "3. Reads like something a researcher would post, not marketing copy\n"
            "4. Doesn't fabricate a specific result number; placeholders or "
            "real values from the history are both fine"
        ),
        "requires_galaxy": True,
    },
]


_RUBRIC_TEMPLATE = """\
You are evaluating a Galaxy AI agent's response to a prompt from the Live26
(GCC2026) demo script. The demo is a histological staining quantification flow.

Acceptance rubric for this case:
{rubric}

Score the response between 0.0 and 1.0:
- 1.0: Excellent, comprehensive, accurate response covering all key points
- 0.7-0.9: Good response covering most key points with minor gaps
- 0.5-0.7: Adequate response but missing some important points
- < 0.5: Poor response with major gaps, hallucinations, or inaccuracies

Return a number; no commentary.
"""


def live26_demo_dataset(
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> Dataset[str, str, dict[str, Any]]:
    """Build the live26_demo Dataset.

    Requires ``judge_model`` to score; without it the dataset has no
    evaluators and cases will report no scores.
    """
    cases: list[Case[str, str, dict[str, Any]]] = []
    for proto in _PROTO_CASES:
        if only and proto["name"] not in only:
            continue
        if not include_galaxy_required and proto.get("requires_galaxy"):
            continue
        evaluators: tuple = ()
        if judge_model is not None:
            rubric = _RUBRIC_TEMPLATE.format(rubric=proto["rubric"])
            evaluators = (
                LLMJudge(
                    rubric=rubric,
                    model=judge_model,
                    include_input=True,
                    score=OutputConfig(evaluation_name="LLMJudge"),
                    assertion=False,
                ),
            )
        cases.append(
            Case(
                name=proto["name"],
                inputs=proto["query"],
                expected_output=None,
                metadata={
                    "rubric": proto["rubric"],
                    "requires_galaxy": proto.get("requires_galaxy", False),
                },
                evaluators=evaluators,
            )
        )
    return Dataset(name="live26_demo", cases=cases)
