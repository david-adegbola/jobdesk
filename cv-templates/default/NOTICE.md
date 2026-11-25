# Default CV layout: origin and licences

`jobdesk-cv.sty` was written for JobDesk on 2026-11-25 as a **clean-room** layout. It was built from a visual
description of the look of the owner's CV repository (github.com/david-adegbola/cv, commit `10abe81`, its
`roles/ai-student-developer/cv-en.pdf` output) and the published screenshots of hmemcpy/cv (commit `454c983`):
centred name in small capitals, a label column, small-capital section titles with a rule, pale skill tags and a
footer with the page count. **No LaTeX code was copied** from either repository or from the "Professional CV"
template by Alessandro Plasmati that they derive from, whose licence is not stated (Overleaf lists it as "Other (as
stated in the work)"). The file is MIT-licensed (`LICENSE`).

When the owner's CV repository changes its look, compare its output with JobDesk's again (`scripts/cv_samples.py`
renders the comparison pages) and adjust this file by hand; don't paste code across.

Fonts and packages used (from TeX Live; none are copied into this repository):
- Linux Libertine and Linux Biolinum (`libertine` package): SIL Open Font License / GPL with font exception.
- `cmap`, `glyphtounicode`, `babel`, `geometry`, `xcolor`, `tikz`, `titlesec`, `enumitem`, `fancyhdr`,
  `lastpage`, `hyperref`, `ragged2e`: LPPL.
