[CmdletBinding()]
param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$AndroidSdkRoot = $env:ANDROID_SDK_ROOT,
    [string]$AndroidJar = '',
    [string]$D8 = '',
    [string]$R8Jar = ''
)
$ErrorActionPreference = 'Stop'

function Require-File([string]$Path, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name was not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

if ([string]::IsNullOrWhiteSpace($JavaHome)) { throw 'JavaHome or JAVA_HOME is required' }
$java = Require-File (Join-Path $JavaHome 'bin\javac.exe') 'javac'
$javaExe = Require-File (Join-Path $JavaHome 'bin\java.exe') 'java'
if ([string]::IsNullOrWhiteSpace($AndroidJar)) {
    if ([string]::IsNullOrWhiteSpace($AndroidSdkRoot)) { throw 'AndroidJar or AndroidSdkRoot is required' }
    $candidate = Get-ChildItem -LiteralPath (Join-Path $AndroidSdkRoot 'platforms') -Filter android.jar -Recurse -File | Sort-Object FullName | Select-Object -Last 1
    if ($null -eq $candidate) { throw 'AndroidJar was not provided and no platform android.jar was found' }
    $AndroidJar = $candidate.FullName
}
$androidJarPath = Require-File $AndroidJar 'android.jar'
if ([string]::IsNullOrWhiteSpace($D8) -and [string]::IsNullOrWhiteSpace($R8Jar)) {
    if ([string]::IsNullOrWhiteSpace($AndroidSdkRoot)) { throw 'D8, R8Jar, or AndroidSdkRoot is required' }
    $D8 = Join-Path $AndroidSdkRoot 'build-tools\35.0.0\d8.bat'
}
$d8Path = if ([string]::IsNullOrWhiteSpace($D8)) { '' } else { Require-File $D8 'd8' }
$r8JarPath = if ([string]::IsNullOrWhiteSpace($R8Jar)) { '' } else { Require-File $R8Jar 'R8 jar' }
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'src\main\java')).Path
$testSourceRoot = Join-Path $PSScriptRoot 'src\test\java'
$build = Join-Path $PSScriptRoot 'build'
$classes = Join-Path $build 'classes'
$testClasses = Join-Path $build 'test-classes'
$dex = Join-Path $build 'dex'
if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Path $classes,$testClasses,$dex | Out-Null
$sources = @(Get-ChildItem -LiteralPath $sourceRoot -Filter *.java -Recurse -File | ForEach-Object { $_.FullName })
if ($sources.Count -eq 0) { throw 'No Java source files found' }
$compileArgs = @('--release', '8', '-encoding', 'UTF-8', '-cp', $androidJarPath, '-d', $classes) + $sources
& $java @compileArgs
if ($LASTEXITCODE -ne 0) {
    $compileArgs = @('-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', $androidJarPath, '-d', $classes) + $sources
    & $java @compileArgs
    if ($LASTEXITCODE -ne 0) { throw "javac failed with exit code $LASTEXITCODE" }
}
$testSources = @(Get-ChildItem -LiteralPath $testSourceRoot -Filter *.java -Recurse -File | ForEach-Object { $_.FullName })
if ($testSources.Count -eq 0) { throw 'No Java self-test sources found' }
$testCompileArgs = @('--release', '8', '-encoding', 'UTF-8', '-cp', "$classes;$androidJarPath", '-d', $testClasses) + $testSources
& $java @testCompileArgs
if ($LASTEXITCODE -ne 0) {
    $testCompileArgs = @('-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', "$classes;$androidJarPath", '-d', $testClasses) + $testSources
    & $java @testCompileArgs
    if ($LASTEXITCODE -ne 0) { throw "Java self-test compilation failed with exit code $LASTEXITCODE" }
}
& $javaExe '-cp' "$testClasses;$classes;$androidJarPath" 'com.okww.combatagent.JsonObjectSelfTest'
if ($LASTEXITCODE -ne 0) { throw "Java self-test failed with exit code $LASTEXITCODE" }
$classFiles = @(Get-ChildItem -LiteralPath $classes -Filter *.class -Recurse -File | ForEach-Object { $_.FullName })
if ($classFiles.Count -eq 0) { throw 'javac produced no class files' }
if ($d8Path -ne '') {
    & $d8Path '--lib' $androidJarPath '--min-api' '26' '--output' $dex @classFiles
} else {
    & $javaExe '-cp' $r8JarPath 'com.android.tools.r8.D8' '--lib' $androidJarPath '--min-api' '26' '--output' $dex @classFiles
}
if ($LASTEXITCODE -ne 0) { throw "d8 failed with exit code $LASTEXITCODE" }
$classesDex = Join-Path $dex 'classes.dex'
Require-File $classesDex 'classes.dex' | Out-Null
$jar = Join-Path $build 'okww-combat-agent.jar'
$jarTool = Join-Path $JavaHome 'bin\jar.exe'
Require-File $jarTool 'jar' | Out-Null
& $jarTool 'cf' $jar '-C' $dex 'classes.dex'
if ($LASTEXITCODE -ne 0) { throw "jar failed with exit code $LASTEXITCODE" }
Require-File $jar 'output jar' | Out-Null
Write-Output $jar
