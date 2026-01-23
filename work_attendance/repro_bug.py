from ortools.sat.python import cp_model

def solve():
    model = cp_model.CpModel()
    horizon = 10
    min_cons = 4
    
    # Simple setup: 1 employee, pattern: OFF, OFF, B, N, OFF
    # Indices: 0, 1, 2, 3, 4. B=Work, N=Work.
    # We want to force this pattern and see if model is INFEASIBLE.
    
    # 0: OFF
    # 1: OFF
    # 2: WORK
    # 3: WORK
    # 4: OFF
    # 5..9: OFF
    
    # Variables: is_work[d]
    is_work = []
    for d in range(horizon):
        is_work.append(model.NewBoolVar(f"w_{d}"))
        
    # Force the "bad" pattern
    model.Add(is_work[0] == 0)
    model.Add(is_work[1] == 0)
    model.Add(is_work[2] == 1)
    model.Add(is_work[3] == 1)
    model.Add(is_work[4] == 0)
    model.Add(is_work[5] == 0) # Just clean up remainder
    
    # Apply the constraint logic from scheduler.py
    if min_cons > 1:
        for k in range(1, min_cons):
            # k working days not allowed unless extended
            # range(1, horizon - k)
            for d in range(1, horizon - k):
                w_block = model.NewBoolVar(f"w_blk_{d}_{k}")
                # is_work[d]...is_work[d+k-1] are ALL true
                model.AddBoolAnd([is_work[t] for t in range(d, d + k)]).OnlyEnforceIf(w_block)
                # If block matches, then d-1 OR d+k must be work
                model.Add(is_work[d - 1] + is_work[d + k] >= 1).OnlyEnforceIf(w_block)
                
                # IMPORTANT: Also need to link w_block to is_work.
                # In scheduler logic:
                # model.AddBoolAnd(...).OnlyEnforceIf(w_block)
                # This implies w_block => All(is_work).
                # But it does NOT imply All(is_work) => w_block.
                # So the solver can just set w_block = False even if pattern exists!
                # THIS IS THE BUG!
                
                # Correct logic logic for "forbidden pattern":
                # We want: IF (All is_work are true) THEN (extension required).
                # Implementation:
                # model.AddImplication(w_block, requirement)  <-- This means w_block -> requirement
                # But we need "Pattern -> Requirement".
                # Current code:
                # model.AddBoolAnd(...).OnlyEnforceIf(w_block)
                # This means w_block -> Pattern.
                # If Pattern exists, solver can set w_block=False and satisfy "False -> Pattern" (always true).
                # Then requirement is not enforced.
                
                # FIX:
                # We need "Pattern => w_block" OR enforce directly "Pattern => Requirement".
                # model.Add(requirement).OnlyEnforceIf([is_work[t] for t in range(d, d+k)])
                pass

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    print(f"Status: {solver.StatusName(status)}")

if __name__ == "__main__":
    solve()
