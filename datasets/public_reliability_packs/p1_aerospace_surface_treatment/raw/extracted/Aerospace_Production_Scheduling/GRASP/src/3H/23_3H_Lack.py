"""
GAMSPy — gerado automaticamente de: 23_3H_Lack.gms
Conversor: gms_to_gamspy_converter.py

INSTALAÇÃO:
    pip install gamspy pandas
    gamspy install solver highs

EXECUÇÃO:
    python 23_3H_Lack.py
"""

import os, sys, time
import pandas as pd
from gamspy import (
    Container, Set, Parameter, Variable,
    Equation, Model, Sum, Sense, Options
)

# ── Opções ────────────────────────────────────────────────────────
m = Container()
options = Options(time_limit=10800, relative_optimality_gap=0.0)

# ── Sets ──────────────────────────────────────────────────────────
T = Set(m, "T", records=[str(t) for t in range(1, 65 + 1)],
        description="Production Period /1*65/")
K = Set(m, "K", records=["K1", "K2"],      description="Tank knapsack")
F = Set(m, "F", records=[str(f) for f in range(1, 10 + 1)],
        description="Clamping Device /1*10/")
G = Set(m, "G", records=["B1", "B2", "B6", "LTS30"],
        description="Groups by Raw Material")
I = Set(m, "I", records=[
        "830D0100",
        "829D0100",
        "787A0100",
        "1320_0101",
        "831A0600",
        "1806_041",
        "1806D0900",
        "1806A0800",
        "1312_0101",
        "1806_5051",
        "1806A0200",
        "4774_0002",
        "1567A0100",
        "4775_0002",
        "810A0400",
        "786A0900",
        "786A0600",
        "786A0700",
        "926_0102",
        "3445A1800",
        "3957A0600",
        "4778_0102",
        "3958A0600",
        "1386A2200",
        "6896A0100",
        "1556A0200",
        "1559A0200",
        "1555A0200",
        "60078_0900",
        "1553A0200",
        "1554A0200",
        "341_0250",
        "60091_011",
        "4781A0100",
        "342_0460",
        "S4_9504612",
        "S4_9504622",
        "6774_01030",
        "6754_0481",
        "3470_085",
        "6753_02011",
        "S4_9704411",
        "918_0102",
        "920A0100",
        "5450A0000",
        "1394_0101",
        "6864_0280",
        "1568_0101",
        "6884_2011",
        "6885_2011",
        "6886_2011",
        "6887_2011",
        "6898A0100",
        "6724_0941",
        "1964A2200",
        "6882_2011",
        "6883_2011",
        "6888_2011",
        "798_0184",
        "962A0100",
        "S4_9704300",
        "1642A0400",
        "70069_23",
        "6724_0271",
        "2434A2200",
        "3470_028"
    ],
        description="Items")

# ── Parâmetros ────────────────────────────────────────────────────
_gm_df = pd.DataFrame([
    ("830D0100", "B2"),
    ("829D0100", "B2"),
    ("787A0100", "B2"),
    ("1320_0101", "LTS30"),
    ("831A0600", "B2"),
    ("1806_041", "LTS30"),
    ("1806D0900", "LTS30"),
    ("1806A0800", "LTS30"),
    ("1312_0101", "LTS30"),
    ("1806_5051", "LTS30"),
    ("1806A0200", "B1"),
    ("4774_0002", "B2"),
    ("1567A0100", "B2"),
    ("4775_0002", "B2"),
    ("810A0400", "B2"),
    ("786A0900", "B2"),
    ("786A0600", "B1"),
    ("786A0700", "B1"),
    ("926_0102", "B1"),
    ("3445A1800", "LTS30"),
    ("3957A0600", "LTS30"),
    ("4778_0102", "B2"),
    ("3958A0600", "LTS30"),
    ("1386A2200", "B2"),
    ("6896A0100", "B2"),
    ("1556A0200", "B2"),
    ("1559A0200", "B2"),
    ("1555A0200", "B2"),
    ("60078_0900", "LTS30"),
    ("1553A0200", "B2"),
    ("1554A0200", "B2"),
    ("341_0250", "LTS30"),
    ("60091_011", "LTS30"),
    ("4781A0100", "B2"),
    ("342_0460", "LTS30"),
    ("S4_9504612", "B1"),
    ("S4_9504622", "B1"),
    ("6774_01030", "LTS30"),
    ("6754_0481", "LTS30"),
    ("3470_085", "LTS30"),
    ("6753_02011", "LTS30"),
    ("S4_9704411", "B2"),
    ("918_0102", "B1"),
    ("920A0100", "B2"),
    ("5450A0000", "B2"),
    ("1394_0101", "LTS30"),
    ("6864_0280", "LTS30"),
    ("1568_0101", "LTS30"),
    ("6884_2011", "B2"),
    ("6885_2011", "B2"),
    ("6886_2011", "B2"),
    ("6887_2011", "B2"),
    ("6898A0100", "B2"),
    ("6724_0941", "LTS30"),
    ("1964A2200", "B2"),
    ("6882_2011", "B2"),
    ("6883_2011", "B2"),
    ("6888_2011", "B2"),
    ("798_0184", "LTS30"),
    ("962A0100", "LTS30"),
    ("S4_9704300", "B6"),
    ("1642A0400", "B6"),
    ("70069_23", "LTS30"),
    ("6724_0271", "LTS30"),
    ("2434A2200", "B2"),
    ("3470_028", "LTS30"),
], columns=["i", "g"])
_gm_df["value"] = 1.0
GM = Parameter(m, "GM", domain=[I, G], records=_gm_df,
               description="Material Group g of Item i")

IE = Parameter(m, "IE", domain=[I],
               records=[
        ("830D0100", 0),
        ("829D0100", 35),
        ("787A0100", 0),
        ("1320_0101", 71),
        ("831A0600", 40),
        ("1806_041", 0),
        ("1806D0900", 0),
        ("1806A0800", 100),
        ("1312_0101", 52),
        ("1806_5051", 0),
        ("1806A0200", 38),
        ("4774_0002", 0),
        ("1567A0100", 40),
        ("4775_0002", 108),
        ("810A0400", 40),
        ("786A0900", 60),
        ("786A0600", 56),
        ("786A0700", 30),
        ("926_0102", 54),
        ("3445A1800", 0),
        ("3957A0600", 114),
        ("4778_0102", 0),
        ("3958A0600", 90),
        ("1386A2200", 56),
        ("6896A0100", 0),
        ("1556A0200", 20),
        ("1559A0200", 20),
        ("1555A0200", 19),
        ("60078_0900", 47),
        ("1553A0200", 15),
        ("1554A0200", 15),
        ("341_0250", 45),
        ("60091_011", 30),
        ("4781A0100", 0),
        ("342_0460", 0),
        ("S4_9504612", 30),
        ("S4_9504622", 30),
        ("6774_01030", 50),
        ("6754_0481", 0),
        ("3470_085", 30),
        ("6753_02011", 50),
        ("S4_9704411", 0),
        ("918_0102", 0),
        ("920A0100", 0),
        ("5450A0000", 0),
        ("1394_0101", 30),
        ("6864_0280", 11),
        ("1568_0101", 20),
        ("6884_2011", 0),
        ("6885_2011", 0),
        ("6886_2011", 0),
        ("6887_2011", 0),
        ("6898A0100", 0),
        ("6724_0941", 20),
        ("1964A2200", 30),
        ("6882_2011", 0),
        ("6883_2011", 0),
        ("6888_2011", 0),
        ("798_0184", 17),
        ("962A0100", 18),
        ("S4_9704300", 0),
        ("1642A0400", 30),
        ("70069_23", 0),
        ("6724_0271", 0),
        ("2434A2200", 40),
        ("3470_028", 30),
    ],
               description="Available Quantity of Item i")

IF_ = Parameter(m, "IF_", domain=[I],
                records=[
        ("830D0100", 12),
        ("829D0100", 12),
        ("787A0100", 3),
        ("1320_0101", 24),
        ("831A0600", 10),
        ("1806_041", 2),
        ("1806D0900", 60),
        ("1806A0800", 12),
        ("1312_0101", 24),
        ("1806_5051", 10),
        ("1806A0200", 2),
        ("4774_0002", 12),
        ("1567A0100", 6),
        ("4775_0002", 12),
        ("810A0400", 12),
        ("786A0900", 6),
        ("786A0600", 3),
        ("786A0700", 8),
        ("926_0102", 12),
        ("3445A1800", 6),
        ("3957A0600", 24),
        ("4778_0102", 8),
        ("3958A0600", 24),
        ("1386A2200", 12),
        ("6896A0100", 12),
        ("1556A0200", 12),
        ("1559A0200", 12),
        ("1555A0200", 12),
        ("60078_0900", 12),
        ("1553A0200", 12),
        ("1554A0200", 8),
        ("341_0250", 12),
        ("60091_011", 12),
        ("4781A0100", 8),
        ("342_0460", 12),
        ("S4_9504612", 21),
        ("S4_9504622", 21),
        ("6774_01030", 12),
        ("6754_0481", 12),
        ("3470_085", 6),
        ("6753_02011", 12),
        ("S4_9704411", 6),
        ("918_0102", 15),
        ("920A0100", 8),
        ("5450A0000", 12),
        ("1394_0101", 24),
        ("6864_0280", 4),
        ("1568_0101", 24),
        ("6884_2011", 8),
        ("6885_2011", 8),
        ("6886_2011", 8),
        ("6887_2011", 8),
        ("6898A0100", 12),
        ("6724_0941", 12),
        ("1964A2200", 8),
        ("6882_2011", 8),
        ("6883_2011", 8),
        ("6888_2011", 8),
        ("798_0184", 5),
        ("962A0100", 6),
        ("S4_9704300", 6),
        ("1642A0400", 6),
        ("70069_23", 12),
        ("6724_0271", 12),
        ("2434A2200", 6),
        ("3470_028", 6),
    ],
                description="Max Pieces of Item i per Fixing Device")

_fk_df = pd.DataFrame([
    ("830D0100", "K1", 5),
    ("830D0100", "K2", 2),
    ("829D0100", "K1", 5),
    ("829D0100", "K2", 2),
    ("787A0100", "K1", 7),
    ("787A0100", "K2", 3),
    ("1320_0101", "K1", 5),
    ("1320_0101", "K2", 2),
    ("831A0600", "K1", 9),
    ("831A0600", "K2", 4),
    ("1806_041", "K1", 6),
    ("1806_041", "K2", 2),
    ("1806D0900", "K1", 10),
    ("1806D0900", "K2", 4),
    ("1806A0800", "K1", 7),
    ("1806A0800", "K2", 3),
    ("1312_0101", "K1", 5),
    ("1312_0101", "K2", 2),
    ("1806_5051", "K1", 6),
    ("1806_5051", "K2", 3),
    ("1806A0200", "K1", 6),
    ("1806A0200", "K2", 3),
    ("4774_0002", "K1", 5),
    ("4774_0002", "K2", 2),
    ("1567A0100", "K1", 8),
    ("1567A0100", "K2", 3),
    ("4775_0002", "K1", 5),
    ("4775_0002", "K2", 2),
    ("810A0400", "K1", 5),
    ("810A0400", "K2", 2),
    ("786A0900", "K1", 9),
    ("786A0900", "K2", 4),
    ("786A0600", "K1", 7),
    ("786A0600", "K2", 2),
    ("786A0700", "K1", 5),
    ("786A0700", "K2", 2),
    ("926_0102", "K1", 5),
    ("926_0102", "K2", 2),
    ("3445A1800", "K1", 8),
    ("3445A1800", "K2", 4),
    ("3957A0600", "K1", 5),
    ("3957A0600", "K2", 2),
    ("4778_0102", "K1", 5),
    ("4778_0102", "K2", 2),
    ("3958A0600", "K1", 5),
    ("3958A0600", "K2", 2),
    ("1386A2200", "K1", 5),
    ("1386A2200", "K2", 2),
    ("6896A0100", "K1", 5),
    ("6896A0100", "K2", 2),
    ("1556A0200", "K1", 5),
    ("1556A0200", "K2", 2),
    ("1559A0200", "K1", 5),
    ("1559A0200", "K2", 2),
    ("1555A0200", "K1", 5),
    ("1555A0200", "K2", 2),
    ("60078_0900", "K1", 8),
    ("60078_0900", "K2", 4),
    ("1553A0200", "K1", 5),
    ("1553A0200", "K2", 2),
    ("1554A0200", "K1", 5),
    ("1554A0200", "K2", 2),
    ("341_0250", "K1", 7),
    ("341_0250", "K2", 3),
    ("60091_011", "K1", 7),
    ("60091_011", "K2", 3),
    ("4781A0100", "K1", 5),
    ("4781A0100", "K2", 2),
    ("342_0460", "K1", 9),
    ("342_0460", "K2", 4),
    ("S4_9504612", "K1", 5),
    ("S4_9504612", "K2", 2),
    ("S4_9504622", "K1", 5),
    ("S4_9504622", "K2", 2),
    ("6774_01030", "K1", 7),
    ("6774_01030", "K2", 3),
    ("6754_0481", "K1", 7),
    ("6754_0481", "K2", 3),
    ("3470_085", "K1", 7),
    ("3470_085", "K2", 3),
    ("6753_02011", "K1", 7),
    ("6753_02011", "K2", 3),
    ("S4_9704411", "K1", 9),
    ("S4_9704411", "K2", 3),
    ("918_0102", "K1", 5),
    ("918_0102", "K2", 2),
    ("920A0100", "K1", 5),
    ("920A0100", "K2", 2),
    ("5450A0000", "K1", 7),
    ("5450A0000", "K2", 3),
    ("1394_0101", "K1", 5),
    ("1394_0101", "K2", 2),
    ("6864_0280", "K1", 6),
    ("6864_0280", "K2", 2),
    ("1568_0101", "K1", 5),
    ("1568_0101", "K2", 2),
    ("6884_2011", "K1", 5),
    ("6884_2011", "K2", 2),
    ("6885_2011", "K1", 5),
    ("6885_2011", "K2", 2),
    ("6886_2011", "K1", 5),
    ("6886_2011", "K2", 2),
    ("6887_2011", "K1", 5),
    ("6887_2011", "K2", 2),
    ("6898A0100", "K1", 5),
    ("6898A0100", "K2", 2),
    ("6724_0941", "K1", 7),
    ("6724_0941", "K2", 3),
    ("1964A2200", "K1", 4),
    ("1964A2200", "K2", 1),
    ("6882_2011", "K1", 5),
    ("6882_2011", "K2", 2),
    ("6883_2011", "K1", 5),
    ("6883_2011", "K2", 2),
    ("6888_2011", "K1", 5),
    ("6888_2011", "K2", 2),
    ("798_0184", "K1", 5),
    ("798_0184", "K2", 3),
    ("962A0100", "K1", 5),
    ("962A0100", "K2", 2),
    ("S4_9704300", "K1", 8),
    ("S4_9704300", "K2", 3),
    ("1642A0400", "K1", 6),
    ("1642A0400", "K2", 3),
    ("70069_23", "K1", 5),
    ("70069_23", "K2", 2),
    ("6724_0271", "K1", 8),
    ("6724_0271", "K2", 3),
    ("2434A2200", "K1", 5),
    ("2434A2200", "K2", 2),
    ("3470_028", "K1", 7),
    ("3470_028", "K2", 3),
], columns=["i", "k", "value"])
FK = Parameter(m, "FK", domain=[I, K], records=_fk_df,
               description="Max Fixing Devices with item i per Tank k")

# ── Variáveis ─────────────────────────────────────────────────────
X = Variable(m, "X", domain=[T, K, F, I], type="integer",
             description="Quantity of Product i via Device f in Tank k at Period t")
U = Variable(m, "U", domain=[T, K], type="binary",
             description="1 if Tank k activated in period t")
Y = Variable(m, "Y", domain=[T, K, F, I], type="binary",
             description="1 if Item i in Tank k at Period t via Device f")
W = Variable(m, "W", domain=[T, K, G], type="binary",
             description="1 if Raw Material g used in Tank k at Period t")
L = Variable(m, "L", domain=[I], type="positive",
             description="Slack — penalizes production shortage")
# ── Equações ──────────────────────────────────────────────────────
obj_expr = Sum((T, K), U[T, K]) + Sum(I, L[I])

RESTRI_1 = Equation(m, "RESTRI_1", domain=[I])
RESTRI_1[I] = Sum((T, K, F), X[T, K, F, I]) + L[I] == IE[I]

RESTRI_2 = Equation(m, "RESTRI_2", domain=[T, K])
RESTRI_2[T, K] = Sum((F, I), Y[T, K, F, I] * (1 / FK[I, K])) <= 1

RESTRI_3 = Equation(m, "RESTRI_3", domain=[T, I, K, F])
RESTRI_3[T, I, K, F] = X[T, K, F, I] <= IF_[I] * Y[T, K, F, I]

RESTRI_4 = Equation(m, "RESTRI_4", domain=[T, K, F])
RESTRI_4[T, K, F] = Sum(I, Y[T, K, F, I]) <= 1

RESTRI_5 = Equation(m, "RESTRI_5", domain=[T, K])
RESTRI_5[T, K] = Sum(G, W[T, K, G]) <= 1

RESTRI_6 = Equation(m, "RESTRI_6", domain=[T, I, K, F])
RESTRI_6[T, I, K, F] = Y[T, K, F, I] <= Sum(G, W[T, K, G] * GM[I, G])

RESTRI_7 = Equation(m, "RESTRI_7", domain=[T, K, F])
RESTRI_7[T, K, F] = Sum(I, Y[T, K, F, I]) >= Sum(I, Y[T, K, F.lead(1), I])

RESTRI_8 = Equation(m, "RESTRI_8", domain=[T, K])
RESTRI_8[T, K] = U[T, K] >= Sum((F, I), Y[T, K, F, I]) / 1000

RESTRI_9 = Equation(m, "RESTRI_9", domain=[T, K, F, I])
RESTRI_9[T, K, F, I] = X[T, K, F, I] >= Y[T, K, F, I]

RESTRI_10 = Equation(m, "RESTRI_10")
RESTRI_10[...] = Sum(T, U[T, "K1"]) - Sum(T, U[T, "K2"]) <= 1

RESTRI_11 = Equation(m, "RESTRI_11")
RESTRI_11[...] = Sum(T, U[T, "K2"]) - Sum(T, U[T, "K1"]) <= 1

RESTRI_12 = Equation(m, "RESTRI_12", domain=[T, K])
RESTRI_12[T.lag(1), K] = U[T, K] >= U[T.lead(1), K]

# ── Modelo ────────────────────────────────────────────────────────
Aerospace = Model(m, name="Aerospace", equations=m.getEquations(),
                  problem="MIP", sense=Sense.MIN, objective=obj_expr)

# ── Resolução ─────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"  Resolvendo: 23_3H_Lack.gms")
print("="*60 + "\n")

t0 = time.time()
Aerospace.solve(output=sys.stdout, options=options)
elapsed = time.time() - t0

# ── Pós-processamento ─────────────────────────────────────────────
u_sol = U.records if U.records is not None else pd.DataFrame()
x_sol = X.records if X.records is not None else pd.DataFrame()
y_sol = Y.records if Y.records is not None else pd.DataFrame()

Starts       = u_sol["level"].sum() if not u_sol.empty else 0.0
Disp         = IE.records["value"].sum()
CI           = x_sol.groupby("I", observed=True)["level"].sum() if not x_sol.empty else pd.Series(dtype=float)
Manufactured = CI.sum()

if not y_sol.empty:
    t_ord = {str(t): t for t in range(1, 65 + 1)}
    ys    = y_sol[y_sol["level"] > 0].copy()
    ys["t_ord"] = ys["T"].astype(str).map(t_ord).astype(int)
    SETUP = (ys["t_ord"] * ys["level"].astype(float)).sum()
else:
    SETUP = 0.0

print("\n" + "="*60)
print("  RESULTADOS")
print("="*60)
print(f"  Peças disponíveis  : {int(Disp)}")
print(f"  Peças produzidas   : {int(Manufactured)}")
print(f"  Ativações (Starts) : {int(Starts)}")
print(f"  SETUP ponderado    : {SETUP:.0f}")
print(f"  F.O. (Z)           : {Aerospace.objective_value:.4f}")
print(f"  Tempo              : {elapsed:.2f}s")
print(f"  Status             : {Aerospace.status}")

# ── CSV ───────────────────────────────────────────────────────────
os.makedirs("results", exist_ok=True)
out_path = os.path.join("results", "23_3H_Lack.csv")
with open(out_path, "w", encoding="utf-8") as fout:
    fout.write(f"AVAILABLE QUANTITY OF ITEM: {int(Disp)}\n")
    fout.write(f"QTD OF MANUFACTURED PIECES: {int(Manufactured)}\n")
    fout.write(f"ELAPSED TIME: {elapsed:8.2f}\n")
    fout.write(f"OBJ. FUNCTION VALUE: {Aerospace.objective_value}\n")
    fout.write(f"STARTS: {int(Starts)}\n")
    fout.write(f"1 IF OPTIMAL SOLUTION: {Aerospace.status}\n\n")
    fout.write("PERIOD;TANK;FIX_DEVICE;ITEM;QUANTITY\n")
    if not x_sol.empty:
        for _, row in x_sol[x_sol["level"] > 0].iterrows():
            fout.write(f"{row['T']};{row['K']};{row['F']};{row['I']};{int(row['level'])}\n")
    fout.write("END")
print(f"\n  CSV salvo em: {os.path.abspath(out_path)}")
