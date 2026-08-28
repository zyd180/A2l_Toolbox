param(
    [string]$Message = "chore: update project",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Command,
        [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$GitArgs
    )
    $Args = @($Command) + @($GitArgs)
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Args -join ' ')"
    }
}

$remote = (& git remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or
    $remote -notmatch '(?i)github\.com[/:]zyd180/A2l_Toolbox(?:\.git)?$') {
    throw "origin is not zyd180/A2l_Toolbox: $remote"
}

$branch = (& git branch --show-current).Trim()
if ([string]::IsNullOrWhiteSpace($branch)) {
    throw "Current checkout is not on a local branch"
}

Write-Host "Repository: $remote"
Write-Host "Branch: $branch"
if ($DryRun) {
    Invoke-Git status --short
    Write-Host "[DRY RUN] Remote and branch checks passed."
    Write-Host "[DRY RUN] Would stage, commit, and force-push local changes."
    exit 0
}
Write-Host "Preparing local changes..."

# Exclude local delivery archives so generated files are not committed.
Invoke-Git add -A -- . ':(exclude)*.rar'
& git diff --cached --check
if ($LASTEXITCODE -ne 0) {
    throw "Whitespace or conflict marker check failed"
}

& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    Invoke-Git commit -m $Message
} else {
    Write-Host "No new local changes; pushing existing commits."
}

Write-Host "Force pushing local $branch to origin/$branch..."
Invoke-Git push origin $branch --force
Write-Host "[OK] Local branch pushed to zyd180/A2l_Toolbox." -ForegroundColor Green
