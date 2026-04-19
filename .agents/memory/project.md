# DigAgent Project Memory

- DigAgent packages project-facing runtime capabilities through `/.agents/skills`, `/.agents/tools`, and `/.agents/memory`.
- Temporary memory stays with session records for interruption recovery and should only be promoted here when it becomes durable.
- Project-specific capabilities should prefer manifest-backed tools instead of ad hoc shell glue.
