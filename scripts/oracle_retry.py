import os
import sys
import time
import subprocess
import oci

def main():
    user_ocid = os.environ.get("OCI_USER_OCID")
    key_content = os.environ.get("OCI_KEY_CONTENT")
    fingerprint = os.environ.get("OCI_FINGERPRINT")
    tenancy_ocid = os.environ.get("OCI_TENANCY_OCID")
    region = os.environ.get("OCI_REGION", "ap-hyderabad-1")
    compartment_ocid = os.environ.get("OCI_COMPARTMENT_OCID", tenancy_ocid)

    missing = [k for k, v in {
        "OCI_USER_OCID": user_ocid,
        "OCI_KEY_CONTENT": key_content,
        "OCI_FINGERPRINT": fingerprint,
        "OCI_TENANCY_OCID": tenancy_ocid,
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

    # 1. Quick initial check
    print("🔍 Checking if 'FRIDAY Universe' instance is already active...")
    try:
        instances = compute_client.list_instances(compartment_id=compartment_ocid).data
        for inst in instances:
            if inst.lifecycle_state in ["RUNNING", "PROVISIONING"]:
                if "A1" in inst.shape or "FRIDAY" in (inst.display_name or ""):
                    print(f"🎉 SUCCESS! Target instance already active: {inst.display_name} ({inst.id})")
                    print(f"Shape: {inst.shape}, State: {inst.lifecycle_state}")
                    return 0
    except Exception as e:
        print(f"⚠️ Warning checking instances: {e}")

    # Launch configuration
    subnet_id = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
    image_id = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
    ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"

    launch_details = oci.core.models.LaunchInstanceDetails(
        display_name="FRIDAY Universe",
        compartment_id=compartment_ocid,
        availability_domain="qvRd:AP-HYDERABAD-1-AD-1",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=1,
            memory_in_gbs=6
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
            boot_volume_size_in_gbs=150,
            boot_volume_vpus_per_gb=10
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            assign_public_ip=True,
            display_name="FRIDAY Universe VNIC",
            subnet_id=subnet_id
        ),
        metadata={
            "ssh_authorized_keys": ssh_key
        },
        is_pv_encryption_in_transit_enabled=True
    )

    # Infinite Relay Configuration:
    # Run for up to 320 minutes (5.3 hours), then trigger next relay job to keep running 24/7 forever
    run_duration_seconds = int(os.environ.get("RUN_DURATION_MINUTES", "320")) * 60
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "30"))

    start_time = time.time()
    attempt = 0

    print(f"🚀 Infinite 24/7 Sniper Active. Retrying every {cycle_delay}s until instance is provisioned...")

    while True:
        attempt += 1
        elapsed_min = round((time.time() - start_time) / 60, 1)

        try:
            inst = compute_client.launch_instance(launch_details).data
            print("\n" + "="*60)
            print("🎉🎉🎉 SUCCESS: AMPERE A1 INSTANCE PROVISIONED! 🎉🎉🎉")
            print(f"Instance ID: {inst.id}")
            print(f"State: {inst.lifecycle_state}")
            print(f"Shape: {inst.shape}")
            print(f"Captured on attempt #{attempt} after {elapsed_min} minutes!")
            print("="*60)
            return 0
        except oci.exceptions.ServiceError as e:
            if e.status == 429:
                print(f"[Attempt #{attempt} | {elapsed_min}m elapsed] Rate limit warning (429). Backing off 20s...")
                time.sleep(20)
                continue
            elif "Out of host capacity" in str(e.message) or e.status in [500]:
                print(f"[Attempt #{attempt} | {elapsed_min}m elapsed] Capacity full in Hyderabad. Retrying in {cycle_delay}s...")
            else:
                print(f"[Attempt #{attempt} | {elapsed_min}m elapsed] OCI Service Error ({e.status}): {e.message}")
        except Exception as e:
            print(f"[Attempt #{attempt}] Unexpected error: {e}")

        # Check if we should pass the baton to the next continuous runner before GitHub 6h timeout
        if time.time() - start_time >= run_duration_seconds:
            print(f"\n⏰ Reached {elapsed_min}m threshold. Passing baton to next 24/7 runner...")
            try:
                subprocess.run(["gh", "workflow", "run", "oracle-capacity-sniper.yml"], check=False)
                print("✅ Next 24/7 sniper relay triggered successfully!")
            except Exception as ex:
                print(f"⚠️ Could not trigger relay via gh CLI: {ex}")
            return 0

        time.sleep(cycle_delay)

if __name__ == "__main__":
    sys.exit(main())
