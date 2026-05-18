## Development Workflow

When I ask for changes or features:
1. Create a separate branch with a short, descriptive name (e.g., `feat/prev-zero-ignore`).
2. Switch to that branch.
3. Make fixes, updates, or add code.
4. Test the changes to ensure they do not fail on execution.
5. Once tested, merge the branch into `dev`.
6. Switch back to the `dev` branch.

## PowerShell Git Conventions
Because this environment uses PowerShell, you MUST NOT use the Linux '&&' operator to chain commands. Instead, use the semicolon ';' as the statement separator.
- Correct: `git add .; git commit -m "msg"; git checkout dev`
- Incorrect: `git add . && git commit -m "msg" && git checkout dev`
