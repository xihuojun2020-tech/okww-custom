param(
  [ValidateSet("all", "unit", "integration", "ui", "image", "fault_injection")]
  [string]$Group = "all"
)

$Python = if (Test-Path ".\.venv\Scripts\python.exe") {
  ".\.venv\Scripts\python.exe"
} elseif (Test-Path ".\.venv\bin\python") {
  ".\.venv\bin\python"
} else {
  "python"
}

$groups = @{
  unit = @(
    "TestAccountIdentity.py", "TestAccountIdentityProtection.py", "TestAccountGraphStore.py", "TestRuntimeServices.py", "TestAccountFieldMetadata.py", "TestAccountProfileStore.py",
    "TestAccountRepositoryRuntime.py", "TestSequenceRepository.py", "TestAccountSwitch.py"
  )
  integration = @(
    "TestAccountConfigBundle.py", "TestAccountPublishService.py", "TestAccountDeletion.py", "TestSecureBackup.py",
    "TestConfigBackup.py", "TestConfigIntegrity.py", "TestAccountRuntimeIntegration.py",
    "TestAccountSwitchEvidence.py", "TestMultiAccountDailyTask.py", "TestAccountRepositoryMigrationScenario.py"
  )
  ui = @(
    "TestAccountManagementTabs.py", "TestCodexLightUI.py", "TestFiveSectionMainWindow.py",
    "TestMainWindowStartup.py", "TestNavigationSections.py", "TestTaskNavigationClassification.py",
    "TestCharacterCodeTab.py"
  )
  image = @(
    "TestChar.py", "TestCD.py", "TestCombatCheck.py", "TestCon.py", "TestConfirm.py",
    "TestEcho.py", "TestEnchaneEcho.py", "TestFarmEcho.py", "TestFeatureSet.py", "TestForte.py",
    "TestKey.py", "TestLevitator.py", "TestMap.py", "TestMergeEchoTask.py", "TestNightmareNestTask.py",
    "TestOCR.py", "TestTacet.py", "TestWorld.py"
  )
  fault_injection = @(
    "TestConfigBackup.py", "TestConfigIntegrity.py", "TestAccountConfigBundle.py", "TestSecureBackup.py",
    "TestAccountPublishService.py"
  )
}

$testFiles = if ($Group -eq "all") {
  Get-ChildItem -Path ".\tests\*.py" | Sort-Object Name
} else {
  $groups[$Group] | ForEach-Object {
    $path = Join-Path ".\tests" $_
    if (Test-Path $path) { Get-Item $path }
  }
}

if (-not $testFiles) {
  throw "No tests are configured for group '$Group'"
}

$testFiles | ForEach-Object {
  Write-Host "Running tests in $($_.FullName)"
  try {
      # Run the Python unittest command
      & $Python -m unittest $_.FullName

      # Check if the previous command succeeded
      if ($LASTEXITCODE -ne 0) {
          throw "Tests failed in $($_.FullName)"
      }
  } catch {
      # Stop the loop and return the error
      Write-Error $_
      exit 1
  }
}
