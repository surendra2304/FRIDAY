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

    # Launch configuration extracted from stack
    subnet_id = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
    image_id = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
    ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"

    launch_details = oci.core.models.LaunchInstanceDetails(
        display_name="FRIDAY Universe",
        compartment_id=compartment_ocid,
        availability_domain="qvRd:AP-HYDERABAD-1-AD-1",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=2,
            memory_in_gbs=12
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

    max_cycles = int(os.environ.get("MAX_CYCLES", "10"))
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "30"))

    print(f"\n🚀 Starting Direct Capacity Sniper ({max_cycles} attempts, {cycle_delay}s delay)...")

    for cycle in range(1, max_cycles + 1):
        print(f"\n--- [Attempt {cycle}/{max_cycles}] Requesting Ampere A1 instance ---")
        try:
            inst = compute_client.launch_instance(launch_details).data
            print("\n" + "="*60)
            print("🎉🎉🎉 SUCCESS: AMPERE A1 INSTANCE PROVISIONED! 🎉🎉🎉")
            print(f"Instance ID: {inst.id}")
            print(f"State: {inst.lifecycle_state}")
            print(f"Shape: {inst.shape}")
            print("="*60)
            return 0
        except oci.exceptions.ServiceError as e:
            if "Out of host capacity" in str(e.message) or e.status in [500, 429]:
                print(f"Status {e.status}: Capacity still full in Hyderabad AD-1.")
            else:
                print(f"OCI Service Error ({e.status}): {e.message}")
        except Exception as e:
            print(f"Unexpected error: {e}")

        if cycle < max_cycles:
            print(f"Waiting {cycle_delay}s before next attempt...")
            time.sleep(cycle_delay)

    print("\nCapacity still unavailable in this run. Next scheduled GitHub Action will retry automatically.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
