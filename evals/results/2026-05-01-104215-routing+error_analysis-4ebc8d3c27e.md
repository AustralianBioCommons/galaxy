# Galaxy agent evals -- 2026-05-01

_Generated 2026-05-01T10:42:15 from `4ebc8d3c27e`._

## routing

| metric             | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------ | ---------------------------------- | --------------------------- | ------------ |
| HandoffMatch       | 15/20                              | 13/20                       | 16/20        |
| median latency (s) | 5.24                               | 3.93                        | 6.79         |

### Per-case detail

| case                      | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b         |
| ------------------------- | ---------------------------------- | --------------------------- | -------------------- |
| greeting                  | OK                                 | WRONG (orchestrator)        | OK                   |
| upload_basics             | OK                                 | WRONG (history)             | OK                   |
| tool_discovery_rnaseq     | OK                                 | OK                          | OK                   |
| citation                  | OK                                 | WRONG (history)             | OK                   |
| off_topic_weather         | OK                                 | OK                          | OK                   |
| oom_137                   | OK                                 | OK                          | ERROR                |
| command_not_found         | OK                                 | OK                          | OK                   |
| bwa_oom                   | OK                                 | OK                          | OK                   |
| tool_wrap_seqtk           | OK                                 | OK                          | OK                   |
| edge_greeting_then_align  | OK                                 | OK                          | WRONG (router)       |
| edge_implicit_failure     | WRONG (orchestrator)               | OK                          | WRONG (orchestrator) |
| edge_align_intent         | OK                                 | OK                          | OK                   |
| edge_qc_intent            | OK                                 | OK                          | OK                   |
| edge_implicit_bwa_failure | OK                                 | OK                          | WRONG (router)       |
| edge_workflow_meta        | WRONG (orchestrator)               | WRONG (orchestrator)        | OK                   |
| edge_off_topic_python     | OK                                 | WRONG (error_analysis)      | OK                   |
| edge_very_short           | OK                                 | WRONG (orchestrator)        | OK                   |
| tool_create_fasta_lines   | ERROR                              | ERROR                       | OK                   |
| edge_wrap_explicit        | ERROR                              | OK                          | OK                   |
| edge_multi_intent         | ERROR                              | OK                          | OK                   |

## error_analysis

| metric             | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------ | ---------------------------------- | --------------------------- | ------------ |
| MustMention        | 5/8                                | 6/8                         | 7/8          |
| LLMJudge           | 8/8                                | 7/8                         | 8/8          |
| median latency (s) | 0.61                               | 1.41                        | 3.78         |

### Per-case detail

| case                       | Llama-4-Maverick-17B-128E-Instruct                                     | Meta-Llama-3.3-70B-Instruct                                            | gpt-oss-120b                                                           |
| -------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| oom_137                    | WRONG (**Error Type**: Resource Exhaustion **Severity**: High \*\*Lik) | WRONG (**Error Type**: Job Failure **Severity**: High \*\*Likely Caus) | OK (judge 1.00)                                                        |
| command_not_found_samtools | WRONG (**Error Type**: Tool Dependency Issue **Severity**: Fatal \*\*) | OK (judge 1.00)                                                        | WRONG (**Error Type**: Missing Dependency **Severity**: Error \*\*Lik) |
| exit_127                   | WRONG (**Error Type**: Tool Not Found Or Unexecutable **Severity**:)   | WRONG (**Error Type**: Unknown Error **Severity**: High \*\*Likely Ca) | OK (judge 1.00)                                                        |
| bwa_oom                    | OK (judge 1.00)                                                        | OK                                                                     | OK (judge 1.00)                                                        |
| disk_full                  | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        |
| missing_input              | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        |
| invalid_param              | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        |
| permission_denied          | OK (judge 1.00)                                                        | OK (judge 1.00)                                                        | OK (judge 0.95)                                                        |
