<#
.SYNOPSIS
    ランキング上位銘柄の含み益検証を並行で実行するスクリプト (split-address 専用).
.DESCRIPTION
    ranking_market_cap_ratio.md から対象企業を抽出し,
    各企業に対して _codex_precheck.py で事前検証を行い,
    N個の Codex CLI ウィンドウを同時起動してタイル配置する.
    完了後にパッチファイルのジオコード一括検証を行う.
.PARAMETER N
    同時起動するウィンドウ数.
    --N <num> または -N <num> の形式で指定可能.
.PARAMETER DryRun
    対象一覧と事前検証結果を表示するだけで起動しない.
    --dry-run または -DryRun で指定可能.
#>
param(
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$_args
)

# --- Argument parsing (supports --N, -N, --dry-run, -DryRun) ---
$N = 1
$DryRun = $false
$i = 0
while ($i -lt $_args.Count) {
    switch ($_args[$i]) {
        { $_ -in '--N', '-N' } {
            $i++
            if ($i -ge $_args.Count) {
                Write-Host "エラー: $($_args[$i-1]) には値が必要です" -ForegroundColor Red
                exit 1
            }
            $N = [int]$_args[$i]
        }
        { $_ -in '--dry-run', '-DryRun' } {
            $DryRun = $true
        }
        default {
            Write-Host "エラー: 不明なオプション: $($_args[$i])" -ForegroundColor Red
            Write-Host "使用法: split-address.ps1 [--N <num>] [--dry-run]" -ForegroundColor Yellow
            exit 1
        }
    }
    $i++
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$rankingFile = Join-Path $projectRoot "data\output\ranking_market_cap_ratio.md"
$patchDir = Join-Path $projectRoot "config\address_patches"

# --- Step 1: ランキング読み込み ---

Write-Host ""
Write-Host "=== 並行 split-address (full) ===" -ForegroundColor Cyan

if (-not (Test-Path $rankingFile)) {
    Write-Host "エラー: ランキングファイルが見つかりません: $rankingFile" -ForegroundColor Red
    exit 1
}

$lines = Get-Content $rankingFile -Encoding UTF8

# Markdownテーブルの本体行（ヘッダーとセパレーターを除く）
$dataLines = $lines | Where-Object {
    $_ -match '^\|' -and $_ -notmatch '^\| ---' -and $_ -notmatch '^\| 順位'
}

$targets = @()
foreach ($line in $dataLines) {
    $cols = $line -split '\|'
    if ($cols.Count -lt 11) { continue }

    $targets += [PSCustomObject]@{
        Rank = $cols[1].Trim()
        Code = $cols[2].Trim()
        Name = $cols[3].Trim()
        Tag  = $cols[10].Trim()
    }
}

if ($targets.Count -eq 0) {
    Write-Host "ランキングに企業が見つかりませんでした." -ForegroundColor Green
    exit 0
}

# 上位N件に絞る
$count = [Math]::Min($N, $targets.Count)
$selected = $targets[0..($count - 1)]

Write-Host ""
Write-Host "対象企業 ($($selected.Count)件):" -ForegroundColor Yellow
foreach ($t in $selected) {
    $rankStr = $t.Rank.PadLeft(4)
    Write-Host "  ${rankStr}位: $($t.Code) $($t.Name)`t[$($t.Tag)]"
}
Write-Host ""

# --- Step 2: 事前検証 (_codex_precheck.py) ---

Write-Host "=== 事前検証 ===" -ForegroundColor Cyan
Write-Host ""

$precheckResults = @{}
foreach ($t in $selected) {
    $code = $t.Code
    Write-Host "  検証中: $code $($t.Name)..." -NoNewline

    try {
        $jsonOutput = & uv run python scripts/_codex_precheck.py $code 2>$null
        $result = $jsonOutput | ConvertFrom-Json
        $precheckResults[$code] = $result

        if ($result.has_risk) {
            $riskSites = ($result.sites | Where-Object { $_.bad_pattern_1_risk -or $_.geocode_level -ne 'gaiku' -or $_.has_multi_loc_warning })
            Write-Host " リスクあり ($($riskSites.Count)拠点)" -ForegroundColor Yellow
        } else {
            Write-Host " リスクなし (全gaiku)" -ForegroundColor Green
        }
    } catch {
        Write-Host " エラー: $_" -ForegroundColor Red
        $precheckResults[$code] = $null
    }
}

Write-Host ""

# --- Step 2.5: CODEX_CHECK フィルタ ---
$filtered = @()
foreach ($t in $selected) {
    $checkCount = & uv run python scripts/_codex_check_tracker.py get $t.Code 2>$null
    if ([int]$checkCount -ge 2) {
        Write-Host "  スキップ: $($t.Code) $($t.Name) (CODEX_CHECK_$checkCount, 調査上限)" -ForegroundColor DarkGray
    } else {
        $filtered += $t
    }
}
$selected = $filtered

if ($selected.Count -eq 0) {
    Write-Host "全企業が CODEX_CHECK 上限に達しています." -ForegroundColor Green
    exit 0
}

$count = $selected.Count
Write-Host "CODEX_CHECK フィルタ後: $count 件" -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    Write-Host "(DryRun: 事前検証結果の詳細)" -ForegroundColor Gray
    Write-Host ""
    foreach ($t in $selected) {
        $code = $t.Code
        $result = $precheckResults[$code]
        if ($null -eq $result) {
            Write-Host "  ${code}: (検証失敗)" -ForegroundColor Red
            continue
        }
        Write-Host "  $code $($t.Name):" -ForegroundColor White
        Write-Host "    all_gaiku=$($result.all_gaiku)  has_risk=$($result.has_risk)" -ForegroundColor Gray
        foreach ($site in $result.sites) {
            $flags = @()
            if ($site.bad_pattern_1_risk) { $flags += "BAD1" }
            if ($site.has_hoka) { $flags += "hoka" }
            if ($site.geocode_level -ne 'gaiku') { $flags += $site.geocode_level }
            if ($site.has_override) { $flags += "override" }
            $flagStr = if ($flags.Count -gt 0) { " [" + ($flags -join ",") + "]" } else { "" }
            Write-Host "    $($site.site_name)  area=$($site.area_m2)  geocode=$($site.geocode_level)$flagStr"
        }
        Write-Host ""
    }
    Write-Host "(DryRun: ここで終了)" -ForegroundColor Gray
    exit 0
}

# --- Step 2.7: CODEX_CHECK カウンタ increment ---
foreach ($t in $selected) {
    & uv run python scripts/_codex_check_tracker.py increment $t.Code 2>$null | Out-Null
}

# --- Step 3: パッチディレクトリ準備 ---

if (Test-Path $patchDir) {
    Remove-Item (Join-Path $patchDir "*.yaml") -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path $patchDir | Out-Null
}
Write-Host "パッチディレクトリ: $patchDir (クリア済み)" -ForegroundColor Gray
Write-Host ""

# --- Step 4: N個のウィンドウを同時起動＆タイル配置 ---

# Win32 API の読み込み
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

# ワーキングエリア取得（タスクバーを除く）
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea

$cols = [Math]::Ceiling([Math]::Sqrt($count))
$rows = [Math]::Ceiling($count / $cols)
$cellW = [int]($screen.Width / $cols)
$cellH = [int]($screen.Height / $rows)

Write-Host "$count ウィンドウを起動します..." -ForegroundColor Yellow

$processes = @()
for ($i = 0; $i -lt $count; $i++) {
    $code = $selected[$i].Code

    $patchFile = "config/address_patches/$code.yaml"

    # Build Codex prompt with precheck context
    $precheckResult = $precheckResults[$code]
    $precheckContext = ""
    if ($null -ne $precheckResult) {
        $precheckJson = ($precheckResult | ConvertTo-Json -Depth 5 -Compress)
        $precheckContext = " --precheck-json '$precheckJson'"
    }

    $codexPrompt = '$' + "split-address $code $patchFile$precheckContext"
    Write-Host "  [$($i + 1)] codex `$split-address $code  -> $patchFile"

    # Escape single quotes for nested PowerShell invocation (' -> '')
    $escapedPrompt = $codexPrompt -replace "'", "''"
    $innerCmd = "`$env:CD = '$projectRoot'; codex --full-auto '$escapedPrompt'"

    $proc = Start-Process -FilePath "powershell.exe" `
        -WorkingDirectory $projectRoot `
        -ArgumentList "-NoExit", "-Command", $innerCmd `
        -PassThru

    $processes += [PSCustomObject]@{
        Process = $proc
        Index   = $i
        Code    = $code
    }
}

# ウィンドウハンドルが取得できるまで少し待つ
Write-Host ""
Write-Host "ウィンドウ配置中..." -ForegroundColor Gray
Start-Sleep -Seconds 3

foreach ($p in $processes) {
    $proc = $p.Process
    $i = $p.Index

    # MainWindowHandle が取得できるまでリトライ
    $handle = [IntPtr]::Zero
    for ($retry = 0; $retry -lt 10; $retry++) {
        $proc.Refresh()
        if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {
            $handle = $proc.MainWindowHandle
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if ($handle -eq [IntPtr]::Zero) {
        Write-Host "  警告: $($p.Code) のウィンドウハンドルを取得できませんでした" -ForegroundColor DarkYellow
        continue
    }

    $col = $i % $cols
    $row = [Math]::Floor($i / $cols)
    $x = $screen.Left + ($col * $cellW)
    $y = $screen.Top + ($row * $cellH)

    [Win32]::ShowWindow($handle, 9) | Out-Null   # SW_RESTORE
    [Win32]::MoveWindow($handle, $x, $y, $cellW, $cellH, $true) | Out-Null
}

Write-Host ""
Write-Host "起動完了." -ForegroundColor Green
Write-Host ""
Write-Host "=== 全ウィンドウ完了後の手順 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. パッチファイルのジオコード検証:" -ForegroundColor White
Write-Host "   各パッチファイルの住所を一括検証するには:" -ForegroundColor Gray
Write-Host ""
Write-Host "   Get-ChildItem config\address_patches\*.yaml | ForEach-Object {" -ForegroundColor White
Write-Host '     $addrs = (Get-Content $_.FullName -Raw | ConvertFrom-Yaml).Values.Values' -ForegroundColor White
Write-Host '     uv run python scripts/_codex_geocode_check.py @addrs' -ForegroundColor White
Write-Host "   }" -ForegroundColor White
Write-Host ""
Write-Host "2. パッチを address_overrides.yaml にマージ:" -ForegroundColor White
Write-Host "   uv run python scripts/merge_address_patches.py" -ForegroundColor White
Write-Host ""
Write-Host "3. パイプライン再実行で結果を確認:" -ForegroundColor White
Write-Host "   uv run python run.py" -ForegroundColor White
