#!/usr/bin/env bash
# Break a stale migration lock — at most one racer ever succeeds.
#
# The claim this breaks is a SYMLINK whose target is the holder's pid (see
# init.sh): `ln -s` publishes the name and the holder in one syscall, so a
# racer can never see a claimed-but-holderless lock and call it stale.
#
# BREAKING one used to be a read then a delete, and no shell primitive makes
# that pair indivisible. The delete was unconditional, so it could be
# overtaken: P1 verifies the holder is dead, P2 frees the name first, P3
# claims it and is genuinely live, and P1's delete lands on P3's LIVE claim.
# Two processes then hold, both copy, and the final rename is a `[[ -d ]]`
# check one syscall from the `mv` — so the loser buries a whole duplicate
# tree inside the live SMM. Demonstrated reachable, not theoretical.
#
# The fix is to stop deleting a name we do not own. `mv` is an atomic
# single-winner take: of N racers renaming the same name, exactly one
# succeeds and the rest fail (verified — 8 racers, 200 trials, one winner
# every time). So a breaker first TAKES the name, then inspects what it
# took. Having taken it, nothing else can be at that name, so there is no
# second delete left to land on a live claim.
#
# Taking the name is not the same as verifying what was under it. If the
# thing taken is not the corpse we checked, a live claim landed in the gap
# and we put it back with `ln -s` — which fails when the name is occupied,
# giving no-clobber restore out of the same primitive used to claim.
#
# Exit codes are the contract with init.sh, the only caller:
#   0  broke a stale lock; the name is now free
#   1  a live holder is there, or another racer won the break
#   2  nothing was at that name
set -uo pipefail

lock="${1:?lock path required}"

BROKE=0
HELD=1
ABSENT=2

[[ -L "${lock}" || -e "${lock}" ]] || exit "${ABSENT}"

# Inspect before taking, so we know what we expect to be holding.
holder=""
if [[ -L "${lock}" ]]; then
    holder="$(readlink "${lock}" 2>/dev/null || true)"
    # A live, verifiable holder is never touched.
    if [[ "${holder}" =~ ^[0-9]+$ ]] && kill -0 "${holder}" 2>/dev/null; then
        exit "${HELD}"
    fi
fi
# Anything not a symlink — including the directory-shaped lock an OLDER
# version of init.sh wrote — names no holder we can verify. Reaping beats
# yielding forever: an unbreakable lock would pin the SMM in the deletable
# root permanently. `holder` stays empty, so the restore branch cannot match
# and the take is final.

breaking="${lock}.breaking.$$"
# Leave no residue if we die between the take and the disposal.
trap 'rm -rf "${breaking}" 2>/dev/null || true' EXIT

# THE atomic step. Losing this is not a failure — it means another racer is
# the breaker, and this process must not also act as one.
mv "${lock}" "${breaking}" 2>/dev/null || exit "${HELD}"

if [[ -L "${breaking}" ]]; then
    took="$(readlink "${breaking}" 2>/dev/null || true)"
    if [[ -n "${holder}" && "${took}" != "${holder}" ]]; then
        # Not the corpse we verified — someone claimed in the gap between the
        # readlink and the rename. Put it back. `ln -s` refuses an occupied
        # name, so a third party's newer claim wins over our restore.
        if ln -s "${took}" "${lock}" 2>/dev/null; then
            rm -f "${breaking}" 2>/dev/null || true
        fi
        exit "${HELD}"
    fi
fi

rm -rf "${breaking}" 2>/dev/null || true
exit "${BROKE}"
