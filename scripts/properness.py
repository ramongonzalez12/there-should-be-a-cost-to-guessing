"""Which scoring rules actually elicit honest probabilities — checked numerically.

A rule is PROPER if a model maximises its expected score by reporting its true
belief q. If it isn't, the model's best play is to misreport, and every
calibration number you compute afterwards is measuring the misreport.
"""
import math


def linear(p, correct):      # Ramon's proposed rule: +p if right, -p if wrong
    return p if correct else -p

def quadratic(p, correct):   # Selten's quadratic rule (= Brier, rescaled)
    return 2*p - p*p if correct else -p*p

def log_rule(p, correct, eps=1e-3):   # unique LOCAL proper rule
    p = min(max(p, eps), 1-eps)
    return 1 + math.log2(p) if correct else 1 + math.log2(1-p)

def spherical(p, correct):
    # Proper form: score the reported probability of the outcome that HAPPENED,
    # normalised by the norm of the reported distribution. Both branches are
    # positive; writing the wrong branch as negative breaks properness.
    d = math.sqrt(p*p + (1-p)*(1-p))
    return (p if correct else (1-p)) / d

def quad_cost(p, correct, c=0.09):
    """Quadratic proper score MINUS a fixed cost c for asserting anything.

    The quadratic rule alone never induces abstention: expected score at the
    honest report is q^2 >= 0, so answering with a tiny p weakly dominates
    silence. Subtracting a cost c from every non-abstention makes the
    answer-vs-abstain break-even q^2 > c, i.e. q > sqrt(c). c is the price of
    putting a claim into the world; sqrt(c) is the abstention threshold, and it
    is the same t as Kalai's -- but now the probability is elicited honestly
    instead of being collapsed into a yes/no decision."""
    return (2*p - p*p if correct else -p*p) - c

def kalai(p, correct, t=0.75):  # threshold rule: report is a DECISION, not a probability
    if p <= t: return 0.0
    return 1.0 if correct else -t/(1-t)

RULES = {"linear (yours)": linear, "quadratic": quadratic, "quad+cost": quad_cost,
         "log": log_rule, "spherical": spherical, "kalai t=.75": kalai}

GRID = [i/200 for i in range(201)]

def best_report(rule, q):
    """The p that maximises expected score when the model truly believes q."""
    ev = lambda p: q*rule(p, True) + (1-q)*rule(p, False)
    return max(GRID, key=lambda p: (round(ev(p), 12), -abs(p-q)))

print("OPTIMAL REPORTED PROBABILITY p*, given a true belief q")
print("A proper rule has p* = q on the diagonal.\n")
hdr = f"{'true q':>7s}" + "".join(f"{name:>16s}" for name in RULES)
print(hdr); print("-"*len(hdr))
for q in (0.05,0.20,0.35,0.45,0.50,0.55,0.65,0.80,0.95):
    print(f"{q:7.2f}" + "".join(f"{best_report(r,q):16.2f}" for r in RULES.values()))

print("\nMAX |p* - q| over q in [0,1] (0 = strictly proper):")
for name, r in RULES.items():
    worst = max(abs(best_report(r,q)-q) for q in GRID[1:-1])
    print(f"  {name:16s} {worst:6.3f}   {'PROPER' if worst < 0.02 else 'IMPROPER'}")

print("""
Why the linear rule degenerates, in one line:
  EV(p) = q*p + (1-q)*(-p) = p*(2q - 1)
which is LINEAR in p, so the optimum is always a corner. Report p=1 whenever you
think you are more likely right than wrong, else p=0. A linear payoff is a bet,
and the optimal bet size under a linear payoff is all-in or nothing.

The fix is one squared term:
  EV(p) = q*(2p - p^2) + (1-q)*(-p^2) = 2qp - p^2,  d/dp = 2q - 2p = 0  =>  p = q.
Concavity in p is exactly what turns a corner solution into an interior one at
the honest belief. Same [-1, +1] range, same 'no answer = 0', and p=0 is
continuous with abstaining -- so it keeps everything you wanted.
""")

print("ABSTENTION: does the rule ever make silence optimal?")
print("Expected score of the best ANSWER vs the score of abstaining (0).\n")
print(f"{'true q':>7s} {'quadratic EV':>14s} {'quad+cost EV':>14s} {'answer?':>9s}")
print("-"*48)
for q in (0.05,0.15,0.25,0.30,0.35,0.50,0.75,0.95):
    ev_q  = max(q*quadratic(p,True)+(1-q)*quadratic(p,False) for p in GRID)
    ev_qc = max(q*quad_cost(p,True)+(1-q)*quad_cost(p,False) for p in GRID)
    print(f"{q:7.2f} {ev_q:14.3f} {ev_qc:14.3f} {('yes' if ev_qc>0 else 'ABSTAIN'):>9s}")
print("""
  Pure quadratic: EV at the honest report is exactly q^2, which is >= 0 for
  every q. So the model always answers -- it just answers with a small p. That
  is elegant (p -> 0 IS the abstention, continuously) but gives you no lever if
  a wrong assertion has costs beyond the score, which in deployment it does.

  quad+cost with c = 0.09: break-even at q = sqrt(0.09) = 0.30. Below that,
  silence beats any answer. You now have BOTH honest probability elicitation
  AND a tunable abstention threshold, from one interpretable knob: c is what it
  costs to make a claim.
""")
