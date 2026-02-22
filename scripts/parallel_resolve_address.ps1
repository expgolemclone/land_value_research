<#
.SYNOPSIS
    ランキング上位銘柄を並行でリサーチするスクリプト.
.DESCRIPTION
    ranking_market_cap_ratio.md から対象企業を抽出し,
    N個の Codex CLI ウィンドウを同時起動してタイル配置する.
    起動時に調査モードを対話的に選択する:
      [1] resolve-address     — 低解像度住所(muni_centroid/oaza_chome)の番地特定
      [2] split-address — タグ無関係で上位銘柄の含み益を検証
.PARAMETER N
    同時起動するウィンドウ数.
    --N <num> または -N <num> の形式で指定可能.
.PARAMETER DryRun
    対象一覧を表示するだけで起動しない.
    --dry-run または -DryRun で指定可能.
.PARAMETER Mode
    調査モードを直接指定 (対話プロンプトをスキップ).
    --mode resolve-address または --mode split-address
#>
param(
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$_args
)

# --- Argument parsing (supports --N, -N, --dry-run, -DryRun, --mode) ---
$N = 1
$DryRun = $false
$Mode = ""
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
        { $_ -in '--mode', '-Mode' } {
            $i++
            if ($i -ge $_args.Count) {
                Write-Host "エラー: --mode には値が必要です" -ForegroundColor Red
                exit 1
            }
            $Mode = $_args[$i]
            if ($Mode -notin 'resolve-address', 'split-address') {
                Write-Host "エラー: 不明なモード: $Mode" -ForegroundColor Red
                Write-Host "  有効値: resolve-address, split-address" -ForegroundColor Yellow
                exit 1
            }
        }
        default {
            Write-Host "エラー: 不明なオプション: $($_args[$i])" -ForegroundColor Red
            Write-Host "使用法: parallel_resolve_address.ps1 [--N <num>] [--dry-run] [--mode <mode>]" -ForegroundColor Yellow
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

# --- Step 0: 調査モード選択 ---

if ($Mode -eq "") {
    Write-Host ""
    Write-Host "=== 調査モード選択 ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] resolve-address      低解像度住所(muni_centroid/oaza_chome)の番地特定" -ForegroundColor White
    Write-Host "  [2] split-address   上位銘柄の含み益を検証(タグ無関係)" -ForegroundColor White
    Write-Host ""
    do {
        $choice = Read-Host "モードを選択してください (1/2)"
    } while ($choice -notin '1', '2')

    if ($choice -eq '1') {
        $Mode = 'resolve-address'
    } else {
        $Mode = 'split-address'
    }
}

Write-Host ""

# --- Step 1: ランキング読み込み＆フィルタ ---

$modeLabel = if ($Mode -eq 'resolve-address') { '並行 resolve-address' } else { '並行 split-address' }
Write-Host "=== $modeLabel ===" -ForegroundColor Cyan

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
    # cols[0]は空,cols[1]=順位, cols[2]=証券コード, cols[3]=企業名, ..., cols[10]=住所解決タグ
    if ($cols.Count -lt 11) { continue }

    $tag = $cols[10].Trim()

    if ($Mode -eq 'resolve-address') {
        # 低解像度タグを含む企業のみ抽出
        if ($tag -match 'muni_centroid|oaza_chome') {
            $targets += [PSCustomObject]@{
                Rank = $cols[1].Trim()
                Code = $cols[2].Trim()
                Name = $cols[3].Trim()
                Tag  = $tag
            }
        }
    } else {
        # split-address: ランキング上位から全企業を対象
        $targets += [PSCustomObject]@{
            Rank = $cols[1].Trim()
            Code = $cols[2].Trim()
            Name = $cols[3].Trim()
            Tag  = $tag
        }
    }
}

if ($targets.Count -eq 0) {
    if ($Mode -eq 'resolve-address') {
        Write-Host "低解像度企業は見つかりませんでした." -ForegroundColor Green
    } else {
        Write-Host "ランキングに企業が見つかりませんでした." -ForegroundColor Green
    }
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

if ($DryRun) {
    Write-Host "(DryRun: ここで終了)" -ForegroundColor Gray
    exit 0
}

# --- Step 2: パッチディレクトリ準備 (両モード共通) ---

if (Test-Path $patchDir) {
    Remove-Item (Join-Path $patchDir "*.yaml") -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path $patchDir | Out-Null
}
Write-Host "パッチディレクトリ: $patchDir" -ForegroundColor Gray
Write-Host ""

# --- Step 3: N個のウィンドウを同時起動＆タイル配置 ---

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
    # SKILL.md が config/address_patches/ パスを検出してパッチモードで動作する
    $codexPrompt = '$' + "$Mode $code $patchFile"
    Write-Host "  [$($i + 1)] codex `$$Mode $code  -> $patchFile"

    $innerCmd = "`$env:CD = '$projectRoot'; codex --full-auto '$codexPrompt'"

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
Write-Host "各ウィンドウでリサーチが終わったら:" -ForegroundColor Green
Write-Host "  python scripts/merge_address_patches.py" -ForegroundColor White
Write-Host "でパッチを address_overrides.yaml にマージしてください." -ForegroundColor Green
