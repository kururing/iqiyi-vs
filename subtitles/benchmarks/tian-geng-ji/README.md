# Benchmark 田耕纪

Code for alignment and A/B evaluation is in `subtitles/benchmarks/`. No episode corpus, translations, international reference tracks, cached model results, or evaluation snapshots are included in this project copy.

To run a full comparison, provide the Chinese source, webapp translations, and the chosen reference tracks locally in the paths expected by `tian_geng_ji.py`. Record the track URL, episode/track metadata, language, file hash, and verification limits before treating a reference as verified. Do not pass reference translations for evaluation episodes into translation prompts.

The comparison code's `--self-test` uses synthetic inputs and can run without subtitle data. Inventory, alignment, and A/B commands require the corresponding local source and baseline data; the project does not claim current full-series comparison results.
