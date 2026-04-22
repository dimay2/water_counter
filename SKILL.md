# Development Workflow Skills

## Engineering Standards
- Perform code changes in an atomic, focused manner.
- Every atomic code change must be committed locally with a descriptive message.
- For every change in code, provide a brief summary of what was done in addition to the code diff.

## Windows PowerShell Best Practices
- When running multiple sequential commands in your Windows 11 PowerShell environment, use the semicolon (`;`) as a command separator. 
- Example: `git status; git log -n 3`
- Do not use `&&` as it is not a valid operator in PowerShell and will cause a parsing error.

## Documentation and Deployment
- Update the `README.md` with the latest changes before completing the final atomic change.
- Perform a local commit for the documentation update.
- Push the changes to the remote repository with an appropriate message once the task is complete.
