# Case Study & Customer Corrections

Corrections applied so Ira and content do not repeat wrong claims.

## Plastoranger Advanced Technologies (March 2026)

- **Wrong (removed):** "Plastoranger is a $200M automotive group."
- **Correct:** Plastoranger Advanced Technologies is a thermoforming / plastics processing company in Pune, India. They are **not** an automotive group and **not** $200M. Do not describe them as such. Use: "A thermoforming leader in India" or "Plastoranger Advanced Technologies" without size or automotive claims.
- **Source of error:** Case study copy had been incorrectly labelled; corrected in `plastoranger-complete-line-india` case study and index.

## India automotive customers — references

**Accurate automotive customers in India (case studies):**
- **IAC International Automotive India** — IMG/TPO, automotive interiors (Manesar).
- **Pinnacle Industries** — Large-format automotive components (PF1-5028 XL).
- **ALP Group** — Automotive components, Mahindra bedliner (Nashik); $200M automotive components conglomerate is correct for ALP only.

**Other automotive customers (not yet full case studies):**
- **Alphafoam** and others — We have many other customers in auto; Alphafoam is one. Do not limit India auto references to only IAC, Pinnacle, ALP. When asked for automotive references in India, consider that additional customers exist beyond the published case studies.

## PF1-X-5028 & PF1 specs (March 2026)

- **516 kW (PF1-X-5028):** Top and bottom heater **combined**, not top only. Total connected 602 kW = 516 kW heater + 86 kW servo.
- **Sheet thickness (PF1-C and PF1-X single-station):** **2–12 mm** for both (not 2–6 mm only).
- **Sheet loading:** Manual or with autoloader (option on both where applicable).
- **Universal frames:** **Sheet size changeover system** (for quick size changeover), not just "for loading".
- **PF1 options:** See `data/knowledge/pf1_specs_and_options.md` and `data/imports/04_Machine_Manuals_and_Specs/PF1 1015 all options format Machinecraft INR.pdf` and `PF1 3520 Machinecraft all Options V02.pdf`.

## Acme Packaging / Acme (March 2026)

- **Wrong:** Any deal analysis, CRM data, or proposal content that describes "Acme Packaging BV", "Erik Janssen", "Q-2024-089", "2× PF1 EUR 450,000", Netherlands, advance payments, or pipeline status for Acme as if it were real customer data.
- **Correct:** "Acme" and "Acme Packaging" in this repo appear only in **eval datasets and test fixtures** (e.g. `tests/eval_dataset.json`) as **example/synthetic data**. Do **not** use them as factual CRM, pipeline, or deal information. For any real Acme deal or contact, use live CRM, pipeline API, or email — not the eval context.
- **Action:** The file `data/knowledge/acme_deal_analysis_and_proposal_outline.md` was based on that eval data and has been retracted; do not cite it for Acme facts.
