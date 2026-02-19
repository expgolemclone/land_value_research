$targets = @(
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\output\ranking_market_cap_ratio_excluded.md',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\output\anomaly_excluded_companies.csv',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\1899_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\5423_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\5563_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\9303_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\9351_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\4044_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\output\4044_output.csv',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\5388_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\output\5388_output.csv',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\cache\pdf\6140_securities_report.pdf',
    'C:\Users\0000250059\Desktop\stock\property\land_value_research\data\output\6140_output.csv',
)

foreach ($path in $targets) {
    if (Test-Path $path) {
        Start-Process $path
    } else {
        Write-Host "not found: $path"
    }
}
