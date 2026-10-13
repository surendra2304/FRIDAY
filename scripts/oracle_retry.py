import os
import sys
import time
import oci

def main():
    user_ocid = os.environ.get("OCI_USER_OCID")
    key_content = os.environ.get("OCI_KEY_CONTENT")
    fingerprint = os.environ.get("OCI_FINGERPRINT")
    tenancy_ocid = os.environ.get("OCI_TENANCY_OCID")
    region = os.environ.get("OCI_REGION", "ap-hyderabad-1")
    stack_ocid = os.environ.get("OCI_STACK_OCID")
    compartment_ocid = os.environ.get("OCI_COMPARTMENT_OCID", tenancy_ocid)

    missing = [k for k, v in {
        "OCI_USER_OCID": user_ocid,
        "OCI_KEY_CONTENT": key_content,
        "OCI_FINGERPRINT": fingerprint,
        "OCI_TENANCY_OCID": tenancy_ocid,
        "OCI_STACK_OCID": stack_ocid,
    }.items() if not v]

    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    config = {
        "user": user_ocid,
        "key_content": key_content,
        "fingerprint": fingerprint,
        "tenancy": tenancy_ocid,
        "region": region,
    }

    try:
        oci.config.validate_config(config)
    except Exception as e:
        print(f"❌ Invalid OCI configuration: {e}")
        sys.exit(1)

    compute_client = oci.core.ComputeClient(config)
    rm_client = oci.resource_manager.ResourceManagerClient(config)

    print("🔍 Checking if 'FRIDAY Universe' instance is already active...")
    try:
        instances = compute_client.list_instances(compartment_id=compartment_ocid).data
        for inst in instances:
            if inst.lifecycle_state in ["RUNNING", "PROVISIONING"]:
                if "A1" in inst.shape or "FRIDAY" in (inst.display_name or ""):
                    print(f"🎉 SUCCESS! Target instance found: {inst.display_name} ({inst.id})")
                    print(f"Shape: {inst.shape}, State: {inst.lifecycle_state}")
                    return 0
    except Exception as e:
        print(f"⚠️ Warning checking instances: {e}")

    # Retry loop within the workflow run (up to 8 attempts, ~5 minutes total per GitHub Action run)
    max_cycles = int(os.environ.get("MAX_CYCLES", "6"))
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "20"))

    for cycle in range(1, max_cycles + 1):
        print(f"\n--- [Cycle {cycle}/{max_cycles}] Checking / Triggering Stack Apply ---")
        try:
            # Check existing jobs on stack
            jobs = rm_client.list_jobs(
                stack_id=stack_ocid,
                sort_by="TIMECREATED",
                sort_order="DESC",
                limit=3
            ).data

            active_job = None
            if jobs and jobs[0].lifecycle_state in ["ACCEPTED", "IN_PROGRESS"]:
                active_job = jobs[0]
                print(f"Existing job already in flight: {active_job.id} ({active_job.lifecycle_state})")
            else:
                print(f"Submitting new APPLY job to stack: {stack_ocid}")
                create_details = oci.resource_manager.models.CreateJobDetails(
                    stack_id=stack_ocid,
                    operation="APPLY",
                    display_name=f"Sniper-Apply-{int(time.time())}",
                    apply_job_plan_resolution=oci.resource_manager.models.ApplyJobPlanResolutionDetails(
                        is_auto_approved=True
                    )
                )
                active_job = rm_client.create_job(create_details).data
                print(f"Created job: {active_job.id} (State: {active_job.lifecycle_state})")

            # Poll active job until completion or timeout
            job_id = active_job.id
            poll_start = time.time()
            job_done = False

            while time.time() - poll_start < 120:  # Poll up to 2 mins
                time.sleep(10)
                status = rm_client.get_job(job_id).data
                print(f"Job status: {status.lifecycle_state}")

                if status.lifecycle_state == "SUCCEEDED":
                    print("\n" + "="*50)
                    print("🎉🎉🎉 SUCCESS: STACK APPLY SUCCEEDED! 🎉🎉🎉")
                    print("Instance has been provisioned by Oracle Cloud!")
                    print("="*50)
                    return 0
                elif status.lifecycle_state in ["FAILED", "CANCELED"]:
                    print(f"Job finished with state: {status.lifecycle_state} (Out of capacity).")
                    job_done = True
                    break

            if not job_done:
                print("Job is still running. Will check on next cycle.")

        except Exception as e:
            print(f"Error during cycle {cycle}: {e}")

        if cycle < max_cycles:
            print(f"Waiting {cycle_delay}s before next attempt...")
            time.sleep(cycle_delay)

    print("\nCapacity still constrained in this run. Next scheduled GitHub Action will retry automatically.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
