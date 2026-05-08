# Galaxy agent evals -- 2026-05-08

_Generated 2026-05-08T12:16:24 from `db9b1cb0799`._

## bioinformatics_workflows

| metric                | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| --------------------- | ---------------------------------- | --------------------------- | ------------ |
| LLMJudge              | 1/8                                | 0/8                         | 4/8          |
| median latency (s)    | 28.20                              | 3.88                        | 13.58        |
| total tokens (in/out) | 21504/2846                         | 25891/426                   | 29753/9784   |
| est. cost ($)         | 0.0128                             | 0.0160                      | 0.0000       |

### Per-case detail

| case                                | Llama-4-Maverick-17B-128E-Instruct                                     | Meta-Llama-3.3-70B-Instruct                                            | gpt-oss-120b                                                         |
| ----------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| scrna_cell_type_identification      | WRONG (The history with ID 0 is empty, containing no datasets. To d)   | WRONG (The dataset is not ready, so we cannot peek at its content. )   | WRONG (**Why these tools?** I attempted multiple searches for tools) |
| bulk_rnaseq_differential_expression | WRONG (**Why these tools?** No tools for differential gene expressi)   | WRONG (**Why these tools?** No tools found matching 'differential e)   | OK (judge 1.00)                                                      |
| qc_triage_fastqc                    | OK (judge 0.80)                                                        | WRONG (**Error Type**: Data Quality **Severity**: Medium \*\*Likely C) | OK (judge 0.90)                                                      |
| low_mapping_rate_troubleshooting    | WRONG (**Error Type**: Mapping Issue **Severity**: Warning \*\*Likely) | WRONG (**Error Type**: Mapping Error **Severity**: Medium \*\*Likely ) | WRONG (A ≈ 50 % mapping rate is lower than you’d normally expect fo) |
| metagenomics_community_composition  | WRONG (**Why these tools?** No metagenomics analysis tools were fou)   | WRONG (To figure out what organisms are present and their relative )   | OK (judge 1.00)                                                      |
| somatic_variant_calling             | WRONG (**Why these tools?** No tools matching 'somatic variant call)   | WRONG (**Why these tools?** No tools found matching 'somatic varian)   | WRONG (**Why these tools?** I attempted multiple searches for commo) |
| general_onboarding_guidance         | WRONG (It looks like your history is empty. Let's start fresh! Sinc)   | WRONG (It seems like you don't have any existing histories in Galax)   | OK (judge 1.00)                                                      |
| coverage_anomalies_artifacts        | WRONG (To determine whether huge coverage spikes and gaps are real )   | WRONG (The functions provided do not enable me to answer these ques)   | WRONG (It looks like there are no Galaxy histories associated with ) |

## orchestrator_planning

| metric                   | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------------ | ---------------------------------- | --------------------------- | ------------ |
| OrchestratorPlanIncludes | 3/3                                | 3/3                         | 2/3          |
| median latency (s)       | 30.85                              | 5.29                        | 15.49        |
| total tokens (in/out)    | 0/0                                | 0/0                         | 3294/2362    |
| est. cost ($)            | 0.0000                             | 0.0000                      | 0.0000       |

### Per-case detail

| case                   | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b                                        |
| ---------------------- | ---------------------------------- | --------------------------- | --------------------------------------------------- |
| find_failed_job        | OK                                 | OK                          | OK                                                  |
| next_step_advice       | OK                                 | OK                          | OK                                                  |
| workflow_design_rnaseq | OK                                 | OK                          | WRONG ({'agent_type': 'router', 'agents_used': []}) |

## tool_recommendation

| metric                | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| --------------------- | ---------------------------------- | --------------------------- | ------------ |
| MustMentionAny        | 7/10                               | 2/10                        | 9/10         |
| LLMJudge              | 3/10                               | 2/10                        | 2/10         |
| median latency (s)    | 22.08                              | 2.71                        | 6.12         |
| total tokens (in/out) | 47314/3377                         | 23867/947                   | 68262/7239   |
| est. cost ($)         | 0.0237                             | 0.0155                      | 0.0000       |

### Per-case detail

| case                       | Llama-4-Maverick-17B-128E-Instruct                                   | Meta-Llama-3.3-70B-Instruct                                          | gpt-oss-120b    |
| -------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- | --------------- |
| rnaseq_alignment           | OK (judge 0.00)                                                      | WRONG (**Why these tools?** No tools found matching 'RNA-seq read a) | OK (judge 0.00) |
| dna_short_read_alignment   | WRONG (**Why these tools?** No alignment or variant calling tools f) | WRONG (**Why these tools?** No tools found matching 'alignment Illu) | OK (judge 0.00) |
| fastq_quality_control      | WRONG (**Why these tools?** No FASTQ quality control tools were fou) | WRONG (**Why these tools?** No tools found matching 'FASTQ quality ) | OK (judge 1.00) |
| adapter_trimming           | OK (judge 1.00)                                                      | WRONG (**Why these tools?** No tools found matching 'trim adapters') | OK (judge 0.00) |
| variant_calling_germline   | WRONG (**Why these tools?** No variant calling tools were found on ) | ERROR                                                                | OK (judge 0.00) |
| differential_expression    | OK (judge 0.00)                                                      | OK (judge 1.00)                                                      | OK (judge 1.00) |
| peak_calling_chipseq       | OK (judge 1.00)                                                      | WRONG (**Why these tools?** No tools found matching 'peak calling C) | OK (judge 0.00) |
| 16s_taxonomy               | OK (judge 0.00)                                                      | WRONG (**Why these tools?** No tools found matching '16S rRNA ampli) | OK (judge 0.00) |
| bam_sort_index             | OK (judge 1.00)                                                      | OK (judge 1.00)                                                      | OK (judge 0.00) |
| ambiguous_what_tools_exist | OK (judge 0.00)                                                      | ERROR                                                                | ERROR           |

## router_tool_use

| metric                | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| --------------------- | ---------------------------------- | --------------------------- | ------------ |
| ToolCallMatch         | 8/10                               | 9/10                        | 10/10        |
| median latency (s)    | 3.87                               | 4.20                        | 1.85         |
| total tokens (in/out) | 67989/545                          | 76343/331                   | 66005/2513   |
| est. cost ($)         | 0.0274                             | 0.0462                      | 0.0000       |

### Per-case detail

| case                         | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ---------------------------- | ---------------------------------- | --------------------------- | ------------ |
| neoform_what_tools_installed | OK                                 | OK                          | OK           |
| show_trim_adapter_tools      | OK                                 | OK                          | OK           |
| rnaseq_workflow_available    | OK                                 | OK                          | OK           |
| list_my_workflows            | OK                                 | OK                          | OK           |
| what_histories_do_i_have     | OK                                 | OK                          | OK           |
| galaxy_version               | OK                                 | OK                          | OK           |
| who_am_i                     | OK                                 | OK                          | OK           |
| am_i_admin                   | OK                                 | OK                          | OK           |
| is_fastqc_installed          | ERROR                              | OK                          | OK           |
| do_we_have_bwa               | ERROR                              | ERROR                       | OK           |
