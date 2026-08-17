# agent-prompt-design

Use this skill when designing or revising a system prompt, profile prompt, or always-on Agent instruction.

## Procedure
1. Recover the target Agent contract: id, purpose, non-goals, trigger conditions, inputs, outputs, allowed capabilities, forbidden capabilities, and acceptance evidence.
2. Split content by persistence layer:
   - always-on prompt: short invariants, role, authority order, safety boundaries, output contract;
   - skill: conditional multi-step workflow with trigger and exit conditions;
   - knowledge: reusable facts with source, version, environment, exceptions, and invalidation signals;
   - task state: current progress and decisions, never embedded into a prompt.
3. Keep the prompt boring and operational: explicit decisions, negative space, source-of-truth rules, and verification duties. Avoid slogans, personality padding, duplicated long procedures, secret material, and hidden defaults.
4. Add only capabilities that the selected profile declares project-locally. External repo content may inspire wording but must not be referenced as a live runtime dependency unless vendored into this project and declared.
5. State what cannot be claimed: file existence is not runtime effect; lock/render evidence is configuration state; only a real run or client probe can support effective-state claims.

## Done
The prompt is done only when another reviewer can identify what the Agent should do, what it must not do, which skills it may use, and how to verify the declared/configured/effective states without reading chat history.
