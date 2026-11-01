# Development workflow

1. Inspect repository branch, history and all changed paths; preserve others'
   work. Never commit real patient data or secret material.
2. Create a descriptive feature branch from reviewed `main`.
3. Implement one cohesive milestone with migrations and tests.
4. Run `git diff --check`, tests, lint and typing where available.
5. Commit actual work; push once; create a reviewable PR targeting `main`.
6. Review CI and relevant threat-model changes; merge only reviewed work.

Never force-push or rewrite shared history. Stop on GitHub permission/rate
errors. The CLI cannot perform normal Git operations if network access to
GitHub is unavailable; authenticated GitHub repository API operations may be
used instead when authorized, with commits and PRs verified from GitHub.
