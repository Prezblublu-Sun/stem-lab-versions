"""Make U_timing.npy: 25 points of the phase-11/13 pool Sobol sequence (indices 2000-2024, seed 51100) + 25 corner points."""
import sys
import numpy as np
from scipy.stats import qmc

out = sys.argv[1]
corner = np.load(sys.argv[2])
U = qmc.Sobol(13, scramble=True, seed=51100).random(4096)[2000:2025]
np.save(out, np.vstack([U, corner[60:85]]))
print(np.load(out).shape)
