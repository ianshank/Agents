param (
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: .\run_reasoning_skills_demo.ps1"
    Write-Host "Demonstrates chaining of reasoning skills: hierarchical-recursive-brainstorm, openspec-quality-plan, openspec-peer-review"
    exit 0
}

Write-Host "====================================================="
Write-Host " Reasoning Skills Demo"
Write-Host "====================================================="
Write-Host ""
Write-Host "Step 1: Running hierarchical-recursive-brainstorm..."
# Simulated output
Start-Sleep -Seconds 1
Write-Host ">> Brainstorming complete. Output saved to artifact: brainstorm_results.md"
Write-Host ""

Write-Host "Step 2: Generating OpenSpec Quality Plan..."
# Simulated output
Start-Sleep -Seconds 1
Write-Host ">> OpenSpec plan generated using brainstorm results. Output saved to artifact: openspec_plan.md"
Write-Host ""

Write-Host "Step 3: Executing OpenSpec Peer Review..."
# Simulated output
Start-Sleep -Seconds 1
Write-Host ">> Peer review complete. Quality metrics passed."
Write-Host ""

Write-Host "Demo complete! Reasoning skills successfully chained."
