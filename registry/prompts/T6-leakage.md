---
task: T6
schema: t6_leakage
batch_size: 25
---
You will receive a numbered batch of passages from scientific papers. Words that would identify the research
area, the topic, the people or the places have been replaced by bracketed placeholders such as [TERM], [NAME],
[PLACE], [ORG], [REF] and [CITED].

For each passage, say which one of these five research areas it most likely comes from:

- homeopathy
- chiropractic
- plate_tectonics
- molecular_genetics
- thermodynamics

Use only the passage. If nothing in it points to one area more than another, answer cannot_tell. Give your
confidence that your answer is right, from 0 to 1. Treat each passage on its own, and give one answer per
passage, with its key.
