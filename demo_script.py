import asyncio
import os
import yaml
import tempfile
import sys
from unittest.mock import MagicMock, AsyncMock

# Add current directory to sys.path
sys.path.append(os.getcwd())

from k8s_operator.settings import Settings
from k8s_operator.ai.engine import AIEngine
from k8s_operator.autonomous.control_system import AutonomousControlSystem
from k8s_operator.models.incident import Incident, IncidentStatus, WorkflowStatus
from k8s_operator.models.job import JobStatus
from k8s_operator.models.resource import ResourceInfo

async def run_demo():
    policy = {
        "policies": [
            {
                "name": "OOMKilled_Policy",
                "incident_type": "OOMKilled",
                "backoff": {
                    "base_seconds": 1,
                    "max_seconds": 2,
                    "jitter_seconds": 0
                },
                "workflow": [
                    {"step": 1, "action": "increase_resources"},
                    {"step": 2, "action": "scale_up"}
                ]
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(policy, f)
        policy_path = f.name

    state_store_dir = tempfile.mkdtemp()
    
    try:
        settings = Settings(
            ai_provider='mock',
            dry_run=True,
            enable_autonomous_control=True,
            state_store_path=state_store_dir,
            control_policy_path=policy_path,
            scheduler_poll_interval=1,
            scheduler_worker_concurrency=1
        )

        ai_engine = AIEngine(settings=settings)
        acs = AutonomousControlSystem(settings=settings, ai_engine=ai_engine)

        call_count = {"increase_resources": 0}
        
        async def fake_execute(job):
            print(f"[Executor] Executing {job.action} (attempt {job.retry_count + 1})")
            if job.action == "increase_resources":
                call_count["increase_resources"] += 1
                if call_count["increase_resources"] <= 2:
                    print(f"[Executor] Failing {job.action} as planned")
                    return {"status": "failed", "error": "Simulated Failure"}
                print(f"[Executor] {job.action} succeeded")
                return {"status": "success"}
            elif job.action == "scale_up":
                print(f"[Executor] {job.action} succeeded")
                return {"status": "success"}
            return {"status": "success"}

        acs.remediation_executor.execute = AsyncMock(side_effect=fake_execute)

        acs_task = asyncio.create_task(acs.start())
        print("[Demo] ACS Started")

        incident = Incident(
            id="demo-incident",
            type="OOMKilled",
            resource=ResourceInfo(name="test-pod", namespace="default", kind="Pod"),
            raw_event={"reason": "OOMKilled"},
            status=IncidentStatus.OPEN
        )
        await acs.state_store.save_incident(incident)
        print(f"[Demo] Injected incident: {incident.type} for {incident.resource.name}")

        for _ in range(15):
            inc = await acs.state_store.get_incident(incident.id)
            jobs = await acs.state_store.list_jobs(incident_id=incident.id)
            
            job_info = ""
            if jobs:
                latest_job = jobs[-1]
                job_info = f" | Latest Job: {latest_job.action} ({latest_job.status}, retries: {latest_job.retry_count})"
            
            print(f"[Monitor] Incident Status: {inc.status} | Workflow: {inc.workflow_status}{job_info}")
            
            if inc.status in [IncidentStatus.RESOLVED, IncidentStatus.FAILED]:
                break
            await asyncio.sleep(2)

        print("\n--- Final State ---")
        inc = await acs.state_store.get_incident(incident.id)
        print(f"Incident: {inc.status}")
        print(f"Workflow: {inc.workflow_status}")
        jobs = await acs.state_store.list_jobs(incident_id=incident.id)
        for j in jobs:
            print(f"Job {j.action}: {j.status} (Retries: {j.retry_count})")

        acs.stop()
        await acs_task
        await ai_engine.cleanup()
        print("[Demo] ACS Stopped and Cleaned up")

    finally:
        if os.path.exists(policy_path):
            os.remove(policy_path)

if __name__ == "__main__":
    asyncio.run(run_demo())
