<#
.SYNOPSIS
    低解像度住所を持つ上位N銘柄を並行でリサーチするスクリプト。
.DESCRIPTION
    ranking_market_cap_ratio.md から muni_centroid / oaza_chome を含む企業を抽出し、
    N個の Codex CLI ウィンドウを同時起動してタイル配置する。
    各インスタンスは address_overrides.yaml を直接編集せず、
    config/address_patches/{証券コード}.yaml に個別出力する。
.PARAMETER N
    同時起動するウィンドウ数（デフォルト: 3）
.PARAMETER DryRun
    対象一覧を表示するだけで起動しない
#>
param(
    [int]$N = 1,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$rankingFile = Join-Path $projectRoot "data\output\ranking_market_cap_ratio.md"
$patchDir = Join-Path $projectRoot "config\address_patches"

# --- Step 1: ランキング読み込み＆フィルタ ---

Write-Host "=== 並行 resolve-address ===" -ForegroundColor Cyan
Write-Host "ランキングから低解像度企業を抽出中..."
Write-Host ""

if (-not (Test-Path $rankingFile)) {
    Write-Host "エラー: ランキングファイルが見つかりません: $rankingFile" -ForegroundColor Red
    exit 1
}

$lines = Get-Content $rankingFile -Encoding UTF8

# Markdownテーブルの本体行（ヘッダーとセパレーターを除く）
$dataLines = $lines | Where-Object {
    $_ -match '^\|' -and $_ -notmatch '^\| ---' -and $_ -notmatch '^\| 順位'
}

# muni_centroid または oaza_chome を住所解決タグ列に含む行を抽出
$targets = @()
foreach ($line in $dataLines) {
    $cols = $line -split '\|'
    # cols[0]は空、cols[1]=順位, cols[2]=証券コード, cols[3]=企業名, ..., cols[10]=住所解決タグ
    if ($cols.Count -lt 11) { continue }

    $tag = $cols[10].Trim()
    if ($tag -match 'muni_centroid|oaza_chome') {
        $targets += [PSCustomObject]@{
            Rank = $cols[1].Trim()
            Code = $cols[2].Trim()
            Name = $cols[3].Trim()
            Tag  = $tag
        }
    }
}

if ($targets.Count -eq 0) {
    Write-Host "低解像度企業は見つかりませんでした。" -ForegroundColor Green
    exit 0
}

# 上位N件に絞る
$count = [Math]::Min($N, $targets.Count)
$selected = $targets[0..($count - 1)]

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

# --- Step 2: パッチディレクトリ準備 ---

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
    $codexPrompt = '$' + "resolve-address $code $patchFile"
    $innerCmd = "Set-Location '$projectRoot'; codex --full-auto '$codexPrompt'"

    Write-Host "  [$($i + 1)] codex `$resolve-address $code  -> $patchFile"

    $proc = Start-Process -FilePath "powershell.exe" `
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
Write-Host "起動完了。各ウィンドウでリサーチが終わったら:" -ForegroundColor Green
Write-Host "  python scripts/merge_address_patches.py" -ForegroundColor White
Write-Host "でパッチを address_overrides.yaml にマージしてください。" -ForegroundColor Green
