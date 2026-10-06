param(
  [ValidateSet("all", "unit", "integration", "ui", "image", "fault_injection")]
  [string]$Group = "all",
  [ValidateRange(1, 3600)]
  [int]$TestTimeoutSeconds = 180
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
    "TestAccountSlots.py", "TestAccountTaskOverview.py",
    "TestForgeryQuotaPlan.py", "TestForgeryQuotaProgress.py",
    "TestWorldBossMaterialPlan.py", "TestWorldBossMaterialTask.py", "TestWorldBossMaterialNavigation.py", "TestCombatTaskModes.py",
    "TestTrioCombatRecovery.py", "TestTacetRewardRecovery.py", "TestTacetTargets.py",
    "TestStorySkip.py",
    "TestStorySkipRecovery.py",
    "TestSeaRuinsRecovery.py", "TestSeaExitRecovery.py",
    "TestDailyClaimStability.py", "TestSeaRuins.py", "TestSeaRuinsFlow.py",
    "TestResonanceSimulation.py",
    "TestAbyssCancelRetry.py", "TestAbyssFormationBack.py", "TestAbyssReturnRecovery.py",
    "TestAccountFeatureVerification.py", "TestAllSoloRotations.py", "TestAutoLoginTicks.py",
    "TestBackgroundNavigationTasks.py", "TestBookTabTransitions.py", "TestCharacterNames.py",
    "TestDiagnosticScheduling.py", "TestEchoesContinuation.py", "TestEchoesRemainTask.py",
    "TestEventSpendSafety.py", "TestJingRan.py", "TestMaterialEntry.py", "TestMaterialPagingSafety.py",
    "TestMaterialScrollEdges.py", "TestPostMessageDrag.py", "TestQingxiaoSolo.py",
    "TestRuntimePerformance.py", "TestSoloTeam.py", "TestSpecialistNavigationStatus.py",
    "TestTaskEntryTransitions.py", "TestTriggerNavigation.py", "TestVisionOptimization.py",
    "TestWeeklyTransitions.py",
    "TestDailyFailureRecovery.py", "TestDailyReservePolicy.py", "TestDailyOutcomeRecovery.py", "TestDailyRegressionFlow.py", "TestSeasonDailyRecovery.py", "TestScreenshotExport.py", "TestUITransition.py",
    "TestNavigationAdapter.py", "TestTravelTransitions.py",
    "TestMaterialModel.py", "TestMaterialRepository.py", "TestMaterialCatalog.py", "TestNasLocation.py",
    "TestUpstreamIntegration.py",
    "TestAccountReminders.py",
    "TestCharacterTrial.py", "TestCharacterIdentityRecovery.py", "TestChallengeFailureRecovery.py", "TestWeeklyRewardRecovery.py",
    "TestAutoCombatRecovery.py",
    "TestWeeklyBossTask.py", "TestWeeklyBossPlan.py", "TestWeeklyGardenState.py", "TestMultiAccountWeeklyGardenTask.py", "TestWeeklyNavigation.py", "TestPianoTeaching.py", "TestSecondSolTask.py",
    "TestWindowsGraphicsRecovery.py", "TestMultiStartState.py", "TestHotkeyRegistration.py",
    "test_extract_issue_log.py", "TestAccountConfigEditor.py", "TestAccountDirectoryAssessment.py",
    "TestAccountFieldMetadata.py", "TestAccountGraphStore.py", "TestAccountIdentity.py",
    "TestAccountIdentityProtection.py", "TestAccountProfileStore.py", "TestAccountRepositoryRuntime.py",
    "TestAbyssEnergyRecovery.py", "TestHsinSupport.py",
    "TestAccountRuntimeBootstrap.py", "TestAccountSwitch.py", "TestAbyssTeamPlanner.py", "TestAutoAbyssTask.py",
    "TestBaseCombatTask.py", "TestConfig.py", "TestCustomCharLoader.py", "TestDiagnosisRetention.py",
    "TestDiagnosisTask.py", "TestDomainRecoveryLoop.py", "TestForgeryDomainLabels.py",
    "TestLoggingRedaction.py", "TestMainProxyConfig.py",
    "TestObservability.py", "TestPackageSmoke.py", "TestReleaseReadiness.py", "TestRuntimeServices.py",
    "TestLanUpdateManifest.py", "TestLanUpdateTransport.py", "TestLanUpdatePackage.py",
    "TestLanUpdatePublisher.py", "TestLanUpdateService.py", "TestLanUpdateApply.py",
    "TestScheduleSupport.py", "TestSecurityBaseline.py", "TestSensitiveIdentifierScan.py",
    "TestTaskStatus.py", "TestLogoutCapture.py", "TestDailyTaskStatus.py", "TestDailyActivityFlow.py", "TestStaminaAccounting.py",
    "TestSequenceRepository.py", "TestTestGroups.py", "TestTestRunner.py", "TestGameRuntimeErrors.py", "TestUpstreamCharacterPort.py", "TestWaitLogin.py",
    "TestWin32LoginInput.py"
  )
  integration = @(
    "TestForgeryQuotaIntegration.py",
    "TestDiagnosticArchive.py", "TestDiagnosticArchiveRetention.py", "TestDiagnosticDetails.py",
    "TestStorageBootstrap.py",
    "TestMaterialIntegration.py",
    "TestWeeklyDailyIntegration.py",
    "TestDiagnosticPipeline.py",
    "TestDiagnosticEvidence.py",
    "TestDiagnosticPolicy.py",
    "TestAccountConfigBundle.py", "TestAccountPublishService.py", "TestAccountDeletion.py", "TestSecureBackup.py",
    "TestConfigBackup.py", "TestConfigIntegrity.py", "TestAccountRuntimeIntegration.py",
    "TestAccountSwitchEvidence.py", "TestMultiAccountDailyTask.py", "TestAccountRepositoryMigrationScenario.py"
  )
  ui = @(
    "TestAccountUIPolish.py", "TestForgeryQuotaUI.py",
    "TestWorldBossMaterialUI.py", "TestAbyssPresetUI.py",
    "TestDiagnosticDetailsUI.py",
    "TestTaskInfoSnapshot.py",
    "TestFlatUI.py",
    "TestDiagnosticStatusCard.py",
    "TestDailyRunConfirmation.py",
    "TestAccountManagementTabs.py", "TestCodexLightUI.py", "TestFiveSectionMainWindow.py",
    "TestMainWindowStartup.py", "TestLanUpdateUI.py", "TestNavigationSections.py", "TestTaskNavigationClassification.py",
    "TestCompletionEvidence.py", "TestCompletionCheckUI.py",
    "TestCharacterCodeTab.py", "TestEnhanceEchoStatusBox.py", "TestSkipDialogConfirm.py",
    "TestSkipDialogWideMode.py", "TestTaskStatusWindow.py", "TestUsabilityUI.py"
  )
  image = @(
    "TestStorySkipImages.py", "TestMaterialCombatImages.py", "TestWorldBossMaterialEntryImages.py",
    "TestDailyClaimStabilityImages.py", "TestSeaRuinsImages.py",
    "TestResonanceSimulationImages.py",
    "TestDailyFollowupImages.py", "TestDailyRegressionImages.py", "TestFullStaminaImage.py",
    "TestAbyssReturnImages.py", "TestAbyssSeasonImages.py", "TestBookTabImages.py", "TestEchoesContinuationImages.py",
    "TestEchoesRemainImages.py", "TestQingxiaoSoloImages.py",
    "TestDailyRecoveryImages.py", "TestDailyNasImages.py", "TestWeeklyNasImages.py", "TestNightmareNasImages.py",
    "TestMaterialVision.py",
    "TestCharacterTrialImages.py",
    "TestWeeklyBossImages.py", "TestGardenPageImages.py", "TestRosterConfirmationImages.py", "TestResidualNestImages.py", "TestNewBookEntryImages.py",
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

$groupOrder = @("unit", "integration", "ui", "image", "fault_injection")
$testNames = if ($Group -eq "all") {
  $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($name in ($groupOrder | ForEach-Object { $groups[$_] })) {
    if ($seen.Add($name)) { $name }
  }
} else {
  $groups[$Group]
}

$testFiles = $testNames | ForEach-Object {
  $path = Join-Path ".\tests" $_
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Configured test file does not exist: $path"
  }
  Get-Item -LiteralPath $path
}

if (-not $testFiles) {
  throw "No tests are configured for group '$Group'"
}

$resultDirectory = Join-Path '.\test_out\test_runs' (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
$testFiles | ForEach-Object {
  $testFile = $_
  Write-Host "Running tests in $($testFile.FullName)"
  try {
      $resultPath = Join-Path $resultDirectory ($testFile.BaseName + '.json')
      & $Python .\scripts\run_test_file.py $testFile.FullName --timeout $TestTimeoutSeconds --result-file $resultPath

      if ($LASTEXITCODE -ne 0) {
          throw "Tests failed in $($testFile.FullName)"
      }
  } catch {
      Write-Error $_
      exit 1
  }
}
