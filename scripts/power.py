"""Statistical power for the arena experiment. Zero dependencies, exact where possible.

Two designs, and they differ enormously in cost:

  BETWEEN-ITEM  each arm gets its own random sample of questions.
                Two-proportion z-test. Wasteful.
  PAIRED        every arm sees THE SAME questions, so a model's response under
                `control` and under `t75` are paired observations on one item.
                Use McNemar on the discordant pairs. This is what arena.py does
                (same item bank across all contracts), and it is far cheaper
                because item difficulty cancels out.

The primary outcome is the ABSTENTION RATE, not accuracy. Under `control` the
observed abstention rate on published GPQA/HLE data is ~0 (0 explicit declines
in 1,980 answers), which is the best possible baseline for detecting a shift:
a one-sided test against p0 ~ 0 needs very few items.
"""
import math


def z(p): # inverse normal CDF, Acklam's rational approximation, |err| < 1.15e-9
    a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,
       1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
    b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,
       6.680131188771972e+01,-1.328068155288572e+01]
    c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,
       -2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00]
    d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,
       3.754408661907416e+00]
    pl,ph=0.02425,1-0.02425
    if p<pl:
        q=math.sqrt(-2*math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p>ph:
        q=math.sqrt(-2*math.log(1-p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q=p-0.5; r=q*q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

def n_two_prop(p1,p2,alpha=0.05,power=0.80,sides=2):
    """Items per arm, two independent proportions."""
    za=z(1-alpha/sides); zb=z(power); pbar=(p1+p2)/2
    num=(za*math.sqrt(2*pbar*(1-pbar))+zb*math.sqrt(p1*(1-p1)+p2*(1-p2)))**2
    return math.ceil(num/ (p1-p2)**2)

def n_mcnemar(p_switch, ratio=0.95, alpha=0.05, power=0.80):
    """Items, paired design. p_switch = fraction of items that CHANGE state
    between arms; ratio = of those, fraction switching in the hypothesised
    direction (abstain under t75 but answered under control)."""
    za=z(1-alpha/2); zb=z(power)
    psi=ratio/(1-ratio) if ratio<1 else 99
    n_disc=((za*math.sqrt(psi+1)+zb*math.sqrt((psi+1)**2-(psi-1)**2*p_switch))**2)/((psi-1)**2*max(p_switch,1e-9))
    return math.ceil(n_disc/max(p_switch,1e-9)*p_switch/max(p_switch,1e-9)), math.ceil(n_disc/p_switch)

def exact_one_sided(p1, n, alpha=0.05):
    """Probability of seeing >=1 abstention in n draws at rate p1 — the relevant
    question when the control rate is literally zero."""
    return 1-(1-p1)**n

print("="*78); print("A. BETWEEN-ITEM (independent samples) — items PER ARM"); print("="*78)
print(f"{'control abstain':>16s} {'treated abstain':>16s} {'n per arm (80% pwr)':>22s} {'n (90% pwr)':>14s}")
for p0,p1 in [(0.00,0.05),(0.00,0.10),(0.01,0.05),(0.01,0.10),(0.02,0.10),
              (0.02,0.20),(0.05,0.15),(0.05,0.25),(0.10,0.30)]:
    p0e=max(p0,0.002)  # exact-zero baseline breaks the normal approximation
    print(f"{p0:16.2f} {p1:16.2f} {n_two_prop(p0e,p1):22d} "
          f"{n_two_prop(p0e,p1,power=0.90):14d}")

print()
print("="*78); print("B. PAIRED (same items across arms) — TOTAL items needed"); print("="*78)
print("p_switch = fraction of items whose answer/abstain state changes between arms")
print(f"{'p_switch':>10s} {'discordant pairs needed':>26s} {'total items':>14s}")
for ps in (0.03,0.05,0.10,0.20,0.30):
    _,tot=n_mcnemar(ps)
    print(f"{ps:10.2f} {math.ceil(tot*ps):26d} {tot:14d}")

print()
print("="*78); print("C. THE ZERO-BASELINE SHORTCUT"); print("="*78)
print("Published control abstention is 0/1980. If a contract induces ANY abstention,")
print("even one instance is evidence. P(observe at least one) at n items:")
print(f"{'true rate':>10s}" + "".join(f"{'n='+str(n):>10s}" for n in (25,50,100,200)))
for p in (0.01,0.02,0.05,0.10,0.20):
    print(f"{p:10.2f}" + "".join(f"{exact_one_sided(p,n):10.3f}" for n in (25,50,100,200)))
print("""
Reading: at a true abstention rate of 5%, 100 items give a 99.4% chance of
seeing at least one abstention. So a FIRST-PASS existence check — "does
announcing the rule make the model ever decline?" — needs ~50-100 items, not
thousands. Estimating the rate PRECISELY is what costs; detecting that it moved
off zero is cheap.

Recommended design:
  Stage 1  50 items x 6 contracts x 2 models  = 600 calls (~$3-8).
           Purpose: does abstention move off zero at all, and do the models
           parse the format? Kill the whole thing here if flat.
  Stage 2  200 items x 6 contracts x 4 models = 4,800 calls (~$25-120).
           Purpose: estimate rates, fit the abstention-vs-t curve, calibration.
  Stage 3  behaviour track, 40 items x 4 contracts x 4 models x 3 reps = 1,920.
           Reps matter here: violation is rare and near-binary, so run-to-run
           variance dominates. Three reps at temperature 1, not one at 0.
""")
