# Run this in PowerShell from the project root:
#   C:\study\projects\jenkins-upgrade-framework
# It cleans up the broken .git folder, makes the initial commit, and pushes.

$ErrorActionPreference = "Stop"

# 1. Remove the broken .git folder left by the earlier sandbox attempt (if any)
if (Test-Path .git) {
    Remove-Item -Recurse -Force .git
}

# 2. Initialize and make the first commit
git init
git add -A
git commit -m "Initial commit: Jenkins check-and-report upgrade framework"
git branch -M main

# 3. Add the remote and push
git remote remove origin 2>$null
git remote add origin https://github.com/animesh-mukherjee/jenkins-upgrade-framework.git
git push -u origin main

Write-Host "`nDone. Pushed to https://github.com/animesh-mukherjee/jenkins-upgrade-framework" -ForegroundColor Green
