# Development Workflow

## Standard Codex task cycle

1. Read applicable `AGENTS.md` instructions.
2. Read the relevant specification/design documents.
3. Inspect existing code and tests.
4. Propose a minimal implementation approach for non-trivial changes.
5. Implement the change.
6. Run relevant tests/checks.
7. Inspect the diff.
8. Update documentation when required.
9. Commit coherent changes with a clear message.

## Git principle
Use small, meaningful commits rather than one enormous commit.

## Before changing architecture
Explain:
- why the current architecture is insufficient;
- what will change;
- what files/modules are affected;
- how backward compatibility will be maintained where applicable.

## Definition of done
A feature is not complete merely because the code runs once. It should have appropriate tests, error handling, documentation, and traceability.
