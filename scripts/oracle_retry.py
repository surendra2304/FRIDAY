import os
import sys
import time
import subprocess
import oci

def make_launch_details(compartment_ocid, ocpus, memory_in_gbs):
    subnet_id = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
    image_id = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
    ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"

    return oci.core.models.LaunchInstanceDetails(
        display_name="FRIDAY Universe",
        compartment_id=compartment_ocid,
        availability_domain="qvRd:AP-HYDERABAD-1-AD-1",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=ocpus,
            memory_in_gbs=memory_in_gbs
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

    # Execution limits (up to 320 minutes per GitHub runner leg, then relays to next runner)
    run_duration_seconds = int(os.environ.get("RUN_DURATION_MINUTES", "320")) * 60
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "10"))

    start_time = time.time()
    attempt = 0

    print("🚀 Auto-Sniper & Auto-Upgrader Active (2 OCPU Priority -> 1 OCPU Fallback -> Auto-Upgrade to 2 OCPUs)")

    while True:
        attempt += 1
        elapsed_min = round((time.time() - start_time) / 60, 1)

        # 1. Inspect current active instances in tenancy
        active_instance = None
        try:
            instances = compute_client.list_instances(compartment_id=compartment_ocid).data
            for inst in instances:
                    # Specifically target Ampere A1 (ARM) instances so AMD micro instances are ignored
                    if "A1" in (inst.shape or ""):
                        active_instance = inst
                        break
        except Exception as e:
            print(f"[Attempt #{attempt}] Warning checking instances: {e}")

        # -------------------------------------------------------------
        # PHASE 2: AUTO-UPGRADE (Instance already exists)
        # -------------------------------------------------------------
        if active_instance:
            current_ocpus = active_instance.shape_config.ocpus if active_instance.shape_config else 1
            if current_ocpus >= 2:
                print("\n" + "="*60)
                print("🎉🎉🎉 FULL GOAL ACHIEVED: 2 OCPUs & 12 GB RAM ACTIVE! 🎉🎉🎉")
                print(f"Instance ID: {active_instance.id}")
                print(f"State: {active_instance.lifecycle_state}")
                print(f"OCPUs: {current_ocpus}")
                print("="*60)
                return 0

            # Instance is on 1 OCPU -> attempt silent automatic upgrade to 2 OCPUs
            print(f"[Attempt #{attempt} | {elapsed_min}m] Instance active on 1 OCPU. Attempting upgrade to 2 OCPUs & 12 GB RAM...")
            try:
                update_details = oci.core.models.UpdateInstanceDetails(
                    shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(
                        ocpus=2,
                        memory_in_gbs=12
                    )
                )
                updated = compute_client.update_instance(active_instance.id, update_details).data
                print("\n" + "="*60)
                print("🎉🎉🎉 SUCCESS: AUTOMATICALLY UPGRADED TO 2 OCPUs & 12 GB RAM! 🎉🎉🎉")
                print(f"Instance ID: {updated.id}")
                print(f"State: {updated.lifecycle_state}")
                print("="*60)
                return 0
            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"Rate limit (429). Backing off 20s...")
                    time.sleep(20)
                    continue
                elif "Out of host capacity" in str(e.message) or e.status in [500]:
                    print(f"2nd core not yet free in Hyderabad. Server running on 1 OCPU. Retrying upgrade in {cycle_delay}s...")
                else:
                    print(f"OCI Service Error ({e.status}): {e.message}")
            except Exception as e:
                print(f"Unexpected error during upgrade: {e}")

        # -------------------------------------------------------------
        # PHASE 1: SERVER CREATION (No instance exists yet)
        # -------------------------------------------------------------
        else:
            # Step A: First try claiming 2 OCPUs directly
            try:
                launch_2 = make_launch_details(compartment_ocid, ocpus=2, memory_in_gbs=12)
                inst = compute_client.launch_instance(launch_2).data
                print("\n" + "="*60)
                print("🎉🎉🎉 SUCCESS: DIRECT 2 OCPUs & 12 GB RAM SERVER CLAIMED! 🎉🎉🎉")
                print(f"Instance ID: {inst.id}")
                print(f"State: {inst.lifecycle_state}")
                print("="*60)
                return 0
            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"Rate limit (429). Backing off 20s...")
                    time.sleep(20)
                    continue

                # Step B: If 2 OCPUs is out of capacity, immediately try 1 OCPU
                if "Out of host capacity" in str(e.message) or e.status in [500]:
                    try:
                        launch_1 = make_launch_details(compartment_ocid, ocpus=1, memory_in_gbs=6)
                        inst_1 = compute_client.launch_instance(launch_1).data
                        print("\n" + "="*60)
                        print("🎉 CLAIMED 1 OCPU SERVER! Now seamlessly switching to auto-upgrade loop...")
                        print(f"Instance ID: {inst_1.id}")
                        print("="*60)
                        time.sleep(5)
                        continue # Next loop iteration enters Phase 2 (Auto-Upgrade to 2 OCPUs)
                    except oci.exceptions.ServiceError as e2:
                        if e2.status == 429:
                            time.sleep(20)
                            continue
                        elif "Out of host capacity" in str(e2.message) or e2.status in [500]:
                            print(f"[Attempt #{attempt} | {elapsed_min}m] 2 OCPU & 1 OCPU both full in Hyderabad. Retrying in {cycle_delay}s...")
                        else:
                            print(f"OCI Service Error on 1 OCPU ({e2.status}): {e2.message}")
                else:
                    print(f"OCI Service Error on 2 OCPU ({e.status}): {e.message}")
            except Exception as e:
                print(f"Unexpected error during launch: {e}")

        # Check relay threshold
        if time.time() - start_time >= run_duration_seconds:
            print(f"\n⏰ Reached {elapsed_min}m threshold. Passing baton to next 24/7 runner...")
            try:
                subprocess.run(["gh", "workflow", "run", "oracle-capacity-sniper.yml"], check=False)
                print("✅ Next 24/7 sniper relay triggered successfully!")
            except Exception as ex:
                print(f"⚠️ Could not trigger relay: {ex}")
            return 0

        time.sleep(cycle_delay)

if __name__ == "__main__":
    sys.exit(main())
