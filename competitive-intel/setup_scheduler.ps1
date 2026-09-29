# Zaregistruje týdenní spouštění scraperu v Task Scheduleru Windows
# Spusť jednou: pravý klik → "Spustit jako správce"

$taskName   = "Competitive Intel Scraper"
$batPath    = "C:\Users\lucie.hlubkova\OneDrive - Direct\Dokumenty\AI\Sledování konkurence\cowork_competitive report\competitive-intel\run_scraper.bat"
$logDir     = "C:\Users\lucie.hlubkova\OneDrive - Direct\Dokumenty\AI\Sledování konkurence\cowork_competitive report\competitive-intel\logs"

# Trigger: každé pondělí v 9:30
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "09:30"

# Akce: spustit .bat soubor
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""

# Nastavení: spustit jen když je uživatel přihlášen (headed browser potřebuje display)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Registrace (přepíše existující úlohu stejného jména)
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "✅ Hotovo. Úloha '$taskName' je zaregistrována." -ForegroundColor Green
Write-Host "   Spouští se: každé pondělí v 9:30"
Write-Host "   Log: $logDir\scheduler.log"
Write-Host ""
Write-Host "Ověření v Task Scheduleru: Win+R → taskschd.msc → Task Scheduler Library"
