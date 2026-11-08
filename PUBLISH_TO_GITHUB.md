# Publish the isolated Gotham competition source (owner action)

**No GitHub repository is created by downloading this ZIP.** This repo must be a new public repo independent from the user's private CBTB War Room, URR and other research systems. Inspect all files for secrets before publishing; never upload the broader combined portfolio.

1. In GitHub, open https://github.com/new and create `gotham-agent-rush-2026` under the `Caz-Codehub` account as **Public**, leaving README/license auto-generation unchecked (they're in this folder).
2. Extract `Gotham-Agent-Rush-Build-v1.1.zip` and open PowerShell in the **project root** (where `README.md` is present).
3. With Git installed and GitHub CLI authenticated (run `gh auth login` only if needed), run:

   ```powershell
   git init
   git branch -M main
   git add .
   git status
   git commit -m "Gotham Project hackathon MVP with real Docker CI and evidence checks"
   git remote add origin https://github.com/Caz-Codehub/gotham-agent-rush-2026.git
   git push -u origin main
   ```

4. Confirm public GitHub Actions `gotham-unit-and-docker-tests` succeeds. The cloud runner actually launches Docker sandboxes; these tests **are not a substitute for Vultr deployment**.
5. Add the live Vultr URL only after it is running and independently verified, then use the URL in LabLab submission.

**If GitHub reports that Git identity is missing**, run `git config --global user.name "YOUR NAME"` and `git config --global user.email "YOUR PUBLIC GIT EMAIL"` using your own chosen values, then retry the commit. GitHub login uses the official login flow—never paste a PAT into this chat.
