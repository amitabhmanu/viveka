"""Synthetic communities with planted behaviour (spec §10, decision D-7).

The simulator generates engine inputs whose truth is known, sets the simulated
thresholds and sizes, and estimates recovery and pilot power. Generation is pure:
all randomness comes from ``numpy.random`` generators seeded by the caller.
"""
