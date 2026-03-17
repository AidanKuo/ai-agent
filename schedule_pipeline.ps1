# schedule_pipeline.ps1
# Run this ONCE to register the pipeline as a Windows Task Scheduler job.
# After running, the pipeline will execute every morning at 8:00 AM automatically.
#
# Usage:
#   .venv\Scripts\Activate.ps1
#   .\schedule_pipeline.ps1

$ProjectDir  = "C:\Users\OpenClawAgent\Projects\ai-agent"
$PythonExe   = "$ProjectDir\.venv\Scripts\python.exe"
$ScriptPath  = "$ProjectDir\run_pipeline.py"
$TaskName    = "OpenClawPipeline"
$RunTime     = "08:00"
$LogFile     = "$ProjectDir\logs\scheduler.log"

# Verify paths exist before registering
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at: $PythonExe"
    Write-Host "Make sure your .venv is set up correctly."
    exit 1
}

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Pipeline script not found at: $ScriptPath"
    exit 1
}

# Build the action — runs python run_pipeline.py from the project directory
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $ScriptPath `
    -WorkingDirectory $ProjectDir

# Daily trigger at 8:00 AM
$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At $RunTime

# Run whether logged in or not, with highest privileges
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -WakeToRun $false

# Remove existing task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "OpenClaw job automation pipeline — scrape, score, notify via Discord" `
    -RunLevel Highest

Write-Host ""
Write-Host "Task registered successfully!" -ForegroundColor Green
Write-Host "  Name:       $TaskName"
Write-Host "  Runs daily: $RunTime"
Write-Host "  Python:     $PythonExe"
Write-Host "  Script:     $ScriptPath"
Write-Host ""
Write-Host "To run it right now to test:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To view logs:"
Write-Host "  Get-Content $LogFile -Tail 50"
Write-Host ""
Write-Host "To remove the task later:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
