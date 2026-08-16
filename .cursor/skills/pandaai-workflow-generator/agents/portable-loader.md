# Portable Loader Prompt

Use this prompt in agents that do not natively discover `SKILL.md` folders.

```text
You have access to a local skill named pandaai-workflow-generator at:
<PANDAAI_WORKFLOW_GENERATOR_SKILL_ROOT>

When the user request matches this skill's SKILL.md description:
1. Read <PANDAAI_WORKFLOW_GENERATOR_SKILL_ROOT>/SKILL.md.
2. Follow the Core workflow and guardrails in that file exactly, including the
   QBTI hand-off (step 0) and the probe-first rule (step 2a).
3. Load referenced files under <PANDAAI_WORKFLOW_GENERATOR_SKILL_ROOT>/references/
   only when needed; always read sandbox_restrictions.md before writing CodeControl code.
4. Assemble output only through scripts/generate_workflow.py or scripts/from_qbti_brief.py;
   never execute generated strategy code locally.
5. Preserve documented API names, node parameter names, template node ids, and
   validation limits; do not invent panda_data methods.
6. Show the disclaimer from references/disclaimer_template.md verbatim before ending the turn.
```
