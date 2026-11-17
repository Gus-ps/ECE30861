# Phase 5 decisions needed

The agent writes an entry here whenever a task depends on a choice that the specification,
code or AGENTS.md doesn't settle (see the rules in `PHASE5_TASKS.md`). Jon picks an
option, and the pod confirms anything that affects the shared contract. Once an option is
chosen, write it under **Chosen** and the agent implements it.

## Entry format

```
## D<n>: <short question>  (blocks: <task IDs>)
Status: OPEN | CHOSEN (option <x>, <date>)
Context: <what is ambiguous and why, with spec section or file references>

1. <option name>: <what it does>. Pros: ... Cons: ... Code size: small/medium/large.
2. ...
(1 to 5 options, each meaningfully different, not variations of one idea.
 Mark at most one "(Recommended)" and say why.)

Chosen: <filled in by Jon>
```

## Known open questions

These are already known to need a decision. The agent writes the options when it first
reaches the blocked task.

- Deletion of schedules and notifications: those tables exist only on the unmerged
  `haruki/phase5-schedule` branch (blocks DEL-1).
- How deletion reaches backups and stored copies: RDS automated backups are kept for
  1 day, and spec §10 requires documenting this (blocks DEL-6).
- Design of the durable deletion reservation (blocks DEL-4, DEL-5).
- The reviewer grant model: `REVIEWER_GRANTS_JSON` currently grants access to every
  workbook an owner has, not to individual workbooks (blocks ACC-2).
- "No plaintext passwords": the service uses bearer tokens stored in
  `API_TOKENS_JSON`/Secrets Manager, not passwords (blocks ACC-4).
- Which automated accessibility scanner to use, and how to run it without adding
  dependencies (blocks UI-6).

## Entries
