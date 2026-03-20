$action    = New-ScheduledTaskAction `
    -Execute 'C:\Users\OpenClawAgent\Projects\ai-agent\.venv\Scripts\python.exe' `
    -Argument 'C:\Users\OpenClawAgent\Projects\ai-agent\run_pipeline.py' `
    -WorkingDirectory 'C:\Users\OpenClawAgent\Projects\ai-agent'

$trigger   = New-ScheduledTaskTrigger -Daily -At 9am

$principal = New-ScheduledTaskPrincipal `
    -UserId 'OpenClawAgent' `
    -LogonType S4U `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName 'OpenClaw Pipeline' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Force

Write-Host "Task updated - will run at 9am even when locked."
