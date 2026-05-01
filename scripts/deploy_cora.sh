#!/usr/bin/env bash
# deploy_cora.sh — Deploy cora_headless scripts to the Cora Z7 and restart the
# doa-controller service. Invoked by the /deploy-cora skill, but also safe to
# run standalone.
#
# Usage:
#   ./scripts/deploy_cora.sh            # deploy + restart service
#   ./scripts/deploy_cora.sh --dry-run  # show what would happen, no changes
#   ./scripts/deploy_cora.sh --no-restart  # copy files, skip service restart

set -eu

CORA_USER="petalinux"
CORA_IP="192.168.1.100"
CORA_DEPLOY_DIR="/home/petalinux/doa/"
HOST_IFACE="enp7s0"
HOST_IP="192.168.1.1/24"
LOCAL_SRC="/home/mau/doa_24ghz_thesis/cora_headless"

DRY_RUN=0
RESTART_SERVICE=1
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-restart) RESTART_SERVICE=0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }
die() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

preflight_checks() {
  # TODO: Fill in pre-flight checks before deploy.
  #
  # This is where the skill's reliability lives. The script will abort if this
  # function returns non-zero. Consider:
  #
  #   1. Host-side static IP: `ip addr show "$HOST_IFACE"` should contain
  #      "$HOST_IP". If missing, the scp will hang. You can either (a) fail
  #      fast and tell the user to run `sudo ip addr add ...`, or (b) try to
  #      add it with `sudo` (needs passwordless sudo for `ip`).
  #
  #   2. Cora reachability: `ping -c1 -W1 "$CORA_IP"` — fail if unreachable.
  #
  #   3. Cora clock sanity: `ssh "$CORA_USER@$CORA_IP" date +%Y` — if it
  #      returns "2018" the clock reset on boot (no RTC). Push host time
  #      with `sudo date -s` so CSV/JSON timestamps are correct. This is the
  #      #1 cause of unusable campaign data.
  #
  #   4. Service state: `ssh "$CORA_USER@$CORA_IP" "systemctl is-active
  #      doa-controller"` — if active, WARN (not error) since restart will
  #      pick up new files; if inactive, NOTE so the user knows to start it.
  #
  #   5. FPGA card identity: the Phase A card has 15 registers at
  #      0x4000_0000 (through 0x38), Phase 0 only has 4 (through 0x0C).
  #      A quick `devmem 0x40000028` check reveals which card is booted —
  #      useful if you're about to deploy v3-only changes to a Phase 0 card.
  #
  # Trade-off you should decide: fail-fast on every check vs. warn-and-continue
  # for "soft" issues like service-not-running. Strict is safer for thesis
  # campaigns; lenient is friendlier for dev iteration.
  #
  # Return 0 to continue, non-zero to abort.

  warn "preflight_checks() not yet implemented — skipping"
  return 0
}

echo "== deploy_cora.sh =="
[ "$DRY_RUN" -eq 1 ] && say "(dry-run mode — no changes will be made)"

preflight_checks || die "pre-flight check failed"

say "Copying Python sources to $CORA_USER@$CORA_IP:$CORA_DEPLOY_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  scp -n "$LOCAL_SRC"/*.py "$CORA_USER@$CORA_IP:$CORA_DEPLOY_DIR"
else
  scp "$LOCAL_SRC"/*.py "$CORA_USER@$CORA_IP:$CORA_DEPLOY_DIR"
  ok "files copied"
fi

if [ "$RESTART_SERVICE" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
  say "Restarting doa-controller service"
  ssh -t "$CORA_USER@$CORA_IP" "sudo /etc/init.d/doa-controller restart" \
    && ok "service restarted" \
    || warn "service restart failed (service may not be installed)"
fi

ok "deploy complete"
