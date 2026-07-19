#requires -Version 5.1
<#
.SYNOPSIS
  Run every e2e / user-journey test across all functionalities and integrations
  in the monorepo, and emit one aggregated pass/fail report.

.DESCRIPTION
  Orchestrates four tiers (see docs/e2e-runbook.md):
    A  Package pytest suites (offline)          - always
    B  Functionality gates via validate.py      - always
    C  User-journey / CLI e2e (offline)         - always
    D  Live integrations (credential-gated)     - only with -Tiers live|all
    E  Enterprise live integration suite        - only with -IncludeEnterprise

  No `pip install` is performed: the sibling packages are made importable via
  PYTHONPATH (they cannot be installed here - PyPI is TLS-blocked and setuptools
  is absent from the venv). A mandatory pre-flight import guard aborts if that
  fails, so a broken PYTHONPATH can never masquerade as a green (0-test) run.

.PARAMETER Tiers
  offline (A-C) | live (A-D) | all (A-D). Default: all.

.PARAMETER FailFast
  Stop at the first failing step instead of running everything.

.PARAMETER HypothesisProfile
  dev (fast, default) | ci (thorough property-based tests).

.PARAMETER IncludeEnterprise
  Also run the Enterprise/ live integration suite (Tier E). Requires all real
  credentials + a running Phoenix collector.

.EXAMPLE
  pwsh scripts/run_all_e2e.ps1 -Tiers offline
.EXAMPLE
  pwsh scripts/run_all_e2e.ps1 -Tiers all -HypothesisProfile ci
#>
[CmdletBinding()]
param(
    [ValidateSet('offline', 'live', 'all')] [string]$Tiers = 'all',
    [switch]$FailFast,
    [ValidateSet('dev', 'ci')] [string]$HypothesisProfile = 'dev',
    [switch]$IncludeEnterprise
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
$RepoRoot = Split-Path -Parent $PSScriptRoot            # scripts/ -> repo root
Set-Location $RepoRoot
# Multi-segment paths are built with [IO.Path]::Combine so the native separator is
# used on whichever OS PowerShell runs on (embedding '\' in a leaf would become a
# literal char on POSIX). Combine works on both Windows PowerShell 5.1 and pwsh 7
# (Join-Path's 3+ segment form does not exist before PS 6).

# Resolve the venv interpreter for whichever OS PowerShell is running on:
# Windows layout (.venv/Scripts/python.exe) or POSIX layout (.venv/bin/python).
$Py = @(
    [System.IO.Path]::Combine($RepoRoot, '.venv', 'Scripts', 'python.exe'),
    [System.IO.Path]::Combine($RepoRoot, '.venv', 'bin', 'python')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Py) { throw "venv python not found under $RepoRoot/.venv (expected a provisioned .venv)" }

$Report = [System.IO.Path]::Combine($RepoRoot, 'artifacts', 'e2e-report')
if (Test-Path $Report) { Remove-Item -Recurse -Force $Report }
New-Item -ItemType Directory -Force -Path $Report | Out-Null
$Fixtures = Join-Path $Report 'fixtures'
New-Item -ItemType Directory -Force -Path $Fixtures | Out-Null

# PYTHONPATH, first entry first:
#  - e2e_shims: a sitecustomize.py that neutralizes the hanging platform._wmi_query
#    (WMI is blocked on this host; Hypothesis calls platform.system() at import, so
#    without this every pytest suite wedges before collecting a single test).
#  - sibling packages: NOT installed, made importable here. Order matters
#    (behavioral_regression imports agent_core/flow_corpus at module load); note
#    claude-foundation exposes `foundation_tools` under tools/.
$PkgPaths = @(
    [System.IO.Path]::Combine($RepoRoot, 'scripts', 'e2e_shims'),
    (Join-Path $RepoRoot 'flow-protocol'),
    (Join-Path $RepoRoot 'flow-corpus'),
    (Join-Path $RepoRoot 'behavioral-regression'),
    [System.IO.Path]::Combine($RepoRoot, 'claude-foundation', 'tools'),
    (Join-Path $RepoRoot 'agent-core')
)
# Native path-list separator: ';' on Windows, ':' on POSIX.
$env:PYTHONPATH = ($PkgPaths -join [System.IO.Path]::PathSeparator)
$env:HYPOTHESIS_PROFILE = $HypothesisProfile
$env:OUT_DIR = $Report          # keep run-journey artifacts inside the report dir
$env:PYTHONUTF8 = '1'

# ---------------------------------------------------------------------------
# .env loader (BOM-safe). IMPORTANT: .env holds live endpoints/keys (Langfuse,
# Phoenix). We must NOT inject them into the offline tiers -- several SDK-optional
# tests assert failsafe behaviour when no endpoint is configured, and a live
# PHOENIX_COLLECTOR_ENDPOINT would make them try to reach localhost:6006. So we
# parse .env into a table now and only apply it just before Tier D.
# ---------------------------------------------------------------------------
function Read-DotEnv {
    param([string]$Path)
    $h = @{}
    if (-not (Test-Path $Path)) { return $h }
    $raw = Get-Content -Raw -Encoding UTF8 -Path $Path
    if ($raw) { $raw = $raw.TrimStart([char]0xFEFF) }         # strip leading BOM
    foreach ($line in ($raw -split "`r?`n")) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $idx = $t.IndexOf('=')
        if ($idx -lt 1) { continue }
        $h[$t.Substring(0, $idx).Trim()] = $t.Substring($idx + 1).Trim().Trim('"').Trim("'")
    }
    return $h
}
$script:DotEnv = Read-DotEnv (Join-Path $RepoRoot '.env')
function Enable-LiveEnv {
    foreach ($k in $script:DotEnv.Keys) { Set-Item -Path "Env:$k" -Value $script:DotEnv[$k] }
}

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
$Results = New-Object System.Collections.Generic.List[object]

# Defined early: Add-Result (FailFast) and the pre-flight guard both call it.
function Write-Summary {
    $json = Join-Path $Report 'summary.json'
    $md = Join-Path $Report 'summary.md'
    $counts = @{ PASS = 0; FAIL = 0; SKIP = 0 }
    foreach ($r in $Results) { if ($counts.ContainsKey($r.status)) { $counts[$r.status]++ } }

    $Results | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $json

    $lines = @()
    $lines += "# E2E run summary"
    $lines += ""
    $lines += ("Tiers: ``{0}``  |  HypothesisProfile: ``{1}``  |  PASS {2} / FAIL {3} / SKIP {4}" -f `
            $Tiers, $HypothesisProfile, $counts.PASS, $counts.FAIL, $counts.SKIP)
    $lines += ""
    $lines += "| Tier | Step | Status | Detail | ms |"
    $lines += "|------|------|--------|--------|----|"
    foreach ($r in $Results) {
        $lines += ("| {0} | {1} | {2} | {3} | {4} |" -f $r.tier, $r.name, $r.status, $r.detail, $r.duration_ms)
    }
    $lines -join "`n" | Set-Content -Encoding UTF8 -Path $md

    Write-Host "`n== Summary ==" -ForegroundColor Cyan
    Write-Host ("PASS {0}  FAIL {1}  SKIP {2}" -f $counts.PASS, $counts.FAIL, $counts.SKIP)
    Write-Host "Report: $md"
}

function Get-OrDefault { param($Value, $Default) if ($Value) { $Value } else { $Default } }

function Add-Result {
    param([string]$Tier, [string]$Name, [string]$Status, [string]$Detail = '', [long]$Ms = 0)
    $Results.Add([pscustomobject]@{
            tier = $Tier; name = $Name; status = $Status; detail = $Detail; duration_ms = $Ms
        })
    $color = switch ($Status) { 'PASS' { 'Green' } 'FAIL' { 'Red' } 'SKIP' { 'Yellow' } default { 'Gray' } }
    Write-Host ("  [{0,-4}] {1,-38} {2}" -f $Status, $Name, $Detail) -ForegroundColor $color
    if ($Status -eq 'FAIL' -and $FailFast) { Write-Summary; throw "FailFast: $Name failed" }
}

$SafeName = { param($n) ($n -replace '[^\w.-]', '_') }

# Run a python step under a hard timeout; returns exit code (124 = timeout).
# Runs inside a background job so (a) the call operator passes the arg array
# verbatim (Start-Process mangles quoting on PS 5.1), (b) $LASTEXITCODE is the
# reliable source of truth, and (c) a wedged step can never hang the whole run.
$script:TimeoutExit = 124
function Invoke-Py {
    param([string]$Name, [string[]]$PyArgs, [string]$WorkDir = $RepoRoot, [int]$TimeoutSec = 900)
    $log = Join-Path $Report ((& $SafeName $Name) + '.log')
    $job = Start-Job -ScriptBlock {
        param($Py, $PyArgs, $WorkDir, $Log, $PyPath, $HypProfile, $OutDir)
        Set-Location $WorkDir
        $env:PYTHONPATH = $PyPath
        $env:HYPOTHESIS_PROFILE = $HypProfile
        $env:OUT_DIR = $OutDir
        $env:PYTHONUTF8 = '1'
        $ErrorActionPreference = 'Continue'   # native stderr is not a terminating error
        & $Py @PyArgs *> $Log
        return $LASTEXITCODE
    } -ArgumentList $Py, $PyArgs, $WorkDir, $log, $env:PYTHONPATH, $env:HYPOTHESIS_PROFILE, $env:OUT_DIR
    if (Wait-Job $job -Timeout $TimeoutSec) {
        # Receive-Job returns everything the job wrote to the success stream. The
        # exit code is the scriptblock's final `return`, so it is the last value on
        # the stream; take the last int-parseable item so any stray host/profile
        # output from the child session cannot crash the [int] cast.
        $out = @(Receive-Job $job)
        Remove-Job $job -Force
        for ($i = $out.Count - 1; $i -ge 0; $i--) {
            $n = $out[$i] -as [int]
            if ($null -ne $n) { return $n }
        }
        return 1   # no exit code captured -> treat as a failure, not a pass
    }
    Stop-Job $job; Remove-Job $job -Force
    return $script:TimeoutExit
}

function Get-JUnitTestCount {
    param([string]$XmlPath)
    if (-not (Test-Path $XmlPath)) { return -1 }
    try {
        [xml]$x = Get-Content -Raw -Encoding UTF8 -Path $XmlPath
        $sum = 0
        foreach ($ts in $x.SelectNodes('//testsuite')) { $sum += [int]$ts.tests }
        return $sum
    }
    catch { return -1 }
}

# A pytest step: run, then assert junit reports > 0 tests (guards vacuous coverage).
function Invoke-PytestStep {
    param([string]$Tier, [string]$Name, [string[]]$PyArgs, [string]$WorkDir = $RepoRoot, [string]$Junit, [int]$TimeoutSec = 900)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $code = Invoke-Py -Name $Name -PyArgs $PyArgs -WorkDir $WorkDir -TimeoutSec $TimeoutSec
    $sw.Stop()
    if ($code -eq $script:TimeoutExit) { Add-Result $Tier $Name 'FAIL' "TIMEOUT after ${TimeoutSec}s" $sw.ElapsedMilliseconds; return }
    $n = Get-JUnitTestCount $Junit
    if ($code -eq 0 -and $n -gt 0) {
        Add-Result $Tier $Name 'PASS' "$n tests" $sw.ElapsedMilliseconds
    }
    elseif ($code -eq 0 -and $n -le 0) {
        Add-Result $Tier $Name 'FAIL' "exit 0 but $n tests collected (see log)" $sw.ElapsedMilliseconds
    }
    else {
        Add-Result $Tier $Name 'FAIL' "exit $code (see $((& $SafeName $Name)).log)" $sw.ElapsedMilliseconds
    }
}

# A plain command step: exit 0 = PASS, else FAIL. Optional -SkipCodes map to SKIP.
function Invoke-CmdStep {
    param([string]$Tier, [string]$Name, [string[]]$PyArgs, [string]$WorkDir = $RepoRoot,
        [int[]]$SkipCodes = @(), [string]$PassDetail = '', [int]$TimeoutSec = 600, [int[]]$PassCodes = @())
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $code = Invoke-Py -Name $Name -PyArgs $PyArgs -WorkDir $WorkDir -TimeoutSec $TimeoutSec
    $sw.Stop()
    if ($code -eq $script:TimeoutExit) { Add-Result $Tier $Name 'FAIL' "TIMEOUT after ${TimeoutSec}s" $sw.ElapsedMilliseconds; return }
    if ($code -eq 0 -or $PassCodes -contains $code) {
        $d = $PassDetail; if ($code -ne 0) { $d = (($PassDetail, "exit $code") | Where-Object { $_ }) -join ' ' }
        Add-Result $Tier $Name 'PASS' $d $sw.ElapsedMilliseconds
    }
    elseif ($SkipCodes -contains $code) { Add-Result $Tier $Name 'SKIP' "exit $code" $sw.ElapsedMilliseconds }
    else { Add-Result $Tier $Name 'FAIL' "exit $code (see $((& $SafeName $Name)).log)" $sw.ElapsedMilliseconds }
}

function Test-EnvSet { param([string[]]$Names) foreach ($n in $Names) { if (-not (Test-Path "Env:$n") -or -not (Get-Item "Env:$n").Value) { return $false } } return $true }

# ---------------------------------------------------------------------------
# Pre-flight import guard (mandatory)
# ---------------------------------------------------------------------------
Write-Host "`n== Pre-flight ==" -ForegroundColor Cyan
$guard = Invoke-Py -Name 'preflight-imports' -PyArgs @('-c', 'import flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness')
if ($guard -ne 0) {
    Add-Result 'PRE' 'preflight-imports' 'FAIL' 'sibling imports failed - aborting (see preflight-imports.log)'
    Write-Summary
    throw "Pre-flight import guard failed; PYTHONPATH is wrong or a package is missing."
}
Add-Result 'PRE' 'preflight-imports' 'PASS' 'flow_protocol, flow_corpus, behavioral_regression, foundation_tools, agent_core, eval_harness'

# ===========================================================================
# TIER A - Package test suites (offline, always)
# ===========================================================================
Write-Host "`n== Tier A: package suites ==" -ForegroundColor Cyan
$suites = @(
    @{ name = 'suite:root';                  dir = $RepoRoot;                                     xml = 'root.xml' },
    @{ name = 'suite:agent-core';            dir = (Join-Path $RepoRoot 'agent-core');            xml = 'agent-core.xml' },
    @{ name = 'suite:behavioral-regression'; dir = (Join-Path $RepoRoot 'behavioral-regression'); xml = 'behavioral-regression.xml' },
    @{ name = 'suite:flow-corpus';           dir = (Join-Path $RepoRoot 'flow-corpus');           xml = 'flow-corpus.xml' },
    @{ name = 'suite:flow-protocol';         dir = (Join-Path $RepoRoot 'flow-protocol');         xml = 'flow-protocol.xml' },
    @{ name = 'suite:claude-foundation';     dir = (Join-Path $RepoRoot 'claude-foundation');     xml = 'claude-foundation.xml' }
)
foreach ($s in $suites) {
    $junit = Join-Path $Report $s.xml
    $suiteArgs = @('-m', 'pytest', '--cov', '--cov-report=term-missing', "--junitxml=$junit", '-p', 'no:cacheprovider')
    Invoke-PytestStep 'A' $s.name $suiteArgs $s.dir $junit
}
# Operational-scripts coverage gate (F-031) - reuses tests/ with a scripts coverage config.
$scriptsXml = Join-Path $Report 'scripts.xml'
Invoke-PytestStep 'A' 'suite:scripts-gate' `
    @('-m', 'pytest', 'tests', '--cov=scripts', '--cov-config=scripts/.coveragerc', '--cov-report=term-missing', "--junitxml=$scriptsXml", '-p', 'no:cacheprovider') `
    $RepoRoot $scriptsXml

# ===========================================================================
# TIER B - Functionality gates (offline, always)
# ===========================================================================
Write-Host "`n== Tier B: functionality gates (features.yaml) ==" -ForegroundColor Cyan
# validate.py runs every done+fast feature's validation_command (all 36 are tier
# fast); deferred features (e.g. F-036) are skipped by design.
Invoke-CmdStep 'B' 'features:validate.py' @('scripts/validate.py', '-v') $RepoRoot -TimeoutSec 1800

# ===========================================================================
# TIER C - User-journey / CLI e2e (offline, always)
# ===========================================================================
Write-Host "`n== Tier C: user-journey / CLI e2e ==" -ForegroundColor Cyan

# C1: skill + hook end-to-end tests (addopts neutralized so per-package coverage
# gates / strict-config don't collide when run from the repo root).
$e2eXml = Join-Path $Report 'e2e_journeys.xml'
Invoke-PytestStep 'C' 'e2e:skills+hooks' `
    @('-m', 'pytest',
      'skills/architecture-drift-guard/tests/test_end_to_end.py',
      'skills/eval-corpus-forge/tests/test_end_to_end.py',
      'skills/project-setup/tests/test_gen_makefile.py',
      'skills/project-setup/tests/test_workspace.py',
      'skills/quality-gate/tests/test_gen_gate.py',
      'skills/deploy/tests/test_gen_deploy.py',
      'claude-foundation/tests/test_hooks_e2e.py',
      '-o', 'addopts=', '--import-mode=importlib', '-p', 'no:cacheprovider', "--junitxml=$e2eXml") `
    $RepoRoot $e2eXml

# C2: eval-harness CLI journeys (offline)
Invoke-CmdStep 'C' 'cli:eval-harness list-plugins' @('-m', 'eval_harness.cli', 'list-plugins')
Invoke-CmdStep 'C' 'cli:eval-harness run' @('-m', 'eval_harness.cli', 'run', '--config', 'config/eval.example.yaml', '--offline')
# Override a harmless field so the --set plumbing is exercised without shrinking
# the (2-item) dataset to zero rows (sample_rate=0.1 would sample 0 -> gate fails).
Invoke-CmdStep 'C' 'cli:eval-harness run --set' @('-m', 'eval_harness.cli', 'run', '--config', 'config/eval.example.yaml', '--set', 'run.seed=123', '--offline')

# C3: generate offline compare/campaign fixtures (config/ is a protected path, so
# these live in the report dir, not the repo).
$compareYaml = Join-Path $Fixtures 'compare.yaml'
@'
schema_version: "1.0"
run: { name: e2e-compare, seed: 7 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "reset password" }, expected: "reset" }
      - { id: q2, inputs: { question: "cancel plan" }, expected: "cancel" }
target: { type: echo, params: { output_key: question } }
scorers:
  - type: contains
    params: { name: mentions_reset, substring: "reset" }
judge:
  type: mock
  params: { default_score: 0.9 }
comparison:
  models:
    - { name: echo_a, target: { type: echo, params: { output_key: question } } }
    - { name: echo_b, target: { type: echo, params: { output_key: expected } } }
'@ | Set-Content -Encoding UTF8 -Path $compareYaml
Invoke-CmdStep 'C' 'cli:eval-harness compare' `
    @('-m', 'eval_harness.cli', 'compare', '--config', $compareYaml, '--offline',
      '--html', (Join-Path $Report 'compare.html'), '--json', (Join-Path $Report 'compare.json'))

$campaignYaml = Join-Path $Fixtures 'campaign.yaml'
@'
schema_version: "1.0"
run: { name: e2e-campaign, seed: 7 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "reset password" }, expected: "reset" }
      - { id: q2, inputs: { question: "cancel plan" }, expected: "cancel" }
target: { type: echo, params: { output_key: question } }
scorers:
  - type: contains
    params: { name: mentions_reset, substring: "reset" }
judge:
  type: mock
  params: { default_score: 0.9 }
ab_campaign:
  campaign_id: e2e-campaign
  arm_a: { name: a, target: { type: echo, params: { output_key: question } } }
  arm_b: { name: b, target: { type: echo, params: { output_key: expected } } }
  score: mentions_reset
  min_sample: 1
'@ | Set-Content -Encoding UTF8 -Path $campaignYaml
$campaignStore = Join-Path $Report 'campaign_store.jsonl'
Invoke-CmdStep 'C' 'cli:eval-harness campaign record' `
    @('-m', 'eval_harness.cli', 'campaign', '--config', $campaignYaml, '--store', $campaignStore, '--mode', 'record', '--offline')
Invoke-CmdStep 'C' 'cli:eval-harness campaign analyze' `
    @('-m', 'eval_harness.cli', 'campaign', '--config', $campaignYaml, '--store', $campaignStore, '--mode', 'analyze', '--offline',
      '--json', (Join-Path $Report 'campaign_analyze.json'))

# C4: behavioral-regression CLI journey (deterministic, offline)
$brJson = Join-Path $Report 'br.json'
Invoke-CmdStep 'C' 'cli:bregress' `
    @('-m', 'behavioral_regression', '--seed', '7', '--out', $brJson, '--html', (Join-Path $Report 'br.html'))
if ((Test-Path $brJson)) {
    try { Get-Content -Raw -Encoding UTF8 $brJson | ConvertFrom-Json | Out-Null }
    catch { Add-Result 'C' 'cli:bregress json-valid' 'FAIL' 'br.json is not valid JSON' }
}

# C5: agent-core merge_gate_ci CLI journey (throwaway store)
$mgStore = Join-Path $Report 'merge_gate_store.jsonl'
# Exit contract: 0=AUTO_MERGE, 10=ESCALATE, 20=REJECT are all valid gate
# decisions (only 1/2 are errors). The journey verifies the CLI decides.
Invoke-CmdStep 'C' 'cli:merge_gate_ci' `
    @('-m', 'agent_core.merge_gate_ci', '--store', $mgStore, '--domain', 'human', '--raw-confidence', '0.9', '--mech-pass') `
    -PassCodes @(10, 20) -PassDetail 'decision'

# C6: skill-marketplace CLI journeys
Invoke-CmdStep 'C' 'cli:skill_marketplace list' @('scripts/skill_marketplace.py', 'list')
Invoke-CmdStep 'C' 'cli:skill_marketplace verify' @('scripts/skill_marketplace.py', 'verify')

# ===========================================================================
# TIER D - Live integrations (credential-gated)
# ===========================================================================
if ($Tiers -in @('live', 'all')) {
    Write-Host "`n== Tier D: live integrations (credential-gated) ==" -ForegroundColor Cyan
    Enable-LiveEnv   # only now inject .env creds/endpoints (kept out of Tiers A-C)

    # Langfuse smoke (script itself exits 2 when creds missing -> SKIP)
    if (Test-EnvSet @('LANGFUSE_SECRET_KEY', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_BASE_URL')) {
        Invoke-CmdStep 'D' 'live:langfuse-smoke' @('artifacts/langfuse_smoke.py') $RepoRoot @(2)
    }
    else { Add-Result 'D' 'live:langfuse-smoke' 'SKIP' 'LANGFUSE_* not set' }

    # Phoenix smoke (needs a running collector)
    if (Test-EnvSet @('PHOENIX_COLLECTOR_ENDPOINT')) {
        Invoke-CmdStep 'D' 'live:phoenix-smoke' @('artifacts/phoenix_smoke.py') $RepoRoot @(2)
    }
    else { Add-Result 'D' 'live:phoenix-smoke' 'SKIP' 'PHOENIX_COLLECTOR_ENDPOINT not set' }

    # Live judge journeys - real judge, offline echo target (bounds cost). One tiny item.
    $liveJudges = @(
        @{ name = 'live:judge-openai';    env = @('OPENAI_API_KEY');    type = 'openai';    model = (Get-OrDefault $env:OPENAI_JUDGE_MODEL    'gpt-4o-mini') },
        @{ name = 'live:judge-anthropic'; env = @('ANTHROPIC_API_KEY'); type = 'anthropic'; model = (Get-OrDefault $env:ANTHROPIC_JUDGE_MODEL 'claude-haiku-4-5-20251001') },
        @{ name = 'live:judge-bedrock';   env = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'); type = 'bedrock'; model = (Get-OrDefault $env:BEDROCK_JUDGE_MODEL 'anthropic.claude-3-haiku-20240307-v1:0') }
    )
    foreach ($j in $liveJudges) {
        if (-not (Test-EnvSet $j.env)) { Add-Result 'D' $j.name 'SKIP' ("{0} not set" -f ($j.env -join ',')); continue }
        $cfg = Join-Path $Fixtures ("live_" + $j.type + ".yaml")
        @"
schema_version: "1.0"
run: { name: live-$($j.type), seed: 7, sample_rate: 1.0 }
dataset:
  type: inline
  params:
    items:
      - { id: q1, inputs: { question: "Reply with the single word: ok" }, expected: "ok" }
target: { type: echo, params: { output_key: question } }
scorers:
  - type: llm_judge
    params: { name: helpfulness }
judge:
  type: $($j.type)
  params: { model: "$($j.model)" }
sinks:
  - { type: console, params: { verbose: false } }
gate: { rules: [] }
"@ | Set-Content -Encoding UTF8 -Path $cfg
        # No --offline: exercise the real judge path.
        Invoke-CmdStep 'D' $j.name @('-m', 'eval_harness.cli', 'run', '--config', $cfg)
    }

    # Live Langfuse sink journey (writes scores to the backend)
    if (Test-EnvSet @('LANGFUSE_SECRET_KEY', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_BASE_URL')) {
        $lfCfg = Join-Path $Fixtures 'live_langfuse_sink.yaml'
        @'
schema_version: "1.0"
run: { name: live-langfuse-sink, seed: 7 }
dataset:
  type: inline
  params:
    items: [ { id: q1, inputs: { question: "reset password" }, expected: "reset" } ]
target: { type: echo, params: { output_key: question } }
scorers: [ { type: contains, params: { name: mentions_reset, substring: "reset" } } ]
judge: { type: mock, params: { default_score: 0.9 } }
sinks:
  - { type: console, params: { verbose: false } }
  - { type: langfuse }
gate: { rules: [] }
'@ | Set-Content -Encoding UTF8 -Path $lfCfg
        Invoke-CmdStep 'D' 'live:langfuse-sink' @('-m', 'eval_harness.cli', 'run', '--config', $lfCfg)
    }
    else { Add-Result 'D' 'live:langfuse-sink' 'SKIP' 'LANGFUSE_* not set' }

    # Live Phoenix sink journey
    if (Test-EnvSet @('PHOENIX_COLLECTOR_ENDPOINT')) {
        $phCfg = Join-Path $Fixtures 'live_phoenix_sink.yaml'
        @'
schema_version: "1.0"
run: { name: live-phoenix-sink, seed: 7 }
phoenix: { enabled: true, project_name: e2e-phoenix, tracing: true }
dataset:
  type: inline
  params:
    items: [ { id: q1, inputs: { question: "reset password" }, expected: "reset" } ]
target: { type: echo, params: { output_key: question } }
scorers: [ { type: contains, params: { name: mentions_reset, substring: "reset" } } ]
judge: { type: mock, params: { default_score: 0.9 } }
sinks:
  - { type: console, params: { verbose: false } }
  - { type: phoenix, params: { enabled: true } }
gate: { rules: [] }
'@ | Set-Content -Encoding UTF8 -Path $phCfg
        Invoke-CmdStep 'D' 'live:phoenix-sink' @('-m', 'eval_harness.cli', 'run', '--config', $phCfg)
    }
    else { Add-Result 'D' 'live:phoenix-sink' 'SKIP' 'PHOENIX_COLLECTOR_ENDPOINT not set' }
}

# ===========================================================================
# TIER E - Enterprise live integration suite (opt-in)
# ===========================================================================
if ($IncludeEnterprise) {
    Write-Host "`n== Tier E: Enterprise live integration suite ==" -ForegroundColor Cyan
    $entDir = [System.IO.Path]::Combine(
        (Split-Path -Parent $RepoRoot), 'Enterprise', 'files', 'langfuse-eval-harness', 'langfuse-eval-harness')
    $entTests = [System.IO.Path]::Combine($entDir, 'tests', 'integration')
    if (Test-Path $entTests) {
        $entXml = Join-Path $Report 'enterprise.xml'
        Invoke-PytestStep 'E' 'enterprise:integration' `
            @('-m', 'pytest', 'tests/integration', '-m', 'integration', '-o', 'addopts=', '-p', 'no:cacheprovider', "--junitxml=$entXml") `
            $entDir $entXml
    }
    else { Add-Result 'E' 'enterprise:integration' 'SKIP' "not found at $entTests" }
}

# ===========================================================================
# Summary
# ===========================================================================
Write-Summary

$failed = @($Results | Where-Object { $_.status -eq 'FAIL' }).Count
if ($failed -gt 0) { exit 1 } else { exit 0 }
