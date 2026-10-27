import os
import sys
import time
import random
import subprocess
import base64
import oci

SUBNET_ID = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
UBUNTU_24_IMAGE = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
UBUNTU_22_IMAGE = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaal66vxpbfui73cgdt2bzw7s2bs7blexelkda5ij7xbtnsct4qmqyq"
SSH_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"

# NOTE: This script must never change friday-universe.duckdns.org.
# Production ingress is pinned to server 1 (140.245.208.100), which fronts all agents via Caddy.
# A newly allocated ARM host is reported through the GitHub issue below; promoting it to public
# ingress is a deliberate manual step, never an automatic side effect of winning capacity.

def generate_cloud_init():
    """Generates a cloud-init bash script executed by Oracle on instance first boot."""
    script = """#!/bin/bash
set -e

# 1. Open firewall for HTTP, HTTPS and the Dokploy dashboard port
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || true
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 3000 -j ACCEPT || true
netfilter-persistent save || true

# 2. Autonomous unattended Dokploy installation
curl -sSL https://dokploy.com/install.sh | sh || true
"""
    return base64.b64encode(script.encode("utf-8")).decode("utf-8")

def make_launch_details(compartment_ocid, ocpus, memory_in_gbs, fault_domain=None, image_id=UBUNTU_24_IMAGE):
    metadata = {
        "ssh_authorized_keys": SSH_KEY,
        "user_data": generate_cloud_init()
    }

    details = oci.core.models.LaunchInstanceDetails(
        display_name="FRIDAY Universe ARM",
        compartment_id=compartment_ocid,
        availability_domain="qvRd:AP-HYDERABAD-1-AD-1",
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=ocpus,
            memory_in_gbs=memory_in_gbs
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
            boot_volume_size_in_gbs=int(os.environ.get("BOOT_VOLUME_GB", "50")),
            boot_volume_vpus_per_gb=10
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            assign_public_ip=True,
            display_name="FRIDAY Universe ARM VNIC",
            subnet_id=SUBNET_ID
        ),
        metadata=metadata,
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

def resolve_instance_public_ip(network_client, compute_client, compartment_id, instance_id):
    """Retrieves the public IP address of an instance once provisioned."""
    print("🌐 Resolving instance public IP address...", end=" ", flush=True)
    for _ in range(15):  # Poll up to 75s
        try:
            vnic_attachments = compute_client.list_vnic_attachments(
                compartment_id=compartment_id,
                instance_id=instance_id
            ).data
            for vnic_att in vnic_attachments:
                if vnic_att.vnic_id:
                    vnic = network_client.get_vnic(vnic_att.vnic_id).data
                    if vnic.public_ip:
                        print(f"[{vnic.public_ip}]")
                        return vnic.public_ip
        except Exception:
            pass
        time.sleep(5)
    print("[IP Assignment Pending]")
    return "Pending Public IP"

def notify_success(instance_id, ocpus, ram, public_ip):
    """Logs markdown summary and creates a GitHub notification issue."""
    summary_md = f"""# 🎉 Oracle Ampere A1 Instance Claimed!

- **Instance OCID**: `{instance_id}`
- **Shape**: `VM.Standard.A1.Flex`
- **Allocation**: {ocpus} OCPUs & {ram} GB RAM
- **Public IP**: `{public_ip}`
- **Production Domain**: `http://friday-universe.duckdns.org` — unchanged, still served by server 1
- **SSH Quick Connect**: `ssh -i C:\\Users\\Surendra\\.ssh\\friday_universe_oracle.key ubuntu@{public_ip}`
- **Cloud-Init Status**: Cloud-init is automatically installing Dokploy and configuring firewall on first boot!
- **Next Step**: Promote this host manually. DuckDNS is intentionally not updated by this workflow.
- **Time**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
"""
    print(summary_md)

    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_path:
        try:
            with open(step_summary_path, "a", encoding="utf-8") as f:
                f.write(summary_md)
        except Exception as e:
            print(f"Could not write to GITHUB_STEP_SUMMARY: {e}")

    try:
        title = f"🎉 Oracle Ampere ARM Server Claimed ({public_ip})"
        body = (
            f"The 24/7 Capacity Sniper has successfully provisioned your Oracle Ampere A1 instance!\n\n"
            f"- **Public IP**: `{public_ip}`\n"
            f"- **OCPUs**: {ocpus}\n"
            f"- **RAM**: {ram} GB\n"
            f"- **Production Domain**: `http://friday-universe.duckdns.org` (unchanged, still on server 1)\n\n"
            f"DuckDNS was deliberately **not** updated. Production ingress stays on server 1 until you\n"
            f"choose to promote this host manually.\n\n"
            f"### SSH Quick Connect:\n"
            f"```bash\n"
            f"ssh -i C:\\Users\\Surendra\\.ssh\\friday_universe_oracle.key ubuntu@{public_ip}\n"
            f"```\n"
        )
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=False)
        print("🔔 GitHub notification issue created successfully!")
    except Exception as e:
        print(f"Could not create GitHub notification issue: {e}")

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
    network_client = oci.core.VirtualNetworkClient(config)

    run_duration_seconds = int(os.environ.get("RUN_DURATION_MINUTES", "320")) * 60
    cycle_delay = int(os.environ.get("CYCLE_DELAY", "45"))

    start_time = time.time()
    attempt = 0

    print("=" * 75)
    print("🚀 HARDENED 24/7 MULTI-TIER ORACLE AMPERE A1 CAPACITY SNIPER INITIALIZING")
    print("   Region: ap-hyderabad-1 (AD-1) | Strict Always Free Limit: 2 OCPUs & 12 GB RAM")
    print("   Targets: 2C/12G (Primary), 2C/8G, 1C/6G, 1C/4G")
    print("   Cadence: 45s intervals + Cloud-Init embedded + In-Place Live Upgrade scaling")
    print("=" * 75)

    active_instance = check_active_arm_instance(compute_client, compartment_ocid)
    if active_instance:
        current_ocpus = active_instance.shape_config.ocpus if active_instance.shape_config else 1
        current_ram = active_instance.shape_config.memory_in_gbs if active_instance.shape_config else 6
        print(f"🔍 Existing ARM instance detected: {active_instance.id} ({current_ocpus} OCPUs, {current_ram} GB RAM, State: {active_instance.lifecycle_state})")

    # High-density target hierarchy: 100% of attempts search across ALL fault domains simultaneously
    TARGET_CONFIGS = [
        {"ocpus": 2, "ram": 12, "fd": None, "img": UBUNTU_24_IMAGE},  # Primary target (ALL 3 fault domains)
        {"ocpus": 1, "ram": 6,  "fd": None, "img": UBUNTU_24_IMAGE},  # 1-core stepping stone (ALL 3 fault domains)
        {"ocpus": 2, "ram": 8,  "fd": None, "img": UBUNTU_24_IMAGE},  # 2-core memory fragmentation fit (ALL 3 fault domains)
        {"ocpus": 1, "ram": 4,  "fd": None, "img": UBUNTU_24_IMAGE},  # 1-core minimal RAM footprint (ALL 3 fault domains)
    ]

    target_idx = 0

    while True:
        attempt += 1
        elapsed_min = round((time.time() - start_time) / 60, 1)

        # Health check every 60 attempts (~45 minutes) to sync instance state
        if attempt % 60 == 0:
            active_instance = check_active_arm_instance(compute_client, compartment_ocid)

        # -------------------------------------------------------------
        # PHASE 2: AUTO-UPGRADE (Instance already secured)
        # -------------------------------------------------------------
        if active_instance:
            current_ocpus = active_instance.shape_config.ocpus if active_instance.shape_config else 1
            current_ram = active_instance.shape_config.memory_in_gbs if active_instance.shape_config else 6

            # If already 2 OCPU and 12 GB (or higher), we are fully done
            if current_ocpus >= 2 and current_ram >= 12:
                pub_ip = resolve_instance_public_ip(network_client, compute_client, compartment_ocid, active_instance.id)
                notify_success(active_instance.id, current_ocpus, current_ram, pub_ip)
                return 0

            # Instance is running on partial specs -> attempt live in-place upgrade
            print(f"[Attempt #{attempt} | {elapsed_min}m] Instance active ({current_ocpus} OCPUs, {current_ram} GB). Upgrading to 2 OCPUs & 12 GB RAM...")
            try:
                update_details = oci.core.models.UpdateInstanceDetails(
                    shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(
                        ocpus=2,
                        memory_in_gbs=12
                    )
                )
                updated = compute_client.update_instance(active_instance.id, update_details).data
                pub_ip = resolve_instance_public_ip(network_client, compute_client, compartment_ocid, updated.id)
                notify_success(updated.id, 2, 12, pub_ip)
                return 0
            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"⚠️ Rate limit (429). Sleeping 90s for full token bucket refill...")
                    time.sleep(90)
                    continue
                elif "Out of host capacity" in str(e.message) or e.status in [500]:
                    print(f"[Attempt #{attempt} | {elapsed_min}m] Full 2 OCPUs / 12 GB not yet released in Hyderabad. Active on {current_ocpus} OCPU / {current_ram} GB. Retrying in {cycle_delay}s...")
                else:
                    print(f"OCI Service Error ({e.status}): {e.message}")
            except Exception as e:
                print(f"Unexpected error during upgrade attempt: {e}")
                time.sleep(10)

        # -------------------------------------------------------------
        # PHASE 1: CAPACITY SNIPER (No instance exists yet)
        # -------------------------------------------------------------
        else:
            cfg = TARGET_CONFIGS[target_idx % len(TARGET_CONFIGS)]
            target_idx += 1
            ocpus = cfg["ocpus"]
            ram = cfg["ram"]
            fd = cfg["fd"]
            img = cfg.get("img", UBUNTU_24_IMAGE)
            fd_label = fd if fd else "Any Fault Domain"

            print(f"[Attempt #{attempt} | {elapsed_min}m] Snipe request: {ocpus} OCPUs, {ram} GB RAM ({fd_label})...", end=" ", flush=True)

            try:
                launch_spec = make_launch_details(compartment_ocid, ocpus=ocpus, memory_in_gbs=ram, fault_domain=fd, image_id=img)
                inst = compute_client.launch_instance(launch_spec).data
                pub_ip = resolve_instance_public_ip(network_client, compute_client, compartment_ocid, inst.id)

                if ocpus >= 2 and ram >= 12:
                    notify_success(inst.id, ocpus, ram, pub_ip)
                    return 0
                else:
                    # Claimed stepping stone server (e.g. 2C/8G, 1C/6G, 4C/24G)!
                    print(f"\n🚀 Server secured ({ocpus} OCPUs, {ram} GB)! Transitioning to live in-place upgrade loop...")
                    notify_success(inst.id, ocpus, ram, pub_ip)
                    active_instance = inst
                    time.sleep(10)
                    continue

            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    print(f"\n⚠️ Rate limit (429). Backing off 90s to refill OCI token bucket...")
                    time.sleep(90)
                    continue
                elif "Out of host capacity" in str(e.message) or e.status in [500]:
                    print("Capacity full.")
                else:
                    print(f"\nOCI Service Error ({e.status}): {e.message}")
                    if "already exists" in str(e.message).lower() or "limit" in str(e.message).lower():
                        active_instance = check_active_arm_instance(compute_client, compartment_ocid)
            except Exception as e:
                print(f"\nUnexpected error during launch: {e}")
                time.sleep(10)

        # Relay check: gracefully hand off to next runner before GitHub Actions timeout
        if time.time() - start_time >= run_duration_seconds:
            print(f"\n⏰ Reached {elapsed_min}m runner threshold. Triggering relay to next runner...")
            try:
                workflow_name = os.environ.get("WORKFLOW_NAME", "oracle-capacity-sniper.yml")
                subprocess.run(["gh", "workflow", "run", workflow_name], check=False)
                print(f"✅ Next 24/7 sniper relay ({workflow_name}) dispatched successfully!")
            except Exception as ex:
                print(f"⚠️ Could not dispatch relay: {ex}")
            return 0

        # Jittered delay to prevent harmonic pattern detection and avoid 429 rate limit
        jittered_sleep = cycle_delay + random.uniform(1.0, 5.0)
        time.sleep(max(42, jittered_sleep))

if __name__ == "__main__":
    sys.exit(main())
