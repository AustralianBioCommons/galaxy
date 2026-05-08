# Galaxy agent evals -- 2026-05-08

_Generated 2026-05-08T11:55:24 from `80da3e0da81`._

## bioinformatics_workflows

| metric             | Llama-4-Maverick-17B-128E-Instruct | Meta-Llama-3.3-70B-Instruct | gpt-oss-120b |
| ------------------ | ---------------------------------- | --------------------------- | ------------ |
| LLMJudge           | 0/8                                | 0/8                         | 5/8          |
| median latency (s) | 28.81                              | 10.55                       | 13.15        |

### Per-case detail

| case                                | Llama-4-Maverick-17B-128E-Instruct                                     | Meta-Llama-3.3-70B-Instruct                                            | gpt-oss-120b                                                         |
| ----------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| scrna_cell_type_identification      | WRONG (It seems like there are no valid histories available for ana)   | WRONG (To figure out what cell types are present in your single-cel)   | OK (judge 1.00)                                                      |
| bulk_rnaseq_differential_expression | WRONG (**Why these tools?** No specific tools for differential gene)   | WRONG (**Why these tools?** No tools found for identifying differen)   | OK (judge 1.00)                                                      |
| qc_triage_fastqc                    | WRONG (To clean up your data, you'll need to trim the poor quality )   | WRONG (**Error Type**: Data Quality Issue **Severity**: Medium \*\*Li) | WRONG (**Why these tools?** I searched the Galaxy server for common) |
| low_mapping_rate_troubleshooting    | WRONG (**Error Type**: Mapping Issue **Severity**: Warning \*\*Likely) | WRONG (**Error Type**: Mapping Error **Severity**: Low \*\*Likely Cau) | OK (judge 1.00)                                                      |
| metagenomics_community_composition  | WRONG (**Why these tools?** No metagenomics analysis tools were fou)   | WRONG (I'm having trouble processing your request right now. Please)   | WRONG (**Why these tools?** I searched the Galaxy server for keywor) |
| somatic_variant_calling             | WRONG (**Why these tools?** No variant calling tools were found on )   | ERROR                                                                  | OK (judge 0.90)                                                      |
| general_onboarding_guidance         | WRONG (Since there are no histories available, it seems like we nee)   | WRONG (It seems like you don't have any existing histories in your )   | OK (judge 0.80)                                                      |
| coverage_anomalies_artifacts        | WRONG (To determine whether huge coverage spikes and gaps are real )   | ERROR                                                                  | WRONG (I’m not seeing any histories in your Galaxy account at the m) |
