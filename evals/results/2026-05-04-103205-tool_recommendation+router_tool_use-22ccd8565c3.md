# Galaxy agent evals -- 2026-05-04

_Generated 2026-05-04T10:32:04 from `22ccd8565c3`._

## tool_recommendation

| metric             | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------ | ---------------------------------- | --------------------------- | ------------ |
| MustMentionAny     | 7/10                               | 7/10                        | 10/10        |
| LLMJudge           | 3/10                               | 5/10                        | 1/10         |
| median latency (s) | 6.97                               | 2.00                        | 5.63         |

### Per-case detail

| case                       | Llama-4-Maverick-17B-128E-Instruct                                   | Meta-Llama-3.3-70B-Instruct                                          | gpt-oss-120b    |
| -------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- | --------------- |
| rnaseq_alignment           | WRONG (**Why these tools?** No RNA-seq alignment tools found on thi) | OK (judge 1.00)                                                      | OK (judge 0.00) |
| dna_short_read_alignment   | OK (judge 0.00)                                                      | OK (judge 0.00)                                                      | OK (judge 0.00) |
| fastq_quality_control      | OK (judge 1.00)                                                      | WRONG (**Why these tools?** No tools found matching 'FASTQ quality ) | OK (judge 0.50) |
| adapter_trimming           | OK (judge 0.00)                                                      | OK (judge 1.00)                                                      | OK (judge 0.00) |
| variant_calling_germline   | OK (judge 0.00)                                                      | WRONG (**Why these tools?** No tools found matching 'germline SNP a) | OK (judge 0.50) |
| differential_expression    | OK (judge 1.00)                                                      | OK (judge 1.00)                                                      | OK (judge 0.00) |
| peak_calling_chipseq       | OK (judge 1.00)                                                      | OK (judge 1.00)                                                      | OK (judge 1.00) |
| 16s_taxonomy               | WRONG (**Recommended Tools:** 1. **nb_classifier** (ID: `toolshed.g) | OK (judge 0.00)                                                      | OK (judge 0.00) |
| bam_sort_index             | WRONG (**Why these tools?** No suitable tools found for sorting and) | OK (judge 1.00)                                                      | OK (judge 0.00) |
| ambiguous_what_tools_exist | OK (judge 0.00)                                                      | ERROR                                                                | OK (judge 0.00) |

## router_tool_use

| metric             | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------ | ---------------------------------- | --------------------------- | ------------ |
| ToolCallMatch      | 10/10                              | 9/10                        | 10/10        |
| median latency (s) | 3.00                               | 3.41                        | 1.86         |

### Per-case detail

| case                         | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ---------------------------- | ---------------------------------- | --------------------------- | ------------ |
| neoform_what_tools_installed | OK                                 | OK                          | OK           |
| is_fastqc_installed          | OK                                 | OK                          | OK           |
| do_we_have_bwa               | OK                                 | ERROR                       | OK           |
| show_trim_adapter_tools      | OK                                 | OK                          | OK           |
| rnaseq_workflow_available    | OK                                 | OK                          | OK           |
| list_my_workflows            | OK                                 | OK                          | OK           |
| what_histories_do_i_have     | OK                                 | OK                          | OK           |
| galaxy_version               | OK                                 | OK                          | OK           |
| who_am_i                     | OK                                 | OK                          | OK           |
| am_i_admin                   | OK                                 | OK                          | OK           |
