# STE rules for LANDFALL

This file gives the writing rules for the LANDFALL documentation. The rules come from ASD-STE100 (Simplified Technical English).

## Scope

The rules apply to these texts:

- `README.md`.
- Every file in `docs/`.
- Every Python docstring.
- Every TypeScript JSDoc block.
- Every string in `web/src/i18n/en-ste.json`.

Code identifiers, commit messages, log lines, and `BUILD_PROMPT.md` are exempt.

## Writing rules

1. Use only approved words, technical names, and technical verbs. "Monte Carlo", "FastAPI", "Cesium", and "HiGHS" are technical names.
2. Use the approved meaning of a word. "Close" is a verb only. Write "near the coast", not "close to the coast".
3. Keep to one topic in each sentence.
4. Write procedural sentences with a maximum of 20 words. Write descriptive sentences with a maximum of 25 words.
5. Write a maximum of 6 sentences in each descriptive paragraph.
6. Use the active voice. Write "The model predicts the track." Do not write "The track is predicted."
7. Use the imperative in procedures. Write "Run `make demo`." Do not write "You should run `make demo`."
8. Use simple verb forms: the infinitive, the imperative, the simple present, the simple past, and the future with "will".
9. Do not use the passive voice in procedures. In descriptive text, use the passive voice only if the agent is unknown.
10. Put an article or a demonstrative before a noun where possible.
11. Do not use noun clusters of more than 3 nouns.
12. Write one instruction in each sentence, unless two actions must occur at the same time.
13. Start a safety instruction with a clear condition and a command.
14. Use "that" for restrictive clauses. Do not use "which" where possible.
15. Do not use slang, idioms, humour, or marketing words.
16. Use digits for all numbers, except at the start of a sentence. Give SI units, with the US unit in parentheses if the source data uses US units.
17. Put a warning or a caution on its own line. Start it with WARNING: or CAUTION:.
18. Use one term for one concept. The glossary below gives the terms.
19. Use a vertical list for a sequence of more than 2 items.
20. Do not use the words in the table. Use the replacement.

| Do not use | Use |
| --- | --- |
| utilize | use |
| leverage | use |
| in order to | to |
| prior to | before |
| subsequent to | after |
| a number of | some, or a digit |
| ensure | make sure |
| robust | strong, or delete |
| seamless | delete |
| optimal | best |
| perform | do |
| commence | start |
| terminate | stop |
| facilitate | help |
| approximately | about |
| additional | more |
| assist | help |
| indicate | show |

## Glossary

| Term | Meaning |
| --- | --- |
| scenario | One of the K reduced storm tracks with a probability. Scenario 0 is the NHC official forecast (OFCL). |
| advisory | One NHC forecast time, every 6 h. The model uses the CARQ fix and the OFCL forecast of that time. |
| track | A time series of storm positions and wind speeds. |
| fix | One observed position and intensity of a storm at one time. |
| zone | One Lee County evacuation zone, A to E. |
| release time | The time when the county orders a zone to leave. |
| clearance time | The time when 99% of the evacuees of a zone are out of the zone. |
| shelter | A public building that holds evacuees. |
| depot | A site that stores supplies and sends trucks. |
| asset | A helicopter, a boat, or a high-water truck for search and rescue. |
| task | One rescue request at one location, with a priority and an asset type. |
| blocked edge | A road segment that trees, water, or bridge damage close. |
| critical link | A causeway or a bridge that connects a barrier island to the mainland. |

## The linter

Run `make ste` to check the rules. The linter is `scripts/ste_lint.py`. It checks these mechanical rules:

| Check | Level |
| --- | --- |
| Descriptive sentence of more than 25 words | error |
| Sentence of more than 20 words in a numbered procedure | error |
| A word from the rule 20 table | error, with the replacement |
| A form of "be" with a past participle in the next 2 words (passive voice) | warning |
| A form of "be" with an "-ing" word after it (present participle) | warning |
| Paragraph of more than 6 sentences | warning |
| 4 or more nouns in a row (noun cluster) | warning |

`make check` fails if the linter finds an error.

## Limitations of the linter

The linter does not understand grammar. Thus, it has these limitations:

- It cannot check rules 1, 2, 3, 10, 12, 13, 14, 15, 16, 17, 18, and 19. A person must check them.
- The passive-voice check uses a word list. It misses some irregular participles. It also gives false warnings for adjectives that end in "-ed", for example "required".
- The present-participle check gives false warnings for nouns that end in "-ing" after "is".
- The noun-cluster check uses a small bundled noun list and capital letters. It does not know all nouns. It treats a capitalised name as a noun.
- The sentence splitter breaks text at ".", "!", "?", ":", and ";". It joins some abbreviations, for example "e.g.". A formula in a sentence counts as many words.
- The linter skips code blocks, inline code, tables, URLs, and HTML tags.
- In Markdown, the linter treats each list item as one unit. A numbered list item is a procedural sentence.
- In Python, the linter reads only docstrings. It does not read comments.
- In TypeScript, the linter reads only `/** ... */` blocks. It does not read `//` comments or UI text that is not in `en-ste.json`.
