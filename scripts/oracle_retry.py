import os
import sys
import time
import random
import subprocess
import oci

SUBNET_ID = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
IMAGE_ID = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
SSH_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"

def make_launch_details(compartment_ocid, ocpus, memory_in_gbs, fault_domain=None):
    details = oci.core.models.LaunchInstanceDetails(
        display_name="FRIDAY Universe",
        compartment_id=compartment_ocid,
        availability_domain="qvRd:AP-HYDERABAD-1-AD-1",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=ocpus,
            memory_in_gbs=memory_in_gbs
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=IMAGE_ID,
            boot_volume_size_in_gbs=150,
            boot_volume_vpus_per_gb=10
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            assign_public_ip=True,
            display_name="FRIDAY Universe VNIC",
            subnet_id=SUBNET_ID
        ),
        metadata={
            "ssh_authorized_keys": SSH_KEY
        },
        is_pv_encryption_in_transit_enabled=True
    )
    if fault_domain:
        details.fault_domain = fault_domain
    return details

def check_active_arm_instance(compute_client, compartment_ocid):
    """Checks if an Ampere A1 instance is already provisioned or active in the tenancy."""
    try:
        instances = compute_client.list_instances(compartment_id=compartment_ocid).data
        for inst in instances:
            if "A1" in (inst.shape or "") and inst.lifecycle_state in ["PROVISIONING", "RUNNING", "STARTING"]:
                return inst
    except Exception as e:
        print(f"⚠️ Warning checking active instances: {e}")
    return None

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

    # Runtime configuration: 300 minutes per GitHub runner leg, 30s base delay between requests
    run_duration_seconds = int(os.environ.get("RUN_DURATION_MINUTES", "300")) * 60
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "30"))

    start_time = time.time()
    attempt = 0

    print("=" * 70)
    print("🚀 HARDENED 24/7 ORACLE AMPERE A1 CAPACITY SNIPER INITIALIZING")
    print("   Target: 2 OCPUs & 12 GB RAM (VM.Standard.A1.Flex) in ap-hyderabad-1")
    print(f"   Rate-limit protection: {cycle_delay}s intervals + Fault Domain rotation + 75s backoff on 429")
    print("=" * 70)

    # Step 0: Check once at startup if instance already exists
    active_instance = check_active_arm_instance(compute_client, compartment_ocid)
    if active_instance:
        current_ocpus = active_instance.shape_config.ocpus if active_instance.shape_config else 1
        print(f"🔍 Existing ARM instance detected: {active_instance.id} (State: {active_instance.lifecycle_state}, OCPUs: {current_ocpus})")

    # Sniper search targets: rotation across fault domains and configurations
    # Prioritizes 2 OCPUs (12 GB RAM), interlaced with 1 OCPU fallback across all 3 fault domains
    TARGET_CONFIGS = [
        {"ocpus": 2, "ram": 12, "fd": "FAULT-DOMAIN-1"},
        {"ocpus": 2, "ram": 12, "fd": "FAULT-DOMAIN-2"},
        {"ocpus": 2, "ram": 12, "fd": "FAULT-DOMAIN-3"},
        {"ocpus": 2, "ram": 12, "fd": None},  # Oracle decides fault domain
        {"ocpus": 1, "ram": 6,  "fd": "FAULT-DOMAIN-1"},
        {"ocpus": 1, "ram": 6,  "fd": "FAULT-DOMAIN-2"},
        {"ocpus": 1, "ram": 6,  "fd": "FAULT-DOMAIN-3"},
        {"ocpus": 1, "ram": 6,  "fd": None},
    ]

    target_idx = 0

    while True:
        attempt += 1
        elapsed_min = round((time.time() - start_time) / 60, 1)

        # Health check every 60 attempts (~30 minutes) to refresh instance status without spamming list_instances
        if attempt % 60 == 0:
            active_instance = check_active_arm_instance(compute_client, compartment_ocid)

        # -------------------------------------------------------------
        # PHASE 2: AUTO-UPGRADE (Instance already exists on 1 OCPU)
        # -------------------------------------------------------------
        if active_instance:
            current_ocpus = active_instance.shape_config.ocpus if active_instance.shape_config else 1
            if current_ocpus >= 2:
                print("\n" + "=" * 70)
                print("🎉🎉🎉 FULL MISSION ACCOMPLISHED: 2 OCPUs & 12 GB RAM ARM ACTIVE! 🎉🎉🎉")
                print(f"Instance ID: {active_instance.id}")
                print(f"Lifecycle State: {active_instance.lifecycle_state}")
                print(f"Shape: {active_instance.shape} | OCPUs: {current_ocpus}")
                print("=" * 70)
                return 0

            # Instance is running on 1 OCPU -> silently attempt upgrade to 2 OCPUs
            print(f"[Attempt #{attempt} | {elapsed_min}m] Instance active on 1 OCPU. Attempting upgrade to 2 OCPUs & 12 GB RAM...")
            try:
                update_details = oci.core.models.UpdateInstanceDetails(
                    shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(
                        ocpus=2,
                        memory_in_gbs=12
                    )
                )
                updated = compute_client.update_instance(active_instance.id, update_details).data
                print("\n" + "=" * 70)
                print("🎉🎉🎉 SUCCESS: AUTOMATICALLY UPGRADED TO 2 OCPUs & 12 GB RAM! 🎉🎉🎉")
                print(f"Instance ID: {updated.id}")
                print(f"State: {updated.lifecycle_state}")
                print("=" * 70)
                return 0
            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"⚠️ Rate limit (429). Sleeping 75s for full token bucket refill...")
                    time.sleep(75)
                    continue
                elif "Out of host capacity" in str(e.message) or e.status in [500]:
                    print(f"[Attempt #{attempt} | {elapsed_min}m] 2nd core not yet released in Hyderabad. Active on 1 OCPU. Retrying in {cycle_delay}s...")
                else:
                    print(f"OCI Service Error ({e.status}): {e.message}")
            except Exception as e:
                print(f"Unexpected error during upgrade attempt: {e}")

        # -------------------------------------------------------------
        # PHASE 1: CAPACITY SNIPER (No instance exists yet)
        # -------------------------------------------------------------
        else:
            cfg = TARGET_CONFIGS[target_idx % len(TARGET_CONFIGS)]
            target_idx += 1
            ocpus = cfg["ocpus"]
            ram = cfg["ram"]
            fd = cfg["fd"]
            fd_label = fd if fd else "Any Fault Domain"

            print(f"[Attempt #{attempt} | {elapsed_min}m] Snipe request: {ocpus} OCPUs, {ram} GB RAM ({fd_label})...", end=" ", flush=True)

            try:
                launch_spec = make_launch_details(compartment_ocid, ocpus=ocpus, memory_in_gbs=ram, fault_domain=fd)
                inst = compute_client.launch_instance(launch_spec).data
                print("\n" + "=" * 70)
                print(f"🎉🎉🎉 SUCCESS: CLAIMED {ocpus} OCPUs & {ram} GB RAM AMPERE SERVER! 🎉🎉🎉")
                print(f"Instance ID: {inst.id}")
                print(f"State: {inst.lifecycle_state}")
                print(f"Fault Domain: {inst.fault_domain}")
                print("=" * 70)

                if ocpus >= 2:
                    return 0
                else:
                    # Claimed 1 OCPU server! Immediately transition to Phase 2 (Auto-Upgrade to 2 OCPUs)
                    print("🚀 Server secured on 1 OCPU! Transitioning to silent 2 OCPU upgrade loop...")
                    active_instance = inst
                    time.sleep(10)
                    continue

            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"\n⚠️ Rate limit (429). Backing off 75s to clear OCI quota...")
                    time.sleep(75)
                    continue
                elif "Out of host capacity" in str(e.message) or e.status in [500]:
                    print(f"Capacity full.")
                else:
                    print(f"\nOCI Service Error ({e.status}): {e.message}")
                    # If error indicates instance already exists, refresh status
                    if "already exists" in str(e.message).lower() or "limit" in str(e.message).lower():
                        active_instance = check_active_arm_instance(compute_client, compartment_ocid)
            except Exception as e:
                print(f"\nUnexpected error: {e}")

        # Relay check: gracefully hand off to next runner before GitHub Actions timeout
        if time.time() - start_time >= run_duration_seconds:
            print(f"\n⏰ Reached {elapsed_min}m runner threshold. Triggering relay to next runner...")
            try:
                subprocess.run(["gh", "workflow", "run", "oracle-capacity-sniper.yml"], check=False)
                print("✅ Next 24/7 sniper relay dispatched successfully!")
            except Exception as ex:
                print(f"⚠️ Could not dispatch relay: {ex}")
            return 0

        # Jittered delay to prevent harmonic pattern detection by Oracle API
        jittered_sleep = cycle_delay + random.uniform(-2, 3)
        time.sleep(max(15, jittered_sleep))

if __name__ == "__main__":
    sys.exit(main())
